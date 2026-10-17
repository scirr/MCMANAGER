"""
mc_java.py — Java runtimes managed by MC Manager.

Each server gets the Java version its Minecraft version requires (read from
Mojang's own version metadata), as an Eclipse Temurin runtime downloaded from
the Adoptium API into <app>/java/<major>/ and verified by its SHA-256. The
system Java is no longer needed; 'mc java use system' keeps it for a server
that must use it.
"""
import os
import platform
import re
import shutil
import sys
import tarfile
import tempfile

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(BASE_DIR)

import mc_http

JAVA_DIR = os.path.join(BASE_DIR, "java")
MANIFEST = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
ADOPTIUM = "https://api.adoptium.net/v3/assets/latest/{major}/hotspot"


def result(ok, code, **data):
    return {"ok": ok, "code": code, **data}


# ── which Java for which Minecraft ───────────────────────────────────────────

def _version_key(v):
    return tuple(int(p) if p.isdigit() else 0 for p in re.split(r"[.\-]", str(v)))


def fallback_java(mc_version):
    """Offline rule of thumb, used only when Mojang's metadata is unreachable."""
    key = _version_key(mc_version)
    if key and key[0] >= 26:          # year-based versions (26.1+)
        return 25
    if key >= (1, 20, 5):
        return 21
    if key >= (1, 18):
        return 17
    if key >= (1, 17):
        return 16
    return 8


def required_java(mc_version, manifest=None):
    """Major Java version Minecraft `mc_version` requires."""
    try:
        manifest = manifest or mc_http.get_json(MANIFEST)
        entry = next(v for v in manifest["versions"] if v["id"] == mc_version)
        meta = mc_http.get_json(entry["url"])
        major = int(meta["javaVersion"]["majorVersion"])
        return 17 if major == 16 else major     # no Temurin 16 builds are kept
    except Exception:
        major = fallback_java(mc_version)
        return 17 if major == 16 else major


# ── installed runtimes ───────────────────────────────────────────────────────

def java_bin(major):
    return os.path.join(JAVA_DIR, str(major), "bin", "java")


def installed():
    """{major: path to the java executable}."""
    found = {}
    try:
        entries = os.listdir(JAVA_DIR)
    except FileNotFoundError:
        return found
    for entry in entries:
        path = java_bin(entry)
        if entry.isdigit() and os.access(path, os.X_OK):
            found[int(entry)] = path
    return found


def _arch():
    machine = platform.machine().lower()
    return {"x86_64": "x64", "amd64": "x64", "aarch64": "aarch64", "arm64": "aarch64",
            "armv7l": "arm", "ppc64le": "ppc64le", "s390x": "s390x"}.get(machine, machine)


def _safe_members(tar, root):
    root = os.path.realpath(root)
    for member in tar.getmembers():
        target = os.path.realpath(os.path.join(root, member.name))
        if not (target == root or target.startswith(root + os.sep)):
            raise ValueError(f"unsafe path in archive: {member.name}")
        if member.issym() or member.islnk():
            link = os.path.realpath(os.path.join(os.path.dirname(target), member.linkname))
            if not link.startswith(root + os.sep):
                raise ValueError(f"unsafe link in archive: {member.name}")
        yield member


def install(major, progress=None):
    """Download and install Temurin `major` (JRE, or JDK when no JRE exists)."""
    major = int(major)
    if major in installed():
        return result(True, "java_present", major=major, path=java_bin(major))
    asset = None
    for image in ("jre", "jdk"):
        try:
            assets = mc_http.get_json(mc_http.url(ADOPTIUM.format(major=major), architecture=_arch(),
                                                  image_type=image, os="linux", vendor="eclipse"))
        except mc_http.HttpError as e:
            if e.status == 404:
                continue
            return result(False, "java_download_failed", major=major, detail=e.detail)
        if assets:
            asset = assets[0]
            break
    if not asset:
        return result(False, "java_unavailable", major=major, arch=_arch())
    package = asset["binary"]["package"]
    os.makedirs(JAVA_DIR, exist_ok=True)
    target = os.path.join(JAVA_DIR, str(major))
    with tempfile.TemporaryDirectory(dir=JAVA_DIR) as tmp:
        archive = os.path.join(tmp, package["name"])
        try:
            mc_http.download(package["link"], archive, {"sha256": package.get("checksum")}, progress=progress)
        except mc_http.HttpError as e:
            return result(False, "java_download_failed", major=major, detail=e.detail)
        extract = os.path.join(tmp, "x")
        os.makedirs(extract)
        try:
            with tarfile.open(archive) as tar:
                tar.extractall(extract, members=list(_safe_members(tar, extract)))  # nosec B202 - members checked
        except (tarfile.TarError, ValueError) as e:
            return result(False, "java_download_failed", major=major, detail=str(e))
        tops = os.listdir(extract)
        home = os.path.join(extract, tops[0]) if len(tops) == 1 else extract
        if not os.access(os.path.join(home, "bin", "java"), os.X_OK):
            return result(False, "java_download_failed", major=major, detail="no bin/java in archive")
        if os.path.isdir(target):
            shutil.rmtree(target)
        shutil.move(home, target)
    return result(True, "java_installed", major=major, path=java_bin(major),
                  version=asset.get("version", {}).get("semver", ""))


def remove(major):
    target = os.path.join(JAVA_DIR, str(int(major)))
    if not os.path.isdir(target):
        return result(False, "java_not_installed", major=int(major))
    shutil.rmtree(target)
    return result(True, "java_removed", major=int(major))


# ── per-server choice ────────────────────────────────────────────────────────

def ensure_for_server(config, mc_version=None, progress=None):
    """Make sure the server has the Java its Minecraft version needs, installing
    it when missing, and record it in config (java_major, java_path). A server
    set to 'system' keeps the system Java. Does not save the config."""
    if config.get("java") == "system":
        return result(True, "java_system")
    mc_version = mc_version or config.get("mc_version")
    if not mc_version:
        return result(False, "java_unknown_version")
    major = required_java(mc_version)
    res = install(major, progress)
    if not res["ok"]:
        return res
    config["java_major"] = major
    config["java_path"] = java_bin(major)
    return dict(res, required=major)


def use(config, choice):
    """choice: 'auto' (Minecraft's requirement), 'system', or a major version."""
    choice = str(choice).strip().lower()
    if choice == "system":
        config["java"] = "system"
        config.pop("java_path", None)
        config.pop("java_major", None)
        return result(True, "java_use_system")
    config.pop("java", None)
    if choice == "auto":
        return ensure_for_server(config)
    if not choice.isdigit():
        return result(False, "java_bad_choice", choice=choice)
    res = install(int(choice))
    if not res["ok"]:
        return res
    config["java_major"] = int(choice)
    config["java_path"] = java_bin(int(choice))
    return result(True, "java_use_major", major=int(choice))
