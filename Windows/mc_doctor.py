"""
mc_doctor.py — Full read-only diagnostic ('mc doctor').
Checks Java, RCON (configured + reachable), firewall (game port), MCManagerDaemon
service, and port conflict — without modifying anything.
"""
import os
import socket
import subprocess

import mc_servers
import mc_config
import mc_core
import mc_firewall
import mc_deploy
from mc_lang import T


def _check_port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        try:
            s.bind(("0.0.0.0", int(port)))
            return False
        except OSError:
            return True


def _check_daemon_service():
    try:
        result = subprocess.run(
            ["sc", "query", "MCManagerDaemon"],
            capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW
        )
    except FileNotFoundError:
        return False, T["doctor_svc_no_sc"]
    if result.returncode != 0:
        return False, T["doctor_svc_not_inst"]
    running = "RUNNING" in result.stdout
    return running, (T["doctor_svc_running"] if running else T["doctor_svc_stopped"])


def check_server(name, info):
    results = []
    dossier = info.get("dossier_serveur", "")

    if not dossier or not os.path.exists(dossier):
        results.append(("err", T["doctor_label_dir"], dossier or "(undefined)",
                         T["doctor_dir_fix"].format(name=name)))
        return results

    config = mc_config.load_config(dossier)
    config["dossier_serveur"] = dossier

    java_ok, java_detail = mc_core.check_java()
    results.append(("ok" if java_ok else "err", T["doctor_label_java"], java_detail,
                     None if java_ok else T["doctor_java_fix"]))

    rcon_configured = bool(config.get("mcrcon_pass"))
    results.append(("ok" if rcon_configured else "err", T["doctor_label_rcon_cfg"],
                     T["doctor_rcon_cfg_ok"] if rcon_configured else T["doctor_rcon_cfg_miss"],
                     None if rcon_configured else T["doctor_rcon_cfg_fix"].format(name=name)))

    running = mc_core.is_server_running(config)
    if running and rcon_configured:
        reachable, detail = mc_core.rcon_handshake(
            "127.0.0.1", config.get("rcon_port", mc_core.DEFAULT_RCON_PORT),
            config.get("mcrcon_pass", ""), ping_only=True
        )
        results.append(("ok" if reachable else "warn", T["doctor_label_rcon_live"], detail,
                         None if reachable else T["doctor_rcon_live_fix"]))
    elif rcon_configured:
        results.append(("warn", T["doctor_label_rcon_live"], T["doctor_rcon_offline"], None))

    port = config.get("port", info.get("port"))
    if port:
        name_rule = mc_firewall.rule_name(port)
        present = mc_firewall.rule_exists(name_rule)
        results.append(("ok" if present else "warn", T["doctor_label_firewall"],
                         T["doctor_fw_present"].format(rule=name_rule) if present else T["doctor_fw_absent"],
                         None if present else mc_firewall.manual_command(port)))

    svc_ok, svc_detail = _check_daemon_service()
    results.append(("ok" if svc_ok else "warn", T["doctor_label_service"], svc_detail,
                     None if svc_ok else T["doctor_svc_fix"]))

    if port and not running:
        busy = _check_port_in_use(port)
        results.append(("warn" if busy else "ok", T["doctor_label_port"],
                         T["doctor_port_busy"] if busy else T["doctor_port_free"],
                         T["doctor_port_busy_fix"] if busy else None))

    return results


def print_doctor_report(name, info, results):
    print(f"\n\033[1m\033[96m[{info.get('id', '?')}] {name}\033[0m")
    for status, label, detail, fix in results:
        mc_deploy.pr(status, f"{label} : {detail}")
        if fix:
            print(f"      \033[90m-> {fix}\033[0m")


def run_doctor(target=None):
    servers = mc_servers.list_servers()
    if not servers:
        mc_deploy.pr("warn", T["no_server_cfg_doctor"])
        return

    if target is not None:
        resolved = mc_servers.resolve_target(target)
        if not resolved:
            return
        name, _ = resolved
        servers = {name: servers[name]}

    any_issue = False
    for name, info in servers.items():
        results = check_server(name, info)
        print_doctor_report(name, info, results)
        if any(status in ("warn", "err") for status, *_ in results):
            any_issue = True

    print()
    if any_issue:
        mc_deploy.pr("warn", T["doctor_has_issues"])
    else:
        mc_deploy.pr("ok", T["doctor_all_ok"])
