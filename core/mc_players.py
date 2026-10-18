"""
mc_players.py — Whitelist, operators, bans, kicks and connection history.

A running server is driven over RCON and the result is confirmed by reading
the server's own JSON file back; a stopped server has its file edited
directly (atomic write). Nothing here prints.
"""
import datetime
import glob
import gzip
import hashlib
import ipaddress
import json
import os
import re
import shutil
import time
import uuid

import mc_core
import mc_http
from mc_platform import plat

NAME_RE = re.compile(r"[A-Za-z0-9_]{3,16}")
MOJANG_PROFILE = "https://api.mojang.com/users/profiles/minecraft/"
CONFIRM_WAIT = 3
DEFAULT_BAN_REASON = "Banned by an operator."

PAST = {"add": "added", "remove": "removed"}
LISTS = {
    "whitelist": {"file": "whitelist.json", "key": "name"},
    "op": {"file": "ops.json", "key": "name"},
    "ban": {"file": "banned-players.json", "key": "name"},
    "banip": {"file": "banned-ips.json", "key": "ip"},
}


def result(ok, code, **data):
    return {"ok": ok, "code": code, **data}


def valid_name(name):
    return bool(NAME_RE.fullmatch(name or ""))


def valid_ip(text):
    try:
        ipaddress.ip_address(text)
        return True
    except ValueError:
        return False


def offline_uuid(name):
    digest = bytearray(hashlib.md5(f"OfflinePlayer:{name}".encode("utf-8")).digest())
    digest[6] = (digest[6] & 0x0F) | 0x30
    digest[8] = (digest[8] & 0x3F) | 0x80
    return str(uuid.UUID(bytes=bytes(digest)))


def read_properties(dossier):
    props = {}
    try:
        with open(os.path.join(dossier, "server.properties"), encoding="utf-8-sig", errors="replace") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    props[key.strip()] = value.strip()
    except OSError:
        pass
    return props


def is_online_mode(config):
    return read_properties(config.get("dossier_serveur", "")).get("online-mode", "true").lower() != "false"


def set_property(dossier, key, value):
    path = os.path.join(dossier, "server.properties")
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
    except OSError:
        lines = []
    for i, line in enumerate(lines):
        if line.split("=", 1)[0].strip() == key:
            lines[i] = f"{key}={value}"
            break
    else:
        lines.append(f"{key}={value}")
    _atomic_write(path, "\n".join(lines) + "\n")


def resolve_uuid(name, config):
    """(uuid, error_code). Offline-mode servers derive it from the name,
    online ones ask Mojang."""
    if not is_online_mode(config):
        return offline_uuid(name), None
    try:
        data = mc_http.get_json(MOJANG_PROFILE + name)
    except mc_http.HttpError as e:
        if e.status in (204, 404):
            return None, "player_unknown"
        return None, "mojang_unreachable"
    raw = (data or {}).get("id", "")
    if not re.fullmatch(r"[0-9a-fA-F]{32}", raw):
        return None, "player_unknown"
    return str(uuid.UUID(raw)), None


def _atomic_write(path, text):
    tmp = path + ".mcmanager.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    try:
        shutil.copymode(path, tmp)
    except OSError:
        pass
    plat.atomic_replace(tmp, path)


def _path(config, kind):
    return os.path.join(config["dossier_serveur"], LISTS[kind]["file"])


def read_list(config, kind):
    try:
        with open(_path(config, kind), encoding="utf-8-sig") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []
    return data if isinstance(data, list) else []


def _write_list(config, kind, entries):
    _atomic_write(_path(config, kind), json.dumps(entries, indent=2, ensure_ascii=False) + "\n")


def _find(entries, kind, subject):
    key = LISTS[kind]["key"]
    return [e for e in entries
            if isinstance(e, dict) and str(e.get(key, "")).lower() == subject.lower()]


def _present(config, kind, subject):
    return bool(_find(read_list(config, kind), kind, subject))


def _stamp():
    return datetime.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z")


def _new_entry(config, kind, subject, reason):
    if kind == "banip":
        return {"ip": subject, "created": _stamp(), "source": "MC Manager",
                "expires": "forever", "reason": reason or DEFAULT_BAN_REASON}, None
    ident, error = resolve_uuid(subject, config)
    if error:
        return None, error
    if kind == "whitelist":
        return {"uuid": ident, "name": subject}, None
    if kind == "op":
        return {"uuid": ident, "name": subject, "level": 4, "bypassesPlayerLimit": False}, None
    return {"uuid": ident, "name": subject, "created": _stamp(), "source": "MC Manager",
            "expires": "forever", "reason": reason or DEFAULT_BAN_REASON}, None


def _rcon_command(kind, action, subject, reason):
    suffix = f" {reason}" if reason and action == "add" and kind in ("ban", "banip") else ""
    if kind == "whitelist":
        return f"whitelist {action} {subject}"
    if kind == "op":
        return f"op {subject}" if action == "add" else f"deop {subject}"
    if kind == "ban":
        return f"ban {subject}{suffix}" if action == "add" else f"pardon {subject}"
    return f"ban-ip {subject}{suffix}" if action == "add" else f"pardon-ip {subject}"


def _validate(kind, subject):
    if kind == "banip":
        return valid_ip(subject)
    return valid_name(subject)


def edit_list(config, kind, action, subject, reason=None, rcon=None):
    """Add or remove `subject` (a name, or an IP for 'banip').

    `rcon(config, command)` -> (ok, reply) is injectable for tests; it
    defaults to the RCON of mc_api."""
    if not _validate(kind, subject):
        return result(False, "invalid_ip" if kind == "banip" else "invalid_name", subject=subject)
    wanted = action == "add"
    entries = read_list(config, kind)
    already = bool(_find(entries, kind, subject))
    if already == wanted:
        return result(True, f"{kind}_already_{action}", subject=subject, changed=False)

    if mc_core.is_server_running(config):
        if rcon is None:
            import mc_api
            def rcon(cfg, cmd):
                return mc_api.rcon_exec(cfg, cmd, wait=mc_api.RCON_RETRY)
        ok, reply = rcon(config, _rcon_command(kind, action, subject, reason))
        if not ok:
            return result(False, "rcon_failed", subject=subject, detail=reply)
        deadline = time.time() + CONFIRM_WAIT
        while True:
            if _present(config, kind, subject) == wanted:
                return result(True, f"{kind}_{PAST[action]}", subject=subject, changed=True, via="rcon")
            if time.time() >= deadline:
                return result(False, "not_confirmed", subject=subject, detail=reply)
            time.sleep(0.3)

    if wanted:
        entry, error = _new_entry(config, kind, subject, reason)
        if error:
            return result(False, error, subject=subject)
        entries.append(entry)
    else:
        key = LISTS[kind]["key"]
        entries = [e for e in entries
                   if not (isinstance(e, dict) and str(e.get(key, "")).lower() == subject.lower())]
    _write_list(config, kind, entries)
    return result(True, f"{kind}_{PAST[action]}", subject=subject, changed=True, via="file")


def _epoch(text):
    try:
        return int(datetime.datetime.strptime(str(text), "%Y-%m-%d %H:%M:%S %z").timestamp())
    except ValueError:
        return None


def _with_timestamps(entry):
    if not isinstance(entry, dict):
        return entry
    return dict(entry, created_ts=_epoch(entry.get("created")), expires_ts=_epoch(entry.get("expires")))


def list_entries(config, kind):
    entries = read_list(config, kind)
    if kind in ("ban", "banip"):
        entries = [_with_timestamps(e) for e in entries]
    if kind == "whitelist":
        props = read_properties(config["dossier_serveur"])
        enabled = props.get("white-list", "false").lower() == "true"
        return result(True, "whitelist_list", entries=entries, enabled=enabled)
    return result(True, f"{kind}_list", entries=entries)


def set_whitelist_enabled(config, enabled, rcon=None):
    if mc_core.is_server_running(config):
        if rcon is None:
            import mc_api
            def rcon(cfg, cmd):
                return mc_api.rcon_exec(cfg, cmd, wait=mc_api.RCON_RETRY)
        ok, reply = rcon(config, "whitelist on" if enabled else "whitelist off")
        if not ok:
            return result(False, "rcon_failed", detail=reply)
    set_property(config["dossier_serveur"], "white-list", "true" if enabled else "false")
    return result(True, "whitelist_on" if enabled else "whitelist_off", enabled=enabled)


def kick(config, player, reason=None, query=None, rcon=None):
    if not valid_name(player):
        return result(False, "invalid_name", subject=player)
    if not mc_core.is_server_running(config):
        return result(False, "kick_offline", subject=player)
    import mc_api
    ok, data = (query or mc_api.query_players)(config, wait=mc_api.RCON_RETRY)
    if not ok:
        return result(False, "rcon_failed", subject=player, detail=data)
    if player.lower() not in {n.lower() for n in data["players"]}:
        return result(False, "player_not_online", subject=player)
    rcon = rcon or (lambda cfg, cmd: mc_api.rcon_exec(cfg, cmd))
    ok, reply = rcon(config, f"kick {player}" + (f" {reason}" if reason else ""))
    if not ok:
        return result(False, "rcon_failed", subject=player, detail=reply)
    return result(True, "kicked", subject=player)


# ── connection history ──────────────────────────────────────────────────────

_LINE = re.compile(r"^\[(\d{2}):(\d{2}):(\d{2})\] \[[^\]]*\]: (.*)$")
_LOGIN = re.compile(r"^([A-Za-z0-9_]{1,16})\[/(.+):(\d+)\] logged in with entity id")
_JOINED = re.compile(r"^([A-Za-z0-9_]{1,16}) joined the game$")
_LEFT = re.compile(r"^([A-Za-z0-9_]{1,16}) left the game$")
_START = re.compile(r"^Starting minecraft server version")
_DATED = re.compile(r"^(\d{4})-(\d{2})-(\d{2})-\d+\.log(?:\.gz)?$")


def _log_files(logs_dir):
    """[(date, is_latest, path)] oldest first. For latest.log the date is the
    modification date, i.e. the day of its last line."""
    files = []
    for path in glob.glob(os.path.join(logs_dir, "*.log*")):
        base = os.path.basename(path)
        match = _DATED.match(base)
        if match:
            files.append((datetime.date(*map(int, match.groups())), False, path))
        elif base == "latest.log":
            try:
                day = datetime.date.fromtimestamp(os.path.getmtime(path))
            except OSError:
                continue
            files.append((day, True, path))
    return sorted(files)


def _open_log(path):
    if path.endswith(".gz"):
        return gzip.open(path, "rt", encoding="utf-8", errors="replace")
    return open(path, encoding="utf-8", errors="replace")


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S") if dt else None


def _timed_lines(path, day, is_latest):
    """[(datetime, text)] of one log file. Day changes are detected when the
    clock goes backwards; latest.log is dated backwards from its last line."""
    rows = []
    with _open_log(path) as f:
        for raw in f:
            match = _LINE.match(raw.rstrip("\n"))
            if match:
                rows.append((int(match.group(1)) * 3600 + int(match.group(2)) * 60 + int(match.group(3)),
                             match.group(4)))
    rollovers, previous = 0, None
    for seconds, _ in rows:
        if previous is not None and seconds < previous - 3600:
            rollovers += 1
        previous = seconds
    offset = rollovers if is_latest else 0
    current = day - datetime.timedelta(days=offset)
    out, previous = [], None
    for seconds, text in rows:
        if previous is not None and seconds < previous - 3600:
            current += datetime.timedelta(days=1)
        previous = seconds
        out.append((datetime.datetime.combine(current, datetime.time()) + datetime.timedelta(seconds=seconds), text))
    return out


def history(dossier, days=7, now=None):
    """Sessions found in the server logs, oldest first:
    [{player, ip, join, leave, duration_s}]. A session still open (or cut by
    a crash or a restart) has leave/duration_s = None."""
    now = now or datetime.datetime.now()
    cutoff = now - datetime.timedelta(days=days)
    pending, sessions = {}, []

    def close(name, when):
        join = pending.pop(name)
        sessions.append({"player": name, "ip": join["ip"], "join": join["join"], "leave": when})

    for day, is_latest, path in _log_files(os.path.join(dossier, "logs")):
        if day < cutoff.date() - datetime.timedelta(days=1):
            continue
        try:
            rows = _timed_lines(path, day, is_latest)
        except OSError:
            continue
        for stamp, text in rows:
            if _START.match(text):
                for name in list(pending):
                    close(name, None)
                continue
            login = _LOGIN.match(text)
            if login:
                name = login.group(1)
                if name in pending:
                    close(name, None)
                pending[name] = {"join": stamp, "ip": login.group(2).strip("[]")}
                continue
            joined = _JOINED.match(text)
            if joined and joined.group(1) not in pending:
                pending[joined.group(1)] = {"join": stamp, "ip": None}
                continue
            left = _LEFT.match(text)
            if left and left.group(1) in pending:
                close(left.group(1), stamp)
    for name in list(pending):
        close(name, None)

    out = []
    for s in sorted(sessions, key=lambda x: x["join"]):
        if s["join"] < cutoff:
            continue
        duration = int((s["leave"] - s["join"]).total_seconds()) if s["leave"] else None
        out.append({"player": s["player"], "ip": s["ip"], "join": _iso(s["join"]),
                    "leave": _iso(s["leave"]), "duration_s": duration,
                    "join_ts": int(s["join"].timestamp()),
                    "leave_ts": int(s["leave"].timestamp()) if s["leave"] else None})
    return out
