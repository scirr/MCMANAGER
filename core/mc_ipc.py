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
from mc_platform import plat

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RUN_DIR = os.environ.get("MCMANAGER_RUN_DIR") or os.path.join(BASE_DIR, "run")
REQUESTS_DIR = os.path.join(RUN_DIR, "requests")
RESPONSES_DIR = os.path.join(RUN_DIR, "responses")
HEARTBEAT_FILE = os.path.join(RUN_DIR, "daemon.heartbeat")

HEARTBEAT_MAX_AGE = 5      # seconds: older means no daemon is listening
REQUEST_MAX_AGE = 300      # the daemon drops requests nobody waits for anymore


def _private_dir(path):
    """Create run/ and its sub-folders readable by their owner only, owned like
    the application folder (a request made with sudo must not lock the service
    out)."""
    for folder in (RUN_DIR, path):
        if not os.path.isdir(folder):
            os.makedirs(folder, mode=0o700, exist_ok=True)
            plat.secure_dir(folder, owner_of=BASE_DIR)
        else:
            plat.secure_dir(folder)


def _write_atomic(path, data):
    _private_dir(os.path.dirname(path))
    plat.write_private_file(path, json.dumps(data), 0o644)


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
        return plat.process_alive(int(hb.get("pid")))
    except Exception:
        return False


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
