"""
mc_httpapi.py — Local HTTP API of the daemon (contract: api/openapi.json).

Linux: Unix socket run/api.sock (0600). Windows: 127.0.0.1 on a free port with a
bearer token in run/api.token. The routing table is built from the contract and
every handler lives in mc_apiops.
"""
import collections
import hmac
import http.server
import json
import logging
import math
import os
import queue
import re
import secrets
import socket
import socketserver
import sys
import threading
import time
import urllib.parse

import mc_api
import mc_apiops
import mc_jobs
import mc_remote
import mc_servers
from mc_platform import plat

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MAX_BODY = 1 << 20
DRAIN_MAX = 4 << 20
PING_S = 15
POLL_S = 5
PLAYERS_POLL_S = 15
MAX_CONSOLE_STREAMS = 3
SETTLE_S = 0.4
HISTORY = 200
SOCKET_NAME = "api.sock"
TOKEN_NAME = "api.token"
PUBLIC = ("getApiInfo", "pairDevice")
LOCAL_ONLY = ("setRemoteAccess", "createPairingCode")
FILTERED = ("listServers", "streamEvents", "listJobs", "getJob", "cancelJob")
METHODS = ("get", "put", "post", "delete", "patch")

STATUS_BY_CODE = {}
for _status, _codes in (
    (404, "not_found no_server folder_missing mod_not_found pack_not_found task_not_found backup_not_found "
          "remote_not_found channel_not_found no_remote no_channel java_not_installed config_key_unset "
          "no_active_server no_log_file job_not_found device_not_found"),
    (409, "server_running stop_first players_online already_active not_sleeping already_frozen mod_exists "
          "mod_ambiguous defines_blocks router_port_conflict folder_not_empty remote_exists channel_exists "
          "task_name_taken blocked_by_maintenance downgrade_refused job_finished console_offline server_offline "
          "config_conflict device_revoked kick_offline player_not_online chunky_missing no_previous "
          "not_cancellable output_exists pregen_offline server_running_not_frozen sleeping"),
    (422, "confirm_required confirmation_required eula_required name_required sleep_after_too_short "
          "sleep_needs_rcon key_not_found s3_credentials_missing restic_password_missing overworld_protected "
          "unknown_dimension unknown_loader not_a_jar unsafe_archive no_level_dat java_bad_choice bad_signature "
          "router_usage status_page_interval_too_short sleep_setting_refused sleep_hold_timeout_range "
          "command_required command_not_allowed warn_not_allowed unsupported_on_windows encrypt_key_missing "
          "tls_unavailable java_unavailable schedule_same_time"),
    (503, "rcon_failed rcon_error daemon_timeout source_unreachable check_failed java_download_failed "
          "announce_failed"),
    (501, "not_implemented"),
    (429, "too_many_streams pair_locked rate_limited"),
    (403, "forbidden"),
):
    STATUS_BY_CODE.update({code: _status for code in _codes.split()})


def status_for(code):
    if code in STATUS_BY_CODE:
        return STATUS_BY_CODE[code]
    if code.startswith(("bad_", "invalid_", "missing_")):
        return 422
    return 500


def spec_path():
    for folder in (BASE_DIR, os.path.join(BASE_DIR, "..", "api")):
        path = os.path.join(folder, "openapi.json")
        if os.path.isfile(path):
            return path
    raise FileNotFoundError("openapi.json")


def load_spec():
    with open(spec_path(), encoding="utf-8") as f:
        return json.load(f)


class Route:
    def __init__(self, spec, template, method, operation):
        self.template = template
        self.method = method.upper()
        self.operation = operation
        self.operation_id = operation["operationId"]
        self.names = re.findall(r"\{(\w+)\}", template)
        self.regex = re.compile("^" + "/".join(
            "([^/]+)" if segment.startswith("{") else re.escape(segment) for segment in template.split("/")) + "$")
        self.public = self.operation_id in PUBLIC
        self.success = min(int(code) for code in operation["responses"] if code.startswith("2"))
        self.parameters = [resolve(spec, p) for p in operation.get("parameters", [])]
        for path_level in spec["paths"][template].get("parameters", []):
            self.parameters.append(resolve(spec, path_level))
        body = operation.get("requestBody")
        self.body_schema = None
        self.body_required = False
        if body:
            self.body_required = bool(body.get("required"))
            self.body_schema = next(iter(body["content"].values())).get("schema")

    def match(self, path):
        found = self.regex.match(path)
        if not found:
            return None
        return {name: urllib.parse.unquote(value) for name, value in zip(self.names, found.groups())}


def resolve(spec, node):
    while isinstance(node, dict) and "$ref" in node:
        target = spec
        for part in node["$ref"][2:].split("/"):
            target = target[part.replace("~1", "/").replace("~0", "~")]
        node = target
    return node


def build_routes(spec):
    routes = []
    for template, item in spec["paths"].items():
        for method, operation in item.items():
            if method in METHODS:
                routes.append(Route(spec, template, method, operation))
    return routes


class BadRequest(Exception):
    def __init__(self, status, code):
        super().__init__(code)
        self.status = status
        self.code = code


class Invalid(Exception):
    def __init__(self, code, detail):
        super().__init__(detail)
        self.code = code
        self.detail = detail


TYPES = {
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "array": lambda v: isinstance(v, list),
    "object": lambda v: isinstance(v, dict),
    "null": lambda v: v is None,
}


def check(spec, value, schema, where="body"):
    schema = resolve(spec, schema)
    for sub in schema.get("allOf", []):
        check(spec, value, sub, where)
    for key in ("oneOf", "anyOf"):
        if key in schema:
            failures = []
            for sub in schema[key]:
                try:
                    check(spec, value, sub, where)
                    break
                except Invalid as exc:
                    failures.append(exc)
            else:
                raise failures[0]
    kinds = schema.get("type")
    if kinds is not None:
        kinds = [kinds] if isinstance(kinds, str) else kinds
        if not any(TYPES[kind](value) for kind in kinds):
            raise Invalid("invalid_field", f"{where}: expected {' or '.join(kinds)}")
    if "enum" in schema and value not in schema["enum"]:
        raise Invalid("invalid_field", f"{where}: must be one of {', '.join(map(str, schema['enum']))}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            raise Invalid("invalid_field", f"{where}: must be at least {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            raise Invalid("invalid_field", f"{where}: must be at most {schema['maximum']}")
    if isinstance(value, dict):
        for name in schema.get("required", []):
            if name not in value:
                raise Invalid("missing_field", f"{where}.{name} is required")
        for name, sub in (schema.get("properties") or {}).items():
            if name in value:
                check(spec, value[name], sub, f"{where}.{name}")
    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        for index, item in enumerate(value):
            check(spec, item, schema["items"], f"{where}[{index}]")


def coerce(spec, text, schema, name):
    schema = resolve(spec, schema)
    kind = schema.get("type")
    value = text
    if kind == "integer":
        try:
            value = int(text)
        except ValueError:
            raise Invalid("invalid_parameter", f"{name}: expected an integer") from None
    elif kind == "boolean":
        if text.lower() not in ("true", "false", "1", "0"):
            raise Invalid("invalid_parameter", f"{name}: expected true or false")
        value = text.lower() in ("true", "1")
    try:
        check(spec, value, schema, name)
    except Invalid as exc:
        raise Invalid("invalid_parameter", exc.detail) from None
    return value


class Request:
    def __init__(self, method, target, headers, body=b"", ip=None):
        parsed = urllib.parse.urlsplit(target)
        self.ip = ip
        self.device = None
        self.operation = None
        self.server = None
        self.paired = None
        self.method = method.upper()
        self.path = parsed.path
        self.query = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query, keep_blank_values=True).items()}
        self.headers = {k.lower(): v for k, v in headers.items()}
        self.body = body


class EventHub:
    def __init__(self):
        self.lock = threading.Lock()
        self.subscribers = []
        self.history = []
        self.counter = 0

    def publish(self, event):
        with self.lock:
            self.counter += 1
            item = (self.counter, event)
            self.history.append(item)
            del self.history[:-HISTORY]
            for box in self.subscribers:
                box.put(item)

    def subscribe(self, after=None):
        box = queue.Queue()
        with self.lock:
            if after is not None:
                for item in self.history:
                    if item[0] > after:
                        box.put(item)
            self.subscribers.append(box)
        return box

    def unsubscribe(self, box):
        with self.lock:
            if box in self.subscribers:
                self.subscribers.remove(box)

    def listening(self):
        return bool(self.subscribers)


def sse(event_id, name, data):
    head = f"id: {event_id}\n" if event_id is not None else ""
    return f"{head}event: {name}\ndata: {data}\n\n".encode("utf-8")


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class ApiApp:
    """Routing, validation and dispatch; knows nothing about sockets."""

    def __init__(self, token=None, release=None, settle=SETTLE_S, remote=None):
        self.remote = remote
        self.spec = load_spec()
        self.routes = build_routes(self.spec)
        self.token = token
        self.release = release
        self.settle = settle
        self.ping_s = PING_S
        self.hub = EventHub()
        self.jobs = mc_jobs.Registry(on_change=lambda doc: self.hub.publish({"type": "job", "job": doc}))
        self.stopping = threading.Event()
        self.streams = 0
        self.device_streams = collections.Counter()
        self.streams_lock = threading.Lock()
        self.seen_states = {}
        self.seen_players = {}
        self.players_at = {}

    # ── dispatch ─────────────────────────────────────────────────────────────

    def error(self, status, code, message, headers=None, **data):
        return mc_apiops.Reply(status, mc_api.wire(mc_api.result(False, code, message=message, **data)), headers)

    def candidates(self, path):
        found = []
        for route in self.routes:
            params = route.match(path)
            if params is not None:
                found.append((route, params))
        return sorted(found, key=lambda item: len(item[0].names))

    def authorized(self, request):
        if self.remote:
            if request.device is None:
                request.device = self.remote.identify(request)
            return request.device is not None
        if not self.token:
            return True
        header = request.headers.get("authorization", "")
        scheme, _, supplied = header.partition(" ")
        return scheme.lower() == "bearer" and hmac.compare_digest(supplied.strip().encode(), self.token.encode())

    def dispatch(self, request):
        try:
            reply = self._dispatch(request)
        except Exception:
            logging.exception("API %s %s failed", request.method, request.path)
            reply = self.error(500, "internal_error", "Internal error.")
        if self.remote:
            self.record(request, reply)
        return reply

    def record(self, request, reply):
        body = getattr(reply, "body", None)
        code = body.get("code") if isinstance(body, dict) else None
        device = request.device["id"] if request.device else request.paired
        try:
            mc_remote.audit(device, request.ip, request.method, request.operation, request.server,
                            reply.status, code)
        except OSError:
            logging.exception("audit log")

    def _dispatch(self, request):
        found = self.candidates(request.path)
        matching = [(r, p) for r, p in found if r.method == request.method]
        if not matching:
            if not self.authorized(request):
                return self.unauthorized()
            if found:
                allow = ", ".join(sorted({r.method for r, _ in found}))
                return self.error(405, "method_not_allowed", "Method not allowed.", {"Allow": allow})
            return self.error(404, "not_found", "No such route.")
        route, params = matching[0]
        request.operation = route.operation_id
        if self.remote is None and route.operation_id == "pairDevice":
            return self.error(404, "not_found", "No such route.")
        if not route.public:
            if not self.authorized(request):
                return self.unauthorized()
            if self.remote:
                denied = self.check_access(request, route, params)
                if denied:
                    return denied
        try:
            body = self.parse_body(request, route)
            query = self.parse_query(request, route, params)
            if route.body_schema is not None:
                check(self.spec, body, route.body_schema)
        except Invalid as exc:
            return self.error(422, exc.code, exc.detail, detail=exc.detail)
        except BadRequest as exc:
            return self.error(exc.status, exc.code, exc.code.replace("_", " ").capitalize() + ".")
        handler = mc_apiops.HANDLERS[route.operation_id]
        context = mc_apiops.Context(self, route, params, query, body, request.headers, request)
        try:
            outcome = handler(context)
        except mc_apiops.Failure as failure:
            return self.reply_for(route, failure.res)
        if isinstance(outcome, (mc_apiops.Reply, mc_apiops.Stream)):
            if isinstance(outcome, mc_apiops.Reply) and outcome.raw is None and outcome.body is not None \
                    and "ok" in outcome.body and not outcome.body["ok"]:
                return self.reply_for(route, outcome.body)
            return outcome
        return self.reply_for(route, outcome)

    def forbidden(self):
        return self.error(403, "forbidden", "Not allowed for this device.")

    def check_access(self, request, route, params):
        """Rate limit, then role and server restriction; runs before any handler."""
        device = request.device
        mc_remote.note_seen(device["id"], request.ip)
        allowed, wait = self.remote.allow(device["id"])
        if not allowed:
            return self.error(429, "rate_limited", "Too many requests.", {"Retry-After": str(max(1, math.ceil(wait)))})
        operation = route.operation_id
        if operation in LOCAL_ONLY:
            return self.forbidden()
        restricted = mc_remote.allowed_servers(device) is not None
        server = None
        if "server" in params:
            server = self.canonical_server(params["server"])
            request.server = server
            if server is None and restricted:
                return self.forbidden()
            if server is not None and not mc_remote.may_use_server(device, server):
                return self.forbidden()
        elif restricted and operation not in FILTERED:
            return self.forbidden()
        role = mc_remote.effective_role(device, server)
        if mc_remote.rank(role) < mc_remote.rank(route.operation.get("x-mcm-role", "admin")):
            return self.forbidden()
        return None

    @staticmethod
    def canonical_server(reference):
        try:
            registry = mc_servers.load_registry()
        except mc_servers.DataFileError:
            return None
        servers = registry.get("servers", {})
        target = registry.get("active") if reference == "active" else mc_servers._lookup_key(servers, reference)
        return target if target in servers else None

    def unauthorized(self):
        return self.error(401, "unauthorized", "Missing or invalid token.", {"WWW-Authenticate": "Bearer"})

    def reply_for(self, route, res):
        body = mc_api.wire(res)
        if body.get("ok"):
            return mc_apiops.Reply(route.success, body)
        code = body.get("code") or "error"
        if code in mc_apiops.REPORTED_FAILURES.get(route.operation_id, ()):
            return mc_apiops.Reply(200, body)
        headers = {"Retry-After": str(body.get("retry_after_s", 900))} if code == "pair_locked" else None
        return mc_apiops.Reply(status_for(code), body, headers)

    def parse_body(self, request, route):
        if not request.body:
            return {}
        try:
            body = json.loads(request.body.decode("utf-8"))
        except ValueError:
            raise BadRequest(400, "invalid_json") from None
        if not isinstance(body, dict):
            raise BadRequest(400, "invalid_json")
        return body

    def parse_query(self, request, route, params):
        query = {}
        for parameter in route.parameters:
            name, where, schema = parameter["name"], parameter["in"], parameter.get("schema", {})
            if where == "path":
                if name in params:
                    params[name] = coerce(self.spec, params[name], schema, name)
            elif where == "query":
                if name in request.query:
                    query[name] = coerce(self.spec, request.query[name], schema, name)
                elif parameter.get("required"):
                    raise Invalid("missing_parameter", f"{name} is required")
        return query

    # ── jobs and streams ─────────────────────────────────────────────────────

    def start_job(self, kind, server, function):
        job = self.jobs.submit(kind, server, function, settle=self.settle)
        if job.finished.is_set() and job.state == "failed":
            status = status_for(job.result.get("code") or "")
            if status < 500:
                self.jobs.discard(job.id)
                return mc_apiops.Reply(status, job.result)
        return mc_apiops.Reply(202, job.document(), {"Location": f"/v1/jobs/{job.id}"})

    def acquire_stream(self, owner=None):
        with self.streams_lock:
            if owner is None:
                if self.streams >= MAX_CONSOLE_STREAMS:
                    return False
                self.streams += 1
            else:
                if self.device_streams[owner] >= MAX_CONSOLE_STREAMS:
                    return False
                self.device_streams[owner] += 1
            return True

    def release_stream(self, owner=None):
        with self.streams_lock:
            if owner is None:
                self.streams = max(0, self.streams - 1)
            else:
                self.device_streams[owner] = max(0, self.device_streams[owner] - 1)

    def event_stream(self, servers, last_id, allowed=None, device_id=None, alive=None):
        wanted = {s for s in (servers or "").split(",") if s} or None
        if allowed is not None:
            wanted = (wanted & set(allowed)) if wanted else set(allowed)
        key = ("events", device_id)
        if device_id is not None and not self.acquire_stream(key):
            raise mc_apiops.Failure(mc_api.result(False, "too_many_streams", message="Too many event streams."))
        try:
            after = int(last_id) if last_id else None
        except ValueError:
            after = None
        box = self.hub.subscribe(after)

        def chunks():
            last_ping = time.monotonic()
            yield b": open\n\n"
            while not self.stopping.is_set() and (alive is None or alive()):
                try:
                    event_id, event = box.get(timeout=0.25)
                except queue.Empty:
                    if time.monotonic() - last_ping >= self.ping_s:
                        last_ping = time.monotonic()
                        yield b": ping\n\n"
                    continue
                owner = event.get("server") or (event.get("job") or {}).get("server")
                if allowed is not None and owner not in wanted:
                    continue
                if wanted and owner and owner not in wanted:
                    continue
                last_ping = time.monotonic()
                yield sse(event_id, event["type"], json.dumps(event, ensure_ascii=False))
        def close():
            self.hub.unsubscribe(box)
            if device_id is not None:
                self.release_stream(key)
        return mc_apiops.Stream(chunks(), close)

    def console_stream(self, name, config, tail, last_id, device_id=None, alive=None):
        if not self.acquire_stream(device_id):
            raise mc_apiops.Failure(mc_api.result(False, "too_many_streams", message="Too many console streams."))
        log = os.path.join(config["dossier_serveur"], "logs", "latest.log")

        def chunks():
            offset = None
            if last_id and last_id.isdigit():
                offset = int(last_id)
            last_ping = time.monotonic()
            yield b": open\n\n"
            pending = b""
            while not self.stopping.is_set() and (alive is None or alive()):
                try:
                    size = os.path.getsize(log)
                except OSError:
                    size = None
                if size is not None:
                    if offset is None:
                        offset, lines = initial_tail(log, size, tail)
                        for line in lines:
                            yield sse(None, "line", line)
                    elif size < offset:
                        offset = 0
                    if size > offset:
                        with open(log, "rb") as f:
                            f.seek(offset)
                            data = f.read(size - offset)
                        offset += len(data)
                        pending += data
                        *complete, pending = pending.split(b"\n")
                        for raw in complete:
                            yield sse(offset, "line", raw.decode("utf-8", "replace").rstrip("\r"))
                        last_ping = time.monotonic()
                if time.monotonic() - last_ping >= self.ping_s:
                    last_ping = time.monotonic()
                    yield b": ping\n\n"
                self.stopping.wait(0.2)
        return mc_apiops.Stream(chunks(), lambda: self.release_stream(device_id))

    # ── event sources ────────────────────────────────────────────────────────

    def poll_once(self, now=None):
        """Publish state and player changes since the last call."""
        now = now if now is not None else time.monotonic()
        try:
            registry = mc_servers.load_registry()
        except mc_servers.DataFileError:
            return
        for name, info in registry.get("servers", {}).items():
            try:
                snapshot = mc_api.server_snapshot(name, info, registry.get("active"))
            except Exception:
                logging.exception("API event poll failed for %s", name)
                continue
            state = snapshot.get("state")
            if name in self.seen_states and state != self.seen_states[name]:
                self.hub.publish({"type": "state", "server": name, "state": state,
                                  "previous": self.seen_states[name], "at": now_iso()})
            self.seen_states[name] = state
            if state == "running" and now - self.players_at.get(name, -PLAYERS_POLL_S) >= PLAYERS_POLL_S:
                self.players_at[name] = now
                self.poll_players(name, info)
        for name in [n for n in self.seen_states if n not in registry.get("servers", {})]:
            self.seen_states.pop(name, None)
            self.seen_players.pop(name, None)

    def poll_players(self, name, info):
        import mc_config
        try:
            config = mc_config.load_config(info["dossier_serveur"])
            config["dossier_serveur"] = info["dossier_serveur"]
            ok, data = mc_api.query_players(config)
        except Exception:
            return
        if not ok:
            return
        current = list(data.get("players", []))
        before = self.seen_players.get(name)
        self.seen_players[name] = current
        if before is None or before == current:
            return
        self.hub.publish({"type": "players", "server": name, "online": data.get("online", len(current)),
                          "max": data.get("max"), "players": current,
                          "joined": [p for p in current if p not in before],
                          "left": [p for p in before if p not in current], "at": now_iso()})

    def alert_event(self, config, event, info):
        dossier = config.get("dossier_serveur")
        name = next((n for n, i in mc_servers.list_servers().items() if i.get("dossier_serveur") == dossier),
                    config.get("nom_serveur", ""))
        if event in ("start", "stop", "crash", "crash_loop", "backup_failed", "update", "sleep", "wake"):
            self.hub.publish({"type": "alert", "server": name, "event": event,
                              "detail": info.get("detail"), "at": now_iso()})


def initial_tail(path, size, lines):
    if lines <= 0:
        return size, []
    with open(path, "rb") as f:
        block = min(size, 64 * 1024)
        f.seek(size - block)
        data = f.read(block)
    text = data.decode("utf-8", "replace").splitlines()
    return size, text[-lines:]


# ── transport ────────────────────────────────────────────────────────────────

class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "MCManager"
    sys_version = ""

    def log_message(self, fmt, *args):
        pass

    def send_reply(self, reply):
        if reply.raw is not None:
            payload, kind = reply.raw, reply.content_type or "application/octet-stream"
        else:
            payload = json.dumps(reply.body, ensure_ascii=False).encode("utf-8")
            kind = "application/json; charset=utf-8"
        self.send_response(reply.status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        for key, value in reply.headers.items():
            self.send_header(key, value)
        if self.close_connection:
            self.send_header("Connection", "close")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)

    def send_stream(self, stream):
        self.close_connection = True
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.flush()
        try:
            for chunk in stream.chunks:
                self.wfile.write(chunk)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionError, OSError):
            pass
        finally:
            stream.chunks.close()
            if stream.on_close:
                stream.on_close()

    def handle_request(self):
        app = self.server.app
        length = self.headers.get("Content-Length")
        body = b""
        if self.headers.get("Transfer-Encoding"):
            self.close_connection = True
            return self.send_reply(app.error(400, "invalid_request", "Chunked bodies are not accepted."))
        if length:
            try:
                size = int(length)
            except ValueError:
                size = -1
            if size < 0:
                self.close_connection = True
                return self.send_reply(app.error(400, "invalid_request", "Bad Content-Length."))
            if size > MAX_BODY:
                self.close_connection = True
                if size <= DRAIN_MAX:
                    self.rfile.read(size)
                return self.send_reply(app.error(413, "payload_too_large", "Request body is larger than 1 MiB."))
            body = self.rfile.read(size)
        outcome = app.dispatch(Request(self.command, self.path, dict(self.headers), body, self.client_address[0]))
        if isinstance(outcome, mc_apiops.Stream):
            return self.send_stream(outcome)
        self.send_reply(outcome)

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = do_OPTIONS = handle_request


class TcpServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, app):
        self.app = app
        super().__init__(address, Handler)

    def server_bind(self):
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = "localhost", self.server_address[1]


if hasattr(socketserver, "UnixStreamServer"):
    class UnixServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
        daemon_threads = True

        def __init__(self, path, app):
            self.app = app
            old = os.umask(0o177)
            try:
                super().__init__(path, Handler)
            finally:
                os.umask(old)
            plat.secure_file(path)

        def get_request(self):
            request, _ = super().get_request()
            return request, ("local", 0)

        def server_bind(self):
            socketserver.UnixStreamServer.server_bind(self)
            self.server_name = "localhost"
            self.server_port = 0


# ── lifecycle ────────────────────────────────────────────────────────────────

def settings_path():
    return os.path.join(os.path.dirname(mc_servers.REGISTRY_FILE), "api.json")


def local_enabled():
    return mc_servers.read_json(settings_path(), {}).get("api_local", True) is not False


def set_local_enabled(enabled):
    settings = mc_servers.read_json(settings_path(), {})
    settings["api_local"] = bool(enabled)
    mc_servers._atomic_write_json(settings_path(), settings)


def default_mode():
    return "tcp" if sys.platform == "win32" or not hasattr(socket, "AF_UNIX") else "unix"


def run_dir():
    import mc_ipc
    return mc_ipc.RUN_DIR


def address(folder=None, mode=None):
    """What a client connects to: {'mode': 'unix', 'path': ...} or {'mode': 'tcp', 'host', 'port', 'token'}."""
    folder = folder or run_dir()
    mode = mode or default_mode()
    if mode == "unix":
        path = os.path.join(folder, SOCKET_NAME)
        return {"mode": "unix", "path": path} if os.path.exists(path) else None
    info = mc_servers.read_json(os.path.join(folder, TOKEN_NAME), None)
    if not info:
        return None
    return {"mode": "tcp", "host": "127.0.0.1", "port": info["port"], "token": info["token"]}


def reachable(found):
    if not found:
        return False
    try:
        if found["mode"] == "unix":
            probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            target = found["path"]
        else:
            probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            target = (found["host"], found["port"])
        probe.settimeout(1)
        with probe:
            probe.connect(target)
        return True
    except OSError:
        return False


class LocalApi:
    """Owns the listener thread; sync() is called from the daemon loop and never raises."""
    label = "Local API"

    def __init__(self, folder=None, mode=None, release=None, settle=SETTLE_S, enabled=None):
        self.folder = folder
        self.mode = mode or default_mode()
        self.release = release
        self.settle = settle
        self.enabled = enabled
        self.app = None
        self.server = None
        self.thread = None
        self.poller = None
        self.retry_at = 0
        self.token = None

    def folder_path(self):
        return self.folder or run_dir()

    def alive(self):
        return bool(self.thread and self.thread.is_alive())

    def wanted(self):
        return local_enabled() if self.enabled is None else self.enabled()

    def sync(self):
        try:
            wanted = self.wanted()
        except Exception:
            wanted = self.alive()
        try:
            if not wanted:
                if self.server:
                    self.stop()
                return
            if self.alive() or time.monotonic() < self.retry_at:
                return
            if self.server:
                self.stop()
            self.retry_at = time.monotonic() + 5
            self.start()
        except Exception:
            logging.exception("Local API")
            try:
                self.stop()
            except Exception:
                pass

    def start(self):
        if sys.stdout is None:
            sys.stdout = open(os.devnull, "w")
        if sys.stderr is None:
            sys.stderr = open(os.devnull, "w")
        folder = self.folder_path()
        os.makedirs(folder, mode=0o700, exist_ok=True)
        plat.secure_dir(folder)
        self.bind(folder)
        self.launch()

    def bind(self, folder):
        self.token = secrets.token_urlsafe(32) if self.mode == "tcp" else None
        self.app = ApiApp(token=self.token, release=self.release, settle=self.settle)
        if self.mode == "unix":
            path = os.path.join(folder, SOCKET_NAME)
            if os.path.exists(path):
                os.remove(path)
            self.server = UnixServer(path, self.app)
        else:
            self.server = TcpServer(("127.0.0.1", 0), self.app)
            port = self.server.server_address[1]
            plat.write_private_file(os.path.join(folder, TOKEN_NAME),
                                    json.dumps({"port": port, "token": self.token}))

    def launch(self):
        import mc_core
        mc_core.LISTENERS.append(self.app.alert_event)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.2},
                                       daemon=True, name="local-api")
        self.thread.start()
        self.poller = threading.Thread(target=self.poll_loop, args=(self.app,), daemon=True, name="api-events")
        self.poller.start()
        logging.info("%s listening.", self.label)

    def poll_loop(self, app):
        while not app.stopping.wait(POLL_S):
            if app.hub.listening():
                try:
                    app.poll_once()
                except Exception:
                    logging.exception("API event poll")

    def stop(self):
        server, app = self.server, self.app
        self.server = self.app = None
        if app:
            app.stopping.set()
            import mc_core
            if app.alert_event in mc_core.LISTENERS:
                mc_core.LISTENERS.remove(app.alert_event)
        if server:
            server.shutdown()
            server.server_close()
        if self.thread:
            self.thread.join(timeout=5)
        self.thread = None
        self.cleanup()

    def cleanup(self):
        folder = self.folder_path()
        for name in (SOCKET_NAME, TOKEN_NAME):
            try:
                os.remove(os.path.join(folder, name))
            except OSError:
                pass


def status():
    enabled = local_enabled()
    found = address()
    return {"enabled": enabled, "mode": default_mode(), "address": found, "listening": reachable(found)}
