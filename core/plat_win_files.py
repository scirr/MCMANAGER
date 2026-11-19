import getpass
import logging
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


# SYSTEM (the daemon service) and Administrators (the mc command) must keep reaching
# files the other one wrote; by SID because names are localised.
_ALWAYS = ("*S-1-5-18", "*S-1-5-32-544")

# Accounts allowed to read what the SYSTEM daemon shares with the desktop users
# (api.token, the IPC files). Every member SID is granted on the file itself, so
# adding a user to the group needs no relogin, only a daemon restart.
SHARED_READ_GROUP = "MCManagerUsers"


def _grant(path, spec, also):
    user = current_user()
    # Under SYSTEM the name is the machine account (PC$), which icacls cannot map.
    principals = ([] if user.endswith("$") else [user]) + list(_ALWAYS) + list(also)
    cmd = ["icacls", path, "/inheritance:r"]
    for principal in principals:
        cmd += ["/grant:r", f"{principal}:{spec}"]
    rc, _out, _err = common.run(cmd)
    return rc == 0


def secure_file(path, also=()):
    return _grant(path, "F", also)


def shared_read_sids():
    # By SID, not name: names are localised and the group SID is machine-specific,
    # so it is resolved at runtime; icacls cannot map names under SYSTEM anyway.
    script = (
        f"New-LocalGroup -Name '{SHARED_READ_GROUP}' -ErrorAction SilentlyContinue;"
        f"$g = Get-LocalGroup -Name '{SHARED_READ_GROUP}' -ErrorAction SilentlyContinue;"
        f"if ($g) {{ $g.SID.Value;"
        f" Get-LocalGroupMember -Name '{SHARED_READ_GROUP}' -ErrorAction SilentlyContinue"
        " | ForEach-Object { $_.SID.Value } }"
    )
    rc, out, _err = common.run_powershell(script)
    if rc != 0:
        return []
    return [f"*{line.strip()}" for line in out.splitlines()
            if line.strip().startswith("S-1-")]


def ensure_shared_read_group():
    # False means "not elevated"; "already exists" is fine, the daemon resolves it.
    rc, _out, _err = common.run(["net", "localgroup", SHARED_READ_GROUP, "/add"])
    return rc == 0


def add_to_shared_read_group(user):
    # The machine account (PC$) of the service cannot be granted anything.
    if user.endswith("$"):
        return False
    rc, _out, _err = common.run(["net", "localgroup", SHARED_READ_GROUP, user, "/add"])
    return rc == 0


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
    elif mode & 0o004 and secure_file(tmp):
        sids = shared_read_sids()
        if sids:
            cmd = ["icacls", tmp]
            for sid in sids:
                cmd += ["/grant:r", f"{sid}:R"]
            if common.run(cmd)[0] != 0:
                logging.warning("%s stays private: icacls failed to grant %s",
                                os.path.basename(path), SHARED_READ_GROUP)
        else:
            logging.warning("%s stays private: no member in %s (install the daemon as administrator)",
                            os.path.basename(path), SHARED_READ_GROUP)
    atomic_replace(tmp, path)


def java_archive_kind():
    return "zip"
