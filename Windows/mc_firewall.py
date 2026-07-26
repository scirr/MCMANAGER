"""
mc_firewall.py — Windows firewall rule for the game port (TCP only).

Minecraft Java uses only TCP for the game port (no vanilla UDP component —
Bedrock/UDP is a separate product, out of scope). The RCON port is NEVER
exposed here: it is an admin interface that must remain accessible only
locally (127.0.0.1).

The rule is named by port only (not server name): more robust for idempotence
— renaming a server never leaves an orphaned rule, only a port change does
(managed via `old_port`).
"""
import subprocess

RULE_PREFIX = "MCManager"


def rule_name(port):
    return f"{RULE_PREFIX} - Port {port}"


def rule_exists(name):
    """Check whether the named netsh rule exists.
    Handles both English ('No rules match') and French ('Aucune règle') Windows."""
    try:
        result = subprocess.run(
            ["netsh", "advfirewall", "firewall", "show", "rule", f"name={name}"],
            capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW
        )
    except FileNotFoundError:
        return False
    if result.returncode != 0:
        return False
    return "No rules match" not in result.stdout and "Aucune règle" not in result.stdout


def remove_rule(name):
    try:
        subprocess.run(
            ["netsh", "advfirewall", "firewall", "delete", "rule", f"name={name}"],
            capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW
        )
    except FileNotFoundError:
        pass


def add_rule(name, port):
    """Add an inbound TCP rule for this port. Returns (success, detail)."""
    result = subprocess.run(
        ["netsh", "advfirewall", "firewall", "add", "rule",
         f"name={name}", "dir=in", "action=allow", "protocol=TCP",
         f"localport={port}"],
        capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW
    )
    return result.returncode == 0, (result.stdout or result.stderr)


def manual_command(port):
    """Return the exact netsh command to paste into an admin terminal if
    automatic rule creation fails (non-elevated terminal, GPO, etc.)."""
    return (f'netsh advfirewall firewall add rule name="{rule_name(port)}" '
            f'dir=in action=allow protocol=TCP localport={port}')


def ensure_game_port_rule(port, old_port=None):
    """
    Ensure a firewall rule exists for the game port. Called from
    mc_config.ensure_provisioning on every deploy/add/configure.
    Idempotent:
    - if `old_port` is given and differs from `port`, the old rule is removed
      (a port change via 'mc configure' must never leave an orphaned rule).
    - if the rule for the current port already exists, does nothing.
    - otherwise attempts to add it; on failure (non-admin terminal,
      netsh blocked/missing) returns the manual command to run instead.
    Never touches the RCON port — callers must never pass rcon_port here.
    """
    name = rule_name(port)
    if old_port is not None and old_port != port:
        remove_rule(rule_name(old_port))

    if rule_exists(name):
        return True, None

    try:
        ok, _detail = add_rule(name, port)
    except FileNotFoundError:
        return False, manual_command(port)

    if ok:
        return True, None
    return False, manual_command(port)
