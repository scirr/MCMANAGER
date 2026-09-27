"""
mc_ipc.py — Request channel between the CLI (or any front end) and the daemon.

Some actions must run inside the daemon: a server started from a terminal
would otherwise be a child of the user's shell, outside the service's cgroup
(no MemorySwapMax, no KillMode protection), and only the daemon owns the
sleep listeners that hold a sleeping server's port.

The channel is a spool directory: a client drops requests/<id>.json, the
daemon answers in responses/<id>.json. Files are written atomically, so no
partial read is possible. The daemon refreshes a heartbeat file every second;
a client only uses the channel when that heartbeat is fresh.
"""
import json
import os
import time
import uuid

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RUN_DIR = os.path.join(BASE_DIR, "run")
REQUESTS_DIR = os.path.join(RUN_DIR, "requests")
RESPONSES_DIR = os.path.join(RUN_DIR, "responses")
HEARTBEAT_FILE = os.path.join(RUN_DIR, "daemon.heartbeat")

HEARTBEAT_MAX_AGE = 5      # seconds: older means no daemon is listening
REQUEST_MAX_AGE = 300      # the daemon drops requests nobody waits for anymore


def _write_atomic(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.chmod(tmp, 0o666)   # a request made with sudo must stay removable by the daemon user
    os.replace(tmp, path)


def _read(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


# ── daemon side ──────────────────────────────────────────────────────────────

def beat():
    try:
        _write_atomic(HEARTBEAT_FILE, {"pid": os.getpid(), "at": time.time()})
    except Exception:
        pass


def pending_requests():
    """[(id, request)] oldest first. Stale or unreadable requests are dropped."""
    try:
        names = sorted(os.listdir(REQUESTS_DIR),
                       key=lambda n: os.path.getmtime(os.path.join(REQUESTS_DIR, n)))
    except Exception:
        return []
    out = []
    for name in names:
        if not name.endswith(".json"):
            continue
        path = os.path.join(REQUESTS_DIR, name)
        req = _read(path)
        try:
            os.remove(path)
        except Exception:
            pass
        if not req or time.time() - req.get("at", 0) > REQUEST_MAX_AGE:
            continue
        out.append((name[:-5], req))
    return out


def respond(request_id, result):
    _write_atomic(os.path.join(RESPONSES_DIR, f"{request_id}.json"), result)


# ── client side ──────────────────────────────────────────────────────────────

def daemon_listening():
    hb = _read(HEARTBEAT_FILE)
    if not hb:
        return False
    if time.time() - hb.get("at", 0) > HEARTBEAT_MAX_AGE:
        return False
    try:
        os.kill(int(hb.get("pid")), 0)
    except PermissionError:
        pass
    except Exception:
        return False
    return True


def call(action, timeout=120, **params):
    """Send a request and wait for the daemon's answer. Returns the result
    dict, or None if the daemon did not answer in time."""
    request_id = uuid.uuid4().hex
    _write_atomic(os.path.join(REQUESTS_DIR, f"{request_id}.json"),
                  {"action": action, "params": params, "at": time.time()})
    answer = os.path.join(RESPONSES_DIR, f"{request_id}.json")
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = _read(answer)
        if result is not None:
            try:
                os.remove(answer)
            except Exception:
                pass
            return result
        time.sleep(0.2)
    # Withdraw the request if the daemon has not picked it up yet.
    try:
        os.remove(os.path.join(REQUESTS_DIR, f"{request_id}.json"))
    except Exception:
        pass
    return None
