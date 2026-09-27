"""
mc_api.py — Machine-facing building blocks: explicit server states, JSON
snapshots, player list, one-shot RCON, world freeze/thaw.

Everything here returns plain data; mc_cli decides how to print it (human
text or --json). The JSON shapes are a public, versioned contract
(SCHEMA_VERSION): fields may be added, never renamed or removed within a
major schema version.
"""
import json
import os
import re
import socket
import sys
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(BASE_DIR)

import mc_config
import mc_core
import mc_servers

SCHEMA_VERSION = 1

# Why a server was stopped (config.json "stop_reason", written by
# 'mc stop --reason'). Absent means "user", the historical meaning.
STOP_REASONS = ("user", "sleep", "update", "maintenance", "switch")

# Explicit states derived from the process, the port and config.json.
#   running          process alive and the game port is listening
#   starting         process alive, game port not listening yet
#   stopped          not running, the daemon will start it (24/7, or opening hours)
#   closed           not running, schedule mode outside opening hours
#   stopped-by-user  not running, maintenance flag set by 'mc stop' (reason user)
#   sleeping         not running, stopped with 'mc stop --reason sleep'
#   maintenance      not running, maintenance for another reason
#                    ('mc mode maintenance', --reason update/maintenance/switch)
STATES = ("running", "starting", "stopped", "closed", "stopped-by-user", "sleeping", "maintenance")

FROZEN_MARKER = ".mcmanager_frozen"
DEFAULT_FREEZE_MAX = 3600


# ── durations ────────────────────────────────────────────────────────────────

def parse_duration(text):
    """'90' / '90s' / '30m' / '2h' / '1h30m' -> seconds. ValueError if invalid."""
    s = str(text).strip().lower()
    if s.isdigit():
        return int(s)
    parts = re.findall(r"(\d+)\s*([hms])", s)
    if not parts or re.sub(r"\d+\s*[hms]", "", s).strip():
        raise ValueError(text)
    return sum(int(n) * {"h": 3600, "m": 60, "s": 1}[u] for n, u in parts)


# ── process details ──────────────────────────────────────────────────────────

def _uptime_seconds(pid):
    """Seconds since the process started, or None."""
    try:
        with open(f"/proc/{pid}/stat") as f:
            fields = f.read().rsplit(")", 1)[1].split()
        start_ticks = int(fields[19])  # field 22 of stat, 0-based after 'comm'
        with open("/proc/uptime") as f:
            boot_uptime = float(f.read().split()[0])
        return max(0, int(boot_uptime - start_ticks / os.sysconf("SC_CLK_TCK")))
    except Exception:
        return None


def _is_listening(port):
    """True if something accepts connections on 127.0.0.1:port."""
    if not port:
        return False
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=1):
            return True
    except OSError:
        return False


def _main_pid(config):
    """The server JVM's PID (preferred over the run.sh wrapper), or the
    recorded PID, or None."""
    dossier = config.get("dossier_serveur", "")
    java = mc_core.server_java_pids(dossier)
    if java:
        return java[0]
    return mc_core.get_server_pid(config)


# ── state ────────────────────────────────────────────────────────────────────

def _should_be_open(config, now=None):
    if config.get("always_on", 1) == 1:
        return True
    return mc_core.is_open_now(config, now)


def server_state(config, now=None):
    """Explicit state of one server (see STATES)."""
    running = mc_core.is_server_running(config)
    maintenance = config.get("mode_maintenance", 0) == 1
    if running:
        return "running" if _is_listening(config.get("port")) else "starting"
    if maintenance:
        reason = config.get("stop_reason") or "user"
        if reason == "sleep":
            return "sleeping"
        if reason == "user":
            return "stopped-by-user"
        return "maintenance"
    return "stopped" if _should_be_open(config, now) else "closed"


def server_snapshot(name, info, active_name=None):
    """Everything a script needs to know about one server, as plain data."""
    dossier = info.get("dossier_serveur", "")
    snap = {
        "name": name,
        "id": info.get("id"),
        "active": name == active_name,
        "path": dossier,
        "state": None,
        "error": None,
    }
    if not dossier or not os.path.isdir(dossier):
        snap["error"] = {"code": "folder_missing", "detail": dossier}
        return snap
    try:
        config = mc_config.load_config(dossier)
    except mc_servers.DataFileError as e:
        snap["error"] = {"code": "config_unreadable", "detail": e.detail, "file": e.path}
        return snap
    config["dossier_serveur"] = dossier

    state = server_state(config)
    loader, version = mc_core.guess_loader_and_version(config)
    snap.update({
        "state": state,
        "mode": mc_core.effective_mode(config),
        "maintenance": config.get("mode_maintenance", 0) == 1,
        "stop_reason": config.get("stop_reason"),
        "port": config.get("port", info.get("port")),
        "rcon_port": config.get("rcon_port", info.get("rcon_port")),
        "loader": loader,
        "version": version,
        "frozen": is_frozen(config),
        "pid": None,
        "uptime_s": None,
        "rss_kb": None,
        "swap_kb": None,
        "cgroup": None,
        "port_holder": None,
    })
    if config.get("always_on", 1) != 1:
        snap["schedule"] = {
            "open": "%02d:%02d" % (int(config.get("heure_ouverture", 20)), int(config.get("minute_ouverture", 0))),
            "close": "%02d:%02d" % (int(config.get("heure_fermeture", 3)), int(config.get("minute_fermeture", 0))),
        }
    if state in ("running", "starting"):
        pid = _main_pid(config)
        snap["pid"] = pid
        if pid:
            snap["uptime_s"] = _uptime_seconds(pid)
            snap["rss_kb"], snap["swap_kb"] = mc_core.proc_memory(pid)
            snap["cgroup"] = mc_core.proc_cgroup(pid)
    elif snap["port"]:
        occupant = mc_core.port_occupant(snap["port"])
        if occupant:
            snap["port_holder"] = {"pid": occupant[0], "program": occupant[1]}
    return snap


def status_document(target_name=None):
    """{"schema": 1, "servers": [...]} for all servers or one."""
    registry = mc_servers.load_registry()
    servers = registry.get("servers", {})
    if target_name is not None:
        servers = {target_name: servers[target_name]}
    active = registry.get("active")
    return {
        "schema": SCHEMA_VERSION,
        "active": active,
        "servers": [server_snapshot(n, i, active) for n, i in servers.items()],
    }


# ── RCON ─────────────────────────────────────────────────────────────────────

def rcon_exec(config, command):
    """Run one command over RCON and return (ok, response_or_error)."""
    ok, sock_or_msg = mc_core.rcon_handshake(
        "127.0.0.1", config.get("rcon_port", mc_core.DEFAULT_RCON_PORT),
        config.get("mcrcon_pass", ""), ping_only=False)
    if not ok:
        return False, sock_or_msg
    sock = sock_or_msg
    try:
        sock.settimeout(5)
        return True, mc_core.rcon_command(sock, command)
    except Exception as e:
        return False, str(e)
    finally:
        try:
            sock.close()
        except Exception:
            pass


_FORMATTING = re.compile(r"§.")
_COUNTS = re.compile(r"(\d+)\s*(?:/|of a max of|out of maximum|sur)\s*(\d+)", re.IGNORECASE)


def parse_player_list(text):
    """Parse the reply to 'list', whatever the server flavour:
      vanilla 1.13+      "There are 1 of a max of 20 players online: Steve"
      older / Paper      "There are 1/20 players online:" (names on the next line)
      Essentials-likes   "Online players (1/20): Steve, Alex"
    Returns (online, max, [names]); (None, None, []) if no count is found.
    """
    clean = _FORMATTING.sub("", text or "").strip()
    match = _COUNTS.search(clean)
    if not match:
        return None, None, []
    online, maximum = int(match.group(1)), int(match.group(2))
    names = []
    rest = clean[match.end():]
    if ":" in rest:
        tail = rest.split(":", 1)[1]
        for chunk in re.split(r"[,\n]", tail):
            name = chunk.strip()
            # Group prefixes ("default: Steve") are dropped, the name is kept.
            if ":" in name:
                name = name.rsplit(":", 1)[1].strip()
            if re.fullmatch(r"[A-Za-z0-9_.\-*]{1,32}", name or ""):
                names.append(name)
    return online, maximum, names


def query_players(config):
    """(ok, data_or_error). data = {"online", "max", "players"}."""
    ok, reply = rcon_exec(config, "list")
    if not ok:
        return False, reply
    online, maximum, names = parse_player_list(reply)
    if online is None:
        return False, reply
    return True, {"online": online, "max": maximum, "players": names}


# ── freeze / thaw ────────────────────────────────────────────────────────────

def _marker_path(config):
    return os.path.join(config.get("dossier_serveur", ""), FROZEN_MARKER)


def read_freeze(config):
    """The freeze marker ({"since", "expires"}) or None."""
    try:
        with open(_marker_path(config), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def is_frozen(config):
    return os.path.exists(_marker_path(config))


def freeze(config, max_seconds=DEFAULT_FREEZE_MAX):
    """Stop world saving so an external tool can copy a consistent world.

    'save-off' then 'save-all flush': from here on the files on disk are
    complete and do not change. A marker file makes the freeze exclusive and
    records a deadline: the daemon thaws automatically once it is passed, so
    a backup script that dies can never leave the world unsaved for good.
    Returns (ok, code) with code in: frozen, already_frozen, offline, rcon_error.
    """
    path = _marker_path(config)
    now = int(time.time())
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        return False, "already_frozen"
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"since": now, "expires": now + int(max_seconds), "pid": os.getpid()}, f)
    if not mc_core.is_server_running(config):
        return True, "offline"
    if not mc_core.send_rcon(config, "save-off") or not mc_core.send_rcon(config, "save-all flush"):
        _remove_marker(config)
        mc_core.send_rcon(config, "save-on")
        return False, "rcon_error"
    return True, "frozen"


def _remove_marker(config):
    try:
        os.remove(_marker_path(config))
    except FileNotFoundError:
        pass


def thaw(config):
    """Re-enable world saving. Safe to call when not frozen.
    Returns (ok, code) with code in: thawed, not_frozen, offline, rcon_error."""
    was_frozen = is_frozen(config)
    if not mc_core.is_server_running(config):
        _remove_marker(config)
        return True, "offline"
    sent = mc_core.send_rcon(config, "save-on")
    if not sent:
        return False, "rcon_error"   # keep the marker: the daemon retries
    _remove_marker(config)
    return True, "thawed" if was_frozen else "not_frozen"


def freeze_expired(config, now=None):
    marker = read_freeze(config)
    if marker is None:
        return is_frozen(config)     # unreadable marker: treat as expired
    return (now or time.time()) >= marker.get("expires", 0)
