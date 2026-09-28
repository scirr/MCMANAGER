import os
import signal
import subprocess
import json
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
    try:
        os.sched_setaffinity(pid, cpu_set)
    except Exception:
        pass

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

# /proc helpers. Every one of them returns None when the information cannot be
# read (process gone, or owned by another user) so callers can tell "unknown"
# apart from "different".

def _proc_state(pid):
    try:
        with open(f"/proc/{pid}/stat") as f:
            return f.read().rsplit(")", 1)[1].split()[0]
    except Exception:
        return None

def _proc_cwd(pid):
    try:
        return os.path.realpath(os.readlink(f"/proc/{pid}/cwd"))
    except Exception:
        return None

def _proc_name(pid):
    try:
        with open(f"/proc/{pid}/comm") as f:
            return f.read().strip()
    except Exception:
        return None

def _proc_argv0(pid):
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            first = f.read().split(b"\x00", 1)[0]
        return os.path.basename(first.decode("utf-8", "replace"))
    except Exception:
        return None

def _is_java(pid):
    return "java" in ((_proc_name(pid) or "") + " " + (_proc_argv0(pid) or "")).lower()

def _same_dir(a, b):
    if not a or not b:
        return False
    return os.path.realpath(a) == os.path.realpath(b)

def is_pid_running(pid: int, dossier=None) -> bool:
    """True if `pid` is alive, not a zombie, and — when `dossier` is given — is
    really this server (its working directory is the server folder).

    PIDs get recycled after a reboot, and a zombie still answers kill(pid, 0):
    neither may make us believe the server is up.
    """
    # Reap the child first if it is ours and already exited (the daemon spawns
    # the servers, the CLI may too).
    try:
        os.waitpid(pid, os.WNOHANG)
    except (ChildProcessError, OSError):
        pass
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    except Exception:
        return False
    if _proc_state(pid) == "Z":
        return False
    if dossier:
        cwd = _proc_cwd(pid)
        if cwd is not None:
            return _same_dir(cwd, dossier)
    # Working directory unreadable (another user's process): fall back to the
    # command line, permissive on read failure.
    argv0 = _proc_argv0(pid)
    if argv0 and not any(m in argv0 for m in ("java", "bash", "sh")):
        return False
    return True

def server_java_pids(dossier) -> list:
    """Live (non-zombie) java processes whose working directory is this server
    folder — the one reliable way to find a server's JVM, whatever its PID file
    or its port say."""
    found = []
    if not dossier:
        return found
    target = os.path.realpath(dossier)
    try:
        entries = os.listdir("/proc")
    except Exception:
        return found
    for entry in entries:
        if not entry.isdigit():
            continue
        pid = int(entry)
        if pid == os.getpid():
            continue
        cwd = _proc_cwd(pid)
        if cwd != target or not _is_java(pid) or _proc_state(pid) in (None, "Z"):
            continue
        found.append(pid)
    return sorted(found)

def _port_in_use(port) -> bool:
    """True if something already LISTENS on this TCP port.

    SO_REUSEADDR mirrors how the JVM binds: without it, a socket lingering in
    TIME_WAIT after a closed connection makes the port look busy for a minute
    and blocks a perfectly safe start.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("0.0.0.0", int(port)))  # nosec B104 - probes the public game port
        return False
    except OSError:
        return True
    except Exception:
        return False

def _listen_inodes(port):
    """Socket inodes LISTENing on this TCP port, read from /proc/net/tcp{,6}."""
    inodes = set()
    for table in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            with open(table) as f:
                next(f, None)
                for line in f:
                    cols = line.split()
                    if len(cols) > 9 and cols[3] == "0A" and int(cols[1].rsplit(":", 1)[1], 16) == int(port):
                        inodes.add(cols[9])
        except Exception:
            continue
    return inodes

def listens_on_all_interfaces(port):
    """True if something listens on 0.0.0.0 / :: for this TCP port (reachable
    from outside unless a firewall blocks it), False if only on specific
    addresses, None if nothing listens."""
    found = None
    for table in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            with open(table) as f:
                next(f, None)
                for line in f:
                    cols = line.split()
                    if len(cols) < 4 or cols[3] != "0A":
                        continue
                    addr, _, hexport = cols[1].rpartition(":")
                    if int(hexport, 16) != int(port):
                        continue
                    if set(addr) == {"0"}:
                        return True
                    found = False
        except Exception:
            continue
    return found

def _port_listener_pid(port) -> int | None:
    """PID listening on the given TCP port, or None if unknown.

    Reads /proc directly (no dependency on 'ss'); only processes we are allowed
    to inspect can be found — others yield None ("busy, owner unknown")."""
    try:
        inodes = _listen_inodes(port)
    except Exception:
        return None
    if not inodes:
        return None
    wanted = {f"socket:[{i}]" for i in inodes}
    try:
        entries = os.listdir("/proc")
    except Exception:
        return None
    for entry in entries:
        if not entry.isdigit():
            continue
        fd_dir = f"/proc/{entry}/fd"
        try:
            fds = os.listdir(fd_dir)
        except Exception:
            continue
        for fd in fds:
            try:
                if os.readlink(f"{fd_dir}/{fd}") in wanted:
                    return int(entry)
            except Exception:
                continue
    return None

def port_occupant(port):
    """(pid, program) of whatever listens on `port`, (None, None) if the port is
    busy but its owner cannot be read, or None if the port is free."""
    if not port or not _port_in_use(port):
        return None
    pid = _port_listener_pid(port)
    if not pid:
        return (None, None)
    return (pid, _proc_name(pid) or "?")

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
    rss = swap = None
    try:
        with open(f"/proc/{pid}/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    rss = int(line.split()[1])
                elif line.startswith("VmSwap:"):
                    swap = int(line.split()[1])
    except Exception:
        pass
    return rss, swap

def proc_cgroup(pid):
    """The process's cgroup path (cgroup v2 unified line), or None."""
    try:
        with open(f"/proc/{pid}/cgroup") as f:
            for line in f:
                if line.startswith("0::"):
                    return line.strip()[3:]
            return None
    except Exception:
        return None

def zombie_java_pids():
    """[(pid, parent_pid)] of java processes left as zombies (never reaped)."""
    out = []
    try:
        entries = os.listdir("/proc")
    except Exception:
        return out
    for entry in entries:
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/stat") as f:
                raw = f.read()
        except Exception:
            continue
        name = raw[raw.find("(") + 1:raw.rfind(")")]
        rest = raw.rsplit(")", 1)[1].split()
        if rest and rest[0] == "Z" and "java" in name.lower():
            out.append((int(entry), int(rest[1])))
    return out

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
    dossier, port = config.get("dossier_serveur", ""), config.get("port")
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

def rcon_handshake(host, port, password, ping_only=False):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
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
    candidates = [
        "/usr/lib/jvm/*/bin/java",
        "/usr/java/*/bin/java",
        "/opt/java/*/bin/java",
        "/opt/jdk*/bin/java",
    ]
    for pattern in candidates:
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
    port = str(config.get("port", "25565"))
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
        os.replace(tmp, args_file)
    except Exception:
        pass  # a broken sync must never prevent the server from starting

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
    if config.get("port"):
        wanted["server-port"] = str(config["port"])
    if config.get("mcrcon_pass"):
        wanted["enable-rcon"] = "true"
        wanted["rcon.port"] = str(config.get("rcon_port", DEFAULT_RCON_PORT))
        wanted["rcon.password"] = str(config["mcrcon_pass"])
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
        os.replace(tmp, props)
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
    port = config.get("port")
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
        launch_args = ["bash", jar_name, "nogui"]
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
        proc = subprocess.Popen(
            launch_args,
            cwd=dossier,
            env=env,
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL
        )
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
    return True, T["server_launched"].format(ip=display_ip, pid=proc.pid)

# ==========================================
# SERVER SHUTDOWN
# ==========================================

STOP_TIMEOUT = 120     # seconds for a clean 'stop' before escalating
TERM_TIMEOUT = 30      # after SIGTERM, before SIGKILL

def _signal_server(config, sig):
    """Send `sig` to this server's processes: the recorded PID (and its process
    group when it leads one — the run.sh wrapper) plus every JVM running in the
    server folder. Never anything identified by the port alone."""
    dossier = config.get("dossier_serveur", "")
    targets = set(server_java_pids(dossier))
    pid = get_server_pid(config)
    if pid and is_pid_running(pid, dossier):
        targets.add(pid)
        try:
            if os.getpgid(pid) == pid:
                os.killpg(pid, sig)
        except Exception:
            pass
    for p in targets:
        try:
            os.kill(p, sig)
        except Exception:
            pass
    return bool(targets)

# Webhook template sent for each 'mc stop --reason'. Missing templates fall back
# to the built-in ones (mc_config._FALLBACK_WEBHOOKS).
STOP_WEBHOOKS = {
    None:          "stop",
    "user":        "stop",
    "sleep":       "stop_sleep",
    "update":      "stop_update",
    "maintenance": "stop_maintenance",
    "switch":      "stop_switch",
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

    if is_proxy(config):
        # Proxies have no RCON and no world: SIGTERM is their clean shutdown.
        _signal_server(config, signal.SIGTERM)
        if wait_for_exit(config, TERM_TIMEOUT):
            _remove_pid_file(config)
            return True, T["stop_done"]
        _signal_server(config, signal.SIGKILL)
        wait_for_exit(config, 10)
        _remove_pid_file(config)
        return True, T["stop_done_kill"].format(secs=TERM_TIMEOUT)

    send_rcon(config, "say " + T["ingame_stopping"])
    send_rcon(config, "save-all flush")
    if not send_rcon(config, "stop"):
        return False, T["stop_rcon_unreachable"]

    if manual and not quiet:
        try:
            nom = config.get("nom_serveur", "Minecraft")
            key = STOP_WEBHOOKS.get(reason, "stop")
            templates = mc_config.load_webhooks(config["dossier_serveur"])
            tpl = templates.get(key) or mc_config.get_fallback_webhook(key) or mc_config.get_fallback_webhook("stop")
            payload = {"embeds": [_build_embed(tpl, {"nom": nom})]}
            send_discord_webhook(config, payload)
        except Exception:
            pass

    if not wait:
        return True, T["stop_sent"]

    if timeout is None:
        try:
            timeout = int(config.get("stop_timeout", STOP_TIMEOUT))
        except (TypeError, ValueError):
            timeout = STOP_TIMEOUT
    if wait_for_exit(config, timeout):
        _remove_pid_file(config)
        return True, T["stop_done"]

    _signal_server(config, signal.SIGTERM)
    if wait_for_exit(config, TERM_TIMEOUT):
        _remove_pid_file(config)
        return True, T["stop_done_term"].format(secs=timeout)

    _signal_server(config, signal.SIGKILL)
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

def force_kill_server(config):
    """SIGKILL this server's processes (identified by PID file and java + server
    folder — never by the port, which a legitimate third-party program may
    hold) and wait for them to be gone. Returns True if nothing survives."""
    _signal_server(config, signal.SIGKILL)
    gone = wait_for_exit(config, 10)
    if gone:
        _remove_pid_file(config)
    return gone

# ==========================================
# BACKUP
# ==========================================

def _prune_old_backups(dossier_backup, retention_days):
    """Delete daily backup folders (YYYY-MM-DD) older than retention_days.

    0 or negative disables pruning. Non-date folders are never touched.
    Returns the number of folders removed.
    """
    if retention_days <= 0 or not os.path.isdir(dossier_backup):
        return 0
    cutoff = (datetime.datetime.now() - datetime.timedelta(days=retention_days)).date()
    removed = 0
    for entry in os.listdir(dossier_backup):
        full = os.path.join(dossier_backup, entry)
        if not os.path.isdir(full):
            continue
        try:
            day = datetime.datetime.strptime(entry, "%Y-%m-%d").date()
        except ValueError:
            continue
        if day < cutoff:
            shutil.rmtree(full, ignore_errors=True)
            removed += 1
    return removed


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

def backup_server(config, type_backup=None):
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
    frozen = os.path.exists(os.path.join(dossier, ".mcmanager_frozen"))
    try:
        if is_server_running(config) and not frozen:
            send_rcon(config, "save-off")
            # 'flush' makes the command return only once every chunk is on
            # disk; the pause covers servers whose RCON replies early.
            send_rcon(config, "save-all flush")
            time.sleep(5)

        if os.path.exists(staging):
            shutil.rmtree(staging)
        os.makedirs(staging)
        for name in world_names:
            shutil.copytree(os.path.join(dossier, name), os.path.join(staging, name))

        with zipfile.ZipFile(zip_name, 'w', zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(staging):
                for file in files:
                    filepath = os.path.join(root, file)
                    arcname = os.path.relpath(filepath, staging)
                    zf.write(filepath, arcname)

        _prune_old_backups(dossier_backup, int(config.get("backup_retention_days", 0) or 0))

        return True, T["backup_ok"].format(btype=type_backup)

    except Exception as e:
        return False, T["backup_error"].format(e=e)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        if is_server_running(config) and not frozen:
            send_rcon(config, "save-on")

