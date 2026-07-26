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
            capture_output=True, text=True
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

def is_server_running(config) -> bool:
    pid = get_server_pid(config)
    if pid and is_pid_running(pid):
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

def rcon_recv_packet(sock):
    raw_len = sock.recv(4)
    if not raw_len:
        return None, None, None
    length = struct.unpack("<i", raw_len)[0]
    data = b""
    while len(data) < length:
        data += sock.recv(length - len(data))
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
    if not force and config.get("mode_maintenance", 0) == 1:
        return False, T["maintenance_active"]

    url = config.get("webhook_url", "")
    if not url:
        return False, T["no_webhook"]

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
        urllib.request.urlopen(req, timeout=10)
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
        version_line = (result.stderr or result.stdout).splitlines()[0]
        return True, version_line
    except Exception:
        return False, "error"

def start_server(config, send_webhook=True):
    import logging
    dossier = config.get("dossier_serveur", "")
    if not dossier or not os.path.exists(dossier):
        logging.error(f"Invalid folder: {dossier}")
        return False, T["invalid_dir"].format(path=dossier)
    if is_server_running(config):
        return False, T["already_online"]

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
        # Forge/NeoForge: run.bat handles its own JVM invocation (user_jvm_args.txt).
        # cmd /c stays alive while java runs, so PID tracking works correctly.
        # "nogui" is forwarded (via run.bat's %*) to the Minecraft server so it
        # starts headless — otherwise it opens its Swing GUI window, and closing
        # that window kills the server. Interact through 'mc console' instead.
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

    domain_full = config.get("duckdns_domain", "")
    token = config.get("duckdns_token", "")
    if domain_full and token:
        prefix = domain_full.split('.')[0]
        try:
            urllib.request.urlopen(
                f"https://www.duckdns.org/update?domains={prefix}&token={token}&ip=",
                timeout=10
            )
        except Exception:
            pass

    port = str(config.get("port", "25565"))
    if domain_full:
        display_domain = domain_full if ".duckdns.org" in domain_full else f"{domain_full}.duckdns.org"
        display_ip = f"{display_domain}:{port}" if port != "25565" else display_domain
    else:
        display_ip = f"Port {port} (Local/Public IP)"

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
    domain_full = config.get("duckdns_domain", "")
    port = str(config.get("port", "25565"))
    if domain_full:
        display_domain = domain_full if ".duckdns.org" in domain_full else f"{domain_full}.duckdns.org"
        display_ip = f"{display_domain}:{port}" if port != "25565" else display_domain
    else:
        display_ip = f"Port {port} (Local/Public IP)"
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
    if pid:
        try:
            subprocess.run(
                ["taskkill", "/F", "/PID", str(pid)],
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

