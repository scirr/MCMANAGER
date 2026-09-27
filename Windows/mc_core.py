import os
import subprocess
import json
import datetime
import sys
import shutil
import time
import zipfile
import urllib.request
import urllib.error
import ctypes
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

def cores_to_affinity_mask(cores_str: str) -> int:
    mask = 0
    for part in cores_str.split(','):
        part = part.strip()
        if '-' in part:
            start, end = map(int, part.split('-'))
            for i in range(start, end + 1):
                mask |= (1 << i)
        else:
            mask |= (1 << int(part))
    return mask

def set_process_affinity(pid: int, mask: int):
    try:
        PROCESS_ALL_ACCESS = 0x1F0FFF
        handle = ctypes.windll.kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
        if handle:
            ctypes.windll.kernel32.SetProcessAffinityMask(handle, mask)
            ctypes.windll.kernel32.CloseHandle(handle)
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

# Images a server process can legitimately run under: java directly, or
# cmd.exe when Forge/NeoForge is launched through run.bat.
_SERVER_IMAGES = {"java.exe", "javaw.exe", "cmd.exe"}

def is_pid_running(pid: int) -> bool:
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, errors="replace"
        )
        # PIDs get recycled after a reboot: a live PID belonging to another
        # program must not make us believe the server is still up.
        for line in result.stdout.splitlines():
            if f'"{pid}"' in line:
                image = line.split('","')[0].strip('"').lower()
                return image in _SERVER_IMAGES
        return False
    except Exception:
        return False

def _port_in_use(port) -> bool:
    """True if anything already listens on this TCP port (bind test)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("0.0.0.0", int(port)))  # nosec B104 - probes the public game port
        return False
    except OSError:
        return True
    except Exception:
        return False

def _port_listener_pid(port) -> int | None:
    """PID listening on the given TCP port, or None if unknown."""
    try:
        # errors="replace": netstat prints localised headers that the console
        # codepage cannot always decode — a crash here would wrongly report the
        # server as offline and let a duplicate start.
        result = subprocess.run(
            ["netstat", "-ano", "-p", "tcp"],
            capture_output=True, text=True, errors="replace", timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
    except Exception:
        return None
    needle = f":{int(port)}"
    for line in (result.stdout or "").splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0].upper() == "TCP" and parts[3].upper() == "LISTENING":
            if parts[1].endswith(needle):
                try:
                    return int(parts[4])
                except ValueError:
                    return None
    return None

def is_server_running(config) -> bool:
    pid = get_server_pid(config)
    if pid and is_pid_running(pid):
        return True

    # The recorded PID is gone, but the server itself may still be up under
    # another PID (service restarted, wrapper replaced by its java child...).
    # Adopt whoever holds the game port so the state repairs itself instead of
    # needing a manual server.pid fix — and so the always-on daemon never spawns
    # a duplicate JVM that dies on the world DirectoryLock.
    port = config.get("port")
    if port:
        listener = _port_listener_pid(port)
        if listener and is_pid_running(listener):
            try:
                with open(pid_file_path(config), 'w') as f:
                    f.write(str(listener))
            except Exception:
                pass
            return True

    pid_file = pid_file_path(config)
    if os.path.exists(pid_file):
        os.remove(pid_file)
    return False

# ==========================================
# MODE
# ==========================================

def effective_mode(config) -> str:
    if config.get("mode_maintenance", 0) == 1:
        return "maintenance"
    if config.get("always_on", 1) == 1:
        return "always-on"
    return "schedule"

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
# RCON
# ==========================================

def rcon_command(sock, command):
    """Send a command and read the full (possibly multi-packet) response.

    RCON fragments long replies across several type-2 packets. We send the
    command then an empty sentinel packet with a distinct id; the server
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
    """Fire-and-forget a single RCON command via native socket.

    Returns True only if the handshake succeeded and the command bytes were
    delivered, so callers can detect a real send from a silent no-op when RCON
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

def find_java():
    java = shutil.which("java")
    if java:
        return java
    candidates = [
        r"C:\Program Files\Java",
        r"C:\Program Files\Eclipse Adoptium",
        r"C:\Program Files\Microsoft",
        r"C:\Program Files\BellSoft",
    ]
    import glob
    for base in candidates:
        for exe in glob.glob(os.path.join(base, "**", "java.exe"), recursive=True):
            return exe
    return "java"

def check_java():
    java_exe = find_java()
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

    A server started through run.bat ignores any -Xms/-Xmx we pass on the command
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
    if port and _port_in_use(port):
        logging.error(f"Port {port} already in use, refusing to start a duplicate.")
        return False, T["start_port_busy"].format(port=port)

    java_ok, java_detail = check_java()
    if not java_ok:
        logging.error(f"Java not found: {java_detail}")
        return False, T["java_not_found_start"]

    cpu_str = config.get("cpu_affinity", DEFAULT_CPU)
    affinity_mask = cores_to_affinity_mask(cpu_str)

    ram = config.get("ram_allocation", DEFAULT_RAM)
    java_flags = config.get("java_flags", DEFAULT_JAVA_FLAGS)
    jar_name = config.get("jar_name", DEFAULT_JAR_NAME)
    java_exe = find_java()

    logging.info(f"Launching Java: {java_exe}")
    logging.info(f"Folder: {dossier}")
    logging.info(f"JAR: {jar_name}")

    if jar_name.endswith(".bat"):
        # Forge/NeoForge: run.bat handles its own JVM invocation, reading its
        # heap settings from user_jvm_args.txt — so ram_allocation has to be
        # pushed into that file rather than passed on the command line.
        # cmd /c stays alive while java runs, so PID tracking works correctly.
        # "nogui" is forwarded (via run.bat's %*) to the Minecraft server so it
        # starts headless — otherwise it opens its Swing GUI window, and closing
        # that window kills the server. Interact through 'mc console' instead.
        _sync_run_script_ram(dossier, ram)
        launch_args = ["cmd", "/c", jar_name, "nogui"]
        logging.info(f"Forge/NeoForge launch via script: {jar_name}")
    else:
        launch_args = [java_exe] + java_flags.split() + [
            f"-Xms{ram}", f"-Xmx{ram}",
            "-jar", os.path.join(dossier, jar_name),
            "nogui"
        ]

    try:
        # CREATE_NO_WINDOW only — NOT DETACHED_PROCESS. Detaching gives the
        # process no console at all, so a console child (java, or the java
        # launched by a Forge/NeoForge run.bat) allocates its own *visible*
        # window. CREATE_NO_WINDOW gives it a hidden console that its children
        # inherit (no window) and that is separate from the launching terminal,
        # so the server keeps running after that terminal is closed.
        proc = subprocess.Popen(
            launch_args,
            cwd=dossier,
            creationflags=subprocess.CREATE_NO_WINDOW,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL
        )
    except Exception as e:
        logging.error(f"Java launch error: {e}")
        return False, T["launch_error"].format(e=e)

    set_process_affinity(proc.pid, affinity_mask)

    # A JVM that dies instantly (port already bound, bad flags, corrupted jar)
    # must not be reported as a successful start.
    time.sleep(3)
    if proc.poll() is not None:
        logging.error(f"Server process exited immediately (code {proc.returncode})")
        return False, T["start_crashed"].format(log=os.path.join(dossier, "logs", "latest.log"))

    with open(pid_file_path(config), 'w') as f:
        f.write(str(proc.pid))
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

def stop_server(config, manual=True):
    if not is_server_running(config):
        return False, T["already_offline"]

    send_rcon(config, "say " + T["ingame_stopping"])
    send_rcon(config, "save-all")
    if not send_rcon(config, "stop"):
        return False, T["stop_rcon_unreachable"]

    if manual:
        try:
            nom = config.get("nom_serveur", "Minecraft")
            templates = mc_config.load_webhooks(config["dossier_serveur"])
            tpl = templates.get("stop") or mc_config.get_fallback_webhook("stop")
            payload = {"embeds": [_build_embed(tpl, {"nom": nom})]}
            send_discord_webhook(config, payload)
        except Exception:
            pass

    return True, T["stop_sent"]

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
    pid = get_server_pid(config)
    if not pid:
        # Stale or missing pid file: fall back to whoever holds the game port,
        # so an orphan JVM (failed start that never exited, service restarted...)
        # can still be killed with 'mc stop --force' instead of by hand.
        port = config.get("port")
        if port:
            pid = _port_listener_pid(port)
    if pid:
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW
            )
        except Exception:
            pass
    pid_file = pid_file_path(config)
    if os.path.exists(pid_file):
        os.remove(pid_file)

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
            with open(prop_file, 'r', encoding='utf-8') as f:
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

    try:
        if is_server_running(config):
            send_rcon(config, "save-off")
            send_rcon(config, "save-all")
            time.sleep(10)  # let the server flush chunks to disk before copying

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
        if is_server_running(config):
            send_rcon(config, "save-on")

