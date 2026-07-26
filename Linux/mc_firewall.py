"""
mc_firewall.py — firewalld rule for the game port (TCP only).

Minecraft Java uses only TCP for the game port (no vanilla UDP component —
Bedrock/UDP is a separate product, out of scope). The RCON port is NEVER
exposed here: it is an admin interface that must remain accessible only
locally (127.0.0.1).

The rule is the port itself (e.g. '25565/tcp' in the permanent firewalld
config): more robust for idempotence — renaming a server never leaves an
orphaned rule, only a port change does (managed via `old_port`).
"""
import shutil
import subprocess


def rule_name(port):
    return f"{port}/tcp"


def _run(args):
    return subprocess.run(args, capture_output=True, text=True, timeout=15)


def firewalld_available():
    return shutil.which("firewall-cmd") is not None


def rule_exists(port_spec):
    """Check whether the permanent firewalld config already opens this port."""
    if not firewalld_available():
        return False
    try:
        result = _run(["firewall-cmd", "--permanent", f"--query-port={port_spec}"])
    except Exception:
        return False
    return result.returncode == 0 and "yes" in result.stdout.lower()


def remove_rule(port_spec):
    if not firewalld_available():
        return
    try:
        _run(["firewall-cmd", "--permanent", f"--remove-port={port_spec}"])
        _run(["firewall-cmd", "--reload"])
    except Exception:
        pass


def add_rule(port_spec):
    """Open this port permanently and reload. Returns (success, detail)."""
    result = _run(["firewall-cmd", "--permanent", f"--add-port={port_spec}"])
    if result.returncode != 0:
        return False, (result.stdout or result.stderr)
    reload_result = _run(["firewall-cmd", "--reload"])
    if reload_result.returncode != 0:
        return False, (reload_result.stdout or reload_result.stderr)
    return True, (result.stdout or result.stderr)


def manual_command(port):
    """Return the exact firewall-cmd commands to paste into a terminal if
    automatic rule creation fails (non-root, firewalld inactive, etc.)."""
    return (f"sudo firewall-cmd --permanent --add-port={port}/tcp "
            f"&& sudo firewall-cmd --reload")


def ensure_game_port_rule(port, old_port=None):
    """
    Ensure a firewalld rule exists for the game port. Called from
    mc_config.ensure_provisioning on every deploy/add/configure.
    Idempotent:
    - if `old_port` is given and differs from `port`, the old rule is removed
      (a port change via 'mc configure' must never leave an orphaned rule).
    - if the rule for the current port already exists, does nothing.
    - otherwise attempts to add it; on failure (non-root, firewalld
      inactive/missing) returns the manual command to run instead.
    Never touches the RCON port — callers must never pass rcon_port here.
    """
    spec = rule_name(port)
    if old_port is not None and old_port != port:
        remove_rule(rule_name(old_port))

    if rule_exists(spec):
        return True, None

    if not firewalld_available():
        return False, manual_command(port)

    try:
        ok, _detail = add_rule(spec)
    except Exception:
        return False, manual_command(port)

    if ok:
        return True, None
    return False, manual_command(port)
