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
import mc_crash
import mc_servers
from mc_lang import T
from mc_platform import plat

SCHEMA_VERSION = 1

# Why a server was stopped (config.json "stop_reason", written by
# 'mc stop --reason'). Absent means "user", the historical meaning.
STOP_REASONS = ("user", "sleep", "update", "maintenance", "switch", "scheduled")

# Explicit states derived from the process, the port and config.json.
#   running          process alive, game port listening and RCON answering
#   starting         process alive, still starting (RCON opens at "Done")
#   crashed          not running, died during startup or in a crash loop: the
#                    daemon no longer relaunches it ('mc resume' does)
#   stopped          not running, the daemon will start it (24/7, or opening hours)
#   closed           not running, schedule mode outside opening hours
#   stopped-by-user  not running, maintenance flag set by 'mc stop' (reason user)
#   sleeping         not running, stopped with 'mc stop --reason sleep'
#   maintenance      not running, maintenance for another reason
#                    ('mc mode maintenance', --reason update/maintenance/switch/scheduled)
STATES = ("running", "starting", "crashed", "stopped", "closed", "stopped-by-user", "sleeping", "maintenance")

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

_uptime_seconds = mc_core.proc_uptime


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
        if mc_core.is_suspended(config):
            return "sleeping"
        ready = _is_listening(mc_core.game_port(config)) and mc_core.server_ready(config)
        return "running" if ready else "starting"
    if maintenance:
        reason = config.get("stop_reason") or "user"
        if reason == "sleep":
            return "sleeping"
        if reason == "user":
            return "stopped-by-user"
        return "maintenance"
    if mc_crash.is_crashed(config):
        return "crashed"
    return "stopped" if _should_be_open(config, now) else "closed"


def server_snapshot(name, info, active_name=None):
    """Everything a script needs to know about one server, as plain data."""
    dossier = info.get("dossier_serveur", "")
    snap = {
        "name": name,
        "server": name,
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
        "frozen_since_ts": (read_freeze(config) or {}).get("since"),
        "frozen_expires_ts": (read_freeze(config) or {}).get("expires"),
        "suspended": mc_core.is_suspended(config) if state == "sleeping" else False,
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
    if mc_core.is_hold_mode(config):
        snap["internal_port"] = mc_core.game_port(config)
    if state in ("running", "starting") or snap["suspended"]:
        pid = _main_pid(config)
        snap["pid"] = pid
        if pid:
            snap["uptime_s"] = _uptime_seconds(pid)
            snap["rss_kb"], snap["swap_kb"] = mc_core.proc_memory(pid)
            snap["cgroup"] = mc_core.proc_cgroup(pid)
    elif snap["port"]:
        occupant = mc_core.port_occupant(snap["port"])
        if state == "sleeping":
            # Held by the daemon's sleep listener, which is the expected case.
            snap["sleep_listener"] = occupant is not None
        elif occupant:
            snap["port_holder"] = {"pid": occupant[0], "program": occupant[1]}
    snap["sleep"] = sleep_info(config)
    if state == "crashed":
        marker = mc_crash.read(config) or {}
        snap["crash"] = {
            "since": marker.get("since"),
            "since_ts": marker.get("since"),
            "failures": len(marker.get("failures", [])),
            "startup": bool(marker.get("startup")),
            "errors": mc_crash.recent_errors(dossier),
        }
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
        "ok": True,
        "code": "status",
        "active": active,
        "servers": [server_snapshot(n, i, active) for n, i in servers.items()],
    }


# ── RCON ─────────────────────────────────────────────────────────────────────

RCON_RETRY = 5


def rcon_exec(config, command, wait=0):
    """Run one command over RCON and return (ok, response_or_error). With
    `wait`, a refused connection is retried for that many seconds: RCON only
    opens when the server finishes starting."""
    deadline = time.time() + wait
    while True:
        ok, sock_or_msg = mc_core.rcon_handshake(
            "127.0.0.1", config.get("rcon_port", mc_core.DEFAULT_RCON_PORT),
            config.get("mcrcon_pass", ""), ping_only=False)
        if ok or time.time() >= deadline or sock_or_msg == T["rcon_auth_failed"]:
            break
        time.sleep(1)
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


def query_players(config, wait=0):
    """(ok, data_or_error). data = {"online", "max", "players"}."""
    ok, reply = rcon_exec(config, "list", wait=wait)
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
    if not mc_core.is_server_running(config) or mc_core.is_suspended(config):
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
    if not mc_core.is_server_running(config) or mc_core.is_suspended(config):
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


# ══════════════════════════════════════════════════════════════════════════════
# Operations — the single entry point for every front end (CLI today, GUI
# tomorrow). Each returns result(): {"ok": bool, "code": str, ...data}. Codes
# are stable identifiers; front ends turn them into text in their own
# language. Nothing here prints.
# ══════════════════════════════════════════════════════════════════════════════

# True inside the daemon process: operations then act directly instead of
# going through the daemon's request channel.
IN_DAEMON = False


def result(ok, code, **data):
    return {"ok": ok, "code": code, **data}


def load_server(target=None):
    """(name, config) for a target (name, number or None = active server), or
    a failure result. Never prints."""
    registry = mc_servers.load_registry()
    servers = registry.get("servers", {})
    if not servers:
        return None, result(False, "no_server")
    name = registry.get("active") if target is None else mc_servers._lookup_key(servers, target)
    if not name or name not in servers:
        return None, result(False, "not_found", target=target,
                            available=[f"{i.get('id')}:{n}" for n, i in servers.items()])
    dossier = servers[name].get("dossier_serveur", "")
    if not dossier or not os.path.isdir(dossier):
        return None, result(False, "folder_missing", server=name, path=dossier)
    config = mc_config.load_config(dossier)
    config["dossier_serveur"] = dossier
    return (name, config), None


# ── start / stop ─────────────────────────────────────────────────────────────

def start(name, config):
    """Start a server. When the daemon is running, it launches the JVM itself,
    so the server lives in the service's cgroup (memory limits, KillMode) and
    never as a child of the caller's shell; otherwise the JVM is launched
    directly and the result says so (outside_service=True)."""
    import mc_ipc
    if mc_core.is_server_running(config):
        return result(True, "already_running", server=name)
    if not IN_DAEMON and mc_ipc.daemon_listening():
        answer = mc_ipc.call("start", server=name)
        if answer is None:
            return result(False, "daemon_timeout", server=name)
        return answer
    ok, msg = mc_core.start_server(config)
    return result(ok, "started" if ok else "start_failed", server=name, message=msg,
                  outside_service=not IN_DAEMON)


def freeze_op(name, config, max_seconds=DEFAULT_FREEZE_MAX):
    ok, code = freeze(config, max_seconds)
    marker = read_freeze(config) or {}
    return result(ok, code, server=name, max_s=int(max_seconds),
                  since_ts=marker.get("since") if ok else None,
                  expires_ts=marker.get("expires") if ok else None)


def thaw_op(name, config):
    ok, code = thaw(config)
    return result(ok, code, server=name)


def use(target):
    if not mc_servers.set_active(target):
        return result(False, "not_found", target=target)
    name = mc_servers.get_active_name()
    return result(True, "active_set", server=name, id=mc_servers.list_servers().get(name, {}).get("id"))


def remove(target, confirmed=False):
    registry = mc_servers.load_registry()
    key = mc_servers._lookup_key(registry.get("servers", {}), target)
    if not key:
        return result(False, "not_found", target=target)
    if not confirmed:
        return result(False, "confirm_required", server=key)
    ok, removed, folder = mc_servers.remove_server(target)
    if not ok:
        return result(False, "not_found", target=target)
    return result(True, "deregistered", server=removed, path=folder, active=mc_servers.get_active_name())


def set_mode(name, config, value):
    setter = {"schedule": mc_config.set_mode_schedule, "always-on": mc_config.set_mode_always_on,
              "maintenance": mc_config.set_mode_maintenance}[value]
    config = setter(config)
    mc_config.save_config(config)
    return result(True, "mode_set", server=name, mode=value)


def resume(name, config):
    """Leave maintenance. A crashed server is restarted explicitly; any other
    stopped server is handed back to the daemon."""
    was_crashed = mc_crash.clear(config)
    config = mc_config.resume_mode(config)
    mc_config.save_config(config)
    running = mc_core.is_server_running(config)
    started = None
    if not running and was_crashed:
        started = start(name, config)
    return result(True, "resumed", server=name, mode=mc_core.effective_mode(config),
                  was_crashed=bool(was_crashed), running=running, start=started)


def backup_now(name, config):
    ok, message = mc_core.backup_server(config)
    latest = None
    if ok:
        import mc_backup
        found = mc_backup.list_backups(config.get("dossier_backup", ""))
        latest = found[0] if found else None
    return result(ok, "backup_created" if ok else "backup_error", server=name, message=message,
                  backup=latest["id"] if latest else None, path=latest["path"] if latest else None,
                  created_ts=latest["created_ts"] if latest else None)


def log_lines(name=None, count=30):
    log_file = os.path.join(BASE_DIR, "logs", "daemon.log")
    if not os.path.exists(log_file):
        return result(False, "no_log_file", server=name)
    with open(log_file, "r", encoding="utf-8", errors="replace") as f:
        lines = f.read().splitlines()
    if name is not None:
        lines = [line for line in lines if f"[{name}]" in line]
    return result(True, "logs", server=name, lines=lines[-count:])


def stop(name, config, reason=None, quiet=False, force=False):
    """Stop a server and hand it over to maintenance with a recorded reason
    (mode_maintenance = 1 is what makes the daemon leave it alone)."""
    reason = reason or "user"
    if reason not in STOP_REASONS:
        return result(False, "bad_reason", reason=reason)
    message = None
    if mc_core.is_server_running(config):
        if force:
            if not mc_core.force_kill_server(config):
                return result(False, "still_running", server=name)
            code = "killed"
        else:
            ok, message = mc_core.stop_server(config, reason=reason, quiet=quiet)
            if not ok:
                return result(False, "stop_failed", server=name, message=message)
            code = "stopped"
    else:
        code = "already_stopped"
    config["mode_maintenance"] = 1
    config["stop_reason"] = reason
    mc_config.save_config(config)
    if is_frozen(config):
        thaw(config)
    return result(True, code, server=name, reason=reason, message=message)


# ── switch ───────────────────────────────────────────────────────────────────

def _free_rcon_port(start_at, taken):
    port = int(start_at) + 1
    while port in taken or mc_core._port_in_use(port):
        port += 1
    return port


def switch(target, force=False):
    """Hand the active server's place (its game port, its RCON port, the
    'active' mark) to another server, atomically:
    refuse while players are online (unless force), stop the outgoing server
    with reason 'switch' and wait for its JVM to exit, swap the ports, resync
    server.properties on both sides, then start the incoming server."""
    registry = mc_servers.load_registry()
    out_name = registry.get("active")
    loaded, error = load_server(target)
    if error:
        return error
    in_name, in_cfg = loaded
    if out_name == in_name:
        return result(False, "already_active", server=in_name)
    out_loaded, error = load_server(out_name) if out_name else (None, None)
    if error or not out_loaded:
        # No valid outgoing server: this is just 'use' + 'start'.
        mc_servers.set_active(in_name)
        in_cfg["mode_maintenance"] = 0
        in_cfg.pop("stop_reason", None)
        mc_config.save_config(in_cfg)
        started = start(in_name, in_cfg)
        return result(started["ok"], "switched" if started["ok"] else "start_failed",
                      server=in_name, previous=None, start=started)
    _, out_cfg = out_loaded

    if mc_core.is_server_running(out_cfg) and not force:
        ok, players = query_players(out_cfg)
        if not ok:
            return result(False, "players_unknown", server=out_name)
        if players["online"] > 0:
            return result(False, "players_online", server=out_name,
                          online=players["online"], players=players["players"])

    stopped = stop(out_name, out_cfg, reason="switch")
    if not stopped["ok"]:
        return result(False, "stop_failed", server=out_name, stop=stopped)
    if mc_core.is_server_running(in_cfg):
        # The incoming server must restart to take its new port.
        ok, msg = mc_core.stop_server(in_cfg, reason="switch", quiet=True)
        if not ok:
            return result(False, "stop_failed", server=in_name, message=msg)

    out_port, out_rcon = out_cfg.get("port"), out_cfg.get("rcon_port", mc_core.DEFAULT_RCON_PORT)
    in_port, in_rcon = in_cfg.get("port"), in_cfg.get("rcon_port", mc_core.DEFAULT_RCON_PORT)
    in_cfg["port"], out_cfg["port"] = out_port, in_port
    in_cfg["rcon_port"], out_cfg["rcon_port"] = out_rcon, in_rcon
    if str(in_rcon) == str(out_rcon):
        taken = set()
        for info in mc_servers.list_servers().values():
            for key in ("port", "rcon_port"):
                if info.get(key):
                    taken.add(int(info[key]))
        taken |= {int(out_port or 0), int(in_port or 0)}
        out_cfg["rcon_port"] = _free_rcon_port(out_rcon, taken)

    in_cfg["mode_maintenance"] = 0
    in_cfg.pop("stop_reason", None)
    mc_config.save_config(out_cfg)
    mc_config.save_config(in_cfg)
    mc_core.sync_server_properties(out_cfg)
    mc_core.sync_server_properties(in_cfg)
    mc_servers.set_active(in_name)

    started = start(in_name, in_cfg)
    return result(started["ok"], "switched" if started["ok"] else "start_failed",
                  server=in_name, previous=out_name, port=in_cfg["port"],
                  rcon_port=in_cfg["rcon_port"], previous_rcon_port=out_cfg["rcon_port"],
                  start=started)


# ── sleep settings ───────────────────────────────────────────────────────────

DEFAULT_SLEEP_AFTER = 2 * 3600
DEFAULT_HOLD_TIMEOUT = 120


def sleep_info(config):
    return {
        "enabled": config.get("sleep_enabled", 0) == 1,
        "after_s": int(config.get("sleep_after", DEFAULT_SLEEP_AFTER)),
        "allow": list(config.get("sleep_allow", [])),
        "join_mode": config.get("sleep_join_mode", "kick"),
        "hold_timeout_s": int(config.get("sleep_hold_timeout", DEFAULT_HOLD_TIMEOUT)),
        "freeze": config.get("sleep_freeze", 0) == 1,
        "internal_port": config.get("internal_port") if config.get("sleep_join_mode") == "hold" else None,
        "proxy_protocol": mc_core.use_proxy_protocol(config) if config.get("sleep_join_mode") == "hold" else None,
    }


def sleep_configure(name, config, enabled=None, after_s=None, allow_add=(), allow_remove=(),
                    join_mode=None, freeze=None, hold_timeout_s=None):
    config = dict(config)
    if join_mode not in (None, "kick", "hold"):
        return result(False, "sleep_setting_refused", message=T["join_mode_needs_sleep"])
    if mc_core.is_suspended(config):
        return result(False, "sleep_setting_refused", message=T["sleep_wake_before_config"])
    effective_mode = "kick" if enabled is False else (join_mode or config.get("sleep_join_mode", "kick"))
    effective_enabled = enabled if enabled is not None else bool(config.get("sleep_enabled"))
    if effective_mode == "hold" and (not effective_enabled or mc_core.is_proxy(config)):
        return result(False, "sleep_setting_refused", message=T["join_mode_needs_sleep"])
    if freeze and not mc_core.freeze_supported():
        return result(False, "unsupported_on_windows", server=name)
    if freeze and effective_mode != "hold":
        return result(False, "sleep_setting_refused", message=T["freeze_needs_hold"])
    if enabled is not None:
        config["sleep_enabled"] = 1 if enabled else 0
    if after_s is not None:
        if after_s < 300:
            return result(False, "sleep_after_too_short", minimum=300)
        config["sleep_after"] = int(after_s)
    if hold_timeout_s is not None:
        if not 10 <= hold_timeout_s <= 600:
            return result(False, "sleep_hold_timeout_range", minimum=10, maximum=600)
        config["sleep_hold_timeout"] = int(hold_timeout_s)
    allow = [n for n in config.get("sleep_allow", []) if n.lower() not in {a.lower() for a in allow_remove}]
    for n in allow_add:
        if n.lower() not in {a.lower() for a in allow}:
            allow.append(n)
    if allow or "sleep_allow" in config:
        config["sleep_allow"] = allow
    if enabled and not config.get("mcrcon_pass"):
        return result(False, "sleep_needs_rcon", server=name)
    mc_config.save_config(config)
    notes = []
    if enabled is False and config.get("sleep_join_mode") == "hold":
        join_mode = "kick"
    for key, value, apply in (("sleep_join_mode", join_mode, mc_config.apply_join_mode),
                              ("sleep_freeze", freeze, mc_config.apply_freeze)):
        if value is None:
            continue
        status, detail = apply(config, name, value if key == "sleep_join_mode" else bool(value))
        if status != "ok":
            return result(False, "sleep_setting_refused", server=name, key=key, message=detail)
        notes += detail
    return result(True, "sleep_updated", server=name, notes=notes, **sleep_info(config))


def wake(name, config):
    """Wake a sleeping server now (same path as a known player joining)."""
    if server_state(config) != "sleeping":
        return result(False, "not_sleeping", server=name, state=server_state(config))
    if mc_core.is_suspended(config):
        ok = mc_core.resume_server(config)
        return result(ok, "resumed" if ok else "suspend_signal_error", server=name)
    config["mode_maintenance"] = 0
    config.pop("stop_reason", None)
    mc_config.save_config(config)
    started = start(name, config)
    if started["ok"]:
        mc_core._alert(config, "wake")
    return started


def suspend(name, config):
    """sleep_freeze: flush the world and SIGSTOP the server instead of stopping it."""
    ok, code = mc_core.suspend_server(config)
    if code == "unsupported":
        return result(False, "unsupported_on_windows", server=name)
    return result(ok, "suspended" if ok else f"suspend_{code}", server=name)


def restart_pending(config):
    """True when the running server was started before its server.properties
    last changed, i.e. a port or bind change has not been applied yet."""
    if not mc_core.is_server_running(config):
        return False
    pid = _main_pid(config)
    uptime = _uptime_seconds(pid) if pid else None
    if uptime is None:
        return False
    try:
        changed = os.path.getmtime(os.path.join(config["dossier_serveur"], "server.properties"))
    except OSError:
        return False
    return changed > time.time() - uptime


def _router_attach(name, server, router, notes):
    """Put a server behind the router: internal port on 127.0.0.1. Returns a
    failure result, or None."""
    if mc_core.is_proxy(server):
        return result(False, "router_backend_invalid", server=name)
    internal = server.get("internal_port") or mc_core.default_internal_port(server.get("port") or 25565)
    for _ in range(100):
        if not 1 <= int(internal) <= 65535:
            return result(False, "router_port_conflict", server=name, port=internal)
        conflict = mc_servers.find_port_conflict(port=internal, rcon_port=internal, exclude_name=name)
        if not conflict and internal not in (router["port"], server.get("port"), server.get("rcon_port")):
            break
        internal += 1
    else:
        return result(False, "router_port_conflict", server=name, port=internal)
    changed = not server.get("router_backend") or server.get("internal_port") != internal
    server.update(router_backend=True, internal_port=internal)
    mc_config.save_config(server)
    mc_core.sync_server_properties(server)
    if changed or restart_pending(server):
        notes.append(T["router_backend_note"].format(server=name, port=internal))
    if not mc_core.use_proxy_protocol(server) and not router["proxy_out"]:
        notes.append(T["join_mode_proxy_unsupported"])
    return None


def _router_release(name, server, notes):
    """Give a server back its public port once nothing routes to it."""
    server.pop("router_backend", None)
    if server.get("sleep_join_mode") != "hold":
        server.pop("internal_port", None)
    mc_config.save_config(server)
    mc_core.sync_server_properties(server)
    props = os.path.join(server["dossier_serveur"], "server.properties")
    if not mc_core.is_hold_mode(server) and mc_config._read_property(props, "server-ip") == "127.0.0.1":
        mc_core.set_properties(server, {"server-ip": ""})
    notes.append(T["router_released_note"].format(server=name, port=server.get("port")))


def _router_release_unused(router, notes, everything=False):
    """Release every router backend no route points to (all of them when the
    router is being disabled). Returns the names released."""
    used = set() if everything else set(router["routes"].values()) | ({router["default"]} if router["default"] else set())
    released = []
    for name, info in mc_servers.list_servers().items():
        if name in used or not info.get("dossier_serveur") or not os.path.isdir(info["dossier_serveur"]):
            continue
        server = mc_config.load_config(info["dossier_serveur"])
        if not server.get("router_backend"):
            continue
        server["dossier_serveur"] = info["dossier_serveur"]
        _router_release(name, server, notes)
        released.append(name)
    return released


def _router_pending(servers):
    pending = []
    for name, info in servers.items():
        if not info.get("dossier_serveur") or not os.path.isdir(info["dossier_serveur"]):
            continue
        try:
            server = mc_config.load_config(info["dossier_serveur"])
        except mc_servers.DataFileError:
            continue
        server["dossier_serveur"] = info["dossier_serveur"]
        if restart_pending(server):
            pending.append(name)
    return pending


def router_command(action, operands=(), port=None, proxy_in=None, proxy_out=None,
                   trusted_proxies=None, per_ip=None, per_second=None):
    import mc_router
    import mc_proxy
    import ipaddress
    try:
        config = mc_router.load()
        args = list(operands)
        notes = []
        released = []
        touched = []
        if action in ("status", "disable", "enable"):
            if args:
                return result(False, "router_usage")
            if action == "disable":
                config["enabled"] = False
                released = _router_release_unused(config, notes, everything=True)
            elif action == "enable":
                for key, value in (("port", port), ("proxy_in", proxy_in), ("proxy_out", proxy_out),
                                   ("trusted_proxies", trusted_proxies), ("per_ip", per_ip),
                                   ("per_second", per_second)):
                    if value is not None:
                        config[key] = value
                config = mc_router.validate(config)
                for name, info in mc_servers.list_servers().items():
                    loaded = mc_config.load_config(info["dossier_serveur"])
                    if config["port"] in (mc_core.game_port(loaded), loaded.get("rcon_port")):
                        return result(False, "router_port_conflict", server=name, port=config["port"])
                config["enabled"] = True
                for target in sorted(set(config["routes"].values()) | ({config["default"]} if config["default"] else set())):
                    found, error = load_server(target)
                    if error:
                        continue
                    error = _router_attach(found[0], found[1], config, notes)
                    if error:
                        return error
                    touched.append(found[0])
        elif action in ("route", "default"):
            if action == "route" and args == ["list"]:
                return result(True, "router_status", config=config,
                              pending_restart=_router_pending(mc_servers.list_servers()))
            if action == "route" and len(args) == 2 and args[0] == "remove":
                config["routes"].pop(mc_router.hostname(args[1]), None)
                released = _router_release_unused(config, notes)
            else:
                if action == "route":
                    if len(args) != 3 or args[0] != "add":
                        return result(False, "router_usage")
                    host, target = mc_router.hostname(args[1]), args[2]
                else:
                    if len(args) != 1:
                        return result(False, "router_usage")
                    target = args[0]
                loaded, error = load_server(target)
                if error:
                    return error
                name, server = loaded
                error = _router_attach(name, server, config, notes)
                if error:
                    return error
                touched.append(name)
                if action == "default":
                    config["default"] = name
                else:
                    config["routes"][host] = name
        elif action in ("allow", "deny"):
            if len(args) != 2 or args[0] not in ("add", "remove") or not mc_proxy.valid_cidr(args[1]):
                return result(False, "router_usage")
            cidr = str(ipaddress.ip_network(args[1], strict=False))
            config[action] = [str(ipaddress.ip_network(value, strict=False)) for value in config[action]]
            if args[0] == "add" and cidr not in config[action]:
                config[action].append(cidr)
            elif args[0] == "remove":
                config[action] = [value for value in config[action] if value != cidr]
        else:
            return result(False, "router_usage")
        if action != "status":
            mc_router.save(config)
        servers = mc_servers.list_servers()
        pending = _router_pending(servers)
        restart_required = action != "status" and bool(set(pending) & (set(touched) | set(released)))
        return result(True, "router_status" if action == "status" else "router_updated",
                      config=config, notes=notes, released=released, pending_restart=pending,
                      restart_required=restart_required)
    except (ValueError, TypeError):
        return result(False, "router_usage")
    except (OSError, mc_servers.DataFileError) as exc:
        return result(False, "router_error", message=str(exc))


# ── content: server software, Java, modpacks, mods by name (2.9) ────────────

def _java_for(config, mc_version, loader):
    """Path of the Java to run installers and the server with, installing the
    right Temurin when needed. Falls back to the system Java if the download
    is impossible (offline)."""
    import mc_java
    import mc_software
    if config.get("java") == "system":
        return mc_core.find_java(config), None
    major = mc_software.java_for(loader, mc_version)
    res = mc_java.install(major)
    if res["ok"]:
        config["java_major"], config["java_path"] = major, res["path"]
        return res["path"], None
    return mc_core.find_java(config), res


def upgrade(name, config, target="latest", progress=None):
    """Move a server to another Minecraft version (or the newest proxy build):
    refuses while running, refuses a downgrade (worlds cannot go back),
    refuses when the loader is not published for that version, and backs the
    world up first."""
    import mc_http
    import mc_software
    loader = mc_software.canonical(config.get("loader")) or mc_software.canonical(
        mc_core.guess_loader_and_version(config)[0])
    if not loader:
        return result(False, "unknown_loader", server=name)
    if mc_core.is_server_running(config):
        return result(False, "server_running", server=name)
    current = config.get("mc_version")
    proxy = loader in mc_software.PROXIES
    try:
        if proxy:
            target = "proxy"
        else:
            if target in (None, "latest"):
                target = mc_software.latest_release()
            if current and mc_software.version_key(target) < mc_software.version_key(current):
                return result(False, "downgrade_refused", server=name, current=current, target=target)
            if current == target:
                return result(True, "already_on_version", server=name, version=target)
            ok, loader_version = mc_software.available(loader, target)
            if not ok:
                return result(False, loader_version, server=name, loader=loader, version=target)
    except mc_http.HttpError as e:
        return result(False, "source_unreachable", detail=e.detail)

    if not proxy:
        ok, msg = mc_core.backup_server(config, "upgrade")
        if not ok and msg != mc_core.T["no_world_found"]:
            return result(False, "backup_failed", server=name, message=msg)
    java, java_problem = _java_for(config, target, loader)
    old_jar = config.get("jar_name")
    res = mc_software.install(config["dossier_serveur"], loader, target if not proxy else None,
                              None if proxy else loader_version, java, progress)
    if not res["ok"]:
        return dict(res, server=name)
    if old_jar and old_jar != res["jar_name"] and old_jar.endswith(".jar"):
        old_path = os.path.join(config["dossier_serveur"], old_jar)
        if os.path.exists(old_path):
            keep = os.path.join(config["dossier_serveur"], ".mcmanager", "previous-jars")
            os.makedirs(keep, exist_ok=True)
            plat.atomic_replace(old_path, os.path.join(keep, old_jar))
    config.update(loader=loader, jar_name=res["jar_name"], loader_version=res.get("loader_version"))
    if not proxy:
        config["mc_version"] = target
    mc_config.save_config(config)
    mc_core.sync_server_properties(config)
    mc_core._alert(config, "update", detail=f"{current or '?'} -> {config.get('mc_version') or res['jar_name']}")
    return result(True, "upgraded", server=name, loader=loader, previous=current, version=config.get("mc_version"),
                  jar=res["jar_name"], java_warning=bool(java_problem),
                  mods_hint=loader in mc_software.MOD_LOADERS + mc_software.PLUGIN_LOADERS)


def modpack_install(source, name=None, folder=None, port=None, rcon_port=None, ram="6G",
                    accept_eula=False, curseforge_key=None, progress=None):
    """Create a new server from a modpack."""
    import mc_deploy
    import mc_modpack
    if not accept_eula:
        return result(False, "eula_required")
    if not name:
        meta = mc_modpack.info(source, curseforge_key)
        if not meta["ok"]:
            return meta
        name = meta.get("title") or "modpack"
    slug = mc_servers.slugify(name, mc_servers.list_servers().keys())
    folder = os.path.abspath(os.path.expanduser(folder or os.path.join(mc_servers.DATA_ROOT, slug, "Server")))
    if mc_deploy._dir_has_server(folder):
        return result(False, "folder_not_empty", path=folder)
    port, rcon_port, error = mc_deploy.allocate_ports(port, rcon_port)
    if error:
        return result(False, error[0], port=error[1])

    java_config = {}

    def java_resolver(mc_version, loader):
        return _java_for(java_config, mc_version, loader)[0]

    created = not os.path.exists(folder)
    res = mc_modpack.install_into(folder, source, curseforge_key, java_resolver, progress)
    if not res["ok"]:
        if created and os.path.isdir(folder) and not os.listdir(folder):
            os.rmdir(folder)
        return res
    mc_deploy.write_eula(folder)
    extra = {"modpack": res["modpack"], "loader_version": res.get("loader_version")}
    extra.update({k: v for k, v in java_config.items() if k in ("java_path", "java_major")})
    done = mc_deploy.finalize_new_server(name, folder, res["loader"], res["mc_version"], res["jar_name"],
                                         port, rcon_port, ram, extra)
    return dict(done, code="pack_deployed", title=res.get("title"), pack_version=res.get("version"),
                files=res.get("files"))


def modpack_update(name, config, curseforge_key=None, progress=None):
    import mc_modpack
    if mc_core.is_server_running(config):
        return result(False, "server_running", server=name)
    ok, msg = mc_core.backup_server(config, "modpack")
    if not ok and msg != mc_core.T["no_world_found"]:
        return result(False, "backup_failed", server=name, message=msg)
    java = _java_for(config, config.get("mc_version"), config.get("loader"))[0]
    res = mc_modpack.update(config, curseforge_key or config.get("curseforge_api_key"), java, progress)
    if res["ok"] and res["code"] == "pack_updated":
        mc_config.save_config(config)
        mc_core._alert(config, "update")
    return dict(res, server=name)


# ── backups: list, restore, destinations (2.10) ─────────────────────────────

def _backup_error(e):
    return result(False, e.code, detail=e.detail, path=e.detail)


def backup_list(name, config):
    import mc_backup
    backups = mc_backup.list_backups(config.get("dossier_backup", ""))
    return result(True, "backup_list", server=name, backups=backups, count=len(backups),
                  keep=int(config.get("backup_keep", 0) or 0),
                  retention_days=int(config.get("backup_retention_days", 0) or 0),
                  remotes=[r.get("name") for r in config.get("backup_remotes", [])])


def backup_restore(name, config, ref):
    """Replace the world with a backup. The server must be stopped for good
    (running, or about to be relaunched by the daemon, is refused); the
    current world is backed up first and the swap rolls back on failure."""
    import mc_backup
    entry = mc_backup.find_backup(config.get("dossier_backup", ""), ref)
    if not entry:
        return result(False, "backup_not_found", server=name, ref=ref)
    state = server_state(config)
    if state in ("running", "starting"):
        return result(False, "server_running", server=name)
    if state == "stopped":
        return result(False, "stop_first", server=name)
    try:
        if entry["encrypted"]:
            key = config.get("backup_encrypt_key_file")
            if not key or not os.path.isfile(key):
                return result(False, "encrypt_key_missing", detail=key or "")
        else:
            mc_backup.inspect_archive(entry["path"])
    except mc_backup.BackupError as e:
        return _backup_error(e)
    ok, message = mc_core.backup_server(config, "pre-restore", housekeeping=False)
    safety = None
    if ok:
        newest = mc_backup.list_backups(config.get("dossier_backup", ""))
        safety = newest[0]["path"] if newest else None
    elif message != mc_core.T["no_world_found"]:
        return result(False, "safety_backup_failed", server=name, message=message)
    level = mc_core._get_level_name(config["dossier_serveur"])
    try:
        restored = mc_backup.restore_archive(
            entry["path"], config["dossier_serveur"],
            extra_names=(level, f"{level}_nether", f"{level}_the_end"),
            key_file=config.get("backup_encrypt_key_file"))
    except mc_backup.BackupError as e:
        return dict(_backup_error(e), safety=safety)
    return result(True, "backup_restored", server=name, backup=entry["id"], restored=restored, safety=safety)


def _remote_by_name(config, rname):
    return next((r for r in config.get("backup_remotes", []) if r.get("name") == rname), None)


def backup_remote_list(name, config):
    import mc_backup
    remotes = [dict(mc_backup.masked(r), target=mc_backup.describe(r)) for r in config.get("backup_remotes", [])]
    return result(True, "backup_remote_list", server=name, remotes=remotes, count=len(remotes),
                  encrypted=bool(config.get("backup_encrypt_key_file")))


def backup_remote_add(name, config, rname, url, key=None, endpoint=None, region=None, access_key=None,
                      secret_key=None, path_style=None, password=None, password_file=None):
    import mc_alert
    import mc_backup
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", rname or ""):
        return result(False, "bad_remote_name", remote=rname)
    if _remote_by_name(config, rname):
        return result(False, "remote_exists", remote=rname)
    try:
        kind, fields = mc_backup.parse_remote_url(url)
    except mc_backup.BackupError:
        return result(False, "bad_remote_url", url=url)
    remote = {"name": rname, "type": kind, **fields}
    if kind == "sftp" and key:
        key = os.path.abspath(os.path.expanduser(key))
        if not os.path.isfile(key):
            return result(False, "key_not_found", path=key)
        remote["key"] = key
    elif kind == "s3":
        access_key = access_key or os.environ.get("AWS_ACCESS_KEY_ID")
        secret_key = secret_key or os.environ.get("AWS_SECRET_ACCESS_KEY")
        if not access_key or not secret_key:
            return result(False, "s3_credentials_missing")
        remote.update(access_key=access_key, secret_key=secret_key, region=region or "us-east-1")
        if endpoint:
            if not mc_alert.valid_url(endpoint if "://" in endpoint else "https://" + endpoint):
                return result(False, "bad_url", url=endpoint)
            remote["endpoint"] = endpoint
        if path_style is not None:
            remote["path_style"] = bool(path_style)
    elif kind == "restic":
        if password_file:
            password_file = os.path.abspath(os.path.expanduser(password_file))
            if not os.path.isfile(password_file):
                return result(False, "key_not_found", path=password_file)
            if not plat.secure_file(password_file):
                raise PermissionError(1, "Operation not permitted", password_file)
        elif password:
            password_file = os.path.join(config["dossier_serveur"], ".mcmanager", f"restic-{rname}.pass")
            mc_servers.write_private_file(password_file, password)
        else:
            return result(False, "restic_password_missing")
        remote["password_file"] = password_file
    config.setdefault("backup_remotes", []).append(remote)
    mc_config.save_config(config)
    return result(True, "backup_remote_added", server=name, remote=rname, type=kind,
                  target=mc_backup.describe(remote))


def backup_remote_remove(name, config, rname):
    remote = _remote_by_name(config, rname)
    if not remote:
        return result(False, "remote_not_found", remote=rname)
    config["backup_remotes"] = [r for r in config["backup_remotes"] if r is not remote]
    if not config["backup_remotes"]:
        config.pop("backup_remotes")
    mc_config.save_config(config)
    return result(True, "backup_remote_removed", server=name, remote=rname)


def backup_remote_test(name, config, rname=None):
    import mc_backup
    remotes = config.get("backup_remotes", [])
    if rname:
        remotes = [r for r in remotes if r.get("name") == rname]
        if not remotes:
            return result(False, "remote_not_found", remote=rname)
    if not remotes:
        return result(False, "no_remote", server=name)
    checks = []
    for remote in remotes:
        try:
            mc_backup.check_remote(remote)
            checks.append({"remote": remote["name"], "ok": True, "detail": ""})
        except mc_backup.BackupError as e:
            checks.append({"remote": remote["name"], "ok": False, "detail": mc_backup.redact(str(e), remote)})
    ok = all(c["ok"] for c in checks)
    return result(ok, "backup_remote_tested" if ok else "backup_remote_test_failed", server=name,
                  checks=checks, failed=", ".join(c["remote"] for c in checks if not c["ok"]))


# ── alerts (2.10) ───────────────────────────────────────────────────────────

def alert_list(name, config):
    import mc_alert
    channels = mc_alert.listing(config)
    return result(True, "alert_list", server=name, channels=channels, count=len(channels),
                  events=list(mc_alert.EVENTS))


def alert_add(name, config, kind, params, events=None, channel_name=None):
    import mc_alert
    if kind not in mc_alert.TYPES:
        return result(False, "bad_type", type=kind)
    wanted = mc_alert.parse_events(events)
    if wanted is None:
        return result(False, "bad_events", events=events, valid=", ".join(mc_alert.EVENTS))
    params = {k: v for k, v in params.items() if v not in (None, "")}
    if kind == "email":
        params.setdefault("port", 587)
        if isinstance(params.get("to"), str):
            params["to"] = [a.strip() for a in params["to"].split(",") if a.strip()]
    problem = mc_alert.validate(kind, params)
    if problem:
        return result(False, problem, type=kind)
    if channel_name:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", channel_name) or channel_name == "discord":
            return result(False, "bad_channel_name", channel=channel_name)
        if any(c.get("name") == channel_name for c in mc_alert.channels(config)):
            return result(False, "channel_exists", channel=channel_name)
    channel = {"name": channel_name or mc_alert.next_name(config, kind), "type": kind,
               "events": wanted, **params}
    config.setdefault("alerts", []).append(channel)
    mc_config.save_config(config)
    return result(True, "alert_added", server=name, channel=channel["name"], type=kind, events=wanted)


def alert_remove(name, config, channel_name):
    import mc_alert
    found = next((c for c in mc_alert.channels(config) if c.get("name") == channel_name), None)
    if not found:
        return result(False, "channel_not_found", channel=channel_name)
    config["alerts"] = [c for c in config["alerts"] if c is not found]
    if not config["alerts"]:
        config.pop("alerts")
    mc_config.save_config(config)
    return result(True, "alert_removed", server=name, channel=channel_name)


def alert_test(name, config, channel_name=None):
    import mc_alert
    found, sent = mc_alert.test_channels(config, channel_name)
    if not found:
        return result(False, "channel_not_found", channel=channel_name)
    if not sent:
        return result(False, "no_channel", server=name)
    checks = [{"channel": n, "ok": ok, "detail": "" if ok else detail} for n, ok, detail in sent]
    ok = all(c["ok"] for c in checks)
    return result(ok, "alert_tested" if ok else "alert_test_failed", server=name, checks=checks,
                  failed=", ".join(c["channel"] for c in checks if not c["ok"]))


# ── players (2.10) ──────────────────────────────────────────────────────────

def player_list(name, config, kind):
    import mc_players
    return dict(mc_players.list_entries(config, kind), server=name)


def player_edit(name, config, kind, action, subject, reason=None):
    import mc_players
    return dict(mc_players.edit_list(config, kind, action, subject, reason=reason), server=name)


def whitelist_enable(name, config, enabled):
    import mc_players
    return dict(mc_players.set_whitelist_enabled(config, enabled), server=name)


def player_kick(name, config, player, reason=None):
    import mc_players
    return dict(mc_players.kick(config, player, reason=reason), server=name)


def player_history(name, config, days=7):
    import mc_players
    sessions = mc_players.history(config["dossier_serveur"], days=max(1, days))
    return result(True, "history", server=name, days=days, sessions=sessions)


# ── worlds (2.10) ───────────────────────────────────────────────────────────

def world_list(name, config):
    import mc_world
    return dict(mc_world.list_worlds(config), server=name)


def world_export(name, config, output=None):
    import mc_world
    return dict(mc_world.export_world(config, output), server=name)


def world_import(name, config, source, confirmed=False):
    import mc_world
    return dict(mc_world.import_world(config, source, confirmed=confirmed), server=name)


def world_reset(name, config, dimension, confirmed=False, include_overworld=False):
    import mc_world
    return dict(mc_world.reset_dimension(config, dimension, confirmed=confirmed,
                                         include_overworld=include_overworld), server=name)


def world_pregen(name, config, radius, center=None):
    """`radius` and `center` ("x,z") are the raw command-line texts."""
    import mc_world
    try:
        parsed_radius = int(radius)
        parsed_center = mc_world.parse_center(center) if center else None
    except (TypeError, ValueError):
        return result(False, "invalid_radius", server=name, radius=radius if radius is not None else "?")
    return dict(mc_world.pregen(config, parsed_radius, parsed_center), server=name)


def world_pregen_status(name, config):
    import mc_world
    return dict(mc_world.pregen_progress(config), server=name)


# ── scheduled tasks (2.10) ──────────────────────────────────────────────────

def task_list(name, config):
    import mc_task
    return dict(mc_task.list_tasks(config), server=name)


def task_add(name, config, cron, action, command=None, warn=None, task_name=None):
    import mc_task
    return dict(mc_task.add_task(config, cron, action, command=command, warn=warn, name=task_name),
                server=name)


def task_remove(name, config, ref):
    import mc_task
    return dict(mc_task.remove_task(config, ref), server=name)


def task_enable(name, config, ref, enabled=True):
    import mc_task
    return dict(mc_task.set_enabled(config, ref, enabled), server=name)


def task_find(config, ref):
    import mc_task
    return mc_task.find_task(config, ref)


def task_run(name, config, task, skip_warn=False):
    """Run one task now and record its outcome."""
    import mc_task
    res = mc_task.execute(name, config, task, skip_warn=skip_warn)
    mc_task.record_run(config, task.get("id"), res["ok"], res["code"])
    return dict(res, server=name)


# ── metrics / status page ────────────────────────────────────────────────────

def metrics_serve(bind=None, allow_remote=False, ready=None):
    """Serve /metrics in the foreground until interrupted. `ready(bind)` is
    called once the socket is bound."""
    import mc_metrics
    bind = bind or mc_metrics.DEFAULT_BIND
    try:
        server = mc_metrics.make_server(bind, allow_remote)
    except ValueError:
        return result(False, "metrics_bind_invalid", bind=bind)
    except PermissionError:
        return result(False, "metrics_remote_refused", bind=bind)
    except OSError as e:
        return result(False, "metrics_bind_failed", bind=bind, detail=str(e))
    host, port = server.server_address[:2]
    if ready:
        ready(f"{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return result(True, "metrics_stopped", bind=f"{host}:{port}")


STATUS_PAGE_DEFAULT_INTERVAL = 60
STATUS_PAGE_MIN_INTERVAL = 10


def statuspage_enable(name, config, directory=None, interval=None, show_players=None):
    import mc_statuspage
    directory = os.path.abspath(os.path.expanduser(
        directory or config.get("status_page_dir") or os.path.join(config["dossier_serveur"], "status_page")))
    interval = STATUS_PAGE_DEFAULT_INTERVAL if interval is None and "status_page_interval" not in config \
        else (interval if interval is not None else int(config["status_page_interval"]))
    if interval < STATUS_PAGE_MIN_INTERVAL:
        return result(False, "status_page_interval_too_short", minimum=STATUS_PAGE_MIN_INTERVAL)
    config["status_page_dir"] = directory
    config["status_page_interval"] = interval
    if show_players is not None:
        config["status_page_players"] = 1 if show_players else 0
    try:
        mc_statuspage.generate(name, config)
    except OSError as e:
        return result(False, "status_page_unwritable", path=directory, detail=str(e))
    mc_config.save_config(config)
    return result(True, "status_page_enabled", server=name, path=directory, interval=interval,
                  players=config.get("status_page_players", 0) == 1)


def statuspage_disable(name, config):
    import mc_statuspage
    directory = config.pop("status_page_dir", None)
    if not directory:
        return result(True, "status_page_already_off", server=name)
    mc_statuspage.remove_page(directory)
    mc_config.save_config(config)
    return result(True, "status_page_disabled", server=name, path=directory)

