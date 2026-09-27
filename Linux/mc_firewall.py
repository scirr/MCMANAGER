"""
mc_firewall.py — Game-port rules for the active firewall: ufw (Debian,
Ubuntu) or firewalld (Fedora, RHEL), detected in that order.

Minecraft Java uses only TCP for the game port. The RCON port is NEVER opened
here: it is an admin interface that must stay reachable from 127.0.0.1 only,
and 'mc doctor' checks that no rule exposes it.

Rules are keyed on the port itself: renaming a server never leaves an
orphaned rule, only a port change does (handled via `old_port`). ufw rules
carry the comment "MC Manager <server>".
"""
import os
import re
import shutil
import subprocess


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


# ── detection ────────────────────────────────────────────────────────────────

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


def detect():
    """'ufw', 'firewalld' or None."""
    if _ufw_enabled():
        return "ufw"
    if _firewalld_running():
        return "firewalld"
    return None


def firewalld_available():
    """Kept for compatibility: True if any supported firewall is active."""
    return detect() is not None


# ── ufw ──────────────────────────────────────────────────────────────────────

def _ufw_port_matches(target, port):
    """Does a ufw 'To' column (e.g. '25565', '25565/tcp', '25560:25570/tcp')
    cover this TCP port?"""
    spec, _, proto = target.partition("/")
    if proto and proto != "tcp":
        return False
    if ":" in spec:
        lo, _, hi = spec.partition(":")
        return lo.isdigit() and hi.isdigit() and int(lo) <= int(port) <= int(hi)
    return spec.isdigit() and int(spec) == int(port)


def parse_ufw_status(text, port):
    """True if 'ufw status' output has an ALLOW rule covering the TCP port,
    False if not, None if ufw is inactive or the output is not recognised."""
    if "Status: active" not in text:
        return None
    for line in text.splitlines():
        m = re.match(r"^(\S+)(?: \(v6\))?\s+(ALLOW|LIMIT)(?: IN)?\s", line)
        if m and _ufw_port_matches(m.group(1), port):
            return True
    return False


def _ufw_status():
    result = _run(["ufw", "status"], root=True)
    if not result or result.returncode != 0:
        return None
    return result.stdout or ""


# ── firewalld ────────────────────────────────────────────────────────────────

def _firewalld_query(port):
    result = _run(["firewall-cmd", "--permanent", f"--query-port={port}/tcp"])
    if not result:
        return None
    if "yes" in (result.stdout or "").lower():
        return True
    if "no" in (result.stdout or "").lower():
        return False
    return None


# ── public API ───────────────────────────────────────────────────────────────

def rule_name(port):
    return f"{port}/tcp"


def port_open(port, backend=None):
    """True/False: is this TCP port allowed by the active firewall? None when
    unknown (no firewall, or its rules cannot be read without root)."""
    backend = backend or detect()
    if backend == "ufw":
        status = _ufw_status()
        return None if status is None else parse_ufw_status(status, port)
    if backend == "firewalld":
        return _firewalld_query(port)
    return None


def rule_exists(port_spec):
    """Kept for compatibility: port_spec is '<port>/tcp'."""
    return bool(port_open(str(port_spec).split("/")[0]))


def manual_command(port, name=None, backend=None):
    """The exact commands to paste if automatic rule creation fails."""
    backend = backend or detect()
    if backend == "ufw" or (backend is None and shutil.which("ufw")):
        comment = f" comment 'MC Manager {name}'" if name else ""
        return f"sudo ufw allow {port}/tcp{comment}"
    return (f"sudo firewall-cmd --permanent --add-port={port}/tcp "
            f"&& sudo firewall-cmd --reload")


def add_rule(port, name=None, backend=None):
    """Open the TCP port. Returns (success, detail)."""
    backend = backend or detect()
    if backend == "ufw":
        args = ["ufw", "allow", f"{port}/tcp"]
        if name:
            args += ["comment", f"MC Manager {name}"]
        result = _run(args, root=True)
    elif backend == "firewalld":
        result = _run(["firewall-cmd", "--permanent", f"--add-port={port}/tcp"], root=True)
        if result and result.returncode == 0:
            result = _run(["firewall-cmd", "--reload"], root=True)
    else:
        return False, "no firewall"
    if not result:
        return False, "not run"
    return result.returncode == 0, (result.stdout or result.stderr or "").strip()


def remove_rule(port, backend=None):
    backend = backend or detect()
    port = str(port).split("/")[0]
    if backend == "ufw":
        _run(["ufw", "delete", "allow", f"{port}/tcp"], root=True)
    elif backend == "firewalld":
        result = _run(["firewall-cmd", "--permanent", f"--remove-port={port}/tcp"], root=True)
        if result and result.returncode == 0:
            _run(["firewall-cmd", "--reload"], root=True)


def ensure_game_port_rule(port, old_port=None, name=None):
    """
    Make sure the game port is open. Called on every deploy/add/configure and
    by 'mc config set port'. Idempotent:
    - a port change (old_port) removes the old rule, never leaving one behind;
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
        remove_rule(old_port, backend)
    if port_open(port, backend):
        return True, None
    ok, _detail = add_rule(port, name, backend)
    return (True, None) if ok else (False, manual_command(port, name, backend))
