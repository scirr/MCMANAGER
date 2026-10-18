import sys


class Unsupported(Exception):
    code = "unsupported_on_windows"


FUNCTIONS = (
    "find_server_processes", "process_alive", "process_name", "process_uptime",
    "process_memory", "process_cpu_seconds", "terminate", "kill", "suspend", "resume",
    "reap_children", "spawn_server", "set_affinity", "find_zombie_java",
    "server_script_name", "script_launch_args", "launch_args_name", "os_name",
    "port_in_use", "port_listener", "listens_on_all_interfaces",
    "service_installed", "service_running", "service_control", "service_install",
    "service_unit_drift",
    "firewall_name", "firewall_port_open", "firewall_allow", "firewall_remove",
    "firewall_manual_command",
    "secure_file", "secure_dir", "file_is_private", "write_private_file",
    "set_executable", "data_dir", "cache_dir", "open_folder", "default_editor",
    "install_launcher", "atomic_replace", "is_elevated", "current_user",
    "java_search_paths", "java_exe_name", "java_archive_kind", "adoptium_os",
    "console_raw_mode", "pick_file_dialog", "shell_quote", "cgroup_of", "setup_console",
)


def missing(module):
    return [name for name in FUNCTIONS if not callable(getattr(module, name, None))]


def _load():
    if sys.platform == "win32":
        import platform_windows as impl
    else:
        import platform_linux as impl
    return impl


class _Lazy:
    _impl = None

    def __getattr__(self, name):
        if _Lazy._impl is None:
            _Lazy._impl = _load()
        return getattr(_Lazy._impl, name)


plat = _Lazy()


def use(module):
    _Lazy._impl = module
