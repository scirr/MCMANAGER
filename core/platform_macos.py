import os
import plistlib
import re
import shlex
import shutil
import subprocess
import sys

from plat_posix import (  # noqa: F401
    atomic_replace, console_raw_mode, file_is_private, is_elevated, kill, launch_args_name,
    pick_file_dialog as _pick_file_dialog_posix, port_in_use, reap_children, resume,
    script_launch_args, secure_dir, secure_file, server_script_name, set_executable,
    setup_console, shell_quote, spawn_server, suspend, terminate, write_private_file,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

SERVICE_LABEL = "io.github.scirr.mcmanager"
LAUNCH_AGENTS_DIR = os.path.expanduser("~/Library/LaunchAgents")
SERVICE_FILE = os.path.join(LAUNCH_AGENTS_DIR, f"{SERVICE_LABEL}.plist")
LAUNCHER_PATHS = ("/usr/local/bin/mc", os.path.expanduser("~/bin/mc"))
SOCKETFILTERFW = "/usr/libexec/ApplicationFirewall/socketfilterfw"
PS_FIELDS = "pid=,ppid=,stat=,etime=,rss=,time=,command="


def _run(args, timeout=15):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                              env=dict(os.environ, LC_ALL="C"))
    except Exception:
        return None


# ── processes ────────────────────────────────────────────────────────────────

def _seconds(text):
    days = 0
    if "-" in text:
        d, _, text = text.partition("-")
        days = int(d)
    total = 0.0
    for part in text.split(":"):
        total = total * 60 + float(part)
    return days * 86400 + total


def parse_ps(text):
    rows = []
    for line in text.splitlines():
        parts = line.split(None, 6)
        if len(parts) < 6:
            continue
        try:
            rows.append({
                "pid": int(parts[0]), "ppid": int(parts[1]), "stat": parts[2],
                "uptime": int(_seconds(parts[3])), "rss": int(parts[4]),
                "cpu": _seconds(parts[5]), "command": parts[6] if len(parts) > 6 else "",
            })
        except ValueError:
            continue
    return rows


def parse_lsof_cwd(text):
    """{pid: directory} from 'lsof -Fpn' output limited to cwd descriptors."""
    out = {}
    pid = None
    for line in text.splitlines():
        if line.startswith("p") and line[1:].isdigit():
            pid = int(line[1:])
        elif line.startswith("n") and pid is not None:
            out[pid] = line[1:]
    return out


def parse_lsof_listen(text):
    """[(pid, command, [addresses])] from 'lsof -Fpcn' output."""
    found = []
    for line in text.splitlines():
        if line.startswith("p") and line[1:].isdigit():
            found.append((int(line[1:]), "", []))
        elif found and line.startswith("c"):
            found[-1] = (found[-1][0], line[1:], found[-1][2])
        elif found and line.startswith("n"):
            found[-1][2].append(line[1:])
    return found


def _ps_rows(*args):
    result = _run(["ps", "-o", PS_FIELDS, *args])
    return parse_ps(result.stdout) if result and result.returncode == 0 else []


def _ps_row(pid):
    rows = _ps_rows("-p", str(int(pid)))
    return rows[0] if rows else None


def _argv0_name(command):
    return os.path.basename(command.split(" -", 1)[0].strip()).lower()


def _is_java_row(row):
    return "java" in _argv0_name(row["command"])


def _cwds(pids):
    if not pids:
        return {}
    result = _run(["lsof", "-a", "-p", ",".join(str(p) for p in pids), "-d", "cwd", "-Fpn"], timeout=30)
    return parse_lsof_cwd(result.stdout) if result else {}


def _proc_cwd(pid):
    cwd = _cwds([pid]).get(pid)
    return os.path.realpath(cwd) if cwd else None


def _same_dir(a, b):
    return bool(a and b) and os.path.realpath(a) == os.path.realpath(b)


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
    row = _ps_row(pid)
    if row and row["stat"].startswith("Z"):
        return False
    if server_dir is None:
        return True
    if server_dir:
        cwd = _proc_cwd(pid)
        if cwd is not None:
            return _same_dir(cwd, server_dir)
    argv0 = _argv0_name(row["command"]) if row else ""
    if argv0 and not any(m in argv0 for m in ("java", "bash", "sh")):
        return False
    return True


def find_server_processes(server_dir):
    if not server_dir:
        return []
    target = os.path.realpath(server_dir)
    candidates = [r["pid"] for r in _ps_rows("-A")
                  if r["pid"] != os.getpid() and _is_java_row(r) and not r["stat"].startswith("Z")]
    cwds = _cwds(candidates)
    return sorted(p for p in candidates if cwds.get(p) and os.path.realpath(cwds[p]) == target)


def process_name(pid):
    result = _run(["ps", "-o", "comm=", "-p", str(int(pid))])
    if not result or result.returncode != 0 or not result.stdout.strip():
        return None
    return os.path.basename(result.stdout.strip())


def process_uptime(pid):
    row = _ps_row(pid)
    return row["uptime"] if row else None


def process_memory(pid):
    row = _ps_row(pid)
    return (row["rss"] if row else None), None


def process_cpu_seconds(pid):
    row = _ps_row(pid)
    return row["cpu"] if row else None


def set_affinity(pid, cpus):
    return False


def find_zombie_java():
    return [(r["pid"], r["ppid"]) for r in _ps_rows("-A")
            if r["stat"].startswith("Z") and _is_java_row(r)]


def os_name():
    return "macOS"


def cgroup_of(pid):
    return None


# ── ports ────────────────────────────────────────────────────────────────────

def _listeners(port):
    result = _run(["lsof", "-nP", f"-iTCP:{int(port)}", "-sTCP:LISTEN", "-Fpcn"], timeout=30)
    if not result or not result.stdout:
        return []
    return parse_lsof_listen(result.stdout)


def listens_on_all_interfaces(port):
    try:
        listeners = _listeners(port)
    except Exception:
        return None
    names = [n for _pid, _cmd, addrs in listeners for n in addrs]
    if not names:
        return None
    return any(n.startswith(("*:", "[::]:", "0.0.0.0:")) for n in names)


def port_listener(port):
    if not port or not port_in_use(port):
        return None
    listeners = _listeners(port)
    if not listeners:
        return (None, None)
    pid, cmd, _ = listeners[0]
    return (pid, cmd or process_name(pid) or "?")


# ── user, files, java ────────────────────────────────────────────────────────

def current_user():
    import getpass
    return os.environ.get("SUDO_USER") or os.environ.get("USER") or getpass.getuser()


def data_dir():
    return os.path.expanduser("~/Library/Application Support/MCManager/Servers")


def cache_dir():
    return os.path.expanduser("~/Library/Caches/MCManager")


def open_folder(path):
    subprocess.Popen(["open", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def default_editor():
    value = os.environ.get("VISUAL") or os.environ.get("EDITOR")
    return shlex.split(value) if value else ["open", "-t"]


def install_launcher():
    python_exe = sys.executable or "python3"
    content = f'#!/bin/sh\nexec "{python_exe}" "{BASE_DIR}/mc_cli.py" "$@"\n'
    launcher_path = os.path.join(BASE_DIR, "mc")
    with open(launcher_path, "w", encoding="utf-8") as f:
        f.write(content)
    set_executable(launcher_path)
    for target in LAUNCHER_PATHS:
        try:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copy(launcher_path, target)
            set_executable(target)
            return True, target
        except OSError:
            continue
    return False, f"permission:{launcher_path}:{LAUNCHER_PATHS[0]}"


def pick_file_dialog():
    script = 'POSIX path of (choose file of type {"public.image"} with prompt "Select server icon")'
    result = _run(["osascript", "-e", script], timeout=300)
    if result and result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    if result is not None and "User canceled" in (result.stderr or ""):
        return None
    return _pick_file_dialog_posix()


def java_search_paths():
    return [
        "/Library/Java/JavaVirtualMachines/*/Contents/Home/bin/java",
        os.path.expanduser("~/Library/Java/JavaVirtualMachines/*/Contents/Home/bin/java"),
        "/opt/homebrew/opt/openjdk*/bin/java",
        "/usr/local/opt/openjdk*/bin/java",
    ]


def java_exe_name():
    return "Contents/Home/bin/java"


def java_archive_kind():
    return "tar.gz"


def adoptium_os():
    return "mac"


# ── service (launchd) ────────────────────────────────────────────────────────

def _domain():
    return f"gui/{os.getuid()}"


def _target():
    return f"{_domain()}/{SERVICE_LABEL}"


def _launchctl(*args):
    return _run(["launchctl", *args], timeout=30)


def parse_launchctl_print(text):
    info = {}
    for line in text.splitlines():
        m = re.match(r"^\t(state|pid) = (\S+)\s*$", line)
        if m and m.group(1) not in info:
            info[m.group(1)] = m.group(2)
    return info


def _loaded():
    result = _launchctl("print", _target())
    if not result or result.returncode != 0:
        return None
    return parse_launchctl_print(result.stdout or "")


def service_installed():
    """None when launchctl is not available at all."""
    if not shutil.which("launchctl"):
        return None
    return os.path.isfile(SERVICE_FILE)


def service_running():
    info = _loaded()
    return bool(info) and info.get("state") == "running"


def _classify(result):
    detail = ((result.stdout or "") + (result.stderr or "")).strip()
    low = detail.lower()
    if "could not find service" in low or "no such file" in low:
        return "not_installed", detail
    if "not privileged" in low or "operation not permitted" in low or "permission denied" in low:
        return "no_permission", detail
    return "error", f"{result.returncode}|{detail}"


def service_control(action):
    if not os.path.isfile(SERVICE_FILE):
        return "not_installed", ""
    loaded = _loaded() is not None
    if action == "stop":
        if not loaded:
            return "ok", ""
        result = _launchctl("bootout", _target())
    elif action == "restart" and loaded:
        result = _launchctl("kickstart", "-k", _target())
    elif action == "start" and loaded:
        result = _launchctl("kickstart", _target())
    else:
        result = _launchctl("bootstrap", _domain(), SERVICE_FILE)
    if result is None:
        return "error", "launchctl"
    if result.returncode == 0:
        return "ok", ""
    return _classify(result)


def _service_plist():
    python_exe = sys.executable or "/usr/bin/python3"
    env = {"PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"}
    shared = os.environ.get("MCMANAGER_DATA_DIR", "").strip()
    if shared:
        env["MCMANAGER_DATA_DIR"] = shared
    logs = os.path.join(BASE_DIR, "logs")
    return {
        "Label": SERVICE_LABEL,
        "ProgramArguments": [python_exe, os.path.join(BASE_DIR, "mc_daemon.py")],
        "WorkingDirectory": BASE_DIR,
        "EnvironmentVariables": env,
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 10,
        "AbandonProcessGroup": True,
        "StandardOutPath": os.path.join(logs, "launchd.log"),
        "StandardErrorPath": os.path.join(logs, "launchd.log"),
    }


def _service_plist_bytes():
    return plistlib.dumps(_service_plist())


def service_unit_drift():
    try:
        with open(SERVICE_FILE, "rb") as f:
            installed = plistlib.load(f)
    except Exception:
        return "missing", []
    expected = _service_plist()
    diffs = []
    for key in ("WorkingDirectory", "RunAtLoad", "KeepAlive", "AbandonProcessGroup", "ThrottleInterval"):
        if installed.get(key) != expected[key]:
            diffs.append((key, installed.get(key), expected[key]))
    args = installed.get("ProgramArguments") or []
    if not args or args[-1] != expected["ProgramArguments"][-1]:
        diffs.append(("ProgramArguments", args[-1] if args else None, expected["ProgramArguments"][-1]))
    return ("outdated" if diffs else "ok"), diffs


def service_install(user=None):
    if os.getuid() == 0:
        return False, "run without sudo: the service is a per-user LaunchAgent"
    try:
        os.makedirs(LAUNCH_AGENTS_DIR, exist_ok=True)
        os.makedirs(os.path.join(BASE_DIR, "logs"), exist_ok=True)
        with open(SERVICE_FILE, "wb") as f:
            f.write(_service_plist_bytes())
        os.chmod(SERVICE_FILE, 0o644)
    except OSError as e:
        return False, str(e)
    if _loaded() is not None:
        _launchctl("bootout", _target())
    result = _launchctl("bootstrap", _domain(), SERVICE_FILE)
    if result is None:
        return False, "launchctl"
    if result.returncode == 0:
        return True, ""
    return False, (result.stderr or result.stdout or "").strip()


# ── firewall (Application Firewall) ──────────────────────────────────────────
# The macOS firewall filters per application, never per port: there is nothing
# to open for a game port, so rules are left to the user.

def firewall_name():
    return "socketfilterfw" if os.path.exists(SOCKETFILTERFW) else None


def firewall_port_open(port, proto="tcp"):
    return None


def firewall_manual_command(port, proto, label):
    return (f"sudo {SOCKETFILTERFW} --add \"$(command -v java)\" "
            f"&& sudo {SOCKETFILTERFW} --unblockapp \"$(command -v java)\"")


def firewall_allow(port, proto, label):
    return False, "manual"


def firewall_remove(port, proto, label):
    return False
