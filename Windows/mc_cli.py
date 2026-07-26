#!/usr/bin/env python3
import argparse
import os
import sys
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
from mc_lang import T, VERSION

def print_res(success, msg):
    color = "\033[92m[OK]\033[0m" if success else "\033[93m[!]\033[0m"
    print(f"{color} {msg}")

def save_config(config):
    mc_config.save_config(config)

def rcon_console(config):
    import time
    import threading
    import msvcrt

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

    try:
        while True:
            if msvcrt.kbhit():
                ch = msvcrt.getwch()
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
                        except Exception:
                            pass
                    print(f"\033[96m>\033[0m ", end='', flush=True)
                elif ch in ('\x00', '\xe0'):  # special key (arrows, F-keys) — discard second byte
                    msvcrt.getwch()
                elif ch == '\x08':  # Backspace
                    with lock:
                        if typed_ref[0]:
                            typed_ref[0] = typed_ref[0][:-1]
                            print('\b \b', end='', flush=True)
                elif ord(ch) >= 32:  # printable
                    with lock:
                        typed_ref[0] += ch
                        print(ch, end='', flush=True)
            else:
                time.sleep(0.01)
    except KeyboardInterrupt:
        print(f"\n{T['console_disconnect']}")
    except Exception as e:
        print_res(False, T["console_error"].format(e=e))
    finally:
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

def render_server_box(name, info, active_name):
    dossier = info.get("dossier_serveur", "")
    server_id = info.get("id", "?")
    title = f"[{server_id}] {name}"
    marker = T["active_marker"] if name == active_name else ""

    if not os.path.exists(dossier):
        field_lines = [
            f"{T['field_status']}   : {T['dir_missing']}",
            f"{T['field_dir']}  : {dossier}",
        ]
        return _box(title, marker, field_lines)

    config = mc_config.load_config(dossier)
    config["dossier_serveur"] = dossier

    en_ligne = mc_core.is_server_running(config)
    pid = mc_core.get_server_pid(config) if en_ligne else None
    if pid:
        statut = T["status_online"].format(pid=pid)
    elif en_ligne:
        statut = T["status_online_nopid"]
    else:
        statut = T["status_offline"]

    mode = mc_core.effective_mode(config)
    if mode == "schedule":
        ho = int(config.get("heure_ouverture", 20))
        mo = int(config.get("minute_ouverture", 0))
        hf = int(config.get("heure_fermeture", 3))
        mf = int(config.get("minute_fermeture", 0))
        mode_label = T["mode_sched_hours"].format(oh=ho, om=mo, ch=hf, cm=mf)
    elif mode == "maintenance":
        was = T["mode_always_on"] if config.get("always_on", 1) == 1 else T["mode_schedule"]
        mode_label = T["mode_maint_was"].format(was=was)
    else:
        mode_label = T["mode_always_on"]

    loader, version = mc_core.guess_loader_and_version(config)
    version_label = version or "?"
    if loader:
        version_label += f" ({loader})"

    port = config.get("port", info.get("port", "?"))

    field_lines = [
        f"{T['field_status']}   : {statut}",
        f"{T['field_mode']}     : {mode_label}",
        f"{T['field_version']}  : {version_label}",
        f"{T['field_dir']}  : {dossier}",
        f"{T['field_port']}     : {port}",
    ]
    return _box(title, marker, field_lines)

def print_dashboard(target=None, with_cheatsheet=False):
    servers = mc_servers.list_servers()
    if not servers:
        print_res(False, T["no_server_dashboard"])
        return

    if target is not None:
        resolved = mc_servers.resolve_target(target)
        if not resolved:
            return
        name, _ = resolved
        servers = {name: servers[name]}

    active_name = mc_servers.get_active_name()
    for name, info in servers.items():
        print(render_server_box(name, info, active_name))
        print()

    if with_cheatsheet:
        print(T["cheatsheet"])

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
            return
        name, _ = resolved
        prefix = f"[{name}]"
        lines = [l for l in lines if prefix in l]

    print("".join(lines[-30:]) or T["logs_nothing"])

# ==========================================
# MAIN
# ==========================================

NEEDS_ACTIVE_RESOLUTION = {"configure", "start", "stop", "console", "backup", "mode", "schedule", "edit", "resume", "open", "announce", "fingerprint"}

def main():
    os.system("")  # enable ANSI colors on Windows

    if len(sys.argv) > 1 and sys.argv[1] in ["start", "resume"]:
        mc_setup.verify_and_install()

    mc_servers.migrate_legacy_single_server()

    parser = argparse.ArgumentParser(description="\033[96m=== MC Manager CLI ===\033[0m")
    parser.add_argument("--version", action="version", version=f"MC Manager v{VERSION}")
    subparsers = parser.add_subparsers(dest="action", title=T["cli_commands_title"], metavar="<command>")

    target_parser = argparse.ArgumentParser(add_help=False)
    target_parser.add_argument("target", nargs="?", default=None, help=T["cli_target_help"])

    subparsers.add_parser("help", help=T["help_help"])
    subparsers.add_parser("version", help=T["help_version"])
    subparsers.add_parser("deploy", help=T["help_deploy"])
    p_add = subparsers.add_parser("add", help=T["help_add"])
    p_add.add_argument("path", nargs="?", default=None, help=T["help_add_path"])
    subparsers.add_parser("status", parents=[target_parser], help=T["help_status"])

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

    args = parser.parse_args()

    if args.action is None:
        print_dashboard(with_cheatsheet=True)
        return

    if args.action == "help":
        parser.print_help()
        return

    if args.action == "version":
        print(f"MC Manager v{VERSION} (Windows)")
        return

    if args.action == "deploy":
        mc_deploy.run_deploy({})
        return

    if args.action == "add":
        mc_deploy.run_add({"dossier_serveur": args.path} if args.path else {})
        return

    if args.action == "status":
        print_dashboard(args.target)
        return

    if args.action == "use":
        if mc_servers.set_active(args.target):
            info = mc_servers.list_servers().get(mc_servers.get_active_name(), {})
            print_res(True, T["set_active_ok"].format(name=mc_servers.get_active_name(), sid=info.get("id", "?")))
        else:
            print_res(False, T["server_not_found_use"].format(target=args.target))
        return

    if args.action == "remove":
        resolved = mc_servers.resolve_target(args.target, require_folder=False)
        if not resolved:
            return
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
            return
        active_name, dossier_serveur = resolved
        if target is None:
            info = mc_servers.list_servers().get(active_name, {})
            print(f"\033[90m[i]\033[0m {T['target_info'].format(name=active_name, sid=info.get('id', '?'))}")
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
        mc_doctor.run_doctor(args.target)
        return

    if args.action == "logs":
        print_logs(args.target)
        return

    if args.action == "daemon":
        dispatch_daemon(args.daemon_action)
        return

    # --- centralized resolution for server-targeting commands ---
    config = None
    dossier_serveur = None
    active_name = None
    if args.action in NEEDS_ACTIVE_RESOLUTION:
        target = getattr(args, "target", None)
        resolved = mc_servers.resolve_target(target)
        if not resolved:
            return
        active_name, dossier_serveur = resolved
        if target is None:
            info = mc_servers.list_servers().get(active_name, {})
            print(f"\033[90m[i]\033[0m {T['target_info'].format(name=active_name, sid=info.get('id', '?'))}")
        config = mc_config.load_config(dossier_serveur)
        config["dossier_serveur"] = dossier_serveur

    if args.action == "configure":
        mc_config.run_setup(active_name)

    elif args.action == "edit":
        editor = os.environ.get("EDITOR", "notepad")
        path = mc_config.config_path(dossier_serveur) if args.what == "config" else mc_config.webhooks_path(dossier_serveur)
        os.system(f'{editor} "{path}"')

    elif args.action == "open":
        os.startfile(dossier_serveur)
        print_res(True, T["folder_opened"].format(path=dossier_serveur))

    elif args.action == "start":
        # 'mc start' only launches the server process; it must not touch the
        # maintenance flag. Leaving maintenance is 'mc resume' only. A server
        # can therefore be started manually while staying in maintenance (the
        # daemon keeps ignoring it, webhooks stay silent) until 'mc resume'.
        logging.basicConfig(level=logging.INFO, format="\033[90m[INFO]\033[0m %(message)s")
        ok, msg = mc_core.start_server(config)
        print_res(ok, msg)
        if ok:
            print(f"\033[90m[i]\033[0m {T['start_console_hint']}")

    elif args.action == "stop":
        was_running = mc_core.is_server_running(config)
        stop_ok = True
        if was_running:
            if getattr(args, "force", False):
                mc_core.force_kill_server(config)
                print_res(True, T["stop_forced"])
            else:
                config["mode_maintenance"] = 0  # ensure webhook fires before maintenance is set
                stop_ok, stop_msg = mc_core.stop_server(config)
                print_res(stop_ok, stop_msg)
        # The server is still running if the stop failed — claiming maintenance
        # was enabled would hide that from the user.
        if stop_ok:
            config["mode_maintenance"] = 1
            save_config(config)
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

def dispatch_daemon(daemon_action):
    if daemon_action == "run":
        print(f"\033[90m[i]\033[0m {T['daemon_launching']}")
        import mc_daemon
        mc_daemon.main()
        return

    import subprocess
    service_name = "MCManagerDaemon"
    labels = {
        "start":   T["daemon_label_started"],
        "stop":    T["daemon_label_stopped"],
        "restart": T["daemon_label_restarted"],
    }
    label = labels[daemon_action]

    if daemon_action == "restart":
        subprocess.run(["sc", "stop", service_name], capture_output=True, text=True)
        result = subprocess.run(["sc", "start", service_name], capture_output=True, text=True)
    else:
        result = subprocess.run(["sc", daemon_action, service_name], capture_output=True, text=True)

    if result.returncode == 0:
        print_res(True, T["daemon_ok"].format(label=label))
        return

    if result.returncode == 1060:
        print_res(False, T["daemon_not_installed"])
    elif result.returncode == 5:
        print_res(False, T["daemon_no_perms"].format(action=daemon_action))
    else:
        detail = (result.stdout or result.stderr or "").strip()
        print_res(False, T["daemon_error_msg"].format(action=daemon_action, code=result.returncode, detail=detail))

if __name__ == "__main__":
    main()
