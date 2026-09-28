"""
mc_update.py — Update check and signed self-update (Windows).

Every release publishes SHA256SUMS (hashes of both packages) and
SHA256SUMS.sig, an Ed25519 signature of that file made in CI with a key that
never leaves GitHub's secrets. An update is installed only if the signature
matches the public key below AND the package matches its listed hash;
anything else is refused and nothing is touched.

The installation being replaced is kept in previous/, so 'mc update
--rollback' can put it back.
"""
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import time
import urllib.request
import zipfile

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(BASE_DIR)
import mc_sig
from mc_lang import VERSION

REPO = "scirr/MCMANAGER"
API = f"https://api.github.com/repos/{REPO}/releases"
ASSET_NAME = "MCManager.zip"
SERVICE_NAME = "MCManagerDaemon"
SUMS_NAME = "SHA256SUMS"
SIG_NAME = "SHA256SUMS.sig"
RELEASE_PUBLIC_KEY = bytes.fromhex("3b6de7bf90729201ba040a923be3e278c0fb1e8ece57daab3bd40900d7a44099")

CACHE_FILE = os.path.join(BASE_DIR, "update_check.json")
PREVIOUS_DIR = os.path.join(BASE_DIR, "previous")
CACHE_TTL = 6 * 3600          # re-check at most every 6 hours
NET_TIMEOUT = 4               # keep commands snappy

# Program files: what an update replaces and a rollback restores. Data
# (servers.json, language.txt, logs/, nssm/...) is never touched.
PROGRAM_PATTERN = re.compile(r".+\.(py|sh|bat)$|^webhook_templates\.json$|^requirements\.txt$")


def result(ok, code, **data):
    return {"ok": ok, "code": code, **data}


# ── version comparison (pure, testable) ──────────────────────────────────────

def parse_version(v):
    """'v2.3.0' / '2.3.0' -> (2, 3, 0). Non-numeric parts degrade to 0."""
    parts = []
    for chunk in str(v).strip().lstrip("vV").split("."):
        num = ""
        for ch in chunk:
            if ch.isdigit():
                num += ch
            else:
                break
        parts.append(int(num) if num else 0)
    return tuple(parts) or (0,)


def is_newer(remote, local):
    return parse_version(remote) > parse_version(local)


# ── release metadata ─────────────────────────────────────────────────────────

def _require_https(url):
    if not str(url).startswith("https://"):
        raise ValueError(f"refusing non-https URL: {url}")


def _get_json(url, timeout=NET_TIMEOUT):
    _require_https(url)
    req = urllib.request.Request(url, headers={"User-Agent": f"MCManager/{VERSION} (https://github.com/scirr/MCMANAGER)",
                                               "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # nosec B310 - https checked
        return json.loads(r.read().decode())


def _fetch_release(version=None, timeout=NET_TIMEOUT):
    """(version, {asset name: url}) of the latest release, or of `version`."""
    url = f"{API}/latest" if version is None else f"{API}/tags/v{str(version).lstrip('vV')}"
    data = _get_json(url, timeout)
    tag = (data.get("tag_name") or "").lstrip("vV")
    assets = {a.get("name"): a.get("browser_download_url") for a in data.get("assets", [])}
    return tag, assets


# ── cache (background notice) ────────────────────────────────────────────────

def _read_cache():
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _write_cache(data):
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception:
        pass


def refresh_if_stale(force=False):
    """Refresh the cached latest-version info, at most once per CACHE_TTL.
    Fully silent: any network/parse error just keeps the previous cache."""
    cache = _read_cache()
    now = time.time()
    if not force and (now - cache.get("checked_at", 0) < CACHE_TTL):
        return
    try:
        tag, assets = _fetch_release()
        _write_cache({"checked_at": now, "latest": tag, "assets": assets})
    except Exception:
        cache["checked_at"] = now  # avoid hammering on repeated failures
        _write_cache(cache)


def get_cached_notice():
    """Return the newer version string if the cache says one is available, else None."""
    latest = _read_cache().get("latest")
    if latest and is_newer(latest, VERSION):
        return latest
    return None


def check():
    """Current vs latest release, fetched now."""
    try:
        tag, assets = _fetch_release(timeout=10)
    except Exception as e:
        return result(False, "check_failed", current=VERSION, detail=str(e))
    _write_cache({"checked_at": time.time(), "latest": tag, "assets": assets})
    return result(True, "checked", current=VERSION, latest=tag,
                  update_available=is_newer(tag, VERSION),
                  signed=SUMS_NAME in assets and SIG_NAME in assets,
                  rollback_available=previous_version() is not None)


# ── verification (pure, testable) ────────────────────────────────────────────

def parse_sums(text):
    """{file name: sha256 hex} from sha256sum-style lines."""
    sums = {}
    for line in text.splitlines():
        m = re.match(r"^([0-9a-fA-F]{64})\s+\*?(\S.*)$", line.strip())
        if m:
            sums[m.group(2).strip()] = m.group(1).lower()
    return sums


def verify_package(package_path, sums_bytes, signature, asset_name=ASSET_NAME, public_key=None):
    """(ok, code): signature of SHA256SUMS first, then the package hash."""
    if not mc_sig.verify(public_key or RELEASE_PUBLIC_KEY, sums_bytes, signature):
        return False, "bad_signature"
    expected = parse_sums(sums_bytes.decode("utf-8", "replace")).get(asset_name)
    if not expected:
        return False, "not_listed"
    digest = hashlib.sha256()
    with open(package_path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    if digest.hexdigest() != expected:
        return False, "bad_checksum"
    return True, "verified"


def decode_signature(raw):
    """The .sig file holds the 64-byte signature, raw or hex-encoded."""
    if len(raw) == 64:
        return raw          # binary: never strip, a byte may look like whitespace
    text = raw.strip()
    if len(text) == 128:
        try:
            return bytes.fromhex(text.decode("ascii"))
        except ValueError:
            pass
    return raw


# ── install / rollback ───────────────────────────────────────────────────────

def _program_files(folder):
    try:
        return [n for n in os.listdir(folder)
                if PROGRAM_PATTERN.match(n) and os.path.isfile(os.path.join(folder, n))]
    except FileNotFoundError:
        return []


def _version_in(folder):
    try:
        with open(os.path.join(folder, "mc_lang.py"), encoding="utf-8") as f:
            m = re.search(r'^VERSION\s*=\s*"([^"]+)"', f.read(), re.M)
        return m.group(1) if m else None
    except Exception:
        return None


def previous_version():
    return _version_in(PREVIOUS_DIR) if os.path.isdir(PREVIOUS_DIR) else None


def _copy_program(src, dest):
    os.makedirs(dest, exist_ok=True)
    for name in _program_files(src):
        target = os.path.join(dest, name)
        shutil.copy2(os.path.join(src, name), target)
        if name.endswith(".sh"):
            os.chmod(target, 0o755)  # nosec B103 - shell scripts must be executable


def _backup_current():
    if os.path.isdir(PREVIOUS_DIR):
        shutil.rmtree(PREVIOUS_DIR)
    _copy_program(BASE_DIR, PREVIOUS_DIR)


def _clear_pycache():
    shutil.rmtree(os.path.join(BASE_DIR, "__pycache__"), ignore_errors=True)


def _restart_daemon():
    try:
        import subprocess
        subprocess.run(["sc", "stop", SERVICE_NAME], capture_output=True,
                       creationflags=subprocess.CREATE_NO_WINDOW)
        result = subprocess.run(["sc", "start", SERVICE_NAME], capture_output=True,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        return result.returncode == 0
    except Exception:
        return False


def _download(url, dest):
    _require_https(url)
    req = urllib.request.Request(url, headers={"User-Agent": f"MCManager/{VERSION} (https://github.com/scirr/MCMANAGER)"})
    with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as f:  # nosec B310 - https checked
        shutil.copyfileobj(r, f)


def perform_update(target=None, progress=None):
    """Install the latest release, or `target` (any version, for a downgrade).
    Returns a result dict; installs nothing unless the package is verified."""
    try:
        tag, assets = _fetch_release(target, timeout=10)
    except Exception as e:
        code = "version_not_found" if target and "404" in str(e) else "check_failed"
        return result(False, code, current=VERSION, target=target, detail=str(e))
    if not tag:
        return result(False, "check_failed", current=VERSION, detail="no tag")
    if parse_version(tag) == parse_version(VERSION) or (target is None and not is_newer(tag, VERSION)):
        return result(True, "up_to_date", current=VERSION, latest=tag)
    if ASSET_NAME not in assets:
        return result(False, "no_asset", version=tag)
    if SUMS_NAME not in assets or SIG_NAME not in assets:
        return result(False, "unsigned", version=tag)

    if progress:
        progress(tag)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            paths = {}
            for name in (ASSET_NAME, SUMS_NAME, SIG_NAME):
                paths[name] = os.path.join(tmp, name)
                _download(assets[name], paths[name])
            with open(paths[SUMS_NAME], "rb") as f:
                sums = f.read()
            with open(paths[SIG_NAME], "rb") as f:
                sig = decode_signature(f.read())
            ok, code = verify_package(paths[ASSET_NAME], sums, sig)
            if not ok:
                return result(False, code, version=tag)

            with zipfile.ZipFile(paths[ASSET_NAME]) as zf:
                for member in zf.namelist():
                    if member.startswith("/") or ".." in member.replace("\\", "/").split("/"):
                        return result(False, "bad_package", version=tag)
                zf.extractall(tmp)
            src = os.path.join(tmp, "MCManager")
            if not os.path.isdir(src) or not _version_in(src):
                return result(False, "bad_package", version=tag)

            _backup_current()
            _copy_program(src, BASE_DIR)
        _clear_pycache()
    except Exception as e:
        return result(False, "update_failed", version=tag, detail=str(e))

    restarted = _restart_daemon()
    return result(True, "updated", previous=VERSION, version=tag, restarted=restarted)


def rollback():
    """Swap the current installation with the one kept in previous/."""
    prev = previous_version()
    if not prev:
        return result(False, "no_previous", current=VERSION)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            current = os.path.join(tmp, "current")
            _copy_program(BASE_DIR, current)
            _copy_program(PREVIOUS_DIR, BASE_DIR)
            shutil.rmtree(PREVIOUS_DIR)
            _copy_program(current, PREVIOUS_DIR)
        _clear_pycache()
    except Exception as e:
        return result(False, "update_failed", detail=str(e))
    restarted = _restart_daemon()
    return result(True, "rolled_back", previous=VERSION, version=prev, restarted=restarted)
