"""
mc_firewall.py — Game-port rules for the active firewall of the platform
(ufw or firewalld on Linux, Windows Firewall on Windows).

Minecraft Java uses only TCP for the game port. The RCON port is NEVER opened
here: it is an admin interface that must stay reachable from 127.0.0.1 only,
and 'mc doctor' checks that no rule exposes it.

Rules are keyed on the port itself: renaming a server never leaves an
orphaned rule, only a port change does (handled via `old_port`). Only rules
created by MC Manager are ever removed.
"""
from mc_platform import plat


def detect():
    """Name of the active firewall, or None."""
    return plat.firewall_name()


def firewalld_available():
    """Kept for compatibility: True if any supported firewall is active."""
    return detect() is not None


def rule_name(port):
    return f"{port}/tcp"


def port_open(port, backend=None):
    """True/False: is this TCP port allowed by the active firewall? None when
    unknown (no firewall, or its rules cannot be read without root)."""
    return plat.firewall_port_open(port, "tcp")


def rule_exists(port_spec):
    """Kept for compatibility: port_spec is '<port>/tcp'."""
    return bool(port_open(str(port_spec).split("/")[0]))


def manual_command(port, name=None, backend=None):
    """The exact commands to paste if automatic rule creation fails."""
    return plat.firewall_manual_command(port, "tcp", name)


def add_rule(port, name=None, backend=None):
    """Open the TCP port. Returns (success, detail)."""
    return plat.firewall_allow(port, "tcp", name)


def remove_rule(port, backend=None, name=None):
    """Remove the rule MC Manager created for this port. A rule still needed
    by another registered server, or not created by MC Manager, is left
    alone. Returns True when a rule was removed."""
    return plat.firewall_remove(int(str(port).split("/")[0]), "tcp", name)


def ensure_game_port_rule(port, old_port=None, name=None):
    """
    Make sure the game port is open. Called on every deploy/add/configure and
    by 'mc config set port'. Idempotent:
    - a port change (old_port) removes the old MC Manager rule, never a manual
      rule and never one another registered server still uses;
    - an already open port is left alone;
    - otherwise the rule is added; on failure (not root, no firewall...) the
      manual command is returned instead.
    Never touches the RCON port — callers must never pass rcon_port here.
    Returns (ok, manual_command_or_None).
    """
    backend = detect()
    if backend is None:
        return False, manual_command(port, name)
    if old_port is not None and str(old_port) != str(port):
        remove_rule(old_port, backend, name)
    if port_open(port, backend):
        return True, None
    ok, _detail = add_rule(port, name, backend)
    return (True, None) if ok else (False, manual_command(port, name, backend))
