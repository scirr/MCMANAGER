import contextlib
import glob
import ntpath
import os
import shutil
import subprocess
import sys
import time

import plat_win_files as _files
import plat_win_firewall as _firewall
import plat_win_net as _net
import plat_win_process as _process
import plat_win_service as _service
from mc_platform import Unsupported

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

_SPECIAL_KEYS = {
    "H": "up", "P": "down", "K": "left", "M": "right", "G": "home", "O": "end",
    "I": "pageup", "Q": "pagedown", "R": "insert", "S": "delete",
    "\x0f": "shift-tab", "s": "ctrl-left", "t": "ctrl-right",
}
_SPECIAL_KEYS.update({chr(0x3B + i): f"f{i + 1}" for i in range(10)})
_SPECIAL_KEYS.update({"\x85": "f11", "\x86": "f12"})

find_server_processes = _process.find_server_processes
process_alive = _process.process_alive
process_name = _process.process_name
process_uptime = _process.process_uptime
process_memory = _process.process_memory
process_cpu_seconds = _process.process_cpu_seconds
terminate = _process.terminate
kill = _process.kill
reap_children = _process.reap_children
spawn_server = _process.spawn_server
set_affinity = _process.set_affinity
find_zombie_java = _process.find_zombie_java
server_script_name = _process.server_script_name
script_launch_args = _process.script_launch_args
launch_args_name = _process.launch_args_name

port_in_use = _net.port_in_use
port_listener = _net.port_listener
listens_on_all_interfaces = _net.listens_on_all_interfaces

service_installed = _service.service_installed
service_running = _service.service_running
service_control = _service.service_control

firewall_name = _firewall.firewall_name
firewall_port_open = _firewall.firewall_port_open
firewall_allow = _firewall.firewall_allow
firewall_remove = _firewall.firewall_remove
firewall_manual_command = _firewall.firewall_manual_command

secure_file = _files.secure_file
secure_dir = _files.secure_dir
file_is_private = _files.file_is_private
write_private_file = _files.write_private_file
data_dir = _files.data_dir
cache_dir = _files.cache_dir
open_folder = _files.open_folder
atomic_replace = _files.atomic_replace
is_elevated = _files.is_elevated
current_user = _files.current_user
java_archive_kind = _files.java_archive_kind


def suspend(pid, tree=False):
    raise Unsupported("suspend is not available on Windows")


def resume(pid, tree=False):
    raise Unsupported("resume is not available on Windows")


def _service_python():
    quiet = sys.executable.replace("python.exe", "pythonw.exe")
    return quiet if os.path.exists(quiet) else sys.executable


def _service_paths():
    nssm = _service.find_nssm(BASE_DIR)
    daemon = ntpath.join(BASE_DIR, "mc_daemon.py")
    return nssm, _service_python(), daemon, BASE_DIR


def service_install(user=None):
    nssm, err = _service.ensure_nssm(BASE_DIR)
    if not nssm:
        return False, err
    daemon = ntpath.join(BASE_DIR, "mc_daemon.py")
    logs = ntpath.join(BASE_DIR, "logs")
    shared = os.environ.get("MCMANAGER_DATA_DIR", "").strip() or None
    code, detail = _service.service_install(nssm, _service_python(), daemon, BASE_DIR, logs, shared)
    return code == "ok", detail


def service_unit_drift():
    nssm, python_exe, daemon, base = _service_paths()
    expected = {"Application": python_exe, "AppParameters": daemon, "AppDirectory": base}
    return _service.service_unit_drift(expected, nssm)


def set_executable(path):
    return None


def default_editor():
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR")
    return editor.split() if editor else ["notepad"]


def install_launcher():
    if not _files.is_elevated():
        return False, "elevation required"
    root = os.environ.get("SystemRoot") or r"C:\Windows"
    dst = ntpath.join(root, "System32", "mc.bat")
    content = f'@echo off\r\npython "{ntpath.join(BASE_DIR, "mc_cli.py")}" %*\r\n'
    try:
        with open(dst, "w", encoding="utf-8", newline="") as f:
            f.write(content)
    except OSError as e:
        return False, str(e)
    return True, dst


def java_search_paths():
    roots = []
    for var in ("ProgramFiles", "ProgramW6432"):
        value = os.environ.get(var)
        if value and value not in roots:
            roots.append(value)
    if not roots:
        roots = [r"C:\Program Files"]
    names = ("Java", "Eclipse Adoptium", "Microsoft", "BellSoft")
    return [ntpath.join(root, name, "**", "java.exe") for root in roots for name in names]


def os_name():
    return "Windows"


def java_exe_name():
    return "bin\\java.exe"


def adoptium_os():
    return "windows"


class _Keys:
    def __init__(self, msvcrt):
        self._m = msvcrt

    def read_key(self, timeout=0.0):
        m = self._m
        deadline = time.monotonic() + max(0.0, timeout)
        while not m.kbhit():
            if time.monotonic() >= deadline:
                return None
            time.sleep(0.01)
        ch = m.getwch()
        if ch in ("\x00", "\xe0"):
            second = m.getwch()
            return _SPECIAL_KEYS.get(second, "special")
        return ch


@contextlib.contextmanager
def console_raw_mode():
    import msvcrt
    yield _Keys(msvcrt)


def pick_file_dialog():
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        try:
            path = filedialog.askopenfilename(filetypes=[
                ("Image files", "*.png *.jpg *.jpeg *.webp *.bmp *.gif *.tiff"),
                ("All files", "*.*")])
        finally:
            root.destroy()
        return path or None
    except Exception:
        return None


def shell_quote(s):
    return subprocess.list2cmdline([s])


def cgroup_of(pid):
    return None


def setup_console():
    if sys.platform != "win32":
        return
    os.system("")
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
