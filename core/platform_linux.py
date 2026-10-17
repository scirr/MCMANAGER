import contextlib
import os
import re
import select
import shlex
import shutil
import signal
import socket
import subprocess
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

SERVICE_NAME = "mc_manager"
SERVICE_FILE = f"/etc/systemd/system/{SERVICE_NAME}.service"
POLKIT_RULE_FILE = "/etc/polkit-1/rules.d/50-mc-manager.rules"
LAUNCHER_PATH = "/usr/local/bin/mc"


# ── processes ────────────────────────────────────────────────────────────────
# Every /proc reader returns None when the information cannot be read (process
# gone, or owned by another user) so callers can tell "unknown" from "different".

def _proc_state(pid):
    try:
        with open(f"/proc/{pid}/stat") as f:
            return f.read().rsplit(")", 1)[1].split()[0]
    except Exception:
        return None


def _proc_cwd(pid):
    try:
        return os.path.realpath(os.readlink(f"/proc/{pid}/cwd"))
    except Exception:
        return None


def _proc_name(pid):
    try:
        with open(f"/proc/{pid}/comm") as f:
            return f.read().strip()
    except Exception:
        return None


def _proc_argv0(pid):
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            first = f.read().split(b"\x00", 1)[0]
        return os.path.basename(first.decode("utf-8", "replace"))
    except Exception:
        return None


def _is_java(pid):
    return "java" in ((_proc_name(pid) or "") + " " + (_proc_argv0(pid) or "")).lower()


def _same_dir(a, b):
    if not a or not b:
        return False
    return os.path.realpath(a) == os.path.realpath(b)


def process_alive(pid, server_dir=None):
    try:
        os.waitpid(pid, os.WNOHANG)
    except (ChildProcessError, OSError):
        pass
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    except Exception:
        return False
    if _proc_state(pid) == "Z":
        return False
    if server_dir is None:
        return True
    if server_dir:
        cwd = _proc_cwd(pid)
        if cwd is not None:
            return _same_dir(cwd, server_dir)
    argv0 = _proc_argv0(pid)
    if argv0 and not any(m in argv0 for m in ("java", "bash", "sh")):
        return False
    return True


def find_server_processes(server_dir):
    found = []
    if not server_dir:
        return found
    target = os.path.realpath(server_dir)
    try:
        entries = os.listdir("/proc")
    except Exception:
        return found
    for entry in entries:
        if not entry.isdigit():
            continue
        pid = int(entry)
        if pid == os.getpid():
            continue
        cwd = _proc_cwd(pid)
        if cwd != target or not _is_java(pid) or _proc_state(pid) in (None, "Z"):
            continue
        found.append(pid)
    return sorted(found)


def process_name(pid):
    return _proc_name(pid)


def process_uptime(pid):
    try:
        with open(f"/proc/{pid}/stat") as f:
            fields = f.read().rsplit(")", 1)[1].split()
        start_ticks = int(fields[19])  # field 22 of stat, 0-based after 'comm'
        with open("/proc/uptime") as f:
            boot_uptime = float(f.read().split()[0])
        return max(0, int(boot_uptime - start_ticks / os.sysconf("SC_CLK_TCK")))
    except Exception:
        return None


def process_memory(pid):
    rss = swap = None
    try:
        with open(f"/proc/{pid}/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    rss = int(line.split()[1])
                elif line.startswith("VmSwap:"):
                    swap = int(line.split()[1])
    except Exception:
        pass
    return rss, swap


def process_cpu_seconds(pid):
    try:
        with open(f"/proc/{pid}/stat") as f:
            fields = f.read().rsplit(")", 1)[1].split()
        ticks = int(fields[11]) + int(fields[12])
        return ticks / os.sysconf("SC_CLK_TCK")
    except Exception:
        return None


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


def set_affinity(pid, cpus):
    try:
        os.sched_setaffinity(pid, cpus)
        return True
    except Exception:
        return False


def find_zombie_java():
    out = []
    try:
        entries = os.listdir("/proc")
    except Exception:
        return out
    for entry in entries:
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/stat") as f:
                raw = f.read()
        except Exception:
            continue
        name = raw[raw.find("(") + 1:raw.rfind(")")]
        rest = raw.rsplit(")", 1)[1].split()
        if rest and rest[0] == "Z" and "java" in name.lower():
            out.append((int(entry), int(rest[1])))
    return out


def server_script_name():
    return "run.sh"


def script_launch_args(script):
    return ["bash", script, "nogui"]


def cgroup_of(pid):
    try:
        with open(f"/proc/{pid}/cgroup") as f:
            for line in f:
                if line.startswith("0::"):
                    return line.strip()[3:]
            return None
    except Exception:
        return None


# ── ports ────────────────────────────────────────────────────────────────────

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


def _listen_inodes(port):
    inodes = set()
    for table in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            with open(table) as f:
                next(f, None)
                for line in f:
                    cols = line.split()
                    if len(cols) > 9 and cols[3] == "0A" and int(cols[1].rsplit(":", 1)[1], 16) == int(port):
                        inodes.add(cols[9])
        except Exception:
            continue
    return inodes


def listens_on_all_interfaces(port):
    found = None
    for table in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            with open(table) as f:
                next(f, None)
                for line in f:
                    cols = line.split()
                    if len(cols) < 4 or cols[3] != "0A":
                        continue
                    addr, _, hexport = cols[1].rpartition(":")
                    if int(hexport, 16) != int(port):
                        continue
                    if set(addr) == {"0"}:
                        return True
                    found = False
        except Exception:
            continue
    return found


def _listener_pid(port):
    try:
        inodes = _listen_inodes(port)
    except Exception:
        return None
    if not inodes:
        return None
    wanted = {f"socket:[{i}]" for i in inodes}
    try:
        entries = os.listdir("/proc")
    except Exception:
        return None
    for entry in entries:
        if not entry.isdigit():
            continue
        fd_dir = f"/proc/{entry}/fd"
        try:
            fds = os.listdir(fd_dir)
        except Exception:
            continue
        for fd in fds:
            try:
                if os.readlink(f"{fd_dir}/{fd}") in wanted:
                    return int(entry)
            except Exception:
                continue
    return None


def port_listener(port):
    if not port or not port_in_use(port):
        return None
    pid = _listener_pid(port)
    if not pid:
        return (None, None)
    return (pid, _proc_name(pid) or "?")


# ── privileges and files ─────────────────────────────────────────────────────

def is_elevated():
    return os.geteuid() == 0


def current_user():
    return os.environ.get("SUDO_USER") or os.environ.get("USER") or "root"


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


def data_dir():
    return os.path.expanduser("~/MCManager/Servers")


def cache_dir():
    return os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")


def open_folder(path):
    subprocess.Popen(["xdg-open", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def default_editor():
    return shlex.split(os.environ.get("VISUAL") or os.environ.get("EDITOR") or "nano")


def install_launcher():
    python_exe = sys.executable or "python3"
    content = f'#!/bin/sh\nexec "{python_exe}" "{BASE_DIR}/mc_cli.py" "$@"\n'
    launcher_path = os.path.join(BASE_DIR, "mc")
    with open(launcher_path, 'w', encoding='utf-8') as f:
        f.write(content)
    set_executable(launcher_path)
    try:
        shutil.copy(launcher_path, LAUNCHER_PATH)
        set_executable(LAUNCHER_PATH)
    except PermissionError:
        return False, f"permission:{launcher_path}:{LAUNCHER_PATH}"
    except Exception as e:
        return False, str(e)
    return True, LAUNCHER_PATH


def shell_quote(s):
    return shlex.quote(s)


# ── java ─────────────────────────────────────────────────────────────────────

def java_search_paths():
    return [
        "/usr/lib/jvm/*/bin/java",
        "/usr/java/*/bin/java",
        "/opt/java/*/bin/java",
        "/opt/jdk*/bin/java",
    ]


def java_exe_name():
    return "bin/java"


def java_archive_kind():
    return "tar.gz"


def adoptium_os():
    return "linux"


# ── service (systemd) ────────────────────────────────────────────────────────

def _service_states():
    if not shutil.which("systemctl"):
        return {}
    try:
        result = subprocess.run(
            ["systemctl", "show", "-p", "LoadState,ActiveState", f"{SERVICE_NAME}.service"],
            capture_output=True, text=True, timeout=10
        )
    except Exception:
        return {}
    return dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)


def service_installed():
    """None when systemctl is not available at all."""
    if not shutil.which("systemctl"):
        return None
    return _service_states().get("LoadState") == "loaded"


def service_running():
    states = _service_states()
    return states.get("LoadState") == "loaded" and states.get("ActiveState") == "active"


def _run_systemctl(action):
    # As root: directly. Otherwise through polkit first (install.sh grants the
    # service user start/stop/restart on this unit only) with --no-ask-password
    # so nothing prompts; sudo is only the fallback for older installs.
    base = ["systemctl", action, SERVICE_NAME]
    if os.geteuid() == 0:
        return subprocess.run(base, capture_output=True, text=True)
    result = subprocess.run(["systemctl", "--no-ask-password", action, SERVICE_NAME],
                            capture_output=True, text=True)
    if result.returncode == 0:
        return result
    try:
        fallback = subprocess.run(["sudo"] + base, capture_output=True, text=True)
        if fallback.returncode == 0:
            return fallback
    except Exception:
        pass
    return result


def service_control(action):
    result = _run_systemctl(action)
    if result.returncode == 0:
        return "ok", ""
    detail = ((result.stdout or "") + (result.stderr or "")).strip()
    low = detail.lower()
    if "not found" in low or "not-found" in low or "no such" in low or "not loaded" in low:
        return "not_installed", detail
    if "access denied" in low or "permission denied" in low or "authentication" in low or "interactive" in low:
        return "no_permission", detail
    return "error", f"{result.returncode}|{detail}"


def _service_unit_content(user):
    python_exe = sys.executable or "/usr/bin/python3"
    daemon_path = os.path.join(BASE_DIR, "mc_daemon.py")
    # A systemd service does not inherit the installing shell's environment, so
    # if a shared data dir is configured we must bake it into the unit — else the
    # daemon would fall back to the local registry and manage nothing shared.
    env_line = ""
    shared = os.environ.get("MCMANAGER_DATA_DIR", "").strip()
    if shared:
        env_line = f'Environment="MCMANAGER_DATA_DIR={shared}"\n'
    # A service running as the user needs no capability at all; root (install
    # without sudo) keeps its own, or it could no longer reach users' files.
    caps = "" if user == "root" else "CapabilityBoundingSet=\nAmbientCapabilities=\n"
    return f"""[Unit]
Description=MC Manager Daemon
After=network.target

[Service]
Type=simple
User={user}
WorkingDirectory={BASE_DIR}
{env_line}ExecStart={python_exe} {daemon_path}
Restart=on-failure
RestartSec=10
# Only kill the daemon itself, never the Minecraft servers it spawned: with the
# default control-group mode, restarting the service would take the servers down
# (leaving a stale server.pid) instead of just reloading the supervisor.
KillMode=process
# Hardening. Servers live anywhere under /home or /srv, so the filesystem stays
# writable except system directories; the JVM needs W+X memory for its JIT, so
# MemoryDenyWriteExecute is deliberately absent.
NoNewPrivileges=yes
PrivateTmp=yes
PrivateDevices=yes
ProtectSystem=full
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectKernelLogs=yes
ProtectControlGroups=yes
ProtectClock=yes
ProtectHostname=yes
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6 AF_NETLINK
RestrictNamespaces=yes
RestrictRealtime=yes
RestrictSUIDSGID=yes
LockPersonality=yes
SystemCallArchitectures=native
{caps}
[Install]
WantedBy=multi-user.target
"""


def _polkit_rule_content(user):
    return f"""// Installed by MC Manager (install.sh). Allows '{user}' to start, stop and
// restart the {SERVICE_NAME} service only.
polkit.addRule(function(action, subject) {{
    if (action.id == "org.freedesktop.systemd1.manage-units" &&
        action.lookup("unit") == "{SERVICE_NAME}.service" &&
        subject.user == "{user}") {{
        var verb = action.lookup("verb");
        if (verb == "start" || verb == "stop" || verb == "restart") {{
            return polkit.Result.YES;
        }}
    }}
}});
"""


def _install_polkit_rule(user):
    folder = os.path.dirname(POLKIT_RULE_FILE)
    if not os.path.isdir(folder) or user == "root":
        return False
    try:
        with open(POLKIT_RULE_FILE, "w", encoding="utf-8") as f:
            f.write(_polkit_rule_content(user))
        os.chmod(POLKIT_RULE_FILE, 0o644)
        return True
    except OSError:
        return False


def _unit_directives(text):
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", ";", "[")) or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out.setdefault(key.strip(), value.strip())
    return out


def service_unit_drift():
    try:
        with open(SERVICE_FILE, "r", encoding="utf-8") as f:
            installed = _unit_directives(f.read())
    except Exception:
        return "missing", []
    expected = _unit_directives(_service_unit_content(installed.get("User", "root")))
    diffs = []
    for key, value in expected.items():
        if key in ("User", "Environment"):
            continue
        have = installed.get(key)
        if key == "ExecStart":
            # Only the daemon script matters, not which python runs it.
            daemon_path = os.path.join(BASE_DIR, "mc_daemon.py")
            if not have or not have.endswith(daemon_path):
                diffs.append((key, have, value))
            continue
        if have != value:
            diffs.append((key, have, value))
    return ("outdated" if diffs else "ok"), diffs


def service_install(user=None):
    user = user or current_user()
    try:
        with open(SERVICE_FILE, 'w', encoding='utf-8') as f:
            f.write(_service_unit_content(user))
    except PermissionError:
        return False, ""
    detail = "polkit" if _install_polkit_rule(user) else ""
    subprocess.run(["systemctl", "daemon-reload"], capture_output=True)
    subprocess.run(["systemctl", "enable", SERVICE_NAME], capture_output=True)
    result = subprocess.run(["systemctl", "restart", SERVICE_NAME], capture_output=True, text=True)
    return result.returncode == 0, detail


# ── firewall (ufw, firewalld) ────────────────────────────────────────────────

def _run(args, root=False):
    """Run a command, through 'sudo -n' when root is needed and we are not
    root. Returns the CompletedProcess, or None if it could not run."""
    if root and os.geteuid() != 0:
        if not shutil.which("sudo"):
            return None
        args = ["sudo", "-n"] + args
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=15)
    except Exception:
        return None


def _ufw_enabled():
    if not shutil.which("ufw") and not os.path.exists("/usr/sbin/ufw"):
        return False
    try:
        with open("/etc/ufw/ufw.conf", encoding="utf-8") as f:
            return any(line.strip().lower() == "enabled=yes" for line in f)
    except Exception:
        return False


def _firewalld_running():
    if not shutil.which("firewall-cmd"):
        return False
    result = _run(["firewall-cmd", "--state"])
    return bool(result) and result.returncode == 0 and "running" in (result.stdout or "")


def firewall_name():
    if _ufw_enabled():
        return "ufw"
    if _firewalld_running():
        return "firewalld"
    return None


def _ufw_port_matches(target, port, proto="tcp"):
    spec, _, rule_proto = target.partition("/")
    if rule_proto and rule_proto != proto:
        return False
    if ":" in spec:
        lo, _, hi = spec.partition(":")
        return lo.isdigit() and hi.isdigit() and int(lo) <= int(port) <= int(hi)
    return spec.isdigit() and int(spec) == int(port)


def parse_ufw_status(text, port, proto="tcp"):
    """True if 'ufw status' output has an ALLOW rule covering the port,
    False if not, None if ufw is inactive or the output is not recognised."""
    if "Status: active" not in text:
        return None
    for line in text.splitlines():
        m = re.match(r"^(\S+)(?: \(v6\))?\s+(ALLOW|LIMIT)(?: IN)?\s", line)
        if m and _ufw_port_matches(m.group(1), port, proto):
            return True
    return False


def _ufw_status():
    result = _run(["ufw", "status"], root=True)
    if not result or result.returncode != 0:
        return None
    return result.stdout or ""


def _firewalld_query(port, proto):
    result = _run(["firewall-cmd", "--permanent", f"--query-port={port}/{proto}"])
    if not result:
        return None
    if "yes" in (result.stdout or "").lower():
        return True
    if "no" in (result.stdout or "").lower():
        return False
    return None


def firewall_port_open(port, proto="tcp"):
    backend = firewall_name()
    if backend == "ufw":
        status = _ufw_status()
        return None if status is None else parse_ufw_status(status, port, proto)
    if backend == "firewalld":
        return _firewalld_query(port, proto)
    return None


def firewall_manual_command(port, proto, label):
    backend = firewall_name()
    if backend == "ufw" or (backend is None and shutil.which("ufw")):
        comment = f" comment 'MC Manager {label}'" if label else ""
        return f"sudo ufw allow {port}/{proto}{comment}"
    return (f"sudo firewall-cmd --permanent --add-port={port}/{proto} "
            f"&& sudo firewall-cmd --reload")


def firewall_allow(port, proto, label):
    backend = firewall_name()
    if backend == "ufw":
        args = ["ufw", "allow", f"{port}/{proto}"]
        if label:
            args += ["comment", f"MC Manager {label}"]
        result = _run(args, root=True)
    elif backend == "firewalld":
        result = _run(["firewall-cmd", "--permanent", f"--add-port={port}/{proto}"], root=True)
        if result and result.returncode == 0:
            result = _run(["firewall-cmd", "--reload"], root=True)
    else:
        return False, "no firewall"
    if not result:
        return False, "not run"
    return result.returncode == 0, (result.stdout or result.stderr or "").strip()


_UFW_NUMBERED = re.compile(
    r"^\[\s*(\d+)\]\s+(\S+)(?: \(v6\))?\s+(?:ALLOW|LIMIT)(?: IN)?\s.*#\s*MC Manager\b.*$")


def parse_ufw_numbered(text, port, proto="tcp"):
    """Rule numbers of the MC Manager rules ('# MC Manager <server>' comment)
    that open exactly <port>/<proto>, in descending order. Rules without that
    comment, whatever their port, are never returned."""
    numbers = []
    for line in text.splitlines():
        m = _UFW_NUMBERED.match(line.strip())
        if m and m.group(2) == f"{port}/{proto}":
            numbers.append(int(m.group(1)))
    return sorted(numbers, reverse=True)


def _port_used_by_other(port, label=None):
    try:
        import mc_servers
        return mc_servers.find_port_conflict(port=port, exclude_name=label) is not None
    except Exception:
        return False


def firewall_remove(port, proto, label):
    backend = firewall_name()
    port = str(port).split("/")[0]
    if _port_used_by_other(port, label):
        return False
    if backend == "ufw":
        result = _run(["ufw", "status", "numbered"], root=True)
        if not result or result.returncode != 0:
            return False
        removed = False
        for number in parse_ufw_numbered(result.stdout or "", port, proto):
            done = _run(["ufw", "--force", "delete", str(number)], root=True)
            removed = removed or bool(done and done.returncode == 0)
        return removed
    if backend == "firewalld":
        result = _run(["firewall-cmd", "--permanent", f"--remove-port={port}/{proto}"], root=True)
        if result and result.returncode == 0:
            _run(["firewall-cmd", "--reload"], root=True)
            return True
    return False


# ── console ──────────────────────────────────────────────────────────────────

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
