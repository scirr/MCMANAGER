"""
mc_crash.py — Crash-loop detection for the daemon.

A server that dies before finishing its startup ("Done" in the log) would be
relaunched every tick forever. Failures are recorded in a marker file inside
the server folder (the CLI and the daemon are separate processes): a startup
failure, or MAX_FAILURES unplanned exits within WINDOW seconds, marks the
server as crashed and the daemon stops relaunching it until 'mc resume'.
"""
import json
import os
import re
import time
from mc_platform import plat

MARKER = ".mcmanager_crash.json"
WINDOW = 600
MAX_FAILURES = 3
BACKOFF_BASE = 60
BACKOFF_MAX = 1800
ERROR_LINES = 10

_ERROR = re.compile(r"/(?:ERROR|FATAL)\]|^\s*(?:ERROR|FATAL)\b")


def marker_path(config):
    return os.path.join(config.get("dossier_serveur", ""), MARKER)


def read(config):
    try:
        with open(marker_path(config), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _write(config, data):
    path = marker_path(config)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f)
    plat.atomic_replace(tmp, path)


def clear(config):
    """Forget every recorded failure. Returns True if a marker existed."""
    try:
        os.remove(marker_path(config))
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return False


def is_crashed(config):
    data = read(config)
    return bool(data and data.get("crashed"))


def record_failure(config, startup, now=None):
    """Record one unplanned exit. `startup` is True when the JVM died before
    finishing its startup. Returns (marker, newly_crashed)."""
    now = now or time.time()
    data = read(config) or {}
    already = bool(data.get("crashed"))
    failures = [t for t in data.get("failures", []) if now - t <= WINDOW] + [now]
    crashed = already or startup or len(failures) >= MAX_FAILURES
    delay = 0 if len(failures) <= 1 else min(BACKOFF_MAX, BACKOFF_BASE * 2 ** (len(failures) - 2))
    data.update({
        "failures": failures,
        "crashed": crashed,
        "startup": bool(startup) or bool(data.get("startup")),
        "since": data.get("since") if already else now,
        "last": now,
        "retry_at": now + delay,
    })
    _write(config, data)
    return data, crashed and not already


def may_start(config, now=None):
    """False while the server is marked crashed or inside its backoff delay."""
    data = read(config)
    if not data:
        return True
    if data.get("crashed"):
        return False
    return (now or time.time()) >= data.get("retry_at", 0)


def recent_errors(dossier, count=ERROR_LINES):
    """The last ERROR/FATAL lines of logs/latest.log."""
    try:
        with open(os.path.join(dossier, "logs", "latest.log"), "r",
                  encoding="utf-8", errors="replace") as f:
            lines = f.readlines()[-5000:]
    except OSError:
        return []
    found = [line.rstrip() for line in lines if _ERROR.search(line)]
    return found[-count:]
