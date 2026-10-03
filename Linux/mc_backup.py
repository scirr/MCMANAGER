"""
mc_backup.py — Backup archives: listing, retention, restoration, and
destinations beyond the local disk (SFTP, S3, restic).

Pure file and transport operations; the checks around them (server stopped,
safety backup) live in mc_api.
"""
import datetime
import os
import re
import shutil
import subprocess
import tempfile
import zipfile

import mc_s3

SUFFIXES = (".zip", ".zip.enc")
STAMP = re.compile(r"(\d{4}-\d{2}-\d{2})_(\d{2}-\d{2}-\d{2})")
NAME = re.compile(r"^backup_(.+?)_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}$")
REMOTE_TYPES = ("sftp", "s3", "restic")
STAGING = "_mcmanager_restore_tmp"
OLD_SUFFIX = ".mcmanager-old"
SECRET_KEYS = ("secret_key", "password")
CMD_TIMEOUT = 3600


class BackupError(Exception):
    def __init__(self, code, detail=""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


# ── archives ────────────────────────────────────────────────────────────────

def _archive_id(filename):
    for suffix in SUFFIXES:
        if filename.endswith(suffix):
            return filename[:-len(suffix)]
    return None


def archive_time(path):
    m = STAMP.search(os.path.basename(path))
    if m:
        try:
            return datetime.datetime.strptime(f"{m.group(1)}_{m.group(2)}", "%Y-%m-%d_%H-%M-%S")
        except ValueError:
            pass
    return datetime.datetime.fromtimestamp(os.path.getmtime(path))


def list_backups(dossier_backup):
    """Archives under the backup folder, newest first."""
    found = []
    if not dossier_backup or not os.path.isdir(dossier_backup):
        return found
    for root, _dirs, files in os.walk(dossier_backup):
        for fname in files:
            ident = _archive_id(fname)
            if ident is None:
                continue
            path = os.path.join(root, fname)
            try:
                size = os.path.getsize(path)
                when = archive_time(path)
            except OSError:
                continue
            m = NAME.match(ident)
            found.append({"id": ident, "file": fname, "path": path, "size": size,
                          "type": m.group(1) if m else "", "created": when.isoformat(timespec="seconds"),
                          "encrypted": fname.endswith(".enc")})
    found.sort(key=lambda b: (b["created"], b["file"]), reverse=True)
    return found


def find_backup(dossier_backup, ref):
    """An archive by id, file name, 'latest', or an existing path."""
    backups = list_backups(dossier_backup)
    if ref == "latest":
        return backups[0] if backups else None
    candidate = os.path.abspath(os.path.expanduser(ref))
    if os.path.isfile(candidate) and _archive_id(os.path.basename(candidate)):
        for b in backups:
            if os.path.samefile(b["path"], candidate):
                return b
        return {"id": _archive_id(os.path.basename(candidate)), "file": os.path.basename(candidate),
                "path": candidate, "size": os.path.getsize(candidate), "type": "",
                "created": archive_time(candidate).isoformat(timespec="seconds"),
                "encrypted": candidate.endswith(".enc")}
    for b in backups:
        if ref in (b["id"], b["file"]):
            return b
    return None


def apply_retention(dossier_backup, keep=0, days=0, today=None):
    """Delete archives beyond the `keep` newest and older than `days` days
    (0 disables each rule). The newest archive is never deleted. Empty dated
    day folders past the cutoff are removed too. Returns {"files", "folders"}."""
    removed = {"files": 0, "folders": 0}
    if not dossier_backup or not os.path.isdir(dossier_backup):
        return removed
    keep, days = max(0, int(keep or 0)), max(0, int(days or 0))
    backups = list_backups(dossier_backup)
    cutoff = ((today or datetime.date.today()) - datetime.timedelta(days=days)) if days else None
    for index, b in enumerate(backups):
        if index == 0:
            continue
        too_many = keep and index >= keep
        too_old = cutoff and datetime.datetime.fromisoformat(b["created"]).date() < cutoff
        if too_many or too_old:
            try:
                os.remove(b["path"])
                removed["files"] += 1
            except OSError:
                pass
    if cutoff:
        for entry in os.listdir(dossier_backup):
            full = os.path.join(dossier_backup, entry)
            try:
                day = datetime.datetime.strptime(entry, "%Y-%m-%d").date()
            except ValueError:
                continue
            if os.path.isdir(full) and day < cutoff and not _holds_newest(full, backups):
                if not any(list_backups(full)):
                    shutil.rmtree(full, ignore_errors=True)
                    removed["folders"] += 1
    return removed


def _holds_newest(folder, backups):
    return bool(backups) and os.path.dirname(backups[0]["path"]) == os.path.abspath(folder)


# ── restoration ─────────────────────────────────────────────────────────────

def _run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=CMD_TIMEOUT, **kw)


def which(name):
    return shutil.which(name)


def decrypt(src, dst, key_file):
    if not which("openssl"):
        raise BackupError("openssl_missing")
    if not key_file or not os.path.isfile(key_file):
        raise BackupError("encrypt_key_missing", key_file or "")
    res = _run(["openssl", "enc", "-d", "-aes-256-cbc", "-pbkdf2", "-pass", f"file:{key_file}",
                "-in", src, "-out", dst])
    if res.returncode != 0:
        raise BackupError("decrypt_failed", res.stderr.strip()[:200])


def encrypt(src, dst, key_file):
    res = _run(["openssl", "enc", "-aes-256-cbc", "-pbkdf2", "-salt", "-pass", f"file:{key_file}",
                "-in", src, "-out", dst])
    if res.returncode != 0:
        raise BackupError("encrypt_failed", res.stderr.strip()[:200])


def _safe_extract(zf, dest):
    root = os.path.realpath(dest)
    for info in zf.infolist():
        target = os.path.realpath(os.path.join(dest, info.filename))
        if os.path.isabs(info.filename) or not (target == root or target.startswith(root + os.sep)):
            raise BackupError("unsafe_archive", info.filename)
    zf.extractall(dest)


def inspect_archive(path):
    """Top-level folders of an archive; BackupError if it is unreadable or
    holds no world (a level.dat)."""
    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
    except (zipfile.BadZipFile, OSError) as e:
        raise BackupError("bad_archive", str(e))
    tops = sorted({n.split("/", 1)[0] for n in names if "/" in n})
    if not any(n.count("/") == 1 and n.endswith("/level.dat") for n in names):
        raise BackupError("no_world_in_archive")
    return tops


def restore_archive(archive, dossier, extra_names=(), key_file=None):
    """Replace the world folders of `dossier` with the archive's, atomically:
    extract aside, move the current folders out of the way, move the new ones
    in, and roll everything back if a step fails. Returns the restored names."""
    work = tempfile.mkdtemp(prefix=STAGING, dir=dossier)
    try:
        source = archive
        if archive.endswith(".enc"):
            source = os.path.join(work, "decrypted.zip")
            decrypt(archive, source, key_file)
        tops = inspect_archive(source)
        stage = os.path.join(work, "extract")
        os.makedirs(stage)
        with zipfile.ZipFile(source) as zf:
            _safe_extract(zf, stage)
        replaced = []
        placed = []
        try:
            for name in sorted(set(tops) | {n for n in extra_names if n}):
                current = os.path.join(dossier, name)
                if os.path.lexists(current):
                    old = current + OLD_SUFFIX
                    if os.path.lexists(old):
                        shutil.rmtree(old, ignore_errors=True)
                    os.rename(current, old)
                    replaced.append((current, old))
            for name in tops:
                os.rename(os.path.join(stage, name), os.path.join(dossier, name))
                placed.append(os.path.join(dossier, name))
        except OSError as e:
            for path in placed:
                shutil.rmtree(path, ignore_errors=True)
            for current, old in replaced:
                if os.path.lexists(old) and not os.path.lexists(current):
                    os.rename(old, current)
            raise BackupError("swap_failed", str(e))
        for _current, old in replaced:
            shutil.rmtree(old, ignore_errors=True)
        return tops
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ── destinations ────────────────────────────────────────────────────────────

def parse_remote_url(url):
    """'sftp://u@h:22/p' | 's3://bucket/prefix' | 'restic:<repo>' -> (type, fields)."""
    if url.startswith("restic:"):
        repo = url[len("restic:"):]
        if not repo:
            raise BackupError("bad_remote_url", url)
        return "restic", {"repo": repo}
    from urllib.parse import urlparse
    parts = urlparse(url)
    if parts.scheme == "sftp":
        if not parts.hostname or not parts.path.strip("/"):
            raise BackupError("bad_remote_url", url)
        return "sftp", {"host": parts.hostname, "port": parts.port or 22, "user": parts.username or "",
                        "path": parts.path}
    if parts.scheme == "s3":
        if not parts.netloc:
            raise BackupError("bad_remote_url", url)
        return "s3", {"bucket": parts.netloc, "prefix": parts.path.strip("/")}
    raise BackupError("bad_remote_url", url)


def describe(remote):
    t = remote.get("type")
    if t == "sftp":
        user = f"{remote['user']}@" if remote.get("user") else ""
        return f"sftp://{user}{remote['host']}:{remote.get('port', 22)}{remote['path']}"
    if t == "s3":
        return f"s3://{remote['bucket']}/{remote.get('prefix', '')}".rstrip("/") + \
            (f" ({remote['endpoint']})" if remote.get("endpoint") else "")
    return f"restic:{remote.get('repo', '')}"


def masked(remote):
    return {k: ("***" if k in SECRET_KEYS and v else v) for k, v in remote.items()}


def _s3_client(remote):
    return mc_s3.S3Client(remote["bucket"], remote["access_key"], remote["secret_key"],
                          remote.get("region") or "us-east-1", remote.get("endpoint"),
                          remote.get("path_style"))


def _s3_key(remote, server, filename):
    return "/".join(p for p in (remote.get("prefix", ""), server, filename) if p)


def _sftp_target(remote):
    return f"{remote['user']}@{remote['host']}" if remote.get("user") else remote["host"]


def _sftp_cmd(remote):
    cmd = ["sftp", "-b", "-", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new",
           "-P", str(remote.get("port", 22))]
    if remote.get("key"):
        cmd += ["-i", remote["key"]]
    return cmd + [_sftp_target(remote)]


def _q(path):
    return '"' + path.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _sftp_batch(remote, lines):
    res = _run(_sftp_cmd(remote), input="\n".join(lines) + "\n")
    if res.returncode != 0:
        raise BackupError("sftp_failed", (res.stderr or res.stdout).strip()[-300:])


def _restic_env(remote):
    env = dict(os.environ, RESTIC_REPOSITORY=remote["repo"])
    if remote.get("password_file"):
        env["RESTIC_PASSWORD_FILE"] = remote["password_file"]
    return env


def _restic(remote, *args):
    res = _run(["restic", *args], env=_restic_env(remote))
    if res.returncode != 0:
        raise BackupError("restic_failed", (res.stderr or res.stdout).strip()[-300:])
    return res.stdout


def check_remote(remote):
    """Verify a destination is reachable and writable in principle. Raises
    BackupError."""
    t = remote["type"]
    if t == "sftp":
        if not which("sftp"):
            raise BackupError("tool_missing", "sftp")
        _sftp_batch(remote, [f"ls {_q(remote['path'])}"])
    elif t == "s3":
        try:
            _s3_client(remote).list(remote.get("prefix", ""), max_keys=1)
        except mc_s3.S3Error as e:
            raise BackupError("s3_failed", str(e))
    elif t == "restic":
        if not which("restic"):
            raise BackupError("tool_missing", "restic")
        _restic(remote, "cat", "config")
    else:
        raise BackupError("bad_type", str(t))


def push(remote, archive, server, key_file=None, warn=None, backup_dir=None):
    """Send one archive to a destination. `key_file` encrypts it first
    (restic encrypts natively, so it is ignored there); `warn(code)` is told
    when encryption was asked for but is not possible."""
    t = remote["type"]
    if t == "restic":
        if not which("restic"):
            raise BackupError("tool_missing", "restic")
        try:
            _restic(remote, "cat", "config")
        except BackupError:
            _restic(remote, "init")
        _restic(remote, "backup", "--tag", "mcmanager", "--host", server or "mcmanager",
                backup_dir or os.path.dirname(archive))
        return os.path.basename(archive)
    tmp_dir = None
    source, name = archive, os.path.basename(archive)
    try:
        if key_file and not name.endswith(".enc"):
            if not which("openssl"):
                if warn:
                    warn("encrypt_unavailable")
            else:
                if not os.path.isfile(key_file):
                    raise BackupError("encrypt_key_missing", key_file)
                tmp_dir = tempfile.mkdtemp(prefix="mcm-enc-")
                source = os.path.join(tmp_dir, name + ".enc")
                encrypt(archive, source, key_file)
                name += ".enc"
        if t == "sftp":
            if not which("sftp"):
                raise BackupError("tool_missing", "sftp")
            _sftp_batch(remote, [f"put {_q(source)} {_q(remote['path'].rstrip('/') + '/' + name)}"])
        elif t == "s3":
            try:
                _s3_client(remote).put_file(_s3_key(remote, server, name), source)
            except mc_s3.S3Error as e:
                raise BackupError("s3_failed", str(e))
        else:
            raise BackupError("bad_type", str(t))
        return name
    finally:
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)


def push_all(config, archive, warn=None):
    """Send `archive` to every configured destination. Returns
    [(name, ok, detail)]; one failing destination never blocks the others."""
    out = []
    server = config.get("nom_serveur", "") or "server"
    server = re.sub(r"[^A-Za-z0-9_.-]+", "_", server)
    for remote in config.get("backup_remotes", []):
        try:
            sent = push(remote, archive, server, config.get("backup_encrypt_key_file") or None, warn,
                         config.get("dossier_backup"))
            out.append((remote.get("name"), True, sent))
        except BackupError as e:
            out.append((remote.get("name"), False, str(e)))
        except (OSError, subprocess.SubprocessError) as e:
            out.append((remote.get("name"), False, str(e)))
    return out
