from mc_platform import FUNCTIONS, Unsupported


class FakePlatform:
    def __init__(self, **results):
        self.calls = []
        self.results = dict(results)
        self.alive = set()
        self.files = {}

    def _rec(self, name, *args):
        self.calls.append((name, args))
        if name in self.results:
            value = self.results[name]
            return value(*args) if callable(value) else value
        return _DEFAULTS[name]

    def called(self, name):
        return [a for n, a in self.calls if n == name]

    def process_alive(self, pid, server_dir=None):
        self.calls.append(("process_alive", (pid, server_dir)))
        if "process_alive" in self.results:
            return self._rec_value("process_alive", pid, server_dir)
        return pid in self.alive

    def _rec_value(self, name, *args):
        value = self.results[name]
        return value(*args) if callable(value) else value

    def suspend(self, pid, tree=False):
        self.calls.append(("suspend", (pid,)))
        raise Unsupported("suspend")

    def resume(self, pid, tree=False):
        self.calls.append(("resume", (pid,)))
        raise Unsupported("resume")

    def write_private_file(self, path, text, mode=0o600):
        self.calls.append(("write_private_file", (path, text, mode)))
        self.files[path] = text

    def spawn_server(self, cmd, cwd, env=None, log=None):
        self.calls.append(("spawn_server", (cmd, cwd, env, log)))
        return _FakeProc()

    def console_raw_mode(self):
        self.calls.append(("console_raw_mode", ()))
        return _FakeConsole(self.results.get("keys", []))


class _FakeProc:
    pid = 4242

    def poll(self):
        return None


class _FakeConsole:
    def __init__(self, keys):
        self._keys = list(keys)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read_key(self, timeout=0.0):
        return self._keys.pop(0) if self._keys else None


_DEFAULTS = {
    "find_server_processes": [], "process_name": "java.exe", "process_uptime": 60.0,
    "process_memory": (1024, None), "process_cpu_seconds": 1.0, "terminate": True,
    "kill": True, "reap_children": None, "set_affinity": True, "find_zombie_java": [],
    "server_script_name": "run.sh", "script_launch_args": None,
    "port_in_use": False, "port_listener": None, "listens_on_all_interfaces": None,
    "service_installed": False, "service_running": False, "service_control": ("ok", ""),
    "service_install": (True, ""), "service_unit_drift": ("ok", []),
    "firewall_name": None, "firewall_port_open": None, "firewall_allow": (True, ""),
    "firewall_remove": True, "firewall_manual_command": "fw-allow",
    "secure_file": True, "secure_dir": True, "file_is_private": (True, ""),
    "set_executable": None, "data_dir": "/fake/data", "cache_dir": "/fake/cache",
    "open_folder": None, "default_editor": ["editor"], "install_launcher": (True, ""),
    "atomic_replace": None, "is_elevated": False, "current_user": "fake",
    "java_search_paths": [], "java_exe_name": "bin/java", "java_archive_kind": "tar.gz",
    "adoptium_os": "linux", "pick_file_dialog": None, "shell_quote": None,
    "cgroup_of": None, "setup_console": None,
}


def _method(name):
    def call(self, *args, **kwargs):
        if name == "script_launch_args":
            self.calls.append((name, args))
            return ["sh", args[0], "nogui"]
        if name == "shell_quote":
            self.calls.append((name, args))
            return "'" + args[0] + "'"
        return self._rec(name, *args)
    call.__name__ = name
    return call


for _name in FUNCTIONS:
    if not hasattr(FakePlatform, _name):
        setattr(FakePlatform, _name, _method(_name))
