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
        if state == "sleeping":
            # Held by the daemon's sleep listener, which is the expected case.
            snap["sleep_listener"] = occupant is not None
        elif occupant:
            snap["port_holder"] = {"pid": occupant[0], "program": occupant[1]}
    snap["sleep"] = sleep_info(config)
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


def sleep_info(config):
    return {
        "enabled": config.get("sleep_enabled", 0) == 1,
        "after_s": int(config.get("sleep_after", DEFAULT_SLEEP_AFTER)),
        "allow": list(config.get("sleep_allow", [])),
    }


def sleep_configure(name, config, enabled=None, after_s=None, allow_add=(), allow_remove=()):
    if enabled is not None:
        config["sleep_enabled"] = 1 if enabled else 0
    if after_s is not None:
        if after_s < 300:
            return result(False, "sleep_after_too_short", minimum=300)
        config["sleep_after"] = int(after_s)
    allow = [n for n in config.get("sleep_allow", []) if n.lower() not in {a.lower() for a in allow_remove}]
    for n in allow_add:
        if n.lower() not in {a.lower() for a in allow}:
            allow.append(n)
    if allow or "sleep_allow" in config:
        config["sleep_allow"] = allow
    if enabled and not config.get("mcrcon_pass"):
        return result(False, "sleep_needs_rcon", server=name)
    mc_config.save_config(config)
    return result(True, "sleep_updated", server=name, **sleep_info(config))


def wake(name, config):
    """Wake a sleeping server now (same path as a known player joining)."""
    if server_state(config) != "sleeping":
        return result(False, "not_sleeping", server=name, state=server_state(config))
    config["mode_maintenance"] = 0
    config.pop("stop_reason", None)
    mc_config.save_config(config)
    return start(name, config)


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
            os.replace(old_path, os.path.join(keep, old_jar))
    config.update(loader=loader, jar_name=res["jar_name"], loader_version=res.get("loader_version"))
    if not proxy:
        config["mc_version"] = target
    mc_config.save_config(config)
    mc_core.sync_server_properties(config)
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
    return dict(res, server=name)
