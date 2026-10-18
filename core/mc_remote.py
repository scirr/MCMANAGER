"""
mc_remote.py — State and rules of the remote API: settings, TLS certificate, paired
devices, pairing codes, roles, rate limits and the audit log. The listener lives in
mc_remoteserver; the handlers in mc_apiops call the functions below.

Tokens and pairing codes are stored hashed (SHA-256); a token is shown once, when the
device pairs.
"""
import collections
import contextlib
import hashlib
import hmac
import ipaddress
import json
import os
import re
import secrets
import shutil
import socket
import ssl
import subprocess
import threading
import time

import mc_api
import mc_servers
from mc_platform import plat

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROLES = ("viewer", "operator", "admin")
DEFAULT_BIND = "0.0.0.0:8765"
FIREWALL_LABEL = "API"
CODE_TTL_S = 300
CODE_MAX_FAILS = 5
PAIR_LOCK_AFTER = 10
PAIR_LOCK_S = 900
PAIR_DELAY_S = 0.4
RATE_LIMIT = 20
RATE_WINDOW_S = 1.0
AUDIT_MAX = 5 << 20
SEEN_FLUSH_S = 60
CERT_DAYS = 3650
DEVICES_FILE = "remote_devices.json"
CODES_FILE = "remote_pairing.json"
SEEN_FILE = "remote_seen.json"
SETTINGS_FILE = "remote.json"

CERT_DIR = None
LOGS_DIR = None


def state_dir():
    return os.path.dirname(mc_servers.REGISTRY_FILE)


def cert_dir():
    if CERT_DIR:
        return CERT_DIR
    import mc_ipc
    return os.path.join(mc_ipc.RUN_DIR, "remote")


def logs_dir():
    return LOGS_DIR or os.path.join(BASE_DIR, "logs")


def _path(name):
    return os.path.join(state_dir(), name)


def _iso(ts=None):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts if ts is not None else time.time()))


_LOCK = threading.RLock()


@contextlib.contextmanager
def locked():
    """Serialises writers: threads of the daemon and, where flock exists, the CLI."""
    with _LOCK:
        handle = None
        try:
            import fcntl
            os.makedirs(state_dir(), exist_ok=True)
            handle = open(_path("remote.lock"), "a")
            fcntl.flock(handle, fcntl.LOCK_EX)
        except (ImportError, OSError):
            if handle:
                handle.close()
            handle = None
        try:
            yield
        finally:
            if handle:
                handle.close()


def _read(name, default):
    try:
        return mc_servers.read_json(_path(name), default)
    except mc_servers.DataFileError:
        return default


def _write(name, data):
    plat.write_private_file(_path(name), json.dumps(data, indent=2, ensure_ascii=False))


def hash_secret(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def fail(code, **data):
    return mc_api.result(False, code, **data)


# ── settings and bind address ────────────────────────────────────────────────

def parse_bind(text):
    """(host, port) from 'host:port' or '[v6]:port'; ValueError when invalid."""
    text = (text or "").strip()
    host, sep, port = text.rpartition(":")
    if not sep or not port.isdigit() or not 0 <= int(port) <= 65535:
        raise ValueError(text)
    host = host.strip("[]")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        raise ValueError(text) from None
    return host, int(port)


def load_settings():
    data = _read(SETTINGS_FILE, {})
    bind = data.get("bind") if isinstance(data.get("bind"), str) else DEFAULT_BIND
    try:
        parse_bind(bind)
    except ValueError:
        bind = DEFAULT_BIND
    return {"enabled": data.get("enabled") is True, "bind": bind}


def is_loopback(host):
    return ipaddress.ip_address(host).is_loopback


# ── certificate ──────────────────────────────────────────────────────────────

def cert_paths():
    folder = cert_dir()
    return os.path.join(folder, "cert.pem"), os.path.join(folder, "key.pem"), os.path.join(folder, "generator")


def have_cryptography():
    try:
        import cryptography.x509  # noqa: F401
        return True
    except ImportError:
        return False


def openssl_path():
    return shutil.which("openssl")


def format_fingerprint(der):
    digest = hashlib.sha256(der).hexdigest().upper()
    return ":".join(digest[i:i + 2] for i in range(0, len(digest), 2))


def certificate_info():
    cert, key, meta = cert_paths()
    if not (os.path.isfile(cert) and os.path.isfile(key)):
        return None
    try:
        with open(cert, encoding="ascii") as f:
            der = ssl.PEM_cert_to_DER_cert(f.read())
        with open(meta, encoding="ascii") as f:
            generator = f.read().strip() or None
    except (OSError, ValueError):
        generator = None
        try:
            with open(cert, encoding="ascii") as f:
                der = ssl.PEM_cert_to_DER_cert(f.read())
        except (OSError, ValueError):
            return None
    return {"cert": cert, "key": key, "fingerprint": format_fingerprint(der), "generator": generator}


def _host_name():
    return re.sub(r"[^A-Za-z0-9._-]", "-", socket.gethostname())[:60] or "mcmanager"


def _san_ip(bind_host):
    if bind_host and not ipaddress.ip_address(bind_host).is_unspecified:
        return bind_host
    return None


def _generate_cryptography(cert, key, host, ip):
    import datetime as dt
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    private = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, host)])
    names = [x509.DNSName(host)] + ([x509.IPAddress(ipaddress.ip_address(ip))] if ip else [])
    now = dt.datetime.now(dt.timezone.utc)
    certificate = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
                   .public_key(private.public_key()).serial_number(x509.random_serial_number())
                   .not_valid_before(now - dt.timedelta(days=1)).not_valid_after(now + dt.timedelta(days=CERT_DAYS))
                   .add_extension(x509.SubjectAlternativeName(names), critical=False)
                   .sign(private, hashes.SHA256()))
    plat.write_private_file(key, private.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode("ascii"))
    plat.write_private_file(cert, certificate.public_bytes(serialization.Encoding.PEM).decode("ascii"))
    return True


def _generate_openssl(cert, key, host, ip):
    san = f"subjectAltName=DNS:{host}" + (f",IP:{ip}" if ip else "")
    command = [openssl_path(), "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:P-256", "-nodes",
               "-keyout", key, "-out", cert, "-days", str(CERT_DAYS), "-subj", f"/CN={host}", "-addext", san]
    try:
        done = subprocess.run(command, capture_output=True, timeout=60, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    plat.secure_file(key)
    return done.returncode == 0 and os.path.isfile(cert) and os.path.isfile(key)


def generators():
    """Certificate generators available here, in order of preference."""
    found = []
    if have_cryptography():
        found.append(("cryptography", _generate_cryptography))
    if openssl_path():
        found.append(("openssl", _generate_openssl))
    return found


def ensure_certificate(bind_host=None, regenerate=False, prefer=None):
    """The certificate info, generating a self-signed one on first use; None when no generator works."""
    existing = None if regenerate else certificate_info()
    if existing:
        return existing
    options = [g for g in generators() if prefer in (None, g[0])]
    folder = cert_dir()
    os.makedirs(folder, exist_ok=True)
    plat.secure_dir(folder)
    cert, key, meta = cert_paths()
    for name, generate in options:
        try:
            done = generate(cert, key, _host_name(), _san_ip(bind_host))
        except Exception:
            done = False
        if done and os.path.isfile(cert) and os.path.isfile(key):
            plat.write_private_file(meta, name)
            return certificate_info()
        for leftover in (cert, key):
            with contextlib.suppress(OSError):
                os.remove(leftover)
    return None


# ── devices ──────────────────────────────────────────────────────────────────

_CACHE = {}


def _devices_doc():
    path = _path(DEVICES_FILE)
    try:
        stamp = os.stat(path)
        key = (stamp.st_mtime_ns, stamp.st_size)
    except OSError:
        return {}
    if _CACHE.get("path") == path and _CACHE.get("key") == key:
        return _CACHE["devices"]
    devices = _read(DEVICES_FILE, {}).get("devices", {})
    _CACHE.update(path=path, key=key, devices=devices)
    return devices


def _save_devices(devices):
    _write(DEVICES_FILE, {"devices": devices})
    _CACHE.clear()


def valid_roles(roles):
    """A normalised {'default', 'servers'} or None."""
    if not isinstance(roles, dict) or roles.get("default") not in ROLES:
        return None
    servers = roles.get("servers") or {}
    if not isinstance(servers, dict) or any(not isinstance(k, str) or v not in ROLES for k, v in servers.items()):
        return None
    return {"default": roles["default"], "servers": dict(servers)}


def valid_servers(servers):
    """(ok, list or None): None means every server."""
    if servers is None:
        return True, None
    if not isinstance(servers, list) or any(not isinstance(s, str) or not s for s in servers):
        return False, None
    return True, sorted(set(servers))


_SEEN = {}
_SEEN_STATE = {"flushed": 0.0}


def note_seen(device_id, ip):
    now = time.time()
    previous = _SEEN.get(device_id)
    _SEEN[device_id] = {"at": _iso(now), "ip": ip}
    if previous is None or previous["ip"] != ip or now - _SEEN_STATE["flushed"] >= SEEN_FLUSH_S:
        flush_seen()


def flush_seen():
    with locked():
        stored = _read(SEEN_FILE, {})
        stored.update(_SEEN)
        _write(SEEN_FILE, stored)
        _SEEN_STATE["flushed"] = time.time()


def _seen(device_id):
    return _SEEN.get(device_id) or _read(SEEN_FILE, {}).get(device_id) or {}


def public_device(device):
    seen = _seen(device["id"])
    return {"id": device["id"], "name": device["name"], "roles": device["roles"], "servers": device.get("servers"),
            "created_at": device["created_at"], "last_seen": seen.get("at"), "last_ip": seen.get("ip"),
            "revoked": bool(device.get("revoked"))}


def list_devices():
    return mc_api.result(True, "device_list",
                         devices=[public_device(d) for d in _devices_doc().values()])


def active_devices():
    return [d for d in _devices_doc().values() if not d.get("revoked")]


def authenticate(token):
    """The device owning a bearer token, or None. Compares against every stored hash."""
    supplied = hash_secret(token or "")
    found = None
    for device in _devices_doc().values():
        stored = device.get("token_hash") or ""
        if hmac.compare_digest(stored.encode(), supplied.encode()) and not device.get("revoked"):
            found = device
    return found


def device_active(device_id):
    device = _devices_doc().get(device_id)
    return bool(device) and not device.get("revoked")


def revoke_device(device_id):
    with locked():
        devices = dict(_read(DEVICES_FILE, {}).get("devices", {}))
        device = devices.get(device_id)
        if not device:
            return fail("device_not_found", id=device_id)
        device = dict(device, revoked=True, revoked_at=_iso(), token_hash=None)
        devices[device_id] = device
        _save_devices(devices)
    return mc_api.result(True, "device_revoked", id=device_id)


def set_device_roles(device_id, roles, servers=False):
    parsed = valid_roles(roles)
    if parsed is None:
        return fail("bad_roles")
    allowed = None
    if servers is not False:
        ok, allowed = valid_servers(servers)
        if not ok:
            return fail("bad_servers")
    with locked():
        devices = dict(_read(DEVICES_FILE, {}).get("devices", {}))
        device = devices.get(device_id)
        if not device:
            return fail("device_not_found", id=device_id)
        if device.get("revoked"):
            return fail("device_revoked", id=device_id)
        device = dict(device, roles=parsed)
        if servers is not False:
            device["servers"] = allowed
        devices[device_id] = device
        _save_devices(devices)
    return mc_api.result(True, "device_updated", **public_device(device))


def effective_role(device, server):
    roles = device["roles"]
    return roles.get("servers", {}).get(server, roles["default"]) if server else roles["default"]


def allowed_servers(device):
    return device.get("servers")


def may_use_server(device, server):
    allowed = device.get("servers")
    return allowed is None or server in allowed


def rank(role):
    return ROLES.index(role) if role in ROLES else -1


# ── pairing ──────────────────────────────────────────────────────────────────

_PAIRING = {"locks": {}}
_PAIRING_LOCK = threading.Lock()


def create_code(role="operator", servers=None, name=None):
    if role not in ROLES:
        return fail("bad_role", role=role)
    ok, allowed = valid_servers(servers)
    if not ok:
        return fail("bad_servers")
    if allowed is not None:
        known = mc_servers.load_registry().get("servers", {})
        missing = [s for s in allowed if s not in known]
        if missing:
            return fail("bad_servers", servers=missing, message="Unknown server: " + ", ".join(missing))
    code = "%08d" % secrets.randbelow(10 ** 8)
    salt = secrets.token_hex(8)
    with locked():
        _write(CODES_FILE, {"salt": salt, "hash": hash_secret(salt + code), "role": role, "servers": allowed,
                            "name": name if isinstance(name, str) else None, "expires": time.time() + CODE_TTL_S, "fails": 0})
    return mc_api.result(True, "pair_code", pairing_code=code, expires_in_s=CODE_TTL_S, role=role, servers=allowed)


def _clear_code():
    with contextlib.suppress(OSError):
        os.remove(_path(CODES_FILE))


def pair_lock_state(ip, now):
    entry = _PAIRING["locks"].get(ip)
    if entry and entry["until"] > now:
        return int(entry["until"] - now) + 1
    if entry and entry["until"]:
        _PAIRING["locks"].pop(ip, None)
    return 0


def _note_failure(ip, now):
    entry = _PAIRING["locks"].setdefault(ip, {"count": 0, "until": 0})
    entry["count"] += 1
    if entry["count"] >= PAIR_LOCK_AFTER:
        entry.update(count=0, until=now + PAIR_LOCK_S)


def pair(code, name, ip):
    """Exchange a pairing code for a device token. Every attempt takes at least PAIR_DELAY_S."""
    started = time.monotonic()
    try:
        return _pair(code, name, ip)
    finally:
        rest = PAIR_DELAY_S - (time.monotonic() - started)
        if rest > 0:
            time.sleep(rest)


def _pair(code, name, ip):
    now = time.time()
    with _PAIRING_LOCK:
        wait = pair_lock_state(ip, now)
        if wait:
            return fail("pair_locked", retry_after_s=wait)
        with locked():
            entry = _read(CODES_FILE, None)
            valid = bool(entry) and entry.get("expires", 0) > now
            candidate = hash_secret((entry or {}).get("salt", "") + str(code))
            matches = hmac.compare_digest(candidate.encode(), str((entry or {}).get("hash", "")).encode())
            if valid and matches and re.fullmatch(r"[0-9]{8}", str(code)):
                _clear_code()
                device_id, token = _new_device(name, entry)
                _PAIRING["locks"].pop(ip, None)
                return mc_api.result(True, "paired", device_id=device_id, token=token, roles={
                    "default": entry["role"]}, servers=entry.get("servers"))
            _note_failure(ip, now)
            if entry and not valid:
                _clear_code()
            elif entry:
                entry["fails"] = entry.get("fails", 0) + 1
                if entry["fails"] >= CODE_MAX_FAILS:
                    _clear_code()
                else:
                    _write(CODES_FILE, entry)
        return fail("bad_pair_code")


def _new_device(name, entry):
    devices = dict(_read(DEVICES_FILE, {}).get("devices", {}))
    device_id = "d_" + secrets.token_hex(4)
    while device_id in devices:
        device_id = "d_" + secrets.token_hex(4)
    token = secrets.token_urlsafe(32)
    devices[device_id] = {"id": device_id, "name": (name or entry.get("name") or "device")[:80], "token_hash": hash_secret(token),
                          "roles": {"default": entry["role"], "servers": {}}, "servers": entry.get("servers"),
                          "created_at": _iso(), "revoked": False}
    _save_devices(devices)
    return device_id, token


# ── request limits ───────────────────────────────────────────────────────────

class Gate:
    """What the remote application asks for each request: identity, rate, liveness."""

    def __init__(self, clock=time.monotonic, limit=RATE_LIMIT, window=RATE_WINDOW_S):
        self.clock = clock
        self.limit = limit
        self.window = window
        self.hits = collections.defaultdict(collections.deque)
        self.lock = threading.Lock()

    def identify(self, request):
        header = request.headers.get("authorization", "")
        scheme, _, supplied = header.partition(" ")
        if scheme.lower() != "bearer":
            return None
        return authenticate(supplied.strip())

    def allow(self, device_id):
        """(True, 0) or (False, seconds to wait)."""
        now = self.clock()
        with self.lock:
            hits = self.hits[device_id]
            while hits and now - hits[0] >= self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return False, max(0.0, self.window - (now - hits[0]))
            hits.append(now)
        return True, 0

    def active(self, device_id):
        return device_active(device_id)


# ── audit ────────────────────────────────────────────────────────────────────

_AUDIT_LOCK = threading.Lock()


def audit_path():
    return os.path.join(logs_dir(), "audit.log")


def audit(device, ip, method, operation, server, status, code=None):
    line = json.dumps({"at": _iso(), "device": device, "ip": ip, "method": method, "op": operation,
                       "server": server, "status": status, "code": code}, ensure_ascii=False)
    path = audit_path()
    with _AUDIT_LOCK:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            if os.path.getsize(path) >= AUDIT_MAX:
                os.replace(path, path + ".1")
        except OSError:
            pass
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def read_audit(limit=100, device=None, server=None):
    entries = []
    path = audit_path()
    with _AUDIT_LOCK:
        for name in (path, path + ".1"):
            try:
                with open(name, encoding="utf-8", errors="replace") as f:
                    lines = f.read().splitlines()
            except OSError:
                continue
            for text in reversed(lines):
                try:
                    row = json.loads(text)
                except ValueError:
                    continue
                if device is not None and row.get("device") != device:
                    continue
                if server is not None and row.get("server") != server:
                    continue
                entries.append({"at": row.get("at"), "action": row.get("op") or "unknown",
                                "device": row.get("device"), "server": row.get("server"),
                                "ok": isinstance(row.get("status"), int) and row["status"] < 400,
                                "result": row.get("code") or str(row.get("status")), "ip": row.get("ip"),
                                "status": row.get("status")})
                if len(entries) >= limit:
                    return entries
    return entries


# ── enabling ─────────────────────────────────────────────────────────────────

def status_document(code="remote_status"):
    settings = load_settings()
    info = certificate_info()
    return mc_api.result(True, code, enabled=settings["enabled"], bind=settings["bind"] if settings["enabled"] else None,
                         devices=len(active_devices()), fingerprint=info["fingerprint"] if info else None,
                         tls=info["generator"] if info else None)


def _manage_firewall(port, old_port, opening):
    if opening:
        ok, manual = _firewall().ensure_game_port_rule(port, old_port=old_port, name=FIREWALL_LABEL)
        return ("opened", None) if ok else ("manual", manual)
    _firewall().remove_rule(port, name=FIREWALL_LABEL)
    return "closed", None


def _firewall():
    import mc_firewall
    return mc_firewall


def set_access(enabled, bind=None, prefer=None):
    before = load_settings()
    if not enabled:
        with locked():
            _write(SETTINGS_FILE, {"enabled": False, "bind": before["bind"]})
        host, port = parse_bind(before["bind"])
        state, manual = "skipped", None
        if before["enabled"] and port and not is_loopback(host):
            state, manual = _manage_firewall(port, None, False)
        return dict(status_document("remote_disabled"), firewall=state)
    try:
        host, port = parse_bind(bind or before["bind"])
    except ValueError:
        return fail("bad_bind", bind=bind)
    info = ensure_certificate(host, prefer=prefer)
    if info is None:
        return fail("tls_unavailable")
    with locked():
        _write(SETTINGS_FILE, {"enabled": True, "bind": f"{host}:{port}" if ":" not in host else f"[{host}]:{port}"})
    state, manual = "skipped", None
    if port and not is_loopback(host):
        old = parse_bind(before["bind"])[1] if before["enabled"] else None
        state, manual = _manage_firewall(port, old, True)
    out = dict(status_document("remote_enabled"), firewall=state)
    if manual:
        out["firewall_command"] = manual
    return out
