#!/usr/bin/env python3
"""
mc_deploy.py — Automated Minecraft server deployment (Linux)
Supports: Vanilla, Paper, Fabric, Forge, NeoForge
"""
import hashlib
import json
import os
import secrets
import shutil
import subprocess
import re
import sys
import urllib.request
import urllib.parse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(BASE_DIR)
import mc_core
import mc_config
import mc_servers
from mc_lang import T, VERSION
from mc_validate import valid_port, valid_ram

# ─── helpers ──────────────────────────────────────────────────────────────────

C = {
    "reset": "\033[0m", "cyan": "\033[96m", "green": "\033[92m",
    "yellow": "\033[93m", "red": "\033[91m", "gray": "\033[90m",
    "bold": "\033[1m",
}

def pr(level, msg):
    icons = {
        "info": f"{C['cyan']}[{T['icon_info']}]{C['reset']}",
        "ok":   f"{C['green']}[{T['icon_ok']}]{C['reset']}",
        "warn": f"{C['yellow']}[{T['icon_warn']}]{C['reset']}",
        "err":  f"{C['red']}[{T['icon_err']}]{C['reset']}",
        "step": f"{C['bold']}{C['cyan']}===>{C['reset']}",
    }
    print(f"{icons.get(level, '')} {msg}")

def ask(prompt, default="", secret=False):
    hint = f" {C['gray']}[{T['word_default']}: {default}]{C['reset']}" if default != "" else ""
    try:
        import getpass
        val = getpass.getpass(f"{prompt}{hint} : ") if secret else input(f"{prompt}{hint} : ").strip()
    except (EOFError, KeyboardInterrupt):
        sys.exit(130)
    return val if val else default

def ask_int(prompt, default, validate=None, error_key="enter_valid_number"):
    while True:
        val = ask(prompt, str(default))
        try:
            ival = int(val)
        except ValueError:
            pr("warn", T["enter_valid_number"])
            continue
        if validate and not validate(ival):
            pr("warn", T[error_key].format(val=ival))
            continue
        return ival

def ask_nonempty(prompt, default=""):
    while True:
        val = ask(prompt, default)
        if val and val.strip():
            return val.strip()
        pr("warn", T["name_empty"])

def ask_yn(prompt, default=True):
    suffix = T["yn_yes"] if default else T["yn_no"]
    val = ask(f"{prompt} {suffix}").lower()
    if val == "":
        return default
    return val in ("o", "oui", "y", "yes")

# Third-party APIs (PaperMC, Modrinth...) ask clients to identify themselves.
USER_AGENT = f"MCManager/{VERSION} (https://github.com/scirr/MCMANAGER)"

def _require_https(url):
    if not str(url).startswith("https://"):
        raise ValueError(f"refusing non-https URL: {url}")

def download(url, dest, label=""):
    pr("info", T["downloading"].format(label=f" {label}" if label else ""))
    try:
        _require_https(url)
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as f:  # nosec B310 - https checked
            total = int(r.headers.get("Content-Length", 0))
            done = 0
            while True:
                chunk = r.read(65536)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if total:
                    pct = done * 100 // total
                    print(f"\r  {pct}% ({done // 1024} Ko / {total // 1024} Ko)  ", end="", flush=True)
        print()
        return True
    except Exception as e:
        pr("err", T["download_failed"].format(e=e))
        return False

def fetch_json(url):
    try:
        _require_https(url)
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=15) as r:  # nosec B310 - https only
            return json.loads(r.read().decode())
    except Exception as e:
        pr("err", T["api_error"].format(e=e))
        return None

def verify_checksum(path, algo, expected):
    """Compare a downloaded file against the hash published by the API.

    Returns True when the file matches (or when no hash was provided — some
    APIs don't publish one). On mismatch the corrupted file is deleted so a
    retry starts clean.
    """
    if not expected:
        return True
    h = hashlib.new(algo)
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    if h.hexdigest().lower() == expected.lower():
        pr("ok", T["checksum_verified"].format(algo=algo.upper()))
        return True
    try:
        os.remove(path)
    except OSError:
        pass
    pr("err", T["checksum_failed"].format(file=os.path.basename(path)))
    return False

def write_eula(server_dir):
    with open(os.path.join(server_dir, "eula.txt"), "w") as f:
        f.write("eula=true\n")
    pr("ok", T["eula_accepted"])


# ─── Check directory is not empty ───────────────────────────────────────────

def _dir_has_server(path):
    if not os.path.isdir(path):
        return False
    return any(
        f.endswith(".jar")
        or f == "eula.txt"
        or f in ("server.properties", "run.bat", "run.sh")
        for f in os.listdir(path)
    )


# ─── server.properties ──────────────────────────────────────────────────────

def generate_server_properties(server_dir, config, rcon_pass="", rcon_port=25575):
    props_path = os.path.join(server_dir, "server.properties")

    # Keys MC Manager owns: they mirror config.json, so a port or RCON change
    # via 'mc configure' must overwrite them — otherwise the server keeps
    # listening on the old port while the dashboard/firewall show the new one.
    managed = {}
    if config.get("port"):
        managed["server-port"] = str(config["port"])
    if config.get("description_serveur"):
        managed["motd"] = config["description_serveur"]
    if rcon_pass:
        managed["enable-rcon"] = "true"
        managed["rcon.password"] = rcon_pass
        managed["rcon.port"] = str(rcon_port)

    defaults = {
        "server-port":         str(config["port"]),
        "motd":                config.get("description_serveur", "A Minecraft Server"),
        "max-players":         "20",
        "online-mode":         "true",
        "difficulty":          "normal",
        "gamemode":            "survival",
        "enable-rcon":         "true" if rcon_pass else "false",
        "rcon.password":       rcon_pass,
        "rcon.port":           str(rcon_port),
        "level-name":          "world",
        "view-distance":       "10",
        "simulation-distance": "10",
    }

    existing = {}
    lines = []
    if os.path.exists(props_path):
        with open(props_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        for line in lines:
            if "=" in line and not line.startswith("#"):
                k, _, _ = line.partition("=")
                existing[k.strip()] = True

    new_lines = []
    for line in lines:
        if "=" in line and not line.startswith("#"):
            k = line.partition("=")[0].strip()
            if k in managed:
                new_lines.append(f"{k}={managed[k]}\n")
                continue
        new_lines.append(line)
    for k, v in defaults.items():
        if k not in existing:
            new_lines.append(f"{k}={v}\n")

    with open(props_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

    pr("ok", T["server_props_gen"])


# ─── Version picker ─────────────────────────────────────────────────────────

def pick_minecraft_version():
    pr("info", T["versions_fetching"])
    data = fetch_json("https://launchermeta.mojang.com/mc/game/version_manifest_v2.json")
    if not data:
        return ask(T["version_prompt"], "1.21.4")
    releases = [v["id"] for v in data["versions"] if v["type"] == "release"][:15]
    print(f"\n{C['cyan']}{T['versions_header']}{C['reset']}")
    for i, v in enumerate(releases, 1):
        print(f"  {C['gray']}{i:2}.{C['reset']} {v}")
    choice = ask(f"\n{T['version_prompt']}", releases[0])
    if choice.isdigit() and 1 <= int(choice) <= len(releases):
        return releases[int(choice) - 1]
    return choice


# ─── Vanilla ─────────────────────────────────────────────────────────────────

def deploy_vanilla(server_dir, mc_version):
    pr("step", T["step_vanilla"])
    data = fetch_json("https://launchermeta.mojang.com/mc/game/version_manifest_v2.json")
    if not data:
        return None
    url = next((v["url"] for v in data["versions"] if v["id"] == mc_version), None)
    if not url:
        pr("err", T["version_not_found"].format(ver=mc_version))
        return None
    meta = fetch_json(url)
    if not meta:
        return None
    dl_url = meta["downloads"]["server"]["url"]
    expected_sha1 = meta["downloads"]["server"].get("sha1")
    jar = f"minecraft_server.{mc_version}.jar"
    dest = os.path.join(server_dir, jar)
    if not download(dl_url, dest, f"Vanilla {mc_version}"):
        return None
    if not verify_checksum(dest, "sha1", expected_sha1):
        return None
    return jar


# ─── Paper ───────────────────────────────────────────────────────────────────

PAPER_API = "https://fill.papermc.io/v3/projects/paper"

def pick_paper_build(builds):
    """(build, warn) from the Fill v3 build list: the newest STABLE build, else
    the newest build of any channel (warn=True). None when there is none."""
    usable = [b for b in builds or []
              if ((b.get("downloads") or {}).get("server:default") or {}).get("url")]
    if not usable:
        return None, False
    stable = [b for b in usable if str(b.get("channel", "")).upper() == "STABLE"]
    pool = stable or usable
    return max(pool, key=lambda b: int(b.get("id", 0))), not stable

def deploy_paper(server_dir, mc_version):
    # PaperMC API v2 was retired: Fill v3 lists builds with their channel,
    # download URL and SHA-256.
    pr("step", T["step_paper"])
    builds = fetch_json(f"{PAPER_API}/versions/{mc_version}/builds")
    if isinstance(builds, dict):
        builds = builds.get("builds", [])
    build, not_stable = pick_paper_build(builds)
    if not build:
        pr("err", T["paper_not_available"].format(ver=mc_version))
        return None
    if not_stable:
        pr("warn", T["paper_no_stable"].format(ver=mc_version, build=build.get("id"),
                                               channel=build.get("channel", "?")))
    download_info = build["downloads"]["server:default"]
    jar_name = download_info.get("name") or f"paper-{mc_version}-{build.get('id')}.jar"
    expected_sha256 = (download_info.get("checksums") or {}).get("sha256")
    dest = os.path.join(server_dir, jar_name)
    if not download(download_info["url"], dest, f"Paper {mc_version} build#{build.get('id')}"):
        return None
    if not verify_checksum(dest, "sha256", expected_sha256):
        return None
    return jar_name


# ─── Fabric ──────────────────────────────────────────────────────────────────

def deploy_fabric(server_dir, mc_version):
    pr("step", T["step_fabric"])
    loaders = fetch_json("https://meta.fabricmc.net/v2/versions/loader")
    installers = fetch_json("https://meta.fabricmc.net/v2/versions/installer")
    if not loaders or not installers:
        return None
    loader_v = loaders[0]["version"]
    installer_v = installers[0]["version"]
    jar_name = f"fabric-server-{mc_version}-{loader_v}.jar"
    url = (f"https://meta.fabricmc.net/v2/versions/loader/{mc_version}"
           f"/{loader_v}/{installer_v}/server/jar")
    dest = os.path.join(server_dir, jar_name)
    if not download(url, dest, f"Fabric {mc_version}"):
        return None
    launch = os.path.join(server_dir, "fabric-server-launch.jar")
    if not os.path.exists(launch):
        shutil.copy2(dest, launch)
    return "fabric-server-launch.jar"


# ─── Forge ───────────────────────────────────────────────────────────────────

def _forge_maven_versions(mc_version):
    url = "https://files.minecraftforge.net/net/minecraftforge/forge/maven-metadata.xml"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=15) as r:  # nosec B310 - https only
            content = r.read().decode()
        return re.findall(r"<version>(" + re.escape(mc_version) + r"-[^<]+)</version>", content)
    except Exception:
        return []

def deploy_forge(server_dir, mc_version):
    pr("step", T["step_forge"])
    versions = _forge_maven_versions(mc_version)
    if not versions:
        pr("err", T["no_forge_versions"].format(ver=mc_version))
        return None
    forge_ver = versions[-1]
    pr("info", T["forge_selected"].format(ver=forge_ver))
    installer_name = f"forge-{forge_ver}-installer.jar"
    url = (f"https://files.minecraftforge.net/net/minecraftforge/forge"
           f"/{forge_ver}/{installer_name}")
    installer_path = os.path.join(server_dir, installer_name)
    if not download(url, installer_path, f"Forge {forge_ver} installer"):
        return None
    pr("info", T["forge_installing"])
    try:
        result = subprocess.run(
            [_installer_java(mc_version), "-jar", installer_name, "--installServer"],
            cwd=server_dir, capture_output=True, text=True, timeout=300
        )
        if result.returncode != 0:
            pr("err", T["forge_failed"])
            print(result.stderr[-2000:])
            return None
    except subprocess.TimeoutExpired:
        pr("err", T["forge_timeout"])
        return None
    finally:
        try:
            os.remove(installer_path)
            pr("info", T["forge_installer_del"])
        except OSError:
            pass

    if os.path.exists(os.path.join(server_dir, "run.sh")):
        pr("ok", T["forge_ok"])
        return "@run.sh"

    jars = [f for f in os.listdir(server_dir)
            if f.endswith(".jar") and "forge" in f.lower() and "installer" not in f.lower()]
    return jars[0] if jars else None


# ─── NeoForge ────────────────────────────────────────────────────────────────

def neoforge_version_prefix(mc_version):
    """Map a Minecraft version to the NeoForge API prefix filter.

    NeoForge versioning: MC 1.X.Y -> NeoForge X.Y.z ; MC 1.X -> NeoForge X.0.z.
    The API filter is a PREFIX match, so the result MUST end with a dot —
    without it, filter "21.1" also matches "21.11.*"/"21.10.*" (Minecraft
    1.21.11/1.21.10) and picks a newer, wrong Minecraft version.
    """
    parts = mc_version.split(".")
    major = parts[1] if len(parts) > 1 else "0"
    minor = parts[2] if len(parts) > 2 else "0"
    return f"{major}.{minor}."

def deploy_neoforge(server_dir, mc_version):
    pr("step", T["step_neoforge"])
    neo_base = neoforge_version_prefix(mc_version)
    data = fetch_json(
        f"https://maven.neoforged.net/api/maven/latest/version/releases"
        f"/net/neoforged/neoforge?filter={neo_base}"
    )
    if not data or "version" not in data:
        pr("err", T["neoforge_not_available"].format(ver=mc_version))
        return None
    neo_ver = data["version"]
    installer_name = f"neoforge-{neo_ver}-installer.jar"
    url = (f"https://maven.neoforged.net/releases/net/neoforged/neoforge"
           f"/{neo_ver}/{installer_name}")
    installer_path = os.path.join(server_dir, installer_name)
    if not download(url, installer_path, f"NeoForge {neo_ver} installer"):
        return None
    pr("info", T["neoforge_installing"])
    try:
        result = subprocess.run(
            [_installer_java(mc_version), "-jar", installer_name, "--install-server", "."],
            cwd=server_dir, capture_output=True, text=True, timeout=300
        )
        if result.returncode != 0:
            pr("err", T["neoforge_failed"])
            print(result.stderr[-2000:])
            return None
    except subprocess.TimeoutExpired:
        pr("err", T["neoforge_timeout"])
        return None
    finally:
        try:
            os.remove(installer_path)
            pr("info", T["neoforge_installer_del"])
        except OSError:
            pass

    if os.path.exists(os.path.join(server_dir, "run.sh")):
        pr("ok", T["neoforge_ok"])
        return "@run.sh"

    jars = [f for f in os.listdir(server_dir)
            if f.endswith(".jar") and "neoforge" in f.lower() and "installer" not in f.lower()]
    return jars[0] if jars else None


# ─── RCON setup ──────────────────────────────────────────────────────────────

def setup_rcon(server_dir, config):
    """RCON on Linux is spoken natively by MC Manager (no external binary):
    only the password and port need to be configured here. The default password
    is randomly generated — RCON grants full server control, so a guessable
    default like 'minecraft' must never be silently accepted."""
    pr("step", T["rcon_step"])
    default_pass = config.get("mcrcon_pass") or secrets.token_hex(16)
    rcon_pass = ask(T["rcon_pass_prompt"], default_pass, secret=True)

    game_port = config.get("port")
    while True:
        rcon_port = ask_int(T["rcon_port_prompt"], config.get("rcon_port", 25575),
                            validate=valid_port, error_key="invalid_port")
        if game_port and rcon_port == game_port:
            pr("warn", T["rcon_same_as_game_port"].format(rcon=rcon_port, game=game_port))
            continue
        conflit = mc_servers.find_port_conflict(rcon_port=rcon_port)
        if conflit:
            pr("warn", T["rcon_port_conflict"].format(port=rcon_port, name=conflit))
            continue
        break

    config["mcrcon_pass"] = rcon_pass
    config["rcon_port"] = rcon_port

    pr("ok", T["rcon_configured_ok"].format(port=rcon_port))
    return config, rcon_pass, rcon_port


# ─── AutoModpack ─────────────────────────────────────────────────────────────

AUTOMODPACK_LOADER_MAP = {
    "Vanilla":  None,
    "Paper":    None,     # plugin-based, not the same AutoModpack mod
    "Fabric":   "fabric",
    "Forge":    "forge",
    "NeoForge": "neoforge",
}

def check_automodpack_availability(mc_version, modrinth_loader):
    if not modrinth_loader:
        return None
    gv_param = urllib.parse.quote(json.dumps([mc_version]))
    loaders_param = urllib.parse.quote(json.dumps([modrinth_loader]))
    url = (
        f"https://api.modrinth.com/v2/project/automodpack/version"
        f"?loaders={loaders_param}&game_versions={gv_param}"
    )
    data = fetch_json(url)
    return data[0] if data else None

def setup_automodpack(server_dir, config, mc_version, srv_name):
    modrinth_loader = AUTOMODPACK_LOADER_MAP.get(srv_name)

    if not modrinth_loader:
        # Not supported for this loader — mark as decided so we never ask again
        config["activer_automodpack"] = 0
        return config

    pr("step", T["automod_checking"])

    # Already installed — skip download and prompt entirely
    mods_dir = os.path.join(server_dir, "mods")
    existing = [f for f in os.listdir(mods_dir) if os.path.isfile(os.path.join(mods_dir, f))
                and "automodpack" in f.lower()] if os.path.isdir(mods_dir) else []
    if existing:
        pr("ok", T["automod_already"])
        config["activer_automodpack"] = 1
        fingerprint = mc_core.get_automodpack_fingerprint(server_dir)
        if fingerprint:
            config["cle_automodpack"] = fingerprint
        return config

    version_info = check_automodpack_availability(mc_version, modrinth_loader)
    if not version_info:
        pr("warn", T["automod_unavail"].format(ver=mc_version, loader=srv_name))
        config["activer_automodpack"] = 0
        return config

    pr("ok", T["automod_avail"].format(aver=version_info['version_number'], loader=srv_name, ver=mc_version))
    pr("info", T["automod_desc"])
    if not ask_yn(T["automod_prompt"], default=True):
        config["activer_automodpack"] = 0
        return config

    os.makedirs(mods_dir, exist_ok=True)
    file_info = version_info["files"][0]
    url = file_info["url"]
    jar_name = url.split("/")[-1].split("?")[0]
    dest = os.path.join(mods_dir, jar_name)

    if not download(url, dest, "AutoModpack"):
        return config

    config["activer_automodpack"] = 1

    fingerprint = mc_core.get_automodpack_fingerprint(server_dir)
    if fingerprint:
        config["cle_automodpack"] = fingerprint
        pr("ok", T["automod_key_found"].format(fp=fingerprint))
    else:
        pr("info", T["automod_key_later"])

    pr("ok", T["automod_installed"].format(path=mods_dir))
    return config


# ─── Other server types (mc_software) ───────────────────────────────────────

def _installer_java(mc_version, loader="Forge"):
    """The Temurin runtime Minecraft `mc_version` needs (downloaded once into
    the application's java/ folder), else the system Java."""
    import mc_java
    import mc_software
    res = mc_java.install(mc_software.java_for(loader, mc_version))
    return res["path"] if res["ok"] else mc_core.find_java()


def _software(loader):
    """deploy_<loader>(server_dir, mc_version) built on mc_software.install."""
    def deploy(server_dir, mc_version):
        import mc_software
        pr("step", T["step_software"].format(loader=loader))
        if loader == "Spigot":
            pr("info", T["spigot_buildtools"])
        res = mc_software.install(server_dir, loader, mc_version, java=_installer_java(mc_version, loader))
        if not res["ok"]:
            pr("err", T["software_failed"].format(loader=loader, ver=mc_version,
                                                  detail=res.get("detail") or res["code"]))
            return None
        if res.get("unstable"):
            pr("warn", T["software_unstable"].format(loader=loader))
        return "@run.sh" if res["jar_name"] == "run.sh" else res["jar_name"]
    return deploy


# ─── Entry point ─────────────────────────────────────────────────────────────

SERVER_TYPES = {
    "1":  ("Vanilla",    deploy_vanilla),
    "2":  ("Paper",      deploy_paper),
    "3":  ("Fabric",     deploy_fabric),
    "4":  ("Forge",      deploy_forge),
    "5":  ("NeoForge",   deploy_neoforge),
    "6":  ("Purpur",     _software("Purpur")),
    "7":  ("Folia",      _software("Folia")),
    "8":  ("Quilt",      _software("Quilt")),
    "9":  ("Spigot",     _software("Spigot")),
    "10": ("Velocity",   _software("Velocity")),
    "11": ("Waterfall",  _software("Waterfall")),
    "12": ("BungeeCord", _software("BungeeCord")),
}
PROXY_CHOICES = {"10", "11", "12"}


def run_deploy(config: dict) -> dict:
    print(f"\n{C['bold']}{C['cyan']}{'='*45}")
    print(f"   {T['deploy_header']}")
    print(f"{'='*45}{C['reset']}\n")

    config["nom_serveur"] = ask_nonempty(T["prompt_server_name"], config.get("nom_serveur", "Minecraft"))
    config["description_serveur"] = ask(
        T["prompt_motd"], config.get("description_serveur", f"Serveur {config['nom_serveur']}")
    )

    existing_slugs = mc_servers.list_servers().keys()
    slug = mc_servers.slugify(config["nom_serveur"], existing_slugs)
    default_dir = os.path.join(mc_servers.DATA_ROOT, slug, "Server")
    server_dir = os.path.expanduser(ask(T["prompt_install_dir"], default_dir))

    if _dir_has_server(server_dir):
        pr("warn", T["dir_has_server"].format(path=server_dir))
        if not ask_yn(T["dir_has_server_cont"], default=False):
            pr("warn", T["deploy_cancelled"])
            return config

    config["dossier_serveur"] = server_dir

    print(f"\n{C['cyan']}{T['server_type_header']}{C['reset']}")
    for k, (name, _) in SERVER_TYPES.items():
        print(f"  {C['gray']}{k}.{C['reset']} {name}")
    srv_choice = ask(f"\n{T['choice']}", "2")
    if srv_choice not in SERVER_TYPES:
        pr("err", T["invalid_choice"])
        return config
    srv_name, deploy_fn = SERVER_TYPES[srv_choice]

    mc_version = "proxy" if srv_choice in PROXY_CHOICES else pick_minecraft_version()
    config["loader"] = srv_name
    config["mc_version"] = mc_version

    while True:
        port = ask_int(T["prompt_port"], config.get("port", 25565),
                       validate=valid_port, error_key="invalid_port")
        conflit = mc_servers.find_port_conflict(port=port)
        if conflit:
            pr("warn", T["port_conflict_deploy"].format(port=port, name=conflit))
            continue
        break
    config["port"] = port

    print(f"\n{C['cyan']}{T['summary']}{C['reset']}")
    pr("info", f"{T['summary_name'].format(name=config['nom_serveur'])}")
    pr("info", f"{T['summary_type'].format(stype=srv_name)}")
    pr("info", f"{T['summary_version'].format(ver=mc_version)}")
    pr("info", f"{T['summary_port'].format(port=port)}")
    pr("info", f"{T['summary_dir'].format(path=server_dir)}")
    if not ask_yn(f"\n{T['confirm_deploy']}"):
        pr("warn", T["deploy_cancelled"])
        return config

    os.makedirs(server_dir, exist_ok=True)
    jar = deploy_fn(server_dir, mc_version)
    if not jar:
        pr("err", T["deploy_failed_dl"])
        return config

    write_eula(server_dir)

    if jar.startswith("@"):
        run_script = jar[1:]
        config["jar_name"] = run_script
        pr("ok", T["jar_run_bat"].format(stype=srv_name, script=run_script))
    else:
        config["jar_name"] = jar
        pr("ok", T["jar_main"].format(jar=jar))

    import mc_java
    import mc_software
    java = mc_java.install(mc_software.java_for(srv_name, mc_version))
    if java["ok"]:
        config["java_major"], config["java_path"] = java["major"], java["path"]
        pr("ok", T["java_managed"].format(major=java["major"]))
    else:
        pr("warn", T["java_managed_failed"].format(major=java.get("major", "?")))

    config = mc_config.ensure_provisioning(config, server_dir)

    print()
    default_backup = os.path.join(mc_servers.DATA_ROOT, slug, "Backup")
    config["dossier_backup"] = os.path.expanduser(ask(
        T["prompt_backup_dir"], config.get("dossier_backup", default_backup)
    ))

    mc_servers.register_server(
        config["nom_serveur"], server_dir,
        port=config.get("port"), rcon_port=config.get("rcon_port"),
        set_active=True
    )
    mc_config.save_config(config)

    print(f"\n{C['green']}{C['bold']}{T['deploy_success'].format(stype=srv_name, ver=mc_version)}{C['reset']}")
    pr("info", T["deploy_dir_info"].format(path=server_dir))

    print()
    if ask_yn(T["advanced_prompt"], default=True):
        config = mc_config.run_setup_schedule(config)
        config = mc_config.run_setup_performance(config)
        config = mc_config.run_setup_integrations(config)
        mc_config.save_config(config)
        pr("ok", T["advanced_saved"])
    else:
        pr("info", T["later_hint"])

    pr("info", T["start_hint"])

    return config


def _free_port(start, taken):
    port = int(start)
    while port in taken or mc_core._port_in_use(port):
        port += 1
    return port


def _registry_ports():
    taken = set()
    for info in mc_servers.list_servers().values():
        for key in ("port", "rcon_port"):
            if info.get(key):
                taken.add(int(info[key]))
    return taken


def run_deploy_auto(name, loader="Paper", version=None, folder=None, port=None, rcon_port=None,
                    ram="4G", accept_eula=False):
    """Non-interactive 'mc deploy --yes'. Returns a result dict; progress lines
    are printed (the caller routes them to stderr in --json mode)."""
    def result(ok, code, **data):
        return {"ok": ok, "code": code, **data}

    if not accept_eula:
        return result(False, "eula_required")
    if not name or not str(name).strip():
        return result(False, "name_required")
    types = {label.lower(): (label, fn) for label, fn in SERVER_TYPES.values()}
    if str(loader).lower() not in types:
        return result(False, "unknown_loader", loader=loader, loaders=[v[0] for v in SERVER_TYPES.values()])
    loader_name, deploy_fn = types[str(loader).lower()]
    if not valid_ram(ram):
        return result(False, "invalid_ram", ram=ram)

    if loader_name in ("Velocity", "Waterfall", "BungeeCord"):
        version = "proxy"
    if not version:
        manifest = fetch_json("https://piston-meta.mojang.com/mc/game/version_manifest_v2.json")
        if not manifest:
            return result(False, "version_lookup_failed")
        version = manifest["latest"]["release"]

    slug = mc_servers.slugify(name, mc_servers.list_servers().keys())
    folder = os.path.abspath(os.path.expanduser(folder or os.path.join(mc_servers.DATA_ROOT, slug, "Server")))
    if _dir_has_server(folder):
        return result(False, "folder_not_empty", path=folder)

    port, rcon_port, error = allocate_ports(port, rcon_port)
    if error:
        return result(False, error[0], port=error[1])

    created = not os.path.exists(folder)
    os.makedirs(folder, exist_ok=True)
    jar = deploy_fn(folder, version)
    if not jar:
        if created and not os.listdir(folder):
            os.rmdir(folder)
        return result(False, "download_failed", loader=loader_name, version=version)
    write_eula(folder)

    return finalize_new_server(name, folder, loader_name, version, jar, port, rcon_port, ram)


def finalize_new_server(name, folder, loader, version, jar, port, rcon_port, ram="4G", extra=None):
    """Write config.json, server.properties, firewall rule and registry entry
    for a freshly installed server. Shared by 'mc deploy --yes' and
    'mc modpack install'."""
    config = {
        "nom_serveur": name,
        "description_serveur": name,
        "dossier_serveur": folder,
        "dossier_backup": os.path.join(os.path.dirname(folder), "Backup"),
        "loader": loader,
        "mc_version": version,
        "port": int(port),
        "rcon_port": int(rcon_port),
        "mcrcon_pass": secrets.token_hex(16),
        "ram_allocation": str(ram),
        "jar_name": jar[1:] if jar.startswith("@") else jar,
        "always_on": 1,
        "activer_automodpack": 0,
    }
    config.update(extra or {})
    if not config.get("java_path"):
        import mc_java
        import mc_software
        res = mc_java.install(mc_software.java_for(loader, version))
        if res["ok"]:
            config["java_major"], config["java_path"] = res["major"], res["path"]
    if mc_core.is_proxy(config):
        config.pop("mcrcon_pass", None)
        config.pop("rcon_port", None)
    config = mc_config.ensure_provisioning(config, folder)
    slug = mc_servers.register_server(name, folder, port=config["port"], rcon_port=config.get("rcon_port"),
                                      set_active=True)
    mc_config.save_config(config)
    return {"ok": True, "code": "deployed", "server": slug, "loader": loader, "version": version,
            "path": folder, "port": config["port"], "rcon_port": config.get("rcon_port"), "jar": config["jar_name"]}


def allocate_ports(port=None, rcon_port=None):
    """(port, rcon_port, error_code): the first free ones when not given."""
    taken = _registry_ports()
    if port is None:
        port = _free_port(25565, taken)
    elif not valid_port(port) or mc_servers.find_port_conflict(port=port, rcon_port=port):
        return None, None, ("port_taken", port)
    taken.add(int(port))
    if rcon_port is None:
        rcon_port = _free_port(25575, taken)
    elif (not valid_port(rcon_port) or int(rcon_port) == int(port)
          or mc_servers.find_port_conflict(port=rcon_port, rcon_port=rcon_port)):
        return None, None, ("port_taken", rcon_port)
    return int(port), int(rcon_port), None


def _detect_existing_port(server_dir, fallback=25565):
    prop_file = os.path.join(server_dir, "server.properties")
    if os.path.exists(prop_file):
        try:
            with open(prop_file, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.startswith("server-port="):
                        return int(line.strip().split("=", 1)[1])
        except Exception:
            pass
    return fallback


def run_add(config: dict) -> dict:
    print(f"\n{C['bold']}{C['cyan']}{'='*45}")
    print(f"   {T['add_header']}")
    print(f"{'='*45}{C['reset']}\n")

    server_dir = ask(T["add_dir_prompt"], config.get("dossier_serveur", ""))
    server_dir = os.path.expanduser(server_dir)

    if not server_dir or not os.path.isdir(server_dir):
        pr("err", T["add_dir_not_exists"].format(path=server_dir))
        return config

    if not _dir_has_server(server_dir):
        pr("warn", T["add_not_a_server"].format(path=server_dir))
        if not ask_yn(T["add_continue_anyway"], default=False):
            pr("warn", T["add_cancelled"])
            return config

    # ── Load existing config.json if present ─────────────────────────────────
    existing = mc_config.load_config(server_dir)
    had_existing_config = bool(existing)
    if existing:
        config.update(existing)
        pr("ok", T["config_loaded"])
        display_fields = [
            ("nom_serveur",         T["prompt_server_name"]),
            ("jar_name",            T["add_jar_prompt"]),
            ("port",                T["prompt_port"]),
            ("dossier_backup",      T["prompt_backup_dir"]),
            ("loader",              T["field_version"]),
            ("mcrcon_pass",         T["rcon_pass_prompt"]),
        ]
        for key, label in display_fields:
            val = config.get(key)
            if val is not None and str(val) != "":
                display = "***" if key == "mcrcon_pass" else val
                print(f"\033[90m{T['config_field_loaded'].format(label=label, val=display)}\033[0m")

    config["dossier_serveur"] = server_dir

    # ── Only ask for missing essential fields ─────────────────────────────────
    if not config.get("nom_serveur"):
        nom_defaut = os.path.basename(server_dir.rstrip("/")) or "Minecraft"
        config["nom_serveur"] = ask_nonempty(T["prompt_server_name"], nom_defaut)

    if not config.get("description_serveur"):
        config["description_serveur"] = ask(
            T["prompt_motd"], f"Serveur {config['nom_serveur']}"
        )

    detected_jar = mc_config.detect_default_jar(server_dir)
    if not config.get("jar_name"):
        config["jar_name"] = ask(T["add_jar_prompt"], detected_jar)

    loader, mc_version = mc_core.guess_loader_and_version(config)
    if loader and not config.get("loader"):
        config["loader"] = loader
    if mc_version and not config.get("mc_version"):
        config["mc_version"] = mc_version
    if not had_existing_config:
        if loader or mc_version:
            pr("info", T["add_detected"].format(loader=config.get("loader") or "?", ver=config.get("mc_version") or "?"))
        else:
            pr("info", T["add_not_detected"])

    if not config.get("port"):
        while True:
            port = ask_int(T["prompt_port"], _detect_existing_port(server_dir),
                           validate=valid_port, error_key="invalid_port")
            conflit = mc_servers.find_port_conflict(port=port)
            if conflit:
                pr("warn", T["add_port_conflict"].format(port=port, name=conflit))
                continue
            break
        config["port"] = port
    else:
        conflit = mc_servers.find_port_conflict(port=config["port"])
        if conflit:
            pr("warn", T["add_port_conflict"].format(port=config["port"], name=conflit))
            while True:
                port = ask_int(T["prompt_port"], _detect_existing_port(server_dir),
                               validate=valid_port, error_key="invalid_port")
                if not mc_servers.find_port_conflict(port=port):
                    config["port"] = port
                    break
                pr("warn", T["add_port_conflict"].format(port=port, name=mc_servers.find_port_conflict(port=port)))

    if not config.get("dossier_backup"):
        default_backup = os.path.join(os.path.dirname(server_dir.rstrip("/")), "Backup")
        config["dossier_backup"] = os.path.expanduser(ask(T["prompt_backup_dir"], default_backup))

    # ── Register and save ─────────────────────────────────────────────────────
    mc_servers.register_server(
        config["nom_serveur"], server_dir,
        port=config.get("port"), rcon_port=config.get("rcon_port"),
        set_active=True
    )
    mc_config.save_config(config)
    pr("ok", T["add_registered_ok"].format(name=config["nom_serveur"]))

    config = mc_config.ensure_provisioning(config, server_dir)
    mc_config.save_config(config)

    # ── Review / advanced options ─────────────────────────────────────────────
    print()
    if had_existing_config:
        if ask_yn(T["review_config_prompt"], default=False):
            config = mc_config.run_setup_schedule(config)
            config = mc_config.run_setup_performance(config)
            config = mc_config.run_setup_integrations(config)
            mc_config.save_config(config)
            pr("ok", T["advanced_saved"])
        else:
            pr("info", T["later_hint"])
    else:
        if ask_yn(T["advanced_prompt"], default=True):
            config = mc_config.run_setup_schedule(config)
            config = mc_config.run_setup_performance(config)
            config = mc_config.run_setup_integrations(config)
            mc_config.save_config(config)
            pr("ok", T["advanced_saved"])
        else:
            pr("info", T["later_hint"])

    pr("info", T["start_hint"])
    return config
