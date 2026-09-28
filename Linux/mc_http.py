"""
mc_http.py — HTTPS access to the download APIs (Mojang, PaperMC, Purpur,
Fabric, Quilt, Forge, NeoForge, Modrinth, CurseForge, Hangar, FTB, Adoptium).

https only, an identifying User-Agent (Modrinth requires one), hashes checked
on every download that publishes one. Nothing here prints: callers turn
HttpError into their own messages.
"""
import hashlib
import json
import os
import shutil
import tempfile
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = "MCManager (github.com/scirr/MCMANAGER)"
TIMEOUT = 30


class HttpError(Exception):
    def __init__(self, url, detail, status=None):
        super().__init__(f"{url}: {detail}")
        self.url = url
        self.detail = detail
        self.status = status


def _request(url, headers=None):
    if not str(url).startswith("https://"):
        raise HttpError(url, "refusing non-https URL")
    return urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})


def url(base, **params):
    """base + query string; list values are JSON-encoded (Modrinth style)."""
    query = {k: (json.dumps(v) if isinstance(v, (list, tuple)) else v)
             for k, v in params.items() if v is not None}
    return base + ("?" + urllib.parse.urlencode(query) if query else "")


def get_bytes(address, headers=None, timeout=TIMEOUT):
    try:
        with urllib.request.urlopen(_request(address, headers), timeout=timeout) as r:  # nosec B310 - https checked
            return r.read()
    except urllib.error.HTTPError as e:
        raise HttpError(address, f"HTTP {e.code}", e.code) from e
    except (urllib.error.URLError, OSError) as e:
        raise HttpError(address, str(getattr(e, "reason", e))) from e


def get_json(address, headers=None, timeout=TIMEOUT):
    raw = get_bytes(address, headers, timeout)
    try:
        return json.loads(raw.decode("utf-8"))
    except ValueError as e:
        raise HttpError(address, "invalid JSON") from e


def get_text(address, headers=None, timeout=TIMEOUT):
    return get_bytes(address, headers, timeout).decode("utf-8", "replace")


def file_hash(path, algo):
    digest = hashlib.new(algo)
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(address, dest, hashes=None, headers=None, progress=None, timeout=120):
    """Download to `dest` atomically. `hashes` = {"sha512": ..., "sha1": ...};
    the strongest available is checked and a mismatch raises HttpError
    (nothing is left at `dest`). progress(done, total) is optional."""
    os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".dl-", dir=os.path.dirname(os.path.abspath(dest)))
    try:
        with os.fdopen(fd, "wb") as out:
            try:
                with urllib.request.urlopen(_request(address, headers), timeout=timeout) as r:  # nosec B310 - https checked
                    total = int(r.headers.get("Content-Length") or 0)
                    done = 0
                    while True:
                        chunk = r.read(1 << 16)
                        if not chunk:
                            break
                        out.write(chunk)
                        done += len(chunk)
                        if progress:
                            progress(done, total)
            except urllib.error.HTTPError as e:
                raise HttpError(address, f"HTTP {e.code}", e.code) from e
            except (urllib.error.URLError, OSError) as e:
                raise HttpError(address, str(getattr(e, "reason", e))) from e
        for algo in ("sha512", "sha256", "sha1", "md5"):
            expected = (hashes or {}).get(algo)
            if expected:
                if file_hash(tmp, algo) != str(expected).lower():
                    raise HttpError(address, f"{algo} mismatch")
                break
        shutil.move(tmp, dest)
        tmp = None
    finally:
        if tmp and os.path.exists(tmp):
            os.remove(tmp)
    return dest
