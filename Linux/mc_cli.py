#!/usr/bin/env python3
import argparse
import json
import os
import sys
import socket
import logging

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(BASE_DIR)

import mc_setup
import mc_config
import mc_core
import mc_deploy
import mc_image
import mc_servers
import mc_doctor
import mc_lang
import mc_update
import mc_api
from mc_lang import T, VERSION

# Exit codes (documented in README_Linux.md — scripts rely on them).
EXIT_OK = 0          # success, or the requested state already holds
EXIT_ERROR = 1       # the command failed
EXIT_USAGE = 2       # invalid command line (argparse)
EXIT_NOT_FOUND = 3   # no server configured, unknown target, folder missing
EXIT_INTERRUPTED = 130

_failed = False

def print_res(success, msg):
    """Print a result line. A failure marks the command as failed (exit 1)."""
    global _failed
    if not success:
        _failed = True
    color = "\033[92m[OK]\033[0m" if success else "\033[93m[!]\033[0m"
    print(f"{color} {msg}")

def print_info(msg):
    print(f"\033[90m[i]\033[0m {msg}")

def print_target(name):
    """'Target: <name>' hint when the active server is used implicitly. On
    stderr, so a command's own output (rcon, players...) stays clean."""
    info = mc_servers.list_servers().get(name, {})
    print(f"\033[90m[i]\033[0m {T['target_info'].format(name=name, sid=info.get('id', '?'))}", file=sys.stderr)

def print_json(obj):
    print(json.dumps(obj, indent=2, ensure_ascii=False))

def resolve_for_json(target):
    """resolve_target with its human messages sent to stderr; returns
    (name, dossier) or None after printing a JSON error on stdout."""
    import contextlib
    with contextlib.redirect_stdout(sys.stderr):
        resolved = mc_servers.resolve_target(target)
    if not resolved:
        print_json({"schema": mc_api.SCHEMA_VERSION,
                    "error": {"code": "not_found", "target": target}})
    return resolved

def save_config(config):
    mc_config.save_config(config)

def rcon_console(config):
    import time
    import threading
    import select
    import termios
    import tty

    if not mc_core.is_server_running(config):
        print_res(False, T["console_offline"])
        return

    host = "127.0.0.1"
    port = config.get("rcon_port", mc_core.DEFAULT_RCON_PORT)
    password = config.get("mcrcon_pass", "minecraft")

    sock = None
    rcon_ok, sock_or_msg = mc_core.rcon_handshake(host, port, password, ping_only=False)
    if rcon_ok:
        sock = sock_or_msg
        sock.settimeout(2)

    dossier = config.get("dossier_serveur", "")
    log_file = os.path.join(dossier, "logs", "latest.log")

    # Show last 20 lines of server log on entry
    if os.path.exists(log_file):
        with open(log_file, 'r', encoding='utf-8', errors='replace') as f:
            recent = f.readlines()[-20:]
        for line in recent:
            print(f"\033[90m{line.rstrip()}\033[0m")
        print()

    if rcon_ok:
        print(f"\033[92m{T['console_connected']}\033[0m")
        print(f"\033[90m{T['console_hint']}\033[0m")
    else:
        print(f"\033[93m[!]\033[0m {T['console_rcon_error'].format(msg=sock_or_msg)}")
        print(f"\033[90m{T['console_log_only']}\033[0m")
    print()

    stop_event = threading.Event()
    lock = threading.Lock()
    typed_ref = ['']

    def tail_log():
        if not os.path.exists(log_file):
            return
        with open(log_file, 'r', encoding='utf-8', errors='replace') as f:
            f.seek(0, 2)
            while not stop_event.is_set():
                line = f.readline()
                if line:
                    with lock:
                        typed = typed_ref[0]
                        erase_len = len(typed) + 3
                        print(f"\r{' ' * erase_len}\r\033[90m{line.rstrip()}\033[0m")
                        print(f"\033[96m>\033[0m {typed}", end='', flush=True)
                else:
                    time.sleep(0.1)

    log_thread = threading.Thread(target=tail_log, daemon=True)
    log_thread.start()

    print(f"\033[96m>\033[0m ", end='', flush=True)

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        while True:
            readable, _, _ = select.select([sys.stdin], [], [], 0.05)
            if not readable:
                continue
            ch = sys.stdin.read(1)
            if ch in ('\r', '\n'):
                with lock:
                    cmd = typed_ref[0].strip()
                    typed_ref[0] = ''
                print()
                if cmd.lower() in ('exit', 'quit', 'q'):
                    print(T["console_disconnect"])
                    break
                if cmd and sock:
                    try:
                        response = mc_core.rcon_command(sock, cmd)
                        if response:
                            print(f"\033[90m{response}\033[0m")
                    except socket.timeout:
                        pass
                    except Exception:
                        pass
                print(f"\033[96m>\033[0m ", end='', flush=True)
            elif ch == '\x1b':  # escape sequence (arrows, F-keys) — discard it
                while select.select([sys.stdin], [], [], 0.005)[0]:
                    sys.stdin.read(1)
            elif ch in ('\x7f', '\x08'):  # Backspace
                with lock:
                    if typed_ref[0]:
                        typed_ref[0] = typed_ref[0][:-1]
                        print('\b \b', end='', flush=True)
            elif ch and ord(ch) >= 32:  # printable
                with lock:
                    typed_ref[0] += ch
                    print(ch, end='', flush=True)
    except KeyboardInterrupt:
        print(f"\n{T['console_disconnect']}")
    except Exception as e:
        print_res(False, T["console_error"].format(e=e))
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        stop_event.set()
        if sock:
            try: sock.close()
            except: pass

# ==========================================
# DASHBOARD
# ==========================================

def _box(title, marker, field_lines):
    width = max([len(title) + (len(marker) + 2 if marker else 0)] + [len(l) for l in field_lines] + [40])
    top = "+" + "-" * (width + 2) + "+"
    if marker:
        header = title + marker.rjust(width - len(title))
    else:
        header = title
    out = [top, f"| {header.ljust(width)} |"]
    for l in field_lines:
        out.append(f"| {l.ljust(width)} |")
    out.append(top)
    return "\n".join(out)

_FIELD_KEYS = ("field_status", "field_mode", "field_version", "field_dir", "field_port",
               "field_ram", "field_uptime", "field_players", "field_cgroup", "field_backup")

def _field(key, value):
    width = max(len(T[k]) for k in _FIELD_KEYS)
    return f"{T[key].ljust(width)} : {value}"

def render_server_box(name, info, active_name):
    dossier = info.get("dossier_serveur", "")
    server_id = info.get("id", "?")
    title = f"[{server_id}] {name}"
    marker = T["active_marker"] if name == active_name else ""

    if not os.path.exists(dossier):
        field_lines = [
            _field('field_status', T['dir_missing']),
            _field('field_dir', dossier),
        ]
        return _box(title, marker, field_lines)

    try:
        config = mc_config.load_config(dossier)
    except mc_servers.DataFileError as e:
        # One unreadable config.json must only affect its own box.
        field_lines = [
            _field('field_status', T['status_config_unreadable']),
            _field('field_dir', dossier),
        ]
        return _box(title, marker, field_lines) + "\n" + f"  \033[91m{e.detail}\033[0m\n  \033[90m-> {T['data_file_fix'].format(path=e.path)}\033[0m"
    config["dossier_serveur"] = dossier

    snap = mc_api.server_snapshot(name, info, active_name)
    state = snap.get("state")
    pid = snap.get("pid")
    if state == "running":
        statut = T["status_online"].format(pid=pid) if pid else T["status_online_nopid"]
    elif state == "starting":
        statut = T["state_starting"].format(pid=pid or "?")
    else:
        statut = T[f"state_{state.replace('-', '_')}"]
        holder = snap.get("port_holder")
        if holder and holder.get("pid"):
            statut += " — " + T["status_port_held"].format(port=snap.get("port"), prog=holder["program"], pid=holder["pid"])
    if snap.get("frozen"):
        statut += " — " + T["state_frozen"]

    mode = mc_core.effective_mode(config)
    if mode == "schedule":
        ho = int(config.get("heure_ouverture", 20))
        mo = int(config.get("minute_ouverture", 0))
        hf = int(config.get("heure_fermeture", 3))
        mf = int(config.get("minute_fermeture", 0))
        mode_label = T["mode_sched_hours"].format(oh=ho, om=mo, ch=hf, cm=mf)
    elif mode == "maintenance":
        was = T["mode_always_on"] if config.get("always_on", 1) == 1 else T["mode_schedule"]
        if state == "sleeping":
            mode_label = T["mode_sleep_was"].format(was=was)
        else:
            mode_label = T["mode_maint_was"].format(was=was)
    else:
        mode_label = T["mode_always_on"]

    loader, version = mc_core.guess_loader_and_version(config)
    version_label = version or "?"
    if loader:
        version_label += f" ({loader})"

    port = config.get("port", info.get("port", "?"))

    field_lines = [
        _field('field_status', statut),
        _field('field_mode', mode_label),
        _field('field_version', version_label),
        _field('field_dir', dossier),
        _field('field_port', port),
    ]
    if state in ("running", "starting"):
        if snap.get("rss_kb"):
            if snap["rss_kb"] >= 1048576:
                ram = T["ram_value"].format(gb=snap["rss_kb"] / 1048576)
            else:
                ram = T["ram_value_mb"].format(mb=snap["rss_kb"] // 1024)
            if snap.get("swap_kb"):
                ram += " " + T["ram_swap"].format(mb=snap["swap_kb"] // 1024)
            field_lines.append(_field('field_ram', ram))
        if snap.get("uptime_s") is not None:
            field_lines.append(_field('field_uptime', _human_duration(snap['uptime_s'])))
        if state == "running" and config.get("mcrcon_pass"):
            ok, data = mc_api.query_players(config)
            if ok:
                who = f" ({', '.join(data['players'])})" if data["players"] else ""
                field_lines.append(_field('field_players', f"{data['online']}/{data['max']}{who}"))
        cgroup = snap.get("cgroup") or ""
        if cgroup and mc_config.SERVICE_NAME not in cgroup and mc_config.check_service_unit()[0] != "missing":
            field_lines.append(_field('field_cgroup', T['cgroup_outside_short']))
    next_backup = _next_backup_label(config, state)
    if next_backup:
        field_lines.append(_field('field_backup', next_backup))
    return _box(title, marker, field_lines)

def _human_duration(seconds):
    days, rem = divmod(int(seconds), 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return f"{days} j {hours} h" if mc_lang.current_language() == "fr" else f"{days}d {hours}h"
    if hours:
        return f"{hours} h {minutes:02d}" if mc_lang.current_language() == "fr" else f"{hours}h{minutes:02d}"
    return f"{minutes} min"

def _next_backup_label(config, state):
    """When the daemon will next back this server up, or None."""
    mode = mc_core.effective_mode(config)
    if mode == "maintenance":
        return None
    if mode == "always-on":
        import datetime
        return T["backup_next_at"].format(time="12:00" if datetime.datetime.now().hour < 12 else "00:00")
    _start, end = mc_core.schedule_minutes(config)
    return T["backup_next_close"].format(time="%02d:%02d" % divmod(end, 60))

def print_dashboard(target=None, with_cheatsheet=False):
    servers = mc_servers.list_servers()
    if not servers:
        print(f"\033[93m[!]\033[0m {T['no_server_dashboard']}")
        return EXIT_NOT_FOUND

    if target is not None:
        resolved = mc_servers.resolve_target(target)
        if not resolved:
            return EXIT_NOT_FOUND
        name, _ = resolved
        servers = {name: servers[name]}

    active_name = mc_servers.get_active_name()
    for name, info in servers.items():
        print(render_server_box(name, info, active_name))
        print()

    if with_cheatsheet:
        print(T["cheatsheet"])
    return EXIT_OK

# ==========================================
# LOGS
# ==========================================

def print_logs(target=None):
    log_file = os.path.join(BASE_DIR, "logs", "daemon.log")
    if not os.path.exists(log_file):
        print_res(False, T["no_log_file"])
        return

    with open(log_file, 'r', encoding='utf-8', errors='replace') as f:
        lines = f.readlines()

    if target is not None:
        resolved = mc_servers.resolve_target(target)
        if not resolved:
            return EXIT_NOT_FOUND
        name, _ = resolved
        prefix = f"[{name}]"
        lines = [l for l in lines if prefix in l]

    print("".join(lines[-30:]) or T["logs_nothing"])

# ==========================================
# LANGUAGE / HELP
# ==========================================

def prompt_language_if_unset():
    """On first launch (no language chosen yet), ask FR/EN interactively."""
    if mc_lang.is_language_set():
        return
    # Never prompt for the background service or in non-interactive contexts.
    if len(sys.argv) > 1 and sys.argv[1] == "daemon":
        return
    try:
        if not sys.stdin.isatty():
            return
    except Exception:
        return
    print(f"\033[96m{T['language_choose']}\033[0m")
    print("  1. Français")
    print("  2. English")
    while True:
        try:
            choice = input("> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return
        if choice in ("1", "fr", "français", "francais"):
            mc_lang.set_language("fr")
            break
        if choice in ("2", "en", "english", "anglais"):
            mc_lang.set_language("en")
            break
    print()

def show_update_notice():
    """Discreet, throttled, silent-on-failure 'update available' line."""
    try:
        mc_update.refresh_if_stale()
        latest = mc_update.get_cached_notice()
        if latest:
            print(f"\033[93m{T['update_available'].format(ver=latest)}\033[0m\n", file=sys.stderr)
    except Exception:
        pass

def print_categorized_help():
    tgt, pth, val = T["arg_target"], T["arg_path"], T["arg_value"]
    categories = [
        (T["help_cat_lifecycle"], [
            (f"start [{tgt}]", T["help_start"]),
            (f"stop [{tgt}] [--force]", T["help_stop"]),
            (f"stop [{tgt}] --reason <r> [--quiet]", T["help_stop_reason"]),
            (f"console [{tgt}]", T["help_console"]),
            (f"rcon \"<cmd>\" [{tgt}]", T["help_rcon"]),
            (f"players [{tgt}] [--json]", T["help_players"]),
            (f"backup [{tgt}]", T["help_backup"]),
            (f"freeze [{tgt}] [-- <cmd>]", T["help_freeze"]),
            (f"thaw [{tgt}]", T["help_thaw"]),
            (f"sleep enable|disable|status|wake [{tgt}] [--after 2h]", T["help_sleep"]),
            (f"sleep allow|deny <{T['arg_player']}> [{tgt}]", T["help_sleep_allow"]),
            (f"announce [{tgt}]", T["help_announce"]),
            (f"fingerprint [{tgt}]", T["help_fingerprint"]),
        ]),
        (T["help_cat_multi"], [
            (f"status [{tgt}] [--json]", T["help_status"]),
            ("active [--path|--json]", T["help_active"]),
            (f"use <{tgt}>", T["help_use"]),
            (f"switch <{tgt}> [--force]", T["help_switch"]),
            (f"remove <{tgt}>", T["help_remove"]),
            (f"open [{tgt}]", T["help_open"]),
        ]),
        (T["help_cat_config"], [
            ("deploy", T["help_deploy"]),
            (f"add [{pth}]", T["help_add"]),
            (f"configure [{tgt}]", T["help_configure"]),
            (f"config get|set <{T['arg_key']}> [<{val}>] [{tgt}]", T["help_config"]),
            (f"edit config|webhooks [{tgt}]", T["help_edit"]),
            (f"image add|rm [{tgt}]", T["help_image"]),
            (f"datapack list|enable|disable [<pack>] [{tgt}]", T["help_datapack"]),
            (f"mod list|add|remove [<mod>] [{tgt}]", T["help_mod"]),
            (f"schedule H M H M [{tgt}]", T["help_schedule"]),
            (f"mode <{val}> [{tgt}]", T["help_mode"]),
            (f"resume [{tgt}]", T["help_resume"]),
        ]),
        (T["help_cat_diag"], [
            (f"doctor [{tgt}]", T["help_doctor"]),
            (f"logs [{tgt}]", T["help_logs"]),
            ("daemon <run|start|stop|restart>", T["help_daemon"]),
        ]),
        (T["help_cat_general"], [
            ("update", T["help_update"]),
            ("version", T["help_version"]),
            ("language [fr|en]", T["help_language"]),
            ("help", T["help_help"]),
        ]),
    ]
    width = max(len(cmd) for _, cmds in categories for cmd, _ in cmds) + 2
    print(f"\033[1m\033[96mMC Manager\033[0m \033[90mv{VERSION}\033[0m")
    print(f"\033[90m{T['help_intro'].format(tgt=tgt)}\033[0m")
    for title, cmds in categories:
        print(f"\n\033[93m{title}\033[0m")
        for cmd, desc in cmds:
            print(f"  \033[96mmc {cmd.ljust(width)}\033[0m {desc}")
    print(f"\n\033[90m{T['help_footer']}\033[0m")

# ==========================================
# MAIN
# ==========================================

NEEDS_ACTIVE_RESOLUTION = {"configure", "start", "stop", "console", "backup", "mode", "schedule", "edit", "resume", "open", "announce", "fingerprint"}

def main():
    prompt_language_if_unset()

    # Only commands that actually launch the JVM need Java; verifying it for
    # everything (status, doctor, logs, image, mode…) would block them and even
    # make `doctor` — the tool meant to diagnose this — unusable when Java is missing.
    if len(sys.argv) > 1 and sys.argv[1] in ("start", "resume"):
        mc_setup.verify_and_install()

    mc_servers.migrate_legacy_single_server()

    parser = argparse.ArgumentParser(description="\033[96m=== MC Manager CLI ===\033[0m")
    parser.add_argument("--version", action="version", version=f"MC Manager v{VERSION}")
    subparsers = parser.add_subparsers(dest="action", title=T["cli_commands_title"], metavar="<command>")

    target_parser = argparse.ArgumentParser(add_help=False)
    target_parser.add_argument("target", nargs="?", default=None, help=T["cli_target_help"])

    subparsers.add_parser("help", help=T["help_help"])
    subparsers.add_parser("version", help=T["help_version"])
    p_lang = subparsers.add_parser("language", help=T["help_language"])
    p_lang.add_argument("lang", nargs="?", choices=["fr", "en"], default=None)
    subparsers.add_parser("update", help=T["help_update"])
    subparsers.add_parser("deploy", help=T["help_deploy"])
    p_add = subparsers.add_parser("add", help=T["help_add"])
    p_add.add_argument("path", nargs="?", default=None, help=T["help_add_path"])

    p_status = subparsers.add_parser("status", parents=[target_parser], help=T["help_status"])
    p_status.add_argument("--json", action="store_true", help=T["help_json"])

    p_active = subparsers.add_parser("active", help=T["help_active"])
    g_active = p_active.add_mutually_exclusive_group()
    g_active.add_argument("--path", action="store_true", help=T["help_active_path"])
    g_active.add_argument("--json", action="store_true", help=T["help_json"])

    p_players = subparsers.add_parser("players", parents=[target_parser], help=T["help_players"])
    p_players.add_argument("--json", action="store_true", help=T["help_json"])

    p_rcon = subparsers.add_parser("rcon", help=T["help_rcon"])
    p_rcon.add_argument("command", help=T["help_rcon_command"])
    p_rcon.add_argument("target", nargs="?", default=None, help=T["cli_target_help"])

    p_freeze = subparsers.add_parser("freeze", parents=[target_parser], help=T["help_freeze"])
    p_freeze.add_argument("--max", default=None, metavar="DURATION", help=T["help_freeze_max"])
    subparsers.add_parser("thaw", parents=[target_parser], help=T["help_thaw"])

    p_switch = subparsers.add_parser("switch", help=T["help_switch"])
    p_switch.add_argument("target", help=T["cli_target_help"])
    p_switch.add_argument("--force", action="store_true", help=T["help_switch_force"])
    p_switch.add_argument("--json", action="store_true", help=T["help_json"])

    p_sleep = subparsers.add_parser("sleep", help=T["help_sleep"])
    p_sleep.add_argument("sleep_action", choices=["enable", "disable", "status", "wake", "allow", "deny"])
    p_sleep.add_argument("args", nargs="*", help=T["help_sleep_args"])
    p_sleep.add_argument("--after", default=None, metavar="DURATION", help=T["help_sleep_after"])
    p_sleep.add_argument("--json", action="store_true", help=T["help_json"])

    p_dp = subparsers.add_parser("datapack", help=T["help_datapack"])
    p_dp.add_argument("dp_action", choices=["list", "enable", "disable"])
    p_dp.add_argument("args", nargs="*", help=T["help_datapack_args"])
    g_dp = p_dp.add_mutually_exclusive_group()
    g_dp.add_argument("--before", metavar="PACK")
    g_dp.add_argument("--after", metavar="PACK")
    g_dp.add_argument("--first", action="store_true")
    g_dp.add_argument("--last", action="store_true")
    p_dp.add_argument("--json", action="store_true", help=T["help_json"])

    p_mod = subparsers.add_parser("mod", help=T["help_mod"])
    p_mod.add_argument("mod_action", choices=["list", "add", "remove"])
    p_mod.add_argument("args", nargs="*", help=T["help_mod_args"])
    p_mod.add_argument("--server-only", action="store_true", help=T["help_mod_server_only"])
    p_mod.add_argument("--yes", action="store_true", help=T["help_mod_yes"])
    p_mod.add_argument("--json", action="store_true", help=T["help_json"])

    p_config = subparsers.add_parser("config", help=T["help_config"])
    p_config.add_argument("config_action", choices=["get", "set"])
    p_config.add_argument("key", nargs="?", default=None)
    p_config.add_argument("rest", nargs="*", help=T["help_config_rest"])

    p_use = subparsers.add_parser("use", help=T["help_use"])
    p_use.add_argument("target", help=T["help_use_target"])

    p_remove = subparsers.add_parser("remove", help=T["help_remove"])
    p_remove.add_argument("target", help=T["help_remove_target"])

    subparsers.add_parser("doctor", parents=[target_parser], help=T["help_doctor"])

    subparsers.add_parser("configure", parents=[target_parser], help=T["help_configure"])
    subparsers.add_parser("start", parents=[target_parser], help=T["help_start"])
    p_stop = subparsers.add_parser("stop", help=T["help_stop"])
    p_stop.add_argument("target", nargs="?", default=None, help=T["cli_target_help"])
    p_stop.add_argument("--force", "-f", action="store_true", help=T["help_stop_force"])
    p_stop.add_argument("--reason", choices=mc_api.STOP_REASONS, default=None, help=T["help_stop_reason_arg"])
    p_stop.add_argument("--quiet", "-q", action="store_true", help=T["help_stop_quiet"])
    subparsers.add_parser("console", parents=[target_parser], help=T["help_console"])
    subparsers.add_parser("backup", parents=[target_parser], help=T["help_backup"])
    subparsers.add_parser("open", parents=[target_parser], help=T["help_open"])
    subparsers.add_parser("resume", parents=[target_parser], help=T["help_resume"])
    subparsers.add_parser("announce", parents=[target_parser], help=T["help_announce"])
    subparsers.add_parser("fingerprint", parents=[target_parser], help=T["help_fingerprint"])
    subparsers.add_parser("logs", parents=[target_parser], help=T["help_logs"])

    p_mode = subparsers.add_parser("mode", help=T["help_mode"])
    p_mode.add_argument("value", choices=["schedule", "always-on", "maintenance"])
    p_mode.add_argument("target", nargs="?", default=None)

    p_schedule = subparsers.add_parser("schedule", help=T["help_schedule"])
    p_schedule.add_argument("open_h", type=int)
    p_schedule.add_argument("open_m", type=int)
    p_schedule.add_argument("close_h", type=int)
    p_schedule.add_argument("close_m", type=int)
    p_schedule.add_argument("target", nargs="?", default=None)

    p_edit = subparsers.add_parser("edit", help=T["help_edit"])
    p_edit.add_argument("what", choices=["config", "webhooks"])
    p_edit.add_argument("target", nargs="?", default=None)

    p_daemon = subparsers.add_parser("daemon", help=T["help_daemon"])
    p_daemon.add_argument("daemon_action", choices=["run", "start", "stop", "restart"])

    p_image = subparsers.add_parser("image", help=T["help_image"])
    image_subs = p_image.add_subparsers(dest="image_action", metavar="<action>")
    p_image_add = image_subs.add_parser("add", help=T["help_image_add"])
    p_image_add.add_argument("path", nargs="?", default=None, help=T["help_image_path"])
    p_image_add.add_argument("target", nargs="?", default=None)
    p_image_rm = image_subs.add_parser("rm", help=T["help_image_rm"])
    p_image_rm.add_argument("target", nargs="?", default=None)

    argv = sys.argv[1:]
    freeze_cmd = None
    if argv and argv[0] == "freeze" and "--" in argv:
        cut = argv.index("--")
        argv, freeze_cmd = argv[:cut], argv[cut + 1:]
    args = parser.parse_args(argv)

    if args.action not in ("daemon", "update") and not getattr(args, "json", False):
        show_update_notice()

    if args.action is None:
        return print_dashboard(with_cheatsheet=True)

    if args.action == "help":
        print_categorized_help()
        return

    if args.action == "version":
        print(f"MC Manager v{VERSION} (Linux)")
        return

    if args.action == "language":
        if args.lang is None:
            print_res(True, T["language_current"].format(lang=mc_lang.current_language()))
            print(f"\033[90m{T['language_usage']}\033[0m")
        else:
            mc_lang.set_language(args.lang)
            print_res(True, T["language_set"].format(lang=args.lang))
        return

    if args.action == "update":
        print_res(*mc_update.perform_update())
        return

    if args.action == "deploy":
        mc_deploy.run_deploy({})
        return

    if args.action == "add":
        mc_deploy.run_add({"dossier_serveur": args.path} if args.path else {})
        return

    if args.action == "status":
        if args.json:
            name = None
            if args.target is not None:
                resolved = resolve_for_json(args.target)
                if not resolved:
                    return EXIT_NOT_FOUND
                name = resolved[0]
            print_json(mc_api.status_document(name))
            return EXIT_OK
        return print_dashboard(args.target)

    if args.action == "active":
        registry = mc_servers.load_registry()
        name = registry.get("active")
        info = registry["servers"].get(name) if name else None
        if not info:
            if args.json:
                print_json({"schema": mc_api.SCHEMA_VERSION, "error": {"code": "no_active_server"}})
            else:
                print(f"\033[93m[!]\033[0m {T['no_active_short']}", file=sys.stderr)
            return EXIT_NOT_FOUND
        if args.json:
            print_json({"schema": mc_api.SCHEMA_VERSION, **mc_api.server_snapshot(name, info, name)})
        elif args.path:
            print(info.get("dossier_serveur", ""))
        else:
            print(name)
        return EXIT_OK

    if args.action == "players":
        return cmd_players(args)

    if args.action == "rcon":
        return cmd_rcon(args)

    if args.action == "config":
        return cmd_config(args)

    if args.action == "switch":
        return cmd_switch(args)

    if args.action == "sleep":
        return cmd_sleep(args)

    if args.action == "datapack":
        return cmd_datapack(args)

    if args.action == "mod":
        return cmd_mod(args)

    if args.action in ("freeze", "thaw"):
        return cmd_freeze_thaw(args, freeze_cmd)

    if args.action == "use":
        if mc_servers.set_active(args.target):
            info = mc_servers.list_servers().get(mc_servers.get_active_name(), {})
            print_res(True, T["set_active_ok"].format(name=mc_servers.get_active_name(), sid=info.get("id", "?")))
        else:
            print_res(False, T["server_not_found_use"].format(target=args.target))
            return EXIT_NOT_FOUND
        return

    if args.action == "remove":
        resolved = mc_servers.resolve_target(args.target, require_folder=False)
        if not resolved:
            return EXIT_NOT_FOUND
        name, dossier = resolved
        info = mc_servers.list_servers().get(name, {})
        print(f"\033[93m[!]\033[0m {T['deregister_warning'].format(name=name, sid=info.get('id', '?'))}")
        print(f"\033[90m[i]\033[0m {T['folder_preserved_info'].format(path=dossier)}")
        if not mc_deploy.ask_yn(T["confirm_deregister"], default=False):
            print_res(False, T["deregister_cancelled"])
            return
        ok, removed_name_or_msg, removed_dossier = mc_servers.remove_server(args.target)
        if ok:
            print_res(True, T["deregister_ok"].format(name=removed_name_or_msg))
            print(f"\033[90m[i]\033[0m {T['files_preserved'].format(path=removed_dossier)}")
            new_active = mc_servers.get_active_name()
            if new_active:
                print(f"\033[90m[i]\033[0m {T['new_active'].format(name=new_active)}")
            else:
                print(f"\033[90m[i]\033[0m {T['no_server_left']}")
        else:
            print_res(False, removed_name_or_msg)
        return

    if args.action == "image":
        image_action = getattr(args, "image_action", None)
        if not image_action:
            print_res(False, T["image_no_action"])
            return
        target = getattr(args, "target", None)
        resolved = mc_servers.resolve_target(target)
        if not resolved:
            return EXIT_NOT_FOUND
        active_name, dossier_serveur = resolved
        if target is None:
            print_target(active_name)
        if image_action == "add":
            src = args.path
            if not src:
                print(f"\033[90m[i]\033[0m {T['image_opening_dialog']}")
                src = mc_image.pick_file_dialog()
                if not src:
                    print_res(False, T["image_no_file_selected"])
                    return
            ok, detail = mc_image.set_icon(src, dossier_serveur)
            if ok:
                print_res(True, T["image_set_ok"].format(path=detail))
            elif detail == "pillow_missing":
                print_res(False, T["image_pillow_missing"])
            elif detail == "source_not_found":
                print_res(False, T["image_source_not_found"].format(path=src))
            else:
                print_res(False, T["image_error"].format(e=detail))
        elif image_action == "rm":
            ok, detail = mc_image.remove_icon(dossier_serveur)
            if ok:
                print_res(True, T["image_removed_ok"])
            else:
                print_res(False, T["image_not_found_icon"])
        return

    if args.action == "doctor":
        return mc_doctor.run_doctor(args.target)

    if args.action == "logs":
        return print_logs(args.target)

    if args.action == "daemon":
        return dispatch_daemon(args.daemon_action)

    # --- centralized resolution for server-targeting commands ---
    config = None
    dossier_serveur = None
    active_name = None
    if args.action in NEEDS_ACTIVE_RESOLUTION:
        target = getattr(args, "target", None)
        resolved = mc_servers.resolve_target(target)
        if not resolved:
            return EXIT_NOT_FOUND
        active_name, dossier_serveur = resolved
        if target is None:
            print_target(active_name)
        config = mc_config.load_config(dossier_serveur)
        config["dossier_serveur"] = dossier_serveur

    if args.action == "configure":
        mc_config.run_setup(active_name)

    elif args.action == "edit":
        import shlex
        import subprocess
        editor = shlex.split(os.environ.get("VISUAL") or os.environ.get("EDITOR") or "nano")
        path = mc_config.config_path(dossier_serveur) if args.what == "config" else mc_config.webhooks_path(dossier_serveur)
        try:
            subprocess.call(editor + [path])
        except FileNotFoundError:
            print_res(False, T["editor_not_found"].format(editor=editor[0]))

    elif args.action == "open":
        import subprocess
        subprocess.Popen(["xdg-open", dossier_serveur],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print_res(True, T["folder_opened"].format(path=dossier_serveur))

    elif args.action == "start":
        # 'mc start' only launches the server process; it must not touch the
        # maintenance flag. Leaving maintenance is 'mc resume' only. A server
        # can therefore be started manually while staying in maintenance (the
        # daemon keeps ignoring it, webhooks stay silent) until 'mc resume'.
        logging.basicConfig(level=logging.INFO, format="\033[90m[INFO]\033[0m %(message)s")
        res = mc_api.start(active_name, config)
        if res["code"] == "already_running":
            print_info(T["already_online"])          # desired state already holds: exit 0
        else:
            print_res(res["ok"], res.get("message") or render(res))
        if res["ok"] and res["code"] != "already_running":
            if res.get("outside_service"):
                print_info(T["start_outside_service"])
            print_info(T["start_console_hint"])

    elif args.action == "stop":
        # The JVM is waited for; the reason is recorded next to the
        # maintenance flag so 'mc status' can say "sleeping", "maintenance"...
        if mc_core.is_server_running(config) and not args.force:
            print_info(T["stop_waiting"])
        res = mc_api.stop(active_name, config, reason=args.reason, quiet=args.quiet, force=args.force)
        if res["code"] == "already_stopped":
            print_info(T["already_offline"])
        elif res["code"] == "killed":
            print_res(True, T["stop_forced"])
        elif res["ok"]:
            print_res(True, res.get("message") or T["stop_done"])
        else:
            print_res(False, res.get("message") or render(res))
        if res["ok"]:
            print_res(True, T["maintenance_activated"])

    elif args.action == "announce":
        ok, detail = mc_core.send_start_webhook(config)
        if ok:
            print_res(True, T["announce_ok"])
        else:
            print_res(False, T["announce_failed"].format(e=detail))

    elif args.action == "fingerprint":
        fp = config.get("cle_automodpack") or mc_core.get_automodpack_fingerprint(dossier_serveur)
        if fp:
            print_res(True, T["fingerprint_result"].format(fp=fp))
        else:
            print_res(False, T["fingerprint_missing"])

    elif args.action == "console":
        rcon_console(config)

    elif args.action == "backup":
        print_res(*mc_core.backup_server(config))

    elif args.action == "mode":
        setter = {
            "schedule":    mc_config.set_mode_schedule,
            "always-on":   mc_config.set_mode_always_on,
            "maintenance": mc_config.set_mode_maintenance,
        }[args.value]
        config = setter(config)
        save_config(config)
        mode_labels = {
            "schedule":    T["mode_schedule"],
            "always-on":   T["mode_always_on"],
            "maintenance": T["mode_maintenance"],
        }
        print_res(True, T["mode_set"].format(mode=mode_labels.get(args.value, args.value)))

    elif args.action == "resume":
        config = mc_config.resume_mode(config)
        save_config(config)
        mode_labels = {
            "schedule":  T["mode_schedule"],
            "always-on": T["mode_always_on"],
        }
        current_mode = mc_core.effective_mode(config)
        print_res(True, T["maintenance_disabled"].format(mode=mode_labels.get(current_mode, current_mode)))
        # Leaving maintenance hands the server back to the daemon, which will
        # bring it up on its own — say so, otherwise 'resume' looks like a
        # no-op and users chain a needless (and now refused) 'mc start'.
        if not mc_core.is_server_running(config):
            print(f"\033[90m[i]\033[0m {T['resume_restart_hint']}")

    elif args.action == "schedule":
        invalid = None
        if not (0 <= args.open_h <= 23):
            invalid = T["invalid_hour"].format(val=args.open_h)
        elif not (0 <= args.open_m <= 59):
            invalid = T["invalid_minute"].format(val=args.open_m)
        elif not (0 <= args.close_h <= 23):
            invalid = T["invalid_hour"].format(val=args.close_h)
        elif not (0 <= args.close_m <= 59):
            invalid = T["invalid_minute"].format(val=args.close_m)
        if invalid:
            print_res(False, invalid)
            return
        if (args.open_h, args.open_m) == (args.close_h, args.close_m):
            print_res(False, T["schedule_same_time"])
            return
        config["always_on"] = 0
        config["heure_ouverture"], config["minute_ouverture"] = args.open_h, args.open_m
        config["heure_fermeture"], config["minute_fermeture"] = args.close_h, args.close_m
        save_config(config)
        print_res(True, T["schedule_updated"])


# ==========================================
# MACHINE-FRIENDLY COMMANDS
# ==========================================

def _load_target_config(target, quiet_json=False):
    """Resolve a target and load its config. Returns (name, config) or None."""
    resolved = resolve_for_json(target) if quiet_json else mc_servers.resolve_target(target)
    if not resolved:
        return None
    name, dossier = resolved
    if target is None and not quiet_json:
        print_target(name)
    config = mc_config.load_config(dossier)
    config["dossier_serveur"] = dossier
    return name, config

def cmd_players(args):
    loaded = _load_target_config(args.target, quiet_json=args.json)
    if not loaded:
        return EXIT_NOT_FOUND
    name, config = loaded
    if not mc_core.is_server_running(config):
        if args.json:
            print_json({"schema": mc_api.SCHEMA_VERSION, "server": name, "online": 0, "max": None,
                        "players": [], "state": mc_api.server_state(config)})
            return EXIT_OK
        print_info(T["players_offline"])
        return EXIT_OK
    ok, data = mc_api.query_players(config)
    if not ok:
        if args.json:
            print_json({"schema": mc_api.SCHEMA_VERSION, "server": name,
                        "error": {"code": "rcon_failed", "detail": data}})
        else:
            print_res(False, T["players_failed"].format(detail=data))
        return EXIT_ERROR
    if args.json:
        print_json({"schema": mc_api.SCHEMA_VERSION, "server": name, **data})
    else:
        names = ", ".join(data["players"]) or "-"
        print(T["players_line"].format(online=data["online"], max=data["max"], names=names))
    return EXIT_OK

def cmd_rcon(args):
    loaded = _load_target_config(args.target)
    if not loaded:
        return EXIT_NOT_FOUND
    _name, config = loaded
    if not mc_core.is_server_running(config):
        print_res(False, T["console_offline"])
        return EXIT_ERROR
    ok, reply = mc_api.rcon_exec(config, args.command)
    if not ok:
        print_res(False, T["rcon_failed"].format(detail=reply))
        return EXIT_ERROR
    if reply:
        print(reply)
    return EXIT_OK

def cmd_freeze_thaw(args, command=None):
    loaded = _load_target_config(args.target)
    if not loaded:
        return EXIT_NOT_FOUND
    name, config = loaded
    if args.action == "thaw":
        ok, code = mc_api.thaw(config)
        print_res(ok, T[f"thaw_{code}"])
        return EXIT_OK if ok else EXIT_ERROR

    try:
        max_s = mc_api.parse_duration(args.max) if args.max else mc_api.DEFAULT_FREEZE_MAX
    except ValueError:
        print_res(False, T["invalid_duration"].format(val=args.max))
        return EXIT_USAGE
    ok, code = mc_api.freeze(config, max_s)
    if not ok:
        print_res(False, T[f"freeze_{code}"])
        return EXIT_ERROR
    if code == "offline":
        print_info(T["freeze_offline"])
    else:
        print_res(True, T["freeze_frozen"].format(mins=max(1, max_s // 60)))
    if not command:
        return EXIT_OK

    # 'mc freeze -- <cmd>': run the command, then ALWAYS thaw — even if the
    # command fails or is interrupted — and exit with the command's own code.
    import subprocess
    rc = EXIT_ERROR
    try:
        rc = subprocess.call(command)
    except FileNotFoundError:
        print_res(False, T["freeze_cmd_not_found"].format(cmd=command[0]))
    except KeyboardInterrupt:
        rc = EXIT_INTERRUPTED
    finally:
        ok, code = mc_api.thaw(config)
        print_res(ok, T[f"thaw_{code}"])
    return rc

def cmd_config(args):
    rest = list(args.rest or [])
    if args.config_action == "get":
        target = rest[0] if rest else None
        loaded = _load_target_config(target, quiet_json=True)
        if not loaded:
            return EXIT_NOT_FOUND
        _name, config = loaded
        if args.key is None:
            config.pop("dossier_serveur", None)
            print_json(config)
            return EXIT_OK
        if args.key not in config:
            print(f"\033[93m[!]\033[0m {T['config_key_unset'].format(key=args.key)}", file=sys.stderr)
            return EXIT_ERROR
        value = config[args.key]
        print(json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value)
        return EXIT_OK

    # set
    if args.key is None or not rest:
        print_res(False, T["config_set_usage"])
        return EXIT_USAGE
    value, target = rest[0], (rest[1] if len(rest) > 1 else None)
    loaded = _load_target_config(target)
    if not loaded:
        return EXIT_NOT_FOUND
    name, config = loaded
    status, detail = mc_config.set_value(config, name, args.key, value)
    if status != "ok":
        print_res(False, detail)
        return EXIT_USAGE if status in ("unknown", "invalid") else EXIT_ERROR
    for line in detail:
        print_info(line)
    print_res(True, T["config_set_ok"].format(key=args.key, value="***" if args.key == "mcrcon_pass" else config[args.key]))
    if mc_core.is_server_running(config) and args.key in mc_config.RESTART_KEYS:
        print_info(T["config_restart_needed"])
    return EXIT_OK


# ==========================================
# SWITCH / SLEEP / DATAPACKS / MODS
# ==========================================

def render(res):
    """Text for an API result, from its code (strings 'res_<code>')."""
    template = T.get(f"res_{res.get('code')}")
    if not template:
        return res.get("message") or res.get("code", "?")
    data = {k: (", ".join(map(str, v)) if isinstance(v, (list, tuple)) else v) for k, v in res.items()}
    try:
        return template.format(**data)
    except (KeyError, IndexError, ValueError):
        return template

def _finish(res, as_json):
    """Print an API result (JSON or text) and return the exit code."""
    if as_json:
        print_json({"schema": mc_api.SCHEMA_VERSION, **res})
    else:
        print_res(res["ok"], render(res))
        if res.get("restart_required"):
            print_info(T["restart_required"])
    if res["ok"]:
        return EXIT_OK
    return EXIT_NOT_FOUND if res["code"] in ("not_found", "no_server", "folder_missing") else EXIT_ERROR

def _load(target, as_json):
    loaded, error = mc_api.load_server(target)
    if error:
        return None, _finish(error, as_json)
    if target is None and not as_json:
        print_target(loaded[0])
    return loaded, None

def _split_target(values, wanted):
    """Positional values = `wanted` operands then an optional target."""
    values = list(values or [])
    operands, rest = values[:wanted], values[wanted:]
    if len(rest) > 1:
        return None, None
    return operands, (rest[0] if rest else None)

def cmd_switch(args):
    if not args.json:
        print_info(T["switch_running"])
    res = mc_api.switch(args.target, force=args.force)
    if res["ok"] and not args.json:
        start = res.get("start") or {}
        if start.get("message"):
            print_info(start["message"])
    return _finish(res, args.json)

def cmd_sleep(args):
    action = args.sleep_action
    wanted = 1 if action in ("allow", "deny") else 0
    operands, target = _split_target(args.args, wanted)
    if operands is None or len(operands) < wanted:
        print_res(False, T["sleep_usage"])
        return EXIT_USAGE
    loaded, code = _load(target, args.json)
    if not loaded:
        return code
    name, config = loaded
    if action == "status":
        info = mc_api.sleep_info(config)
        state = mc_api.server_state(config)
        if args.json:
            print_json({"schema": mc_api.SCHEMA_VERSION, "server": name, "state": state, **info})
            return EXIT_OK
        if info["enabled"]:
            print_res(True, T["sleep_status_on"].format(after=_human_duration(info["after_s"])))
        else:
            print_info(T["sleep_status_off"])
        print_info(T["sleep_status_state"].format(state=state))
        if info["allow"]:
            print_info(T["sleep_status_allow"].format(names=", ".join(info["allow"])))
        return EXIT_OK
    if action == "wake":
        return _finish(mc_api.wake(name, config), args.json)
    after = None
    if args.after:
        try:
            after = mc_api.parse_duration(args.after)
        except ValueError:
            print_res(False, T["invalid_duration"].format(val=args.after))
            return EXIT_USAGE
    if action == "enable":
        res = mc_api.sleep_configure(name, config, enabled=True, after_s=after)
    elif action == "disable":
        res = mc_api.sleep_configure(name, config, enabled=False)
    elif action == "allow":
        res = mc_api.sleep_configure(name, config, allow_add=operands)
    else:
        res = mc_api.sleep_configure(name, config, allow_remove=operands)
    if res["ok"] and not args.json:
        res = dict(res, after=_human_duration(res["after_s"]))
    return _finish(res, args.json)

def cmd_datapack(args):
    import mc_content
    wanted = 0 if args.dp_action == "list" else 1
    operands, target = _split_target(args.args, wanted)
    if operands is None or len(operands) < wanted:
        print_res(False, T["datapack_usage"])
        return EXIT_USAGE
    loaded, code = _load(target, args.json)
    if not loaded:
        return code
    _name, config = loaded
    if args.dp_action == "list":
        res = mc_content.datapack_list(config)
        if args.json:
            return _finish(res, True)
        if not res["running"]:
            print_info(T["datapack_offline_list"])
        for pack in res["packs"]:
            state = {True: T["dp_enabled"], False: T["dp_disabled"], None: "?"}[pack["enabled"]]
            flags = []
            if pack["order"] is not None:
                flags.append(f"#{pack['order'] + 1}")
            if pack["worldgen"]:
                flags.append(T["dp_worldgen"])
            line = f"  {pack['file']:<40} {state:<12} {' '.join(flags)}"
            print(line.rstrip())
            if pack["problem"]:
                print(f"    \033[93m-> {T['res_pack_' + pack['problem']].format(name=pack['file'])}\033[0m")
        if not res["packs"]:
            print_info(T["datapack_none"].format(folder=res["folder"]))
        return EXIT_OK
    res = mc_content.datapack_set(config, operands[0], enable=args.dp_action == "enable",
                                  before=args.before, after=args.after,
                                  first=args.first, last=args.last)
    return _finish(res, args.json)

def cmd_mod(args):
    import mc_content
    wanted = 0 if args.mod_action == "list" else 1
    operands, target = _split_target(args.args, wanted)
    if operands is None or len(operands) < wanted:
        print_res(False, T["mod_usage"])
        return EXIT_USAGE
    loaded, code = _load(target, args.json)
    if not loaded:
        return code
    _name, config = loaded
    if args.mod_action == "list":
        res = mc_content.mod_list(config)
        if args.json:
            return _finish(res, True)
        for mod in res["mods"]:
            where = []
            if mod["server"]:
                where.append(T["mod_where_server"])
            if mod["modpack"]:
                where.append(T["mod_where_modpack"])
            print(f"  {mod['file']:<50} {' + '.join(where)}")
        print_info(T["mod_count"].format(n=len(res["mods"])))
        return EXIT_OK
    if args.mod_action == "add":
        res = mc_content.mod_add(config, operands[0], server_only=args.server_only)
    else:
        res = mc_content.mod_remove(config, operands[0], confirm_blocks=args.yes)
    if res["ok"] and res["code"] == "added" and not args.json:
        res = dict(res, copies=len(res["copies"]))
    if res["ok"] and res["code"] == "removed" and not args.json:
        res = dict(res, moved=len(res["moved"]))
    return _finish(res, args.json)

def dispatch_daemon(daemon_action):
    if daemon_action == "run":
        print(f"\033[90m[i]\033[0m {T['daemon_launching']}")
        import mc_daemon
        mc_daemon.main()
        return

    labels = {
        "start":   T["daemon_label_started"],
        "stop":    T["daemon_label_stopped"],
        "restart": T["daemon_label_restarted"],
    }
    label = labels[daemon_action]

    # Goes through sudo when not root: a plain systemctl call would be handed to
    # polkit, which asks for a password the CLI cannot answer.
    result = mc_config.run_systemctl(daemon_action)

    if result.returncode == 0:
        print_res(True, T["daemon_ok"].format(label=label))
        return EXIT_OK

    detail = (result.stdout or "") + (result.stderr or "")
    detail_lower = detail.lower()
    if "not found" in detail_lower or "not-found" in detail_lower or "no such" in detail_lower or "not loaded" in detail_lower:
        print_res(False, T["daemon_not_installed"])
    elif "access denied" in detail_lower or "permission denied" in detail_lower or "authentication" in detail_lower or "interactive" in detail_lower:
        print_res(False, T["daemon_no_perms"].format(action=daemon_action))
    else:
        print_res(False, T["daemon_error_msg"].format(action=daemon_action, code=result.returncode, detail=detail.strip()))

# ==========================================
# ENTRY POINT
# ==========================================

class _AnsiStripper:
    """Wraps a stream and drops ANSI colour codes. Used when the output is not a
    terminal (pipes, logs, scripts) or when NO_COLOR is set."""
    import re as _re
    _ANSI = _re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

    def __init__(self, stream):
        self._stream = stream

    def write(self, data):
        return self._stream.write(self._ANSI.sub("", data))

    def __getattr__(self, name):
        return getattr(self._stream, name)

def _setup_output():
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name)
        try:
            plain = os.environ.get("NO_COLOR") is not None or not stream.isatty()
        except Exception:
            plain = True
        if plain:
            setattr(sys, name, _AnsiStripper(stream))

def _log_crash():
    """Write the traceback to logs/cli-error.log and return that path."""
    import traceback
    import datetime
    path = os.path.join(BASE_DIR, "logs", "cli-error.log")
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"\n=== {datetime.datetime.now().isoformat(timespec='seconds')} "
                    f"MC Manager v{VERSION} — mc {' '.join(sys.argv[1:])}\n")
            traceback.print_exc(file=f)
    except Exception:
        return None
    return path

def run():
    """Run the CLI and exit with a documented code. No raw Python traceback ever
    reaches the user: unexpected errors are logged and summarised (set
    MCMANAGER_DEBUG=1 to see the traceback)."""
    _setup_output()
    try:
        code = main()
    except KeyboardInterrupt:
        print()
        code = EXIT_INTERRUPTED
    except SystemExit:
        raise
    except mc_servers.DataFileError as e:
        print(f"\033[91m[{T['icon_err']}]\033[0m {T['data_file_unreadable'].format(path=e.path, detail=e.detail)}")
        print(f"\033[90m[i]\033[0m {T['data_file_fix'].format(path=e.path)}")
        code = EXIT_ERROR
    except Exception as e:
        if os.environ.get("MCMANAGER_DEBUG"):
            raise
        log = _log_crash()
        print(f"\033[91m[{T['icon_err']}]\033[0m {T['unexpected_error'].format(e=f'{type(e).__name__}: {e}')}")
        if log:
            print(f"\033[90m[i]\033[0m {T['unexpected_error_log'].format(path=log)}")
        code = EXIT_ERROR
    if code is None:
        code = EXIT_ERROR if _failed else EXIT_OK
    sys.stdout.flush()
    sys.exit(code)

if __name__ == "__main__":
    run()
