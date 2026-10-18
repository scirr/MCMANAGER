import csv
import io
import json
import os
import re
import subprocess
import time

from plat_win_common import Unsupported, run, run_powershell, is_windows

MARKER = "-Dmcmanager.server="
CREATE_NEW_PROCESS_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200)
DETACHED_PROCESS = getattr(subprocess, "DETACHED_PROCESS", 0x8)

_CIM_JAVA = ("ConvertTo-Json -Compress -InputObject @(Get-CimInstance Win32_Process "
             "-Filter \"Name='java.exe' OR Name='javaw.exe'\" | "
             "Select-Object ProcessId,ParentProcessId,Name,CommandLine)")
_CIM_PID = ("ConvertTo-Json -Compress -InputObject @(Get-CimInstance Win32_Process "
            "-Filter \"ProcessId=%d\" | Select-Object ProcessId,ParentProcessId,Name,"
            "CommandLine,WorkingSetSize,KernelModeTime,UserModeTime,"
            "@{n='Start';e={([DateTimeOffset]$_.CreationDate).ToUnixTimeSeconds()}})")


def _now():
    return time.time()


def _popen(cmd, **kwargs):
    return subprocess.Popen(cmd, **kwargs)


def _cim_rows(script):
    rc, out, _ = run_powershell(script)
    if rc != 0:
        return None
    out = out.strip()
    if not out:
        return []
    try:
        data = json.loads(out)
    except ValueError:
        return None
    if data is None:
        return []
    if isinstance(data, dict):
        data = [data]
    return [row for row in data if isinstance(row, dict)]


def _cim_info(pid):
    rows = _cim_rows(_CIM_PID % int(pid))
    if not rows:
        return None
    return rows[0]


def _norm_dir(path):
    return path.replace("/", "\\").rstrip("\\").lower()


def command_line_has_marker(command_line, server_dir):
    if not command_line or not server_dir:
        return False
    line = command_line.replace("/", "\\").lower()
    want = MARKER.lower() + _norm_dir(server_dir)
    start = 0
    while True:
        at = line.find(want, start)
        if at < 0:
            return False
        end = at + len(want)
        rest = line[end:end + 2]
        if rest == "" or rest[0] == '"' or rest in ("\\", '\\"'):
            return True
        if rest[0] == " " and (len(rest) == 1 or rest[1] in '-@"'):
            return True
        start = end


def find_server_processes(server_dir):
    if not server_dir:
        return []
    rows = _cim_rows(_CIM_JAVA)
    me = os.getpid()
    pids = set()
    for row in rows or []:
        pid = row.get("ProcessId")
        if isinstance(pid, int) and pid != me and \
                command_line_has_marker(row.get("CommandLine"), server_dir):
            pids.add(pid)
    return sorted(pids)


def _alive_ctypes(pid):
    if not is_windows():
        return None
    try:
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        handle = kernel32.OpenProcess(0x1000, False, int(pid))
        if not handle:
            return True if ctypes.get_last_error() == 5 else False
        try:
            code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return None
            return code.value == 259
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return None


def parse_tasklist_csv(text):
    rows = []
    for row in csv.reader(io.StringIO(text or "")):
        if len(row) >= 2 and row[1].strip().isdigit():
            rows.append((row[0], int(row[1])))
    return rows


def _tasklist(pid):
    rc, out, _ = run(["tasklist", "/FI", "PID eq %d" % int(pid), "/FO", "CSV", "/NH"])
    if rc != 0:
        return []
    return [r for r in parse_tasklist_csv(out) if r[1] == int(pid)]


def process_alive(pid, server_dir=None):
    if not isinstance(pid, int) or pid <= 0:
        return False
    alive = _alive_ctypes(pid)
    if alive is None:
        alive = bool(_tasklist(pid))
    if alive and server_dir:
        return pid in find_server_processes(server_dir)
    return alive


def process_name(pid):
    info = _cim_info(pid)
    if info and info.get("Name"):
        return info["Name"]
    rows = _tasklist(pid)
    return rows[0][0] if rows else None


def _parse_start(value):
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        m = re.search(r"Date\((-?\d+)", value)
        if m:
            return int(m.group(1)) / 1000.0
        try:
            return float(value)
        except ValueError:
            return None
    return None


def process_uptime(pid):
    info = _cim_info(pid)
    start = _parse_start(info.get("Start")) if info else None
    if start is None:
        return None
    return max(0.0, _now() - start)


def process_memory(pid):
    info = _cim_info(pid)
    size = info.get("WorkingSetSize") if info else None
    if not isinstance(size, (int, float)):
        return None, None
    return int(size) // 1024, None


def process_cpu_seconds(pid):
    info = _cim_info(pid)
    if not info:
        return None
    kernel, user = info.get("KernelModeTime"), info.get("UserModeTime")
    if not isinstance(kernel, (int, float)) or not isinstance(user, (int, float)):
        return None
    return (kernel + user) / 1e7


def terminate(pid, tree=False):
    return False


def kill(pid, tree=False):
    cmd = ["taskkill", "/PID", str(int(pid))]
    if tree:
        cmd.append("/T")
    cmd.append("/F")
    rc, _, _ = run(cmd)
    return rc == 0


def suspend(pid, tree=False):
    raise Unsupported("suspend is not available on Windows")


def resume(pid, tree=False):
    raise Unsupported("resume is not available on Windows")


def reap_children():
    return None


def find_zombie_java():
    return []


def set_affinity(pid, cpus):
    if not is_windows() or not cpus:
        return False
    try:
        import ctypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(0x0200 | 0x1000, False, int(pid))
        if not handle:
            return False
        try:
            mask = sum(1 << int(c) for c in cpus)
            return bool(kernel32.SetProcessAffinityMask(handle, mask))
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return False


def server_script_name():
    return "run.bat"


def script_launch_args(script):
    return ["cmd", "/c", script, "nogui"]


def launch_args_name():
    return "win_args.txt"


def spawn_server(cmd, cwd, env=None, log=None):
    handle = open(log, "ab") if log else None
    try:
        return _popen(
            cmd, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
            stdout=handle if handle else subprocess.DEVNULL,
            stderr=subprocess.STDOUT if handle else subprocess.DEVNULL,
            creationflags=CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS,
            close_fds=True)
    finally:
        if handle:
            handle.close()
