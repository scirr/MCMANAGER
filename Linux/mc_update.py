"""
mc_update.py — Automatic update check and self-update (Linux).

Queries the latest GitHub release (public repo, no token needed), compares its
version to the running one, and can download+apply it. The check is cached and
throttled so it never slows down or breaks a command (silent on failure/offline).
"""
import os
import sys
import json
import time
import shutil
import tempfile
import zipfile
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(BASE_DIR)
from mc_lang import T, VERSION

REPO = "scirr/MCMANAGER"
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
ASSET_NAME = "MCManager-Linux.zip"
CACHE_FILE = os.path.join(BASE_DIR, "update_check.json")
CACHE_TTL = 6 * 3600          # re-check at most every 6 hours
NET_TIMEOUT = 4               # keep commands snappy


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


# ── cache ────────────────────────────────────────────────────────────────────

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


def _fetch_latest():
    req = urllib.request.Request(
        API_LATEST,
        headers={"User-Agent": "MCManager", "Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(req, timeout=NET_TIMEOUT) as r:
        data = json.loads(r.read().decode())
    tag = (data.get("tag_name") or "").lstrip("vV")
    assets = {a.get("name"): a.get("browser_download_url") for a in data.get("assets", [])}
    return tag, assets


def refresh_if_stale(force=False):
    """Refresh the cached latest-version info, at most once per CACHE_TTL.
    Fully silent: any network/parse error just keeps the previous cache."""
    cache = _read_cache()
    now = time.time()
    if not force and (now - cache.get("checked_at", 0) < CACHE_TTL):
        return
    try:
        tag, assets = _fetch_latest()
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


# ── self-update ──────────────────────────────────────────────────────────────

def _restart_daemon():
    try:
        import mc_config
        return mc_config.run_systemctl("restart").returncode == 0
    except Exception:
        return False


def perform_update():
    """Download and apply the latest release. Returns (ok, message)."""
    refresh_if_stale(force=True)
    cache = _read_cache()
    latest = cache.get("latest")
    if not latest:
        return False, T["update_check_failed"]
    if not is_newer(latest, VERSION):
        return False, T["update_current"].format(ver=VERSION)

    url = (cache.get("assets") or {}).get(ASSET_NAME)
    if not url:
        return False, T["update_no_asset"]

    print(f"\033[90m{T['update_downloading'].format(ver=latest)}\033[0m")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            zip_path = os.path.join(tmp, ASSET_NAME)
            req = urllib.request.Request(url, headers={"User-Agent": "MCManager"})
            with urllib.request.urlopen(req, timeout=60) as r, open(zip_path, "wb") as f:
                shutil.copyfileobj(r, f)
            with zipfile.ZipFile(zip_path) as zf:
                zf.extractall(tmp)
            src = os.path.join(tmp, "MCManager")
            if not os.path.isdir(src):
                return False, T["update_no_asset"]
            # Copy program files over the install; per-server data, servers.json,
            # language.txt, logs and the service unit live outside the package and
            # are untouched. Preserve the executable bit on shell scripts.
            for name in os.listdir(src):
                dest = os.path.join(BASE_DIR, name)
                shutil.copy2(os.path.join(src, name), dest)
                if name.endswith(".sh"):
                    os.chmod(dest, 0o755)
        pycache = os.path.join(BASE_DIR, "__pycache__")
        if os.path.isdir(pycache):
            shutil.rmtree(pycache, ignore_errors=True)
    except Exception as e:
        return False, T["update_failed"].format(e=e)

    restarted = _restart_daemon()
    msg = T["update_done"].format(ver=latest)
    if not restarted:
        msg += " " + T["update_daemon_manual"]
    return True, msg
