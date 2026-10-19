import http.client
import json
import os
import socket
import threading
import time
from urllib.parse import quote

from . import corepath

corepath.ensure()

JOB_DONE = ("succeeded", "failed", "cancelled")


class ApiError(Exception):
    def __init__(self, code, message="", status=0, document=None):
        super().__init__(code)
        self.code = code
        self.message = message
        self.status = status
        self.document = document or {}


class UnixConnection(http.client.HTTPConnection):
    def __init__(self, path, timeout=20):
        super().__init__("localhost", timeout=timeout)
        self.path = path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.path)


class LocalTransport:
    """The daemon on this machine, through its Unix socket (run/api.sock)."""

    def __init__(self, path):
        self.path = path

    @classmethod
    def discover(cls, run_folder=None):
        import mc_httpapi
        found = mc_httpapi.address(run_folder or os.environ.get("MCMANAGER_RUN_DIR") or None, "unix")
        return cls(found["path"]) if found else None

    def request(self, method, path, body=None):
        conn = UnixConnection(self.path)
        try:
            data = None
            headers = {}
            if body is not None:
                data = json.dumps(body).encode()
                headers["Content-Type"] = "application/json"
            conn.request(method, path, data, headers)
            response = conn.getresponse()
            payload = response.read()
        except (OSError, http.client.HTTPException) as exc:
            return 0, {"ok": False, "code": "daemon_unreachable", "detail": type(exc).__name__}
        finally:
            conn.close()
        return response.status, parse_document(payload)

    def open_stream(self, path, last_id=None):
        conn = UnixConnection(self.path, timeout=60)
        headers = {"Last-Event-ID": str(last_id)} if last_id else {}
        conn.request("GET", path, headers=headers)
        return conn, conn.getresponse()


class RemoteTransport:
    """A paired remote server: delegates to the core client (pinned certificate, device token)."""

    def __init__(self, remote):
        self.remote = remote

    @classmethod
    def from_profile(cls, name):
        import mc_remoteclient
        remote = mc_remoteclient.Remote.from_profile(name)
        return cls(remote) if remote else None

    def request(self, method, path, body=None):
        return self.remote.request(method, path, body)

    def open_stream(self, path, last_id=None):
        return self.remote.stream(path)


def parse_document(payload):
    try:
        document = json.loads(payload)
    except ValueError:
        return {"ok": False, "code": "bad_answer"}
    return document if isinstance(document, dict) else {"ok": False, "code": "bad_answer"}


def sse_messages(response):
    """Yield (event id, name, data) for each Server-Sent Event; comments are skipped."""
    name, data, event_id = None, [], None
    while True:
        raw = response.fp.readline()
        if not raw:
            return
        line = raw.decode("utf-8", "replace").rstrip("\r\n")
        if line == "":
            if name or data:
                yield event_id, name or "message", "\n".join(data)
            name, data = None, []
            continue
        if line.startswith(":"):
            continue
        key, _, value = line.partition(":")
        value = value[1:] if value.startswith(" ") else value
        if key == "event":
            name = value
        elif key == "data":
            data.append(value)
        elif key == "id":
            event_id = value


class EventStream:
    """Reads an SSE route in a thread and calls on_message(name, data); reconnects until stop()."""

    def __init__(self, transport, path, on_message, on_state=None, retry_s=2.0, max_retries=None):
        self.transport, self.path = transport, path
        self.on_message, self.on_state = on_message, on_state
        self.retry_s, self.max_retries = retry_s, max_retries
        self._stop = threading.Event()
        self._response = None
        self._lock = threading.Lock()
        self.thread = None
        self.last_id = None

    def start(self):
        self.thread = threading.Thread(target=self._run, daemon=True, name="sse")
        self.thread.start()
        return self

    def stop(self, join=True):
        self._stop.set()
        with self._lock:
            response = self._response
        sock = getattr(getattr(getattr(response, "fp", None), "raw", None), "_sock", None)
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        if join and self.thread and self.thread is not threading.current_thread():
            self.thread.join(5)

    def _state(self, state):
        if self.on_state:
            self.on_state(state)

    def _run(self):
        failures = 0
        while not self._stop.is_set():
            try:
                conn, response = self.transport.open_stream(self.path, self.last_id)
            except (OSError, http.client.HTTPException):
                conn, response = None, None
            if response is not None and response.status == 200:
                with self._lock:
                    self._response = response
                failures = 0
                self._state("open")
                try:
                    if self._stop.is_set():
                        raise ValueError("stopped")
                    for event_id, name, data in sse_messages(response):
                        if event_id:
                            self.last_id = event_id
                        self.on_message(name, data)
                except (OSError, http.client.HTTPException, ValueError):
                    pass
            elif response is not None:
                self._state("refused:%d" % response.status)
                try:
                    response.read()
                except (OSError, http.client.HTTPException):
                    pass
            if conn is not None:
                try:
                    conn.close()
                except OSError:
                    pass
            with self._lock:
                self._response = None
            if self._stop.is_set():
                break
            failures += 1
            if self.max_retries is not None and failures > self.max_retries:
                self._state("failed")
                return
            self._state("lost")
            self._stop.wait(self.retry_s)
        self._state("closed")


class ApiClient:
    def __init__(self, transport):
        self.transport = transport

    def call(self, method, path, body=None):
        status, document = self.transport.request(method, path, body)
        if status == 0 or not 200 <= status < 300 or document.get("ok") is False:
            raise ApiError(document.get("code") or "unknown", document.get("message") or "", status, document)
        return status, document

    def get(self, path):
        return self.call("GET", path)[1]

    @staticmethod
    def ref(server):
        return quote(str(server), safe="")

    def info(self):
        status, document = self.transport.request("GET", "/v1")
        if status != 200:
            raise ApiError(document.get("code") or "daemon_unreachable", "", status, document)
        return document

    def list_servers(self):
        return self.get("/v1/servers").get("servers", [])

    def get_server(self, server):
        return self.get("/v1/servers/" + self.ref(server))

    def players(self, server):
        return self.get("/v1/servers/%s/players" % self.ref(server))

    def player_list(self, server, kind):
        return self.get("/v1/servers/%s/lists/%s" % (self.ref(server), self.ref(kind)))

    def add_to_list(self, server, kind, subject, reason=None):
        body = {"subject": subject}
        if reason:
            body["reason"] = reason
        path = "/v1/servers/%s/lists/%s" % (self.ref(server), self.ref(kind))
        return self.call("POST", path, body)[1]

    def remove_from_list(self, server, kind, subject):
        path = "/v1/servers/%s/lists/%s/%s" % (self.ref(server), self.ref(kind), self.ref(subject))
        return self.call("DELETE", path)[1]

    def kick(self, server, player, reason=None):
        body = {"player": player}
        if reason:
            body["reason"] = reason
        return self.call("POST", "/v1/servers/%s/kick" % self.ref(server), body)[1]

    def config(self, server):
        return self.get("/v1/servers/%s/config" % self.ref(server))

    def job(self, job_id):
        return self.get("/v1/jobs/" + self.ref(job_id))

    def action(self, server, name):
        """Start, stop, restart or wake. Returns (status, document); 202 carries a job."""
        return self.call("POST", "/v1/servers/%s/%s" % (self.ref(server), name))

    def send_command(self, server, command):
        return self.call("POST", "/v1/servers/%s/console" % self.ref(server), {"command": command})[1]

    def list_backups(self, server):
        return self.get("/v1/servers/%s/backups" % self.ref(server))

    def create_backup(self, server):
        return self.call("POST", "/v1/servers/%s/backups" % self.ref(server))[1]

    def restore_backup(self, server, backup):
        path = "/v1/servers/%s/backups/%s/restore" % (self.ref(server), self.ref(backup))
        return self.call("POST", path, {"confirm": True})[1]

    def list_mods(self, server):
        return self.get("/v1/servers/%s/mods" % self.ref(server))

    def add_mod(self, server, ref, source=None, server_only=False):
        body = {"ref": ref}
        if source:
            body["source"] = source
        if server_only:
            body["server_only"] = True
        return self.call("POST", "/v1/servers/%s/mods" % self.ref(server), body)[1]

    def remove_mod(self, server, mod, confirm_blocks=False):
        path = "/v1/servers/%s/mods/%s" % (self.ref(server), self.ref(mod))
        return self.call("DELETE", path + ("?confirm_blocks=true" if confirm_blocks else ""))[1]

    def update_mods(self, server, name=None):
        return self.call("POST", "/v1/servers/%s/mods/update" % self.ref(server), {"name": name})[1]

    def list_datapacks(self, server):
        return self.get("/v1/servers/%s/datapacks" % self.ref(server))

    def set_datapack(self, server, pack, enabled, placement=None):
        body = {"enabled": bool(enabled)}
        if enabled and placement:
            body[placement] = True
        return self.call("PUT", "/v1/servers/%s/datapacks/%s" % (self.ref(server), self.ref(pack)), body)[1]

    def list_worlds(self, server):
        return self.get("/v1/servers/%s/worlds" % self.ref(server))

    def pregen_status(self, server):
        return self.get("/v1/servers/%s/worlds/pregen" % self.ref(server))

    def start_pregen(self, server, radius, center=None):
        body = {"radius": radius}
        if center:
            body["center"] = center
        return self.call("POST", "/v1/servers/%s/worlds/pregen" % self.ref(server), body)[1]

    def reset_dimension(self, server, dimension, include_overworld=False):
        path = "/v1/servers/%s/worlds/%s/reset" % (self.ref(server), self.ref(dimension))
        return self.call("POST", path, {"confirmed": True, "include_overworld": bool(include_overworld)})[1]

    def list_tasks(self, server):
        return self.get("/v1/servers/%s/tasks" % self.ref(server))

    def create_task(self, server, action, cron, name=None, command=None, warn=None):
        body = {"action": action, "cron": cron}
        for key, value in (("name", name), ("command", command), ("warn", warn)):
            if value:
                body[key] = value
        return self.call("POST", "/v1/servers/%s/tasks" % self.ref(server), body)[1]

    def update_task(self, server, task, enabled):
        path = "/v1/servers/%s/tasks/%s" % (self.ref(server), self.ref(task))
        return self.call("PATCH", path, {"enabled": bool(enabled)})[1]

    def delete_task(self, server, task):
        return self.call("DELETE", "/v1/servers/%s/tasks/%s" % (self.ref(server), self.ref(task)))[1]

    def run_task(self, server, task, skip_warn=False):
        path = "/v1/servers/%s/tasks/%s/run" % (self.ref(server), self.ref(task))
        return self.call("POST", path, {"skip_warn": bool(skip_warn)})[1]

    def set_config_value(self, server, key, value):
        path = "/v1/servers/%s/config/%s" % (self.ref(server), self.ref(key))
        return self.call("PUT", path, {"value": value})[1]

    def set_mode(self, server, mode):
        return self.call("PUT", "/v1/servers/%s/mode" % self.ref(server), {"mode": mode})[1]

    def set_schedule(self, server, open_hour, open_minute, close_hour, close_minute):
        body = {"open_hour": open_hour, "open_minute": open_minute,
                "close_hour": close_hour, "close_minute": close_minute}
        return self.call("PUT", "/v1/servers/%s/schedule" % self.ref(server), body)[1]

    def sleep_settings(self, server):
        return self.get("/v1/servers/%s/sleep" % self.ref(server))

    def set_sleep(self, server, **fields):
        return self.call("PUT", "/v1/servers/%s/sleep" % self.ref(server), fields)[1]

    def server_java(self, server):
        return self.get("/v1/servers/%s/java" % self.ref(server))

    def set_server_java(self, server, choice):
        return self.call("PUT", "/v1/servers/%s/java" % self.ref(server), {"choice": str(choice)})[1]

    def create_server(self, name, loader, accept_eula, version=None, ram=None, port=None, rcon_port=None):
        body = {"name": name, "loader": loader, "accept_eula": bool(accept_eula)}
        for key, value in (("version", version), ("ram", ram), ("port", port), ("rcon_port", rcon_port)):
            if value:
                body[key] = value
        return self.call("POST", "/v1/servers", body)[1]

    def wait_job(self, job_id, timeout=3600, step=0.5, sleep=time.sleep, now=time.time, on_progress=None):
        end = now() + timeout
        while now() < end:
            job = self.job(job_id)
            if on_progress:
                on_progress(job.get("progress") or 0)
            if job.get("state") in JOB_DONE:
                result = job.get("result")
                if job["state"] != "succeeded" or (isinstance(result, dict) and result.get("ok") is False):
                    result = result if isinstance(result, dict) else {}
                    raise ApiError(result.get("code") or "job_" + job["state"], result.get("message") or "", 200, result)
                return result or job
            sleep(step)
        raise ApiError("daemon_timeout", "", 0)

    def events(self, on_message, on_state=None, **kwargs):
        return EventStream(self.transport, "/v1/events", on_message, on_state, **kwargs)

    def console(self, server, on_message, on_state=None, tail=200, **kwargs):
        path = "/v1/servers/%s/console?tail=%d" % (self.ref(server), tail)
        return EventStream(self.transport, path, on_message, on_state, **kwargs)


def pair_remote(address, fingerprint, code, name, profile):
    """Exchange a pairing code and store the profile; returns the paired Remote."""
    import mc_remoteclient
    try:
        host, port = mc_remoteclient.split_address(address)
    except ValueError:
        raise ApiError("invalid_address")
    document, remote = mc_remoteclient.pair(host, port, fingerprint, code, name)
    if remote is None:
        raise ApiError(document.get("code") or "unknown", document.get("message") or "", 0, document)
    profiles = mc_remoteclient.load_profiles()
    profiles[profile] = {"host": host, "port": port, "fingerprint": fingerprint, "token": remote.token}
    mc_remoteclient.save_profiles(profiles)
    return remote


def probe_fingerprint(address):
    import mc_remoteclient
    try:
        host, port = mc_remoteclient.split_address(address)
    except ValueError:
        raise ApiError("invalid_address")
    try:
        return mc_remoteclient.fetch_fingerprint(host, port)
    except OSError:
        raise ApiError("remote_unreachable")
