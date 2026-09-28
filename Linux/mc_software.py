"""
mc_software.py — Server software installers, non-interactive.

One entry point per question:
- latest_release()                 newest Minecraft release
- available(loader, mc_version)    is this loader published for that version?
- install(folder, loader, ...)     download (and run the installer when the
                                   loader has one), verified by the hashes the
                                   APIs publish

Loaders: Vanilla, Paper, Folia, Purpur, Fabric, Quilt, Forge, NeoForge,
Spigot (BuildTools), and the proxies Velocity and BungeeCord. Everything
returns result dicts; nothing prints.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(BASE_DIR)

import mc_http

MOJANG_MANIFEST = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
PAPER_FILL = "https://fill.papermc.io/v3/projects"
PURPUR = "https://api.purpurmc.org/v2/purpur"
FABRIC_META = "https://meta.fabricmc.net/v2/versions"
QUILT_META = "https://meta.quiltmc.org/v3/versions"
QUILT_INSTALLER = "https://maven.quiltmc.org/repository/release/org/quiltmc/quilt-installer"
FORGE_MAVEN = "https://maven.minecraftforge.net/net/minecraftforge/forge"
NEOFORGE_API = "https://maven.neoforged.net/api/maven/latest/version/releases/net/neoforged/neoforge"
NEOFORGE_MAVEN = "https://maven.neoforged.net/releases/net/neoforged/neoforge"
BUILDTOOLS = "https://hub.spigotmc.org/jenkins/job/BuildTools/lastSuccessfulBuild/artifact/target/BuildTools.jar"
BUNGEECORD = "https://ci.md-5.net/job/BungeeCord/lastSuccessfulBuild/artifact/bootstrap/target/BungeeCord.jar"

LOADERS = ("Vanilla", "Paper", "Folia", "Purpur", "Fabric", "Quilt", "Forge", "NeoForge",
           "Spigot", "Velocity", "Waterfall", "BungeeCord")
PROXIES = ("Velocity", "Waterfall", "BungeeCord")
PLUGIN_LOADERS = ("Paper", "Folia", "Purpur", "Spigot", "Velocity", "Waterfall", "BungeeCord")
MOD_LOADERS = ("Fabric", "Quilt", "Forge", "NeoForge")


def result(ok, code, **data):
    return {"ok": ok, "code": code, **data}


def canonical(loader):
    """'neoforge' / 'NeoForge' / 'quilt-loader' -> the LOADERS spelling."""
    key = str(loader or "").lower().replace("-loader", "").replace("_", "")
    for name in LOADERS:
        if name.lower() == key:
            return name
    return None


def version_key(v):
    return tuple(int(p) if p.isdigit() else 0 for p in re.split(r"[.\-+]", str(v)))


# ── Minecraft versions ───────────────────────────────────────────────────────

def mojang_manifest():
    return mc_http.get_json(MOJANG_MANIFEST)


def latest_release(manifest=None):
    return (manifest or mojang_manifest())["latest"]["release"]


def minecraft_exists(mc_version, manifest=None):
    return any(v["id"] == mc_version for v in (manifest or mojang_manifest())["versions"])


# ── PaperMC (Paper, Folia, Velocity) ─────────────────────────────────────────

def _paper_builds(project, version):
    """[(build_number, file_name, url, sha256, stable)] from PaperMC Fill v3,
    STABLE builds first, newest first (the v2 API was retired)."""
    try:
        data = mc_http.get_json(f"{PAPER_FILL}/{project}/versions/{version}/builds")
    except mc_http.HttpError as e:
        if e.status == 404:
            return []
        raise
    builds = data if isinstance(data, list) else data.get("builds", [])
    out = []
    for b in builds:
        dl = (b.get("downloads") or {}).get("server:default") or {}
        if dl.get("url"):
            stable = str(b.get("channel", "")).upper() == "STABLE"
            out.append((int(b.get("id", 0)), dl.get("name") or f"{project}-{version}-{b.get('id')}.jar",
                        dl["url"], (dl.get("checksums") or {}).get("sha256"), stable))
    return sorted(out, key=lambda t: (t[4], t[0]), reverse=True)


def _paper_project_versions(project):
    for address in (f"{PAPER_FILL}/{project}",):
        try:
            data = mc_http.get_json(address)
        except mc_http.HttpError:
            continue
        versions = data.get("versions", [])
        flat = []
        if isinstance(versions, dict):
            for group in versions.values():
                flat += list(group) if isinstance(group, list) else [group]
        else:
            flat = list(versions)
        if flat:
            return sorted(set(flat), key=version_key)
    return []


# ── availability ─────────────────────────────────────────────────────────────

def available(loader, mc_version):
    """(True, loader_version) if `loader` exists for `mc_version`, else
    (False, reason_code). Network errors raise mc_http.HttpError."""
    loader = canonical(loader)
    if loader is None:
        return False, "unknown_loader"
    if loader in PROXIES:
        return True, None
    if loader != "Spigot" and not minecraft_exists(mc_version):
        return False, "unknown_minecraft_version"
    if loader in ("Vanilla", "Spigot"):
        return True, None
    if loader in ("Paper", "Folia"):
        builds = _paper_builds(loader.lower(), mc_version)
        return (True, str(builds[0][0])) if builds else (False, "loader_unavailable")
    if loader == "Purpur":
        try:
            data = mc_http.get_json(f"{PURPUR}/{mc_version}")
        except mc_http.HttpError as e:
            if e.status == 404:
                return False, "loader_unavailable"
            raise
        latest = (data.get("builds") or {}).get("latest")
        return (True, str(latest)) if latest else (False, "loader_unavailable")
    if loader in ("Fabric", "Quilt"):
        meta = FABRIC_META if loader == "Fabric" else QUILT_META
        try:
            entries = mc_http.get_json(f"{meta}/loader/{mc_version}")
        except mc_http.HttpError as e:
            if e.status in (400, 404):
                return False, "loader_unavailable"
            raise
        if not entries:
            return False, "loader_unavailable"
        stable = [e for e in entries if (e.get("loader") or {}).get("stable", True)]
        return True, (stable or entries)[0]["loader"]["version"]
    if loader == "Forge":
        versions = forge_versions(mc_version)
        return (True, versions[-1].split("-", 1)[1]) if versions else (False, "loader_unavailable")
    if loader == "NeoForge":
        try:
            data = mc_http.get_json(mc_http.url(NEOFORGE_API, filter=neoforge_prefix(mc_version)))
        except mc_http.HttpError as e:
            if e.status == 404:
                return False, "loader_unavailable"
            raise
        return (True, data["version"]) if data.get("version") else (False, "loader_unavailable")
    return False, "unknown_loader"


def forge_versions(mc_version):
    xml = mc_http.get_text(f"{FORGE_MAVEN}/maven-metadata.xml")
    return re.findall(r"<version>(" + re.escape(mc_version) + r"-[^<]+)</version>", xml)


def neoforge_prefix(mc_version):
    """1.21.1 -> '21.1.' ; 1.21 -> '21.0.' (the trailing dot keeps 21.1 from
    matching 21.10/21.11). Year-based versions 26.1 -> '26.1.'."""
    parts = mc_version.split(".")
    if parts[0] != "1":
        return f"{parts[0]}.{parts[1] if len(parts) > 1 else '0'}."
    major = parts[1] if len(parts) > 1 else "0"
    minor = parts[2] if len(parts) > 2 else "0"
    return f"{major}.{minor}."


# ── install ──────────────────────────────────────────────────────────────────

def _run_installer(args, folder, timeout):
    try:
        proc = subprocess.run(args, cwd=folder, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, "installer timed out"
    except OSError as e:
        return False, str(e)
    if proc.returncode != 0:
        return False, (proc.stderr or proc.stdout or "")[-1500:]
    return True, ""


def install(folder, loader, mc_version, loader_version=None, java="java", progress=None):
    """Install `loader` for `mc_version` into `folder`. Returns a result with
    jar_name (a jar, or 'run.sh' for Forge/NeoForge) and loader_version."""
    loader = canonical(loader)
    if loader is None:
        return result(False, "unknown_loader")
    os.makedirs(folder, exist_ok=True)
    try:
        if loader == "Vanilla":
            manifest = mojang_manifest()
            entry = next((v for v in manifest["versions"] if v["id"] == mc_version), None)
            if not entry:
                return result(False, "unknown_minecraft_version", loader=loader, mc_version=mc_version)
            server = mc_http.get_json(entry["url"])["downloads"]["server"]
            jar = f"minecraft_server.{mc_version}.jar"
            mc_http.download(server["url"], os.path.join(folder, jar), {"sha1": server.get("sha1")}, progress=progress)
            return result(True, "installed", loader=loader, mc_version=mc_version, jar_name=jar, loader_version=None)

        if loader in ("Paper", "Folia", "Velocity", "Waterfall"):
            project = loader.lower()
            version = mc_version
            if loader in PROXIES:
                versions = _paper_project_versions(project)
                version = loader_version or (versions[-1] if versions else None)
                if not version:
                    return result(False, "loader_unavailable", loader=loader, mc_version=mc_version)
            builds = _paper_builds(project, version)
            if not builds:
                return result(False, "loader_unavailable", loader=loader, mc_version=mc_version)
            build, name, address, sha256, stable = builds[0]
            mc_http.download(address, os.path.join(folder, name), {"sha256": sha256}, progress=progress)
            return result(True, "installed", loader=loader, mc_version="proxy" if loader in PROXIES else mc_version,
                          jar_name=name, loader_version=str(version if loader in PROXIES else build),
                          unstable=not stable)

        if loader == "Purpur":
            ok, build = available("Purpur", mc_version)
            if not ok:
                return result(False, build, loader=loader, mc_version=mc_version)
            info = mc_http.get_json(f"{PURPUR}/{mc_version}/{build}")
            jar = f"purpur-{mc_version}-{build}.jar"
            mc_http.download(f"{PURPUR}/{mc_version}/{build}/download", os.path.join(folder, jar),
                             {"md5": info.get("md5")}, progress=progress)
            return result(True, "installed", loader=loader, mc_version=mc_version, jar_name=jar, loader_version=build)

        if loader == "Fabric":
            if not loader_version:
                ok, loader_version = available("Fabric", mc_version)
                if not ok:
                    return result(False, loader_version, loader=loader, mc_version=mc_version)
            installers = mc_http.get_json(f"{FABRIC_META}/installer")
            installer = next((i["version"] for i in installers if i.get("stable")), installers[0]["version"])
            jar = "fabric-server-launch.jar"
            mc_http.download(f"{FABRIC_META}/loader/{mc_version}/{loader_version}/{installer}/server/jar",
                             os.path.join(folder, jar), progress=progress)
            return result(True, "installed", loader=loader, mc_version=mc_version, jar_name=jar,
                          loader_version=loader_version)

        if loader == "Quilt":
            if not loader_version:
                ok, loader_version = available("Quilt", mc_version)
                if not ok:
                    return result(False, loader_version, loader=loader, mc_version=mc_version)
            xml = mc_http.get_text(f"{QUILT_INSTALLER}/maven-metadata.xml")
            installer = re.search(r"<release>([^<]+)</release>", xml).group(1)
            with tempfile.TemporaryDirectory() as tmp:
                jar_path = os.path.join(tmp, "quilt-installer.jar")
                mc_http.download(f"{QUILT_INSTALLER}/{installer}/quilt-installer-{installer}.jar", jar_path)
                ok, detail = _run_installer([java, "-jar", jar_path, "install", "server", mc_version, loader_version,
                                             "--download-server", f"--install-dir={folder}"], folder, 600)
            if not ok:
                return result(False, "installer_failed", loader=loader, mc_version=mc_version, detail=detail)
            return result(True, "installed", loader=loader, mc_version=mc_version,
                          jar_name="quilt-server-launch.jar", loader_version=loader_version)

        if loader in ("Forge", "NeoForge"):
            if not loader_version:
                ok, loader_version = available(loader, mc_version)
                if not ok:
                    return result(False, loader_version, loader=loader, mc_version=mc_version)
            if loader == "Forge":
                full = f"{mc_version}-{loader_version}"
                name = f"forge-{full}-installer.jar"
                address = f"{FORGE_MAVEN}/{full}/{name}"
                args = ["--installServer"]
            else:
                name = f"neoforge-{loader_version}-installer.jar"
                address = f"{NEOFORGE_MAVEN}/{loader_version}/{name}"
                args = ["--install-server", "."]
            installer_path = os.path.join(folder, name)
            mc_http.download(address, installer_path, progress=progress)
            try:
                ok, detail = _run_installer([java, "-jar", name] + args, folder, 900)
            finally:
                for leftover in (installer_path, installer_path + ".log"):
                    if os.path.exists(leftover):
                        os.remove(leftover)
            if not ok:
                return result(False, "installer_failed", loader=loader, mc_version=mc_version, detail=detail)
            if not os.path.exists(os.path.join(folder, "run.sh")):
                return result(False, "installer_failed", loader=loader, mc_version=mc_version, detail="no run.sh")
            return result(True, "installed", loader=loader, mc_version=mc_version, jar_name="run.sh",
                          loader_version=loader_version)

        if loader == "Spigot":
            if not shutil.which("git"):
                return result(False, "git_required", loader=loader, mc_version=mc_version)
            with tempfile.TemporaryDirectory() as tmp:
                tools = os.path.join(tmp, "BuildTools.jar")
                mc_http.download(BUILDTOOLS, tools, progress=progress)
                ok, detail = _run_installer([java, "-jar", tools, "--rev", mc_version, "--compile", "SPIGOT",
                                             "--output-dir", folder], tmp, 3600)
            jar = f"spigot-{mc_version}.jar"
            if not ok or not os.path.exists(os.path.join(folder, jar)):
                return result(False, "installer_failed", loader=loader, mc_version=mc_version, detail=detail)
            return result(True, "installed", loader=loader, mc_version=mc_version, jar_name=jar, loader_version=None)

        if loader == "BungeeCord":
            jar = "BungeeCord.jar"
            mc_http.download(BUNGEECORD, os.path.join(folder, jar), progress=progress)
            return result(True, "installed", loader=loader, mc_version="proxy", jar_name=jar, loader_version=None)
    except mc_http.HttpError as e:
        return result(False, "download_failed", loader=loader, mc_version=mc_version, detail=e.detail)
    return result(False, "unknown_loader", loader=loader)


def java_for(loader, mc_version):
    """Major Java version to run `loader`: Minecraft's own requirement, 21 for
    proxies."""
    if canonical(loader) in PROXIES:
        return 21
    import mc_java
    return mc_java.required_java(mc_version)
