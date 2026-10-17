import os
import subprocess
import json
import logging
import datetime
import sys
import shutil
import time
import zipfile
import urllib.request
import urllib.error
import base64
import hashlib
import socket
import struct

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(BASE_DIR)
import mc_config
from mc_lang import T
from mc_platform import plat, Unsupported

DEFAULT_CPU = "0-3"
DEFAULT_RAM = "4G"
DEFAULT_JAVA_FLAGS = "--add-modules=jdk.incubator.vector -XX:+UseG1GC -XX:+ParallelRefProcEnabled -XX:MaxGCPauseMillis=200 -XX:+UnlockExperimentalVMOptions -XX:+DisableExplicitGC -XX:+AlwaysPreTouch -XX:G1HeapWastePercent=5 -XX:G1MixedGCCountTarget=4 -XX:InitiatingHeapOccupancyPercent=15 -XX:G1MixedGCLiveThresholdPercent=90 -XX:G1RSetUpdatingPauseTimePercent=5 -XX:SurvivorRatio=32 -XX:+PerfDisableSharedMem -XX:MaxTenuringThreshold=1 -Dusing.aikars.flags=https://mcflags.emc.gs -Daikars.new.flags=true -XX:G1NewSizePercent=30 -XX:G1MaxNewSizePercent=40 -XX:G1HeapRegionSize=8M -XX:G1ReservePercent=20"
DEFAULT_JAR_NAME = "fabric-server-launch.jar"
DEFAULT_RCON_PORT = 25575

def pid_file_path(config) -> str:
    return os.path.join(config["dossier_serveur"], "server.pid")

# ==========================================
# UTILITAIRES CPU AFFINITY
# ==========================================

def cores_to_cpu_set(cores_str: str) -> set:
    cpu_set = set()
    for part in cores_str.split(','):
        part = part.strip()
        if '-' in part:
            start, end = map(int, part.split('-'))
            cpu_set.update(range(start, end + 1))
        else:
            cpu_set.add(int(part))
    return cpu_set

def set_process_affinity(pid: int, cpu_set: set):
    plat.set_affinity(pid, cpu_set)

# ==========================================
# SERVER DETECTION
# ==========================================

def get_server_pid(config) -> int | None:
    pid_file = pid_file_path(config)
    if not os.path.exists(pid_file):
        return None
    try:
        with open(pid_file, 'r') as f:
            return int(f.read().strip())
    except Exception:
        return None

def _write_pid_file(config, pid):
    try:
        with open(pid_file_path(config), 'w') as f:
            f.write(str(pid))
    except Exception:
        pass

def _remove_pid_file(config):
    try:
        os.remove(pid_file_path(config))
    except FileNotFoundError:
        pass
    except Exception:
        pass

def is_pid_running(pid: int, dossier=None) -> bool:
    """True if `pid` is alive, not a zombie, and — when `dossier` is given — is
    really this server (its working directory is the server folder).

    PIDs get recycled after a reboot, and a zombie still answers kill(pid, 0):
    neither may make us believe the server is up.
    """
    return plat.process_alive(pid, dossier)

def server_java_pids(dossier) -> list:
    """Live (non-zombie) java processes whose working directory is this server
    folder — the one reliable way to find a server's JVM, whatever its PID file
    or its port say."""
    return plat.find_server_processes(dossier)

def _port_in_use(port) -> bool:
    """True if something already LISTENS on this TCP port."""
    return plat.port_in_use(port)

def listens_on_all_interfaces(port):
    """True if something listens on 0.0.0.0 / :: for this TCP port (reachable
    from outside unless a firewall blocks it), False if only on specific
    addresses, None if nothing listens."""
    return plat.listens_on_all_interfaces(port)

def port_occupant(port):
    """(pid, program) of whatever listens on `port`, (None, None) if the port is
    busy but its owner cannot be read, or None if the port is free."""
    if not port or not _port_in_use(port):
        return None
    return plat.port_listener(port)

def is_server_running(config) -> bool:
    dossier = config.get("dossier_serveur", "")
    pid = get_server_pid(config)
    if pid and is_pid_running(pid, dossier):
        return True

    # The recorded PID is gone, but the server itself may still be up under
    # another PID (daemon restarted, run.sh wrapper replaced by its java
    # child...). Adopt its JVM — identified by java + working directory, never
    # by the port alone, which another program (another server, a sleep proxy)
    # may legitimately hold.
    java = server_java_pids(dossier)
    if java:
        _write_pid_file(config, java[0])
        return True

    _remove_pid_file(config)
    return False

def proc_memory(pid):
    """(rss_kb, swap_kb) of a process, or (None, None) if unreadable."""
    return plat.process_memory(pid)

def proc_cgroup(pid):
    """The process's cgroup path, or None."""
    return plat.cgroup_of(pid)

def zombie_java_pids():
    """[(pid, parent_pid)] of java processes left as zombies (never reaped)."""
    return plat.find_zombie_java()

def java_major_version(version_line):
    """'openjdk version "21.0.4" ...' -> 21 ; '"1.8.0_402"' -> 8 ; None if unknown."""
    import re
    m = re.search(r'version "(\d+)(?:\.(\d+))?', version_line or "")
    if not m:
        return None
    major = int(m.group(1))
    if major == 1 and m.group(2):
        major = int(m.group(2))
    return major

def _server_alive(config) -> bool:
    """Read-only liveness check (never rewrites server.pid)."""
    dossier = config.get("dossier_serveur", "")
    pid = get_server_pid(config)
    if pid and is_pid_running(pid, dossier):
        return True
    return bool(server_java_pids(dossier))

def wait_for_exit(config, timeout) -> bool:
    """Wait until the server process has really exited (zombies count as
    exited). The game port is released a moment BEFORE the JVM ends, so a
    restart that only waits for the port would launch a second JVM that fails
    on the world lock. Returns True if the process is gone."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not _server_alive(config):
            return True
        time.sleep(1)
    return not _server_alive(config)

# ==========================================
# MODE
# ==========================================

def effective_mode(config) -> str:
    if config.get("mode_maintenance", 0) == 1:
        return "maintenance"
    if config.get("always_on", 1) == 1:
        return "always-on"
    return "schedule"

def is_open_hours(current_m, start_m, end_m):
    """True if minute-of-day current_m falls in [start_m, end_m), across midnight."""
    if start_m < end_m:
        return start_m <= current_m < end_m
    return current_m >= start_m or current_m < end_m

def schedule_minutes(config):
    start = int(config.get("heure_ouverture", 20)) * 60 + int(config.get("minute_ouverture", 0))
    end = int(config.get("heure_fermeture", 3)) * 60 + int(config.get("minute_fermeture", 0))
    return start, end

def is_open_now(config, now=None):
    now = now or datetime.datetime.now()
    start, end = schedule_minutes(config)
    return is_open_hours(now.hour * 60 + now.minute, start, end)

PROXY_LOADERS = ("Velocity", "Waterfall", "BungeeCord")

def is_proxy(config):
    """Velocity, Waterfall and BungeeCord forward players to servers: no world, no RCON,
    stopped with SIGTERM, port set in their own config file."""
    return config.get("loader") in PROXY_LOADERS

def sync_proxy_port(config):
    """Write the configured port into velocity.toml / BungeeCord config.yml.
    Returns True if the file was changed."""
    import re
    dossier, port = config.get("dossier_serveur", ""), game_port(config)
    if not port:
        return False
    if config.get("loader") == "Velocity":
        path, pattern, repl = (os.path.join(dossier, "velocity.toml"),
                               r'(?m)^(\s*bind\s*=\s*")[^"]*(")', rf'\g<1>0.0.0.0:{port}\g<2>')
    else:
        path, pattern, repl = (os.path.join(dossier, "config.yml"),
                               r"(?m)^(\s*host:\s*)\S+", rf"\g<1>0.0.0.0:{port}")
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return False
    new = re.sub(pattern, repl, text, count=1)
    if new == text:
        return False
    with open(path, "w", encoding="utf-8") as f:
        f.write(new)
    return True

def guess_loader_and_version(config) -> tuple:
    loader = config.get("loader")
    mc_version = config.get("mc_version")
    if loader and mc_version:
        return loader, mc_version

    jar_name = (config.get("jar_name") or "").lower()
    if not loader:
        if "fabric" in jar_name:
            loader = "Fabric"
        elif "paper" in jar_name:
            loader = "Paper"
        elif "neoforge" in jar_name:
            loader = "NeoForge"
        elif "forge" in jar_name:
            loader = "Forge"
        elif "minecraft_server" in jar_name:
            loader = "Vanilla"

    if not mc_version:
        import re
        match = re.search(r"(\d+\.\d+(?:\.\d+)?)", jar_name)
        if match:
            mc_version = match.group(1)

    return loader, mc_version

# ==========================================
# RCON (native implementation, no external binary)
# ==========================================

def rcon_send_packet(sock, pkt_id, pkt_type, payload):
    payload_bytes = payload.encode("utf-8") + b"\x00\x00"
    length = 4 + 4 + len(payload_bytes)
    packet = struct.pack("<iii", length, pkt_id, pkt_type) + payload_bytes
    sock.sendall(packet)

def _recv_exact(sock, n):
    """Read exactly n bytes, or return None if the peer closed the connection.
    A bare recv() loop spins forever on a closed socket (recv returns b"")."""
    data = b""
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            return None
        data += chunk
    return data

def rcon_recv_packet(sock):
    raw_len = _recv_exact(sock, 4)
    if not raw_len:
        return None, None, None
    length = struct.unpack("<i", raw_len)[0]
    if length < 10 or length > 1 << 20:
        return None, None, None
    data = _recv_exact(sock, length)
    if data is None:
        return None, None, None
    pkt_id = struct.unpack("<i", data[0:4])[0]
    pkt_type = struct.unpack("<i", data[4:8])[0]
    payload = data[8:-2].decode("utf-8", errors="replace")
    return pkt_id, pkt_type, payload

def rcon_handshake(host, port, password, ping_only=False, timeout=5):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((host, int(port)))
        rcon_send_packet(sock, 1, 3, password)
        pkt_id, _, _ = rcon_recv_packet(sock)
        if pkt_id == -1:
            sock.close()
            return False, T["rcon_auth_failed"]
    except ConnectionRefusedError:
        return False, T["rcon_conn_refused"]
    except Exception as e:
        return False, T["rcon_error_generic"].format(e=e)
    if pkt_id is None:
        sock.close()
        return False, T["rcon_error_generic"].format(e="connection closed")

    if ping_only:
        sock.close()
        return True, "OK"
    return True, sock

def rcon_command(sock, command):
    """Send a command and read the full (possibly multi-packet) response.

    RCON fragments long replies across several type-2 packets. We send the
    command, then an empty "sentinel" packet with a distinct id; the server
    answers requests in order, so every fragment of the command reply arrives
    before the sentinel's echo. We accumulate until we see the sentinel id.
    """
    SENTINEL_ID = 999
    rcon_send_packet(sock, 2, 2, command)
    rcon_send_packet(sock, SENTINEL_ID, 2, "")
    chunks = []
    while True:
        try:
            pkt_id, _, payload = rcon_recv_packet(sock)
        except socket.timeout:
            break
        if pkt_id is None or pkt_id == SENTINEL_ID:
            break
        if payload:
            chunks.append(payload)
    return "".join(chunks)

def send_rcon(config, command):
    """Fire-and-forget a single RCON command.

    Returns True only if the handshake succeeded and the command bytes were
    delivered, so callers can tell a real send from a silent no-op when RCON
    is unreachable or misconfigured.
    """
    password = config.get("mcrcon_pass", "minecraft")
    rcon_port = config.get("rcon_port", DEFAULT_RCON_PORT)
    ok, sock_or_msg = rcon_handshake("127.0.0.1", rcon_port, password)
    if not ok:
        return False
    sock = sock_or_msg
    delivered = False
    try:
        rcon_send_packet(sock, 2, 2, command)
        delivered = True
        rcon_recv_packet(sock)  # best-effort; server may close socket on 'stop'
    except Exception:
        pass
    finally:
        try:
            sock.close()
        except Exception:
            pass
    return delivered

# ==========================================
# STARTUP READINESS
# ==========================================

def proc_uptime(pid):
    """Seconds since the process started, or None."""
    return plat.process_uptime(pid)

def rcon_responds(config):
    """True when RCON answers, False when it does not, None when no RCON is
    configured. A refused password still means the server is up."""
    if not config.get("mcrcon_pass"):
        return None
    ok, detail = rcon_handshake("127.0.0.1", config.get("rcon_port", DEFAULT_RCON_PORT),
                                config["mcrcon_pass"], ping_only=True, timeout=2)
    return ok or detail == T["rcon_auth_failed"]

def log_has_done(config, since=None, slack=5):
    """True when the current log shows the server finished starting ('Done (').
    `since` is the epoch the process started: an older log belongs to a
    previous run."""
    path = os.path.join(config.get("dossier_serveur", ""), "logs", "latest.log")
    try:
        if since is not None and os.path.getmtime(path) < since - slack:
            return False
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return any("Done (" in line for line in f)
    except OSError:
        return False

def server_ready(config):
    """True once the server can be driven: RCON answers, or (RCON absent or
    broken) the log reports 'Done'. Meaningful only for a live process."""
    responds = rcon_responds(config)
    if responds:
        return True
    pid = get_server_pid(config)
    uptime = proc_uptime(pid) if pid else None
    if uptime is None:
        for jvm in server_java_pids(config.get("dossier_serveur", "")):
            uptime = proc_uptime(jvm)
            if uptime is not None:
                break
    since = time.time() - uptime if uptime is not None else None
    return log_has_done(config, since, slack=0)

def startup_in_progress(config):
    return _server_alive(config) and not server_ready(config)

def wait_for_rcon(config, timeout):
    """Wait until the server answers on RCON. False if the process vanished
    or the delay ran out."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not _server_alive(config):
            return False
        if rcon_responds(config):
            return True
        time.sleep(1)
    return bool(rcon_responds(config))

# ==========================================
# AUTOMODPACK
# ==========================================

def get_automodpack_fingerprint(dossier_serveur):
    cert_path = os.path.join(dossier_serveur, "automodpack", ".private", "cert.crt")
    if not os.path.exists(cert_path):
        return None
    try:
        with open(cert_path, "r", encoding="utf-8") as f:
            pem = f.read()
        body = "".join(
            line.strip() for line in pem.splitlines()
            if line.strip() and not line.startswith("-----")
        )
        der = base64.b64decode(body)
        return hashlib.sha256(der).hexdigest()
    except Exception:
        return None

# ==========================================
# WEBHOOKS DISCORD
# ==========================================

def send_discord_webhook(config, payload, force=False):
    # Maintenance is silent, except explicit commands (mc announce) that pass force=True.
    if not force and config.get("mode_maintenance", 0) == 1:
        return False, T["maintenance_active"]

    url = config.get("webhook_url", "")
    if not url:
        return False, T["no_webhook"]
    if not url.startswith("https://"):
        return False, T["webhook_error"].format(e="https:// URL required")

    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "MCManagerBot/2.0"
            },
            method="POST"
        )
        urllib.request.urlopen(req, timeout=10)  # nosec B310 - https enforced above
        return True, "OK"
    except Exception as e:
        return False, T["webhook_error"].format(e=e)

class _SafeDict(dict):
    def __missing__(self, key):
        return "{" + key + "}"

def _build_embed(tpl, variables: dict, display_ip: str = None) -> dict:
    safe_vars = _SafeDict(variables)
    embed = {
        "title": tpl.get("title", "").format_map(safe_vars),
        "color": tpl.get("color", 0),
        "description": tpl.get("description", "").format_map(safe_vars)
    }
    fields = []
    if display_ip and tpl.get("show_ip", False):
        fields.append({"name": "🌐 IP", "value": f"`{display_ip}`", "inline": True})
    version_label = variables.get("version_label", "")
    if version_label and tpl.get("show_version", True):
        fields.append({"name": "⚙️ Version", "value": version_label, "inline": True})
    if fields:
        embed["fields"] = fields
    return embed

# ==========================================
# SERVER STARTUP
# ==========================================

def find_java(config=None):
    """The server's own runtime (mc java) when it has one, else the system Java."""
    if config and config.get("java") != "system":
        managed = config.get("java_path")
        if managed and os.access(managed, os.X_OK):
            return managed
    java = shutil.which("java")
    if java:
        return java
    import glob
    for pattern in plat.java_search_paths():
        for exe in sorted(glob.glob(pattern), reverse=True):
            if os.access(exe, os.X_OK):
                return exe
    return "java"

def check_java(config=None):
    java_exe = find_java(config)
    if java_exe == "java" and not shutil.which("java"):
        return False, "not found"
    try:
        result = subprocess.run(
            [java_exe, "-version"],
            capture_output=True, text=True, timeout=10
        )
        # Skip JVM notices such as "Picked up JAVA_TOOL_OPTIONS: ..." that can
        # precede the version line.
        lines = (result.stderr or result.stdout or "").splitlines()
        version_line = next((l for l in lines if "version" in l), lines[0] if lines else "?")
        return True, version_line.strip()
    except Exception:
        return False, "error"

def _display_address(config):
    """Address shown to players in webhooks: the configured domain/link if set,
    otherwise a port hint. IP<->DNS linking is done on the DNS provider's site,
    so MC Manager only displays the address, it never updates any DNS."""
    domaine = (config.get("domaine") or "").strip()
    port = str(public_port(config) or "25565")
    if domaine:
        return f"{domaine}:{port}" if port != "25565" else domaine
    return f"Port {port} (Local/Public IP)"

_JVM_ARGS_MARKER = "# Managed by MC Manager"

def _sync_run_script_ram(dossier, ram):
    """Write the configured heap size into Forge/NeoForge's user_jvm_args.txt.

    A server started through run.sh ignores any -Xms/-Xmx we pass on the command
    line: the script feeds the JVM that file instead. Without this sync the RAM
    chosen in MC Manager is silently dropped and the server runs on whatever the
    file says — by default nothing at all, i.e. the JVM's own heuristic.
    Commented lines are kept (they document the file); only active heap flags
    are replaced.
    """
    args_file = os.path.join(dossier, "user_jvm_args.txt")
    if not os.path.exists(args_file):
        return
    try:
        with open(args_file, "r", encoding="utf-8") as f:
            lines = f.readlines()

        kept = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith(_JVM_ARGS_MARKER):
                continue
            if not stripped.startswith("#") and ("-Xmx" in line or "-Xms" in line):
                continue
            kept.append(line)

        # The stock file ends without a newline: appending blindly would glue
        # our first flag onto the last comment.
        if kept and not kept[-1].endswith("\n"):
            kept[-1] += "\n"
        kept += [f"{_JVM_ARGS_MARKER}\n", f"-Xms{ram}\n", f"-Xmx{ram}\n"]

        tmp = args_file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.writelines(kept)
        plat.atomic_replace(tmp, args_file)
    except Exception:
        pass  # a broken sync must never prevent the server from starting

def is_hold_mode(config):
    return config.get("sleep_join_mode") == "hold" and config.get("sleep_enabled", 0) == 1


def game_port(config):
    """Port the server itself listens on: the internal one in hold mode (the
    sleep listener owns the public port), the configured one otherwise."""
    if (is_hold_mode(config) or config.get("router_backend")) and config.get("internal_port"):
        return int(config["internal_port"])
    return config.get("port")


def public_port(config):
    """Port players connect to: the router's when the server sits behind an
    enabled router, otherwise the configured one (in hold mode that is the
    port the sleep listener holds, never the internal one)."""
    if config.get("router_backend"):
        try:
            import mc_router
            router = mc_router.load()
            if router["enabled"]:
                return router["port"]
        except Exception:
            pass
    return config.get("port")


def default_internal_port(port):
    port = int(port)
    return port + 10000 if port + 10000 <= 65535 else port - 10000


def edit_yaml_scalar(path, key, value):
    """Set `key: value` on the first line of a YAML file that defines `key`,
    leaving every other byte alone. Returns the previous value, or None when
    the file or the key does not exist (nothing is written then)."""
    import re
    try:
        with open(path, "r", encoding="utf-8", errors="surrogateescape", newline="") as f:
            text = f.read()
    except OSError:
        return None
    pattern = re.compile(r"(?m)^(\s*" + re.escape(key) + r":[ \t]*)([^\s#]*)")
    match = pattern.search(text)
    if not match:
        return None
    old = match.group(2)
    if old != str(value):
        text = text[:match.start(2)] + str(value) + text[match.end(2):]
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8", errors="surrogateescape", newline="") as f:
            f.write(text)
        plat.atomic_replace(tmp, path)
    return old


def paper_proxy_protocol(config):
    """True/False when a Paper-family server's config/paper-global.yml says
    whether it expects PROXY protocol; None for a server without that file."""
    path = os.path.join(config.get("dossier_serveur", ""), "config", "paper-global.yml")
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            import re
            match = re.search(r"(?m)^\s*proxy-protocol:\s*(\w+)", f.read())
    except OSError:
        return None
    return match.group(1).lower() == "true" if match else None


def use_proxy_protocol(config):
    """Whether the sleep listener should send a PROXY v2 header to the server.
    'auto' follows what the server is configured to expect."""
    setting = str(config.get("sleep_proxy_protocol", "auto")).lower()
    if setting == "on":
        return True
    if setting == "off":
        return False
    return paper_proxy_protocol(config) is True


def sync_server_properties(config, apply=True):
    """Make server.properties agree with config.json, the single source of truth
    for the ports and RCON. A port changed by hand in config.json used to leave
    the server listening on the old one while the registry, dashboard and
    firewall showed the new one.

    Only the keys MC Manager owns are touched; every other line is kept as is.
    Returns the list of (key, old, new) changes, empty if already consistent.
    """
    dossier = config.get("dossier_serveur", "")
    props = os.path.join(dossier, "server.properties")
    if not dossier or not os.path.exists(props):
        return []
    wanted = {}
    port = game_port(config)
    if port:
        wanted["server-port"] = str(port)
    if is_hold_mode(config) or config.get("router_backend"):
        wanted["server-ip"] = "127.0.0.1"
    if config.get("mcrcon_pass"):
        wanted["enable-rcon"] = "true"
        wanted["rcon.port"] = str(config.get("rcon_port", DEFAULT_RCON_PORT))
        wanted["rcon.password"] = str(config["mcrcon_pass"])
    return _edit_properties(props, wanted, apply)

def set_properties(config, wanted):
    """Set server.properties keys (a dict of strings); returns the changes."""
    props = os.path.join(config.get("dossier_serveur", ""), "server.properties")
    if not os.path.exists(props):
        return []
    return _edit_properties(props, wanted, True)

def _edit_properties(props, wanted, apply):
    if not wanted:
        return []
    try:
        # surrogateescape keeps any non-UTF-8 byte of the file intact.
        with open(props, "r", encoding="utf-8", errors="surrogateescape") as f:
            lines = f.readlines()
    except Exception:
        return []

    changes, seen, out = [], set(), []
    for line in lines:
        stripped = line.lstrip("\ufeff")
        if "=" in stripped and not stripped.lstrip().startswith("#"):
            key, _, value = stripped.partition("=")
            key = key.strip()
            if key in wanted:
                seen.add(key)
                value = value.rstrip("\r\n")
                if value != wanted[key]:
                    changes.append((key, value, wanted[key]))
                    line = f"{key}={wanted[key]}\n"
        out.append(line)
    for key, value in wanted.items():
        if key not in seen:
            if out and not out[-1].endswith("\n"):
                out[-1] += "\n"
            out.append(f"{key}={value}\n")
            changes.append((key, None, value))
    if not changes or not apply:
        return changes
    try:
        tmp = props + ".tmp"
        with open(tmp, "w", encoding="utf-8", errors="surrogateescape") as f:
            f.writelines(out)
        plat.atomic_replace(tmp, props)
    except Exception:
        return []
    return changes

def start_server(config, send_webhook=True):
    import logging
    dossier = config.get("dossier_serveur", "")
    if not dossier or not os.path.exists(dossier):
        logging.error(f"Invalid folder: {dossier}")
        return False, T["invalid_dir"].format(path=dossier)
    if is_server_running(config):
        return False, T["already_online"]

    # Last-resort guard: something still holds the game port (a listener we
    # could not attribute to a PID, a foreign program...). Launching anyway
    # would start a JVM that fails on the world DirectoryLock and then lingers,
    # eating GBs of RAM without ever serving anything.
    port = game_port(config)
    occupant = port_occupant(port) if port else None
    if occupant:
        pid, prog = occupant
        logging.error(f"Port {port} already in use by {prog} (PID {pid}), refusing to start.")
        if pid:
            return False, T["start_port_busy_by"].format(port=port, prog=prog, pid=pid)
        return False, T["start_port_busy"].format(port=port)

    # config.json is the source of truth: push its ports/RCON into
    # server.properties and the registry before launching.
    for key, old, new in sync_server_properties(config):
        shown_old, shown_new = old, new
        if key == "rcon.password":
            shown_old, shown_new = "***", "***"
        if old is None:
            shown_old = "-"
        logging.warning(T["props_resynced"].format(key=key, old=shown_old, new=shown_new))
    try:
        import mc_servers
        mc_servers.update_cached_ports(dossier, port=config.get("port"), rcon_port=config.get("rcon_port"))
    except Exception:
        pass

    java_ok, java_detail = check_java(config)
    if not java_ok:
        logging.error(f"Java not found: {java_detail}")
        return False, T["java_not_found_start"]

    if is_proxy(config):
        sync_proxy_port(config)

    cpu_str = config.get("cpu_affinity", DEFAULT_CPU)
    try:
        cpu_set = cores_to_cpu_set(cpu_str)
    except Exception:
        cpu_set = None

    ram = config.get("ram_allocation", DEFAULT_RAM)
    java_flags = config.get("java_flags", DEFAULT_JAVA_FLAGS)
    jar_name = config.get("jar_name", DEFAULT_JAR_NAME)
    java_exe = find_java(config)

    logging.info(f"Launching Java: {java_exe}")
    logging.info(f"Folder: {dossier}")
    logging.info(f"JAR: {jar_name}")

    if jar_name.endswith(".sh"):
        # Forge/NeoForge: run.sh handles its own JVM invocation, reading its
        # heap settings from user_jvm_args.txt — so ram_allocation has to be
        # pushed into that file rather than passed on the command line.
        # bash stays alive while java runs, so PID tracking works correctly.
        # "nogui" is forwarded (via run.sh's $@) to the Minecraft server so it
        # starts headless — otherwise it opens its Swing GUI window, and closing
        # that window kills the server. Interact through 'mc console' instead.
        _sync_run_script_ram(dossier, ram)
        launch_args = plat.script_launch_args(jar_name)
        logging.info(f"Forge/NeoForge launch via script: {jar_name}")
    else:
        launch_args = [java_exe] + java_flags.split() + [
            f"-Xms{ram}", f"-Xmx{ram}",
            "-jar", os.path.join(dossier, jar_name),
        ]
        if not is_proxy(config):
            launch_args.append("nogui")

    # run.sh (Forge/NeoForge) calls plain 'java': put the server's runtime
    # first on PATH so it is the one used.
    env = dict(os.environ)
    if os.path.isabs(java_exe):
        env["JAVA_HOME"] = os.path.dirname(os.path.dirname(java_exe))
        env["PATH"] = os.path.dirname(java_exe) + os.pathsep + env.get("PATH", "")

    try:
        proc = plat.spawn_server(launch_args, dossier, env)
    except Exception as e:
        logging.error(f"Java launch error: {e}")
        return False, T["launch_error"].format(e=e)

    if cpu_set:
        set_process_affinity(proc.pid, cpu_set)

    # A JVM that dies instantly (port already bound, bad flags, corrupted jar)
    # must not be reported as a successful start.
    time.sleep(3)
    if proc.poll() is not None:
        logging.error(f"Server process exited immediately (code {proc.returncode})")
        try:
            import mc_crash
            mc_crash.record_failure(config, startup=True)
        except Exception:
            pass
        return False, T["start_crashed"].format(log=os.path.join(dossier, "logs", "latest.log"))

    _write_pid_file(config, proc.pid)
    logging.info(f"Server started PID={proc.pid}")

    display_ip = _display_address(config)

    if send_webhook:
        try:
            nom = config.get("nom_serveur", "Minecraft")
            automod = config.get("activer_automodpack", 0)
            cle = config.get("cle_automodpack", "")

            if automod == 1:
                fingerprint = get_automodpack_fingerprint(dossier)
                if fingerprint and fingerprint != cle:
                    cle = fingerprint
                    config["cle_automodpack"] = fingerprint
                    try:
                        mc_config.save_config(config)
                    except Exception:
                        pass

            loader, mc_version = guess_loader_and_version(config)
            version_label = " ".join(filter(None, [loader, mc_version]))

            templates = mc_config.load_webhooks(dossier)

            if automod == 1 and cle:
                tpl = templates.get("start_automod") or mc_config.get_fallback_webhook("start_automod")
                variables = {"nom": nom, "cle": cle, "version_label": version_label}
            else:
                tpl = templates.get("start_normal") or mc_config.get_fallback_webhook("start_normal")
                variables = {"nom": nom, "version_label": version_label}

            payload = {"embeds": [_build_embed(tpl, variables, display_ip)]}
            send_discord_webhook(config, payload)
        except Exception:
            pass
        _alert(config, "start")
    return True, T["server_launched"].format(ip=display_ip, pid=proc.pid)

# ==========================================
# SERVER SHUTDOWN
# ==========================================

STOP_TIMEOUT = 120     # seconds for a clean 'stop' before escalating
TERM_TIMEOUT = 30      # after SIGTERM, before SIGKILL
STARTUP_WAIT = 120     # a stop requested during startup waits this long for RCON

def _signal_server(config, action):
    """Apply `action` ('terminate', 'kill', 'suspend' or 'resume') to this
    server's processes: the recorded PID (and its process group when it leads
    one — the run.sh wrapper) plus every JVM running in the server folder.
    Never anything identified by the port alone."""
    dossier = config.get("dossier_serveur", "")
    targets = set(server_java_pids(dossier))
    sent = False
    pid = get_server_pid(config)
    leader = None
    if pid and is_pid_running(pid, dossier):
        targets.add(pid)
        leader = pid
    do = getattr(plat, action)
    for p in targets:
        if do(p, tree=(p == leader)):
            sent = True
    return sent

# Webhook template sent for each 'mc stop --reason'. Missing templates fall back
# to the built-in ones (mc_config._FALLBACK_WEBHOOKS).
STOP_WEBHOOKS = {
    None:          "stop",
    "user":        "stop",
    "sleep":       "stop_sleep",
    "update":      "stop_update",
    "maintenance": "stop_maintenance",
    "switch":      "stop_switch",
    "scheduled":   "stop_maintenance",
}

def stop_server(config, manual=True, wait=True, timeout=None, reason=None, quiet=False):
    """Stop the server cleanly and, by default, wait until its process is gone.

    Sequence: warn players, 'save-all flush' (the world is on disk from here
    on), 'stop' over RCON, wait; if the JVM hangs in its shutdown (seen: an
    RCON thread blocking it forever while holding GBs of RAM), SIGTERM, then
    SIGKILL — without data loss, the world was flushed first.
    `reason` picks the Discord announcement (see STOP_WEBHOOKS); `quiet`
    sends none. Returns (ok, message).
    """
    if not is_server_running(config):
        return False, T["already_offline"]
    resume_server(config)

    if timeout is None:
        try:
            timeout = int(config.get("stop_timeout", STOP_TIMEOUT))
        except (TypeError, ValueError):
            timeout = STOP_TIMEOUT

    if is_proxy(config):
        # Proxies have no RCON and no world: SIGTERM is their clean shutdown.
        _signal_server(config, "terminate")
        if wait_for_exit(config, TERM_TIMEOUT):
            _remove_pid_file(config)
            return True, T["stop_done"]
        _signal_server(config, "kill")
        wait_for_exit(config, 10)
        _remove_pid_file(config)
        return True, T["stop_done_kill"].format(secs=TERM_TIMEOUT)

    # RCON only opens once the server reports "Done": a stop issued during
    # startup waits for it, then falls back to SIGTERM (Minecraft saves the
    # world in its shutdown hook) instead of failing.
    startup_term = False
    if startup_in_progress(config):
        if not wait_for_rcon(config, STARTUP_WAIT):
            if not _server_alive(config):
                _remove_pid_file(config)
                return True, T["stop_done"]
            startup_term = True

    if not startup_term:
        send_rcon(config, "say " + T["ingame_stopping"])
        send_rcon(config, "save-all flush")
        if not send_rcon(config, "stop"):
            # The server looked ready but RCON refuses: never fail dry while the
            # JVM lives. Wait for RCON, then fall back to SIGTERM.
            if not _server_alive(config):
                _remove_pid_file(config)
                return True, T["stop_done"]
            sent = (config.get("mcrcon_pass") and wait_for_rcon(config, STARTUP_WAIT)
                    and send_rcon(config, "stop"))
            if not sent:
                if not _server_alive(config):
                    _remove_pid_file(config)
                    return True, T["stop_done"]
                startup_term = True

    if startup_term:
        _signal_server(config, "terminate")

    if manual and not quiet:
        # The scheduler raises the maintenance flag before stopping, so that the
        # daemon does not relaunch the server: its own stop is still announced.
        scheduled = reason == "scheduled"
        try:
            nom = config.get("nom_serveur", "Minecraft")
            key = STOP_WEBHOOKS.get(reason, "stop")
            templates = mc_config.load_webhooks(config["dossier_serveur"])
            tpl = templates.get(key) or mc_config.get_fallback_webhook(key) or mc_config.get_fallback_webhook("stop")
            payload = {"embeds": [_build_embed(tpl, {"nom": nom})]}
            send_discord_webhook(config, payload, force=scheduled)
        except Exception:
            pass
        _alert(config, "sleep" if reason == "sleep" else "stop", force=scheduled, reason=reason or "user")

    if not wait:
        return True, T["stop_sent"]

    if wait_for_exit(config, TERM_TIMEOUT if startup_term else timeout):
        _remove_pid_file(config)
        return True, T["stop_done_startup_term"] if startup_term else T["stop_done"]

    _signal_server(config, "terminate")
    if wait_for_exit(config, TERM_TIMEOUT):
        _remove_pid_file(config)
        return True, T["stop_done_term"].format(secs=timeout)

    _signal_server(config, "kill")
    gone = wait_for_exit(config, 10)
    if gone:
        _remove_pid_file(config)
        return True, T["stop_done_kill"].format(secs=timeout + TERM_TIMEOUT)
    return False, T["stop_still_running"]

def send_start_webhook(config):
    """Send the server startup announcement to Discord, bypassing maintenance mode."""
    dossier = config.get("dossier_serveur", "")
    display_ip = _display_address(config)
    nom = config.get("nom_serveur", "Minecraft")
    automod = config.get("activer_automodpack", 0)
    cle = config.get("cle_automodpack", "")
    if automod == 1:
        fingerprint = get_automodpack_fingerprint(dossier)
        if fingerprint:
            cle = fingerprint
    loader, mc_version = guess_loader_and_version(config)
    version_label = " ".join(filter(None, [loader, mc_version]))
    templates = mc_config.load_webhooks(dossier)
    if automod == 1 and cle:
        tpl = templates.get("start_automod") or mc_config.get_fallback_webhook("start_automod")
        variables = {"nom": nom, "cle": cle, "version_label": version_label}
    else:
        tpl = templates.get("start_normal") or mc_config.get_fallback_webhook("start_normal")
        variables = {"nom": nom, "version_label": version_label}
    payload = {"embeds": [_build_embed(tpl, variables, display_ip)]}
    return send_discord_webhook(config, payload, force=True)

SUSPENDED_MARKER = ".mcmanager_suspended"

def _suspended_path(config):
    return os.path.join(config.get("dossier_serveur", ""), SUSPENDED_MARKER)

def is_suspended(config):
    """True while the server's processes are held by SIGSTOP (sleep_freeze). A
    marker left behind by a JVM that has since died is removed."""
    path = _suspended_path(config)
    if not os.path.exists(path):
        return False
    if is_server_running(config):
        return True
    try:
        os.remove(path)
    except OSError:
        pass
    return False

def freeze_supported():
    """False when this platform cannot suspend a process (Windows). Probes with
    a PID that cannot exist, so nothing is ever signalled."""
    try:
        plat.suspend(2 ** 31 - 1)
    except Unsupported:
        return False
    except Exception:
        pass
    return True

def suspend_server(config):
    """SIGSTOP the server once its world is flushed. RAM stays allocated, CPU
    drops to zero. Returns (ok, code)."""
    if not is_server_running(config):
        return False, "offline"
    if is_suspended(config):
        return True, "already_suspended"
    if not send_rcon(config, "save-all flush"):
        return False, "rcon_error"
    try:
        with open(_suspended_path(config), "w", encoding="utf-8") as f:
            json.dump({"since": int(time.time())}, f)
    except OSError:
        return False, "marker_error"
    try:
        signaled = _signal_server(config, "suspend")
    except Unsupported:
        os.remove(_suspended_path(config))
        return False, "unsupported"
    if not signaled:
        os.remove(_suspended_path(config))
        return False, "signal_error"
    return True, "suspended"

def resume_server(config):
    """SIGCONT a suspended server. True if it was suspended."""
    path = _suspended_path(config)
    if not is_suspended(config):
        return False
    try:
        resumed = _signal_server(config, "resume")
    except Unsupported:
        return False
    if not resumed:
        return False
    try:
        os.remove(path)
    except OSError:
        pass
    return True

def force_kill_server(config):
    """SIGKILL this server's processes (identified by PID file and java + server
    folder — never by the port, which a legitimate third-party program may
    hold) and wait for them to be gone. Returns True if nothing survives."""
    _signal_server(config, "kill")
    gone = wait_for_exit(config, 10)
    if gone:
        _remove_pid_file(config)
    return gone

# ==========================================
# BACKUP
# ==========================================

def _prune_old_backups(dossier_backup, retention_days):
    """Delete backups older than retention_days (and their empty day folders).

    0 or negative disables pruning. The newest backup always survives and
    non-date folders are never touched. Returns the number of day folders
    removed.
    """
    import mc_backup
    if retention_days <= 0:
        return 0
    return mc_backup.apply_retention(dossier_backup, 0, retention_days)["folders"]


FREEZE_BACKUP_MAX = 1800


def _alert(config, event, **info):
    try:
        import mc_alert
        mc_alert.notify(config, event, **info)
    except Exception:
        pass


def _get_level_name(dossier):
    prop_file = os.path.join(dossier, "server.properties")
    if os.path.exists(prop_file):
        try:
            with open(prop_file, 'r', encoding='utf-8-sig', errors='replace') as f:
                for line in f:
                    if line.startswith("level-name="):
                        return line.strip().split("=", 1)[1] or "world"
        except Exception:
            pass
    return "world"

def backup_server(config, type_backup=None, housekeeping=True):
    if type_backup is None:
        type_backup = T["backup_type_manual"]
    dossier = config.get("dossier_serveur", "")
    dossier_backup = config.get("dossier_backup", "")

    if not dossier or not dossier_backup:
        return False, T["invalid_paths"]

    os.makedirs(dossier_backup, exist_ok=True)
    date_str = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    dossier_jour = os.path.join(dossier_backup, datetime.datetime.now().strftime("%Y-%m-%d"))
    os.makedirs(dossier_jour, exist_ok=True)

    level_name = _get_level_name(dossier)
    world_names = [
        name for name in (level_name, f"{level_name}_nether", f"{level_name}_the_end")
        if os.path.exists(os.path.join(dossier, name))
    ]
    if not world_names:
        return False, T["no_world_found"]

    zip_name = os.path.join(dossier_jour, f"backup_{type_backup}_{date_str}.zip")
    staging = os.path.join(dossier, "_mcmanager_backup_staging")

    # An external tool froze the world ('mc freeze'): saving is already off
    # and the world flushed; leave the freeze to its owner.
    import mc_api
    import mc_backup
    owns_freeze = False
    try:
        if is_server_running(config) and not mc_api.is_frozen(config) and not is_suspended(config):
            ok, code = mc_api.freeze(config, FREEZE_BACKUP_MAX)
            if not ok and code != "already_frozen":
                return False, T["backup_error"].format(e=code)
            owns_freeze = code == "frozen"
            if owns_freeze:
                # 'flush' makes the command return only once every chunk is on
                # disk; the pause covers servers whose RCON replies early.
                time.sleep(5)

        if os.path.exists(staging):
            shutil.rmtree(staging)
        os.makedirs(staging)
        for name in world_names:
            shutil.copytree(os.path.join(dossier, name), os.path.join(staging, name))
        if owns_freeze:
            mc_api.thaw(config)
            owns_freeze = False

        with zipfile.ZipFile(zip_name, 'w', zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(staging):
                for file in files:
                    filepath = os.path.join(root, file)
                    arcname = os.path.relpath(filepath, staging)
                    zf.write(filepath, arcname)
    except Exception as e:
        _alert(config, "backup_failed", detail=str(e))
        return False, T["backup_error"].format(e=e)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        if owns_freeze:
            mc_api.thaw(config)

    message = T["backup_ok"].format(btype=type_backup)
    if not housekeeping:
        return True, message
    mc_backup.apply_retention(dossier_backup, config.get("backup_keep", 0), config.get("backup_retention_days", 0))
    failed = [(n, d) for n, ok, d in mc_backup.push_all(
        config, zip_name, warn=lambda code: logging.warning(T[f"backup_{code}"])) if not ok]
    if failed:
        detail = "; ".join(f"{n}: {d}" for n, d in failed)
        _alert(config, "backup_failed", detail=detail)
        message += " " + T["backup_remote_failed"].format(detail=detail)
    return True, message
