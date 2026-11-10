import getpass
import ntpath
import os
import time

import plat_win_common as common

APP_DIR_NAME = "MCManager"
REPLACE_ATTEMPTS = 10
REPLACE_DELAY = 0.1
_LOCKED_WINERRORS = (5, 32, 33)


def current_user():
    name = os.environ.get("USERNAME") or ""
    if not name:
        try:
            name = getpass.getuser()
        except Exception:
            return "unknown"
    domain = os.environ.get("USERDOMAIN") or ""
    return f"{domain}\\{name}" if domain else name


def is_elevated():
    if not common.is_windows():
        return False
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _grant(path, spec, also):
    cmd = ["icacls", path, "/inheritance:r", "/grant:r", f"{current_user()}:{spec}"]
    for principal in also:
        cmd += ["/grant:r", f"{principal}:{spec}"]
    rc, _out, _err = common.run(cmd)
    return rc == 0


def secure_file(path, also=()):
    return _grant(path, "F", also)


def secure_dir(path, also=(), owner_of=None):
    return _grant(path, "(OI)(CI)F", also)


def file_is_private(path):
    return None, ""


def _base(var, fallback_parts):
    root = os.environ.get(var)
    if not root:
        root = ntpath.join(os.path.expanduser("~"), *fallback_parts)
    return root


def data_dir():
    shared = (os.environ.get("MCMANAGER_DATA_DIR") or "").strip()
    if shared:
        return shared
    return ntpath.join(_base("APPDATA", ("AppData", "Roaming")), APP_DIR_NAME)


def cache_dir():
    return ntpath.join(_base("LOCALAPPDATA", ("AppData", "Local")), APP_DIR_NAME, "cache")


def open_folder(path):
    starter = getattr(os, "startfile", None)
    if starter is not None:
        try:
            starter(path)
            return True
        except OSError:
            return False
    common.run(["explorer", path])
    return True


def _is_locked(error):
    if isinstance(error, PermissionError):
        return True
    return getattr(error, "winerror", None) in _LOCKED_WINERRORS


def atomic_replace(src, dst, attempts=REPLACE_ATTEMPTS, delay=REPLACE_DELAY):
    last = None
    for attempt in range(max(1, attempts)):
        try:
            os.replace(src, dst)
            return
        except OSError as e:
            if not _is_locked(e):
                raise
            last = e
            if attempt + 1 < attempts:
                time.sleep(delay)
    raise last


def write_private_file(path, text, mode=0o600):
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    if mode == 0o600:
        secure_file(tmp)
    atomic_replace(tmp, path)


def java_archive_kind():
    return "zip"
