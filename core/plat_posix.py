import contextlib
import os
import select
import shlex
import shutil
import signal
import socket
import subprocess
import sys


def _signal(pid, sig, tree):
    if tree:
        try:
            if os.getpgid(pid) == pid:
                os.killpg(pid, sig)
        except Exception:
            pass
    try:
        os.kill(pid, sig)
        return True
    except Exception:
        return False


def terminate(pid, tree=False):
    return _signal(pid, signal.SIGTERM, tree)


def kill(pid, tree=False):
    return _signal(pid, signal.SIGKILL, tree)


def suspend(pid, tree=False):
    return _signal(pid, signal.SIGSTOP, tree)


def resume(pid, tree=False):
    return _signal(pid, signal.SIGCONT, tree)


def reap_children():
    while True:
        try:
            pid, _ = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            return
        except Exception:
            return
        if pid == 0:
            return


def spawn_server(cmd, cwd, env=None, log=None):
    handle = open(log, "ab") if log else None
    try:
        return subprocess.Popen(
            cmd,
            cwd=cwd,
            env=env,
            start_new_session=True,
            stdout=handle if handle else subprocess.DEVNULL,
            stderr=subprocess.STDOUT if handle else subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
        )
    finally:
        if handle:
            handle.close()


def server_script_name():
    return "run.sh"


def script_launch_args(script):
    return ["bash", script, "nogui"]


def launch_args_name():
    return "unix_args.txt"


def port_in_use(port):
    # SO_REUSEADDR mirrors how the JVM binds: without it, a socket lingering in
    # TIME_WAIT makes the port look busy for a minute and blocks a safe start.
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("0.0.0.0", int(port)))  # nosec B104 - probes the public game port
        return False
    except OSError:
        return True
    except Exception:
        return False


def is_elevated():
    return os.geteuid() == 0


def secure_file(path):
    try:
        os.chmod(path, 0o600)
        return True
    except OSError:
        return False


def secure_dir(path, owner_of=None):
    # owner_of: a folder just made by root is handed to the owner of that
    # path, or the service (running as the user) could no longer reach it.
    try:
        if owner_of and os.geteuid() == 0:
            st = os.stat(owner_of)
            os.chown(path, st.st_uid, st.st_gid)
        if os.stat(path).st_uid == os.geteuid():
            os.chmod(path, 0o700)
        return True
    except OSError:
        return False


def file_is_private(path):
    try:
        st = os.stat(path)
    except OSError:
        return None, ""
    if not st.st_mode & 0o077:
        return True, ""
    return False, f"chmod 600 {path}"


def _owner_to_keep(path):
    if os.geteuid() != 0:
        return None
    for candidate in (path, os.path.dirname(path) or "."):
        try:
            st = os.stat(candidate)
            return st.st_uid, st.st_gid
        except OSError:
            continue
    return None


def write_private_file(path, text, mode=0o600):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    owner = _owner_to_keep(path) if mode == 0o600 else None
    tmp_path = f"{path}.{os.getpid()}.tmp"
    fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        f.write(text)
    os.chmod(tmp_path, mode)
    if owner:
        os.chown(tmp_path, *owner)
    os.replace(tmp_path, path)


def set_executable(path):
    os.chmod(path, 0o755)  # nosec B103 - launchers and shell scripts must be executable


def atomic_replace(src, dst):
    os.replace(src, dst)


def shell_quote(s):
    return shlex.quote(s)


class _Keys:
    def __init__(self, stream):
        self._stream = stream

    def read_key(self, timeout=0.0):
        readable, _, _ = select.select([self._stream], [], [], max(0.0, timeout))
        if not readable:
            return None
        ch = self._stream.read(1)
        if ch == "\x1b":
            while select.select([self._stream], [], [], 0.005)[0]:
                self._stream.read(1)
            return "special"
        return ch


@contextlib.contextmanager
def console_raw_mode():
    import termios
    import tty
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        yield _Keys(sys.stdin)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def setup_console():
    return None


def pick_file_dialog():
    """Open a native file picker (tkinter, then zenity/kdialog as fallback).
    Returns the selected path or None."""
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        path = filedialog.askopenfilename(
            title="Select server icon",
            filetypes=[
                ("Image files", "*.png *.jpg *.jpeg *.webp *.bmp *.gif *.tiff"),
                ("All files", "*.*"),
            ],
        )
        root.destroy()
        return path or None
    except Exception:
        pass

    if shutil.which("zenity"):
        try:
            result = subprocess.run(
                ["zenity", "--file-selection", "--title=Select server icon",
                 "--file-filter=Images | *.png *.jpg *.jpeg *.webp *.bmp *.gif *.tiff"],
                capture_output=True, text=True, timeout=300
            )
            path = result.stdout.strip()
            return path if result.returncode == 0 and path else None
        except Exception:
            pass

    if shutil.which("kdialog"):
        try:
            result = subprocess.run(
                ["kdialog", "--getopenfilename", os.path.expanduser("~"),
                 "image/png image/jpeg image/webp image/bmp image/gif image/tiff"],
                capture_output=True, text=True, timeout=300
            )
            path = result.stdout.strip()
            return path if result.returncode == 0 and path else None
        except Exception:
            pass

    return None
