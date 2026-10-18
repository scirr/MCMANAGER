import hashlib
import json
import ntpath
import os
import re
import shutil
import time

import plat_win_common as common
import plat_win_files as files

SERVICE_NAME = "MCManagerDaemon"
STOP_TIMEOUT = 30.0
NSSM_URL = "https://nssm.cc/release/nssm-2.24.zip"
NSSM_SHA256 = "727d1e42275c605e0f04aba98095c38a8e1e46def453cdffce42869428aa6743"

_PS_STATE = (
    f"$s = Get-Service -Name '{SERVICE_NAME}' -ErrorAction SilentlyContinue; "
    "if ($null -eq $s) { '' } else { ConvertTo-Json -Compress -InputObject "
    "@($s | Select-Object Name, @{n='Status';e={[string]$_.Status}}) }"
)

_STATE_BY_NAME = {
    "running": "running",
    "stopped": "stopped",
    "paused": "paused",
    "startpending": "pending",
    "stoppending": "pending",
    "continuepending": "pending",
    "pausepending": "pending",
}
_STATE_BY_NUMBER = {1: "stopped", 2: "pending", 3: "pending", 4: "running",
                    5: "pending", 6: "pending", 7: "paused"}
_SC_STATE_NAMES = {"STOPPED": "stopped", "START_PENDING": "pending", "STOP_PENDING": "pending",
                   "RUNNING": "running", "CONTINUE_PENDING": "pending", "PAUSE_PENDING": "pending",
                   "PAUSED": "paused"}
_SC_FIELD = re.compile(r"^\s*[^:\r\n]+:\s*(\d+)\s+([A-Z_]+)\b", re.MULTILINE)

ERR_NOT_FOUND = 1060
ERR_DENIED = 5
ERR_ALREADY_RUNNING = 1056
ERR_NOT_RUNNING = 1062


def find_nssm(base_dir=None):
    if base_dir:
        candidate = ntpath.join(base_dir, "nssm", "nssm.exe")
        if os.path.exists(candidate):
            return candidate
    return shutil.which("nssm")


def download_nssm(base_dir, opener=None):
    import platform
    import tempfile
    import urllib.request
    import zipfile

    opener = opener or urllib.request.urlopen
    arch = "win64" if platform.machine().endswith("64") else "win32"
    target = ntpath.join(base_dir, "nssm", "nssm.exe")
    with tempfile.TemporaryDirectory() as tmp:
        archive = os.path.join(tmp, "nssm.zip")
        with opener(NSSM_URL, timeout=60) as response, open(archive, "wb") as out:  # nosec B310
            shutil.copyfileobj(response, out)
        with open(archive, "rb") as f:
            digest = hashlib.sha256(f.read()).hexdigest()
        if digest != NSSM_SHA256:
            os.remove(archive)
            raise ValueError(f"checksum mismatch (got {digest}, expected {NSSM_SHA256})")
        with zipfile.ZipFile(archive) as zf:
            member = next(n for n in zf.namelist() if n.endswith(f"{arch}/nssm.exe"))
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with zf.open(member) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
    return target


def ensure_nssm(base_dir, opener=None):
    found = find_nssm(base_dir)
    if found:
        return found, ""
    try:
        return download_nssm(base_dir, opener), ""
    except Exception as e:
        return None, f"nssm download failed: {e}"


def _as_list(data):
    if data is None:
        return []
    if isinstance(data, dict):
        return [data]
    return list(data)


def _state_from_value(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return _STATE_BY_NUMBER.get(value)
    text = str(value).strip().lower()
    if text.isdigit():
        return _STATE_BY_NUMBER.get(int(text))
    return _STATE_BY_NAME.get(text)


_START_BY_NAME = {"automatic": "automatic", "automaticdelayedstart": "automatic",
                  "manual": "manual", "disabled": "disabled", "boot": "boot", "system": "system"}
_START_BY_NUMBER = {0: "boot", 1: "system", 2: "automatic", 3: "manual", 4: "disabled"}


def parse_start_type(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return _START_BY_NUMBER.get(value)
    text = str(value).strip().lower().replace(" ", "").replace("(", "").replace(")", "")
    if text.isdigit():
        return _START_BY_NUMBER.get(int(text))
    return _START_BY_NAME.get(text)


def parse_powershell_state(text, name=SERVICE_NAME):
    text = (text or "").strip()
    if not text:
        return "absent"
    try:
        entries = _as_list(json.loads(text))
    except ValueError:
        return None
    for entry in entries:
        if isinstance(entry, dict) and str(entry.get("Name", "")).lower() == name.lower():
            return _state_from_value(entry.get("Status"))
    return "absent"


def parse_sc_query(text):
    for _number, word in _SC_FIELD.findall(text or ""):
        if word in _SC_STATE_NAMES:
            return _SC_STATE_NAMES[word]
    return None


def service_state():
    rc, out, _err = common.run_powershell(_PS_STATE)
    if rc == 0:
        state = parse_powershell_state(out)
        if state is not None:
            return state
    rc, out, err = common.run(["sc", "query", SERVICE_NAME])
    if rc == ERR_NOT_FOUND:
        return "absent"
    if rc != 0:
        return None
    return parse_sc_query(out + "\n" + err)


def service_installed():
    return service_state() not in ("absent", None)


def service_running():
    return service_state() == "running"


def _code_for(rc, verb):
    if rc == 0:
        return "ok"
    if rc == ERR_NOT_FOUND:
        return "not_installed"
    if rc == ERR_DENIED:
        return "no_permission"
    if verb == "start" and rc == ERR_ALREADY_RUNNING:
        return "ok"
    if verb == "stop" and rc == ERR_NOT_RUNNING:
        return "ok"
    return "error"


def _sc(verb):
    rc, out, err = common.run(["sc", verb, SERVICE_NAME])
    return _code_for(rc, verb), (out + err).strip()


def _wait_stopped(timeout):
    deadline = time.monotonic() + timeout
    while True:
        if service_state() in ("stopped", "absent"):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.5)


def service_control(action, timeout=STOP_TIMEOUT):
    if action in ("start", "stop"):
        return _sc(action)
    if action != "restart":
        raise ValueError(action)
    code, detail = _sc("stop")
    if code != "ok":
        return code, detail
    if not _wait_stopped(timeout):
        return "error", "service did not stop in time"
    return _sc("start")


def service_restart():
    return service_control("restart")


def service_admin_command(action):
    if action == "restart":
        return f"net stop {SERVICE_NAME} && net start {SERVICE_NAME}"
    return f"net {action} {SERVICE_NAME}"


def _clean(text):
    text = (text or "").replace("\x00", "").replace("﻿", "")
    return text.lstrip("\xff\xfe\xa0\u25a0").strip()


def nssm_get(nssm_exe, parameter):
    rc, out, _err = common.run([nssm_exe, "get", SERVICE_NAME, parameter])
    if rc != 0:
        return None
    value = _clean(out)
    return value if value else None


def service_kill_tree_disabled(nssm_exe=None):
    nssm_exe = nssm_exe or find_nssm()
    if not nssm_exe:
        return None
    value = nssm_get(nssm_exe, "AppKillProcessTree")
    if value == "0":
        return True
    if value == "1":
        return False
    return None


def service_install(nssm_exe, python_exe, daemon_path, app_dir, logs_dir, shared_data_dir=None):
    def nssm(*args):
        return common.run([nssm_exe, *args])

    nssm("stop", SERVICE_NAME)
    nssm("remove", SERVICE_NAME, "confirm")
    steps = [
        ("install", SERVICE_NAME, python_exe, daemon_path),
        ("set", SERVICE_NAME, "AppDirectory", app_dir),
        ("set", SERVICE_NAME, "Start", "SERVICE_AUTO_START"),
        ("set", SERVICE_NAME, "AppStderr", ntpath.join(logs_dir, "daemon_error.log")),
        ("set", SERVICE_NAME, "AppRotateFiles", "0"),
        ("set", SERVICE_NAME, "AppKillProcessTree", "0"),
    ]
    if shared_data_dir:
        steps.append(("set", SERVICE_NAME, "AppEnvironmentExtra",
                      f"MCMANAGER_DATA_DIR={shared_data_dir}"))
    for step in steps:
        rc, out, err = nssm(*step)
        if rc != 0:
            if not files.is_elevated():
                return "no_permission", f'"{nssm_exe}" {" ".join(step)}'
            return "error", _clean(out + err)
    if service_kill_tree_disabled(nssm_exe) is not True:
        return "error", "AppKillProcessTree is not 0"
    rc, out, err = nssm("start", SERVICE_NAME)
    if rc != 0:
        return "error", _clean(out + err)
    return "ok", ""


def _norm(directive, value):
    value = (value or "").strip().strip('"')
    if directive in ("Application", "AppDirectory"):
        return ntpath.normcase(ntpath.normpath(value))
    return " ".join(value.replace('"', "").split()).lower()


def service_unit_drift(expected=None, nssm_exe=None):
    state = service_state()
    if state == "absent":
        return "missing", []
    wanted = dict(expected or {})
    wanted["AppKillProcessTree"] = "0"
    nssm_exe = nssm_exe or find_nssm()
    if not nssm_exe or state is None:
        return "ok", []
    drift = []
    for directive, target in wanted.items():
        actual = nssm_get(nssm_exe, directive)
        if actual is None:
            continue
        if _norm(directive, actual) != _norm(directive, target):
            drift.append((directive, actual, target))
    return ("outdated" if drift else "ok"), drift
