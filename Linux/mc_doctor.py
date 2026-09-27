"""
mc_doctor.py — Full read-only diagnostic ('mc doctor').
Checks Java, RCON (configured + reachable), firewall (game port), mc_manager
systemd service, and port conflict — without modifying anything.
"""
import os
import shutil
import subprocess

import mc_servers
import mc_config
import mc_core
import mc_firewall
import mc_deploy
from mc_lang import T


def _check_port_in_use(port):
    return mc_core._port_in_use(port)


def _check_daemon_service():
    if not shutil.which("systemctl"):
        return False, T["doctor_svc_no_sc"]
    try:
        result = subprocess.run(
            ["systemctl", "show", "-p", "LoadState,ActiveState",
             f"{mc_config.SERVICE_NAME}.service"],
            capture_output=True, text=True, timeout=10
        )
    except Exception:
        return False, T["doctor_svc_no_sc"]
    states = dict(
        line.split("=", 1) for line in result.stdout.splitlines() if "=" in line
    )
    if states.get("LoadState") != "loaded":
        return False, T["doctor_svc_not_inst"]
    running = states.get("ActiveState") == "active"
    return running, (T["doctor_svc_running"] if running else T["doctor_svc_stopped"])


def check_private_file(path):
    """Files holding secrets must be 0600. Tightening them is safe, so doctor
    does it and says so; returns a result line, or None if nothing to say."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    if not st.st_mode & 0o077:
        return None
    name = os.path.basename(path)
    if st.st_uid == os.geteuid() or os.geteuid() == 0:
        try:
            os.chmod(path, 0o600)
            return ("ok", T["doctor_label_perms"], T["doctor_perms_fixed"].format(file=name), None)
        except OSError:
            pass
    return ("warn", T["doctor_label_perms"], T["doctor_perms_open"].format(file=name, mode=oct(st.st_mode & 0o777)),
            f"chmod 600 {path}")


def _daemon_pid():
    try:
        import json
        import mc_ipc
        with open(mc_ipc.HEARTBEAT_FILE, encoding="utf-8") as f:
            return int(json.load(f).get("pid"))
    except Exception:
        return None


def check_host():
    """Checks that concern the machine, not one server."""
    results = []
    svc_ok, svc_detail = _check_daemon_service()
    results.append(("ok" if svc_ok else "warn", T["doctor_label_service"], svc_detail,
                     None if svc_ok else T["doctor_svc_fix"]))

    unit_state, diffs = mc_config.check_service_unit()
    if unit_state == "outdated":
        detail = ", ".join(f"{k}={want}" for k, _have, want in diffs)
        results.append(("warn", T["doctor_label_unit"], T["doctor_unit_outdated"].format(detail=detail),
                         T["unit_reinstall_hint"].format(path=mc_config.BASE_DIR)))
    elif unit_state == "ok":
        results.append(("ok", T["doctor_label_unit"], T["unit_ok"], None))

    java_ok, java_detail = mc_core.check_java()
    major = mc_core.java_major_version(java_detail) if java_ok else None
    if not java_ok:
        results.append(("err", T["doctor_label_java"], java_detail, T["doctor_java_fix"]))
    elif major is not None and major != 21:
        results.append(("warn", T["doctor_label_java"], java_detail,
                         T["doctor_java_not21"].format(major=major)))
    else:
        results.append(("ok", T["doctor_label_java"], java_detail, None))

    registry_perms = check_private_file(mc_servers.REGISTRY_FILE)
    if registry_perms:
        results.append(registry_perms)
    run_dir = os.path.join(mc_config.BASE_DIR, "run")
    try:
        if os.stat(run_dir).st_mode & 0o077:
            os.chmod(run_dir, 0o700)
    except OSError:
        pass

    zombies = mc_core.zombie_java_pids()
    if zombies:
        detail = ", ".join(f"{pid} (parent {ppid})" for pid, ppid in zombies)
        results.append(("warn", T["doctor_label_zombies"], detail, T["doctor_zombies_fix"]))
    else:
        results.append(("ok", T["doctor_label_zombies"], T["doctor_zombies_none"], None))
    return results


def check_server(name, info):
    results = []
    dossier = info.get("dossier_serveur", "")

    if not dossier or not os.path.exists(dossier):
        results.append(("err", T["doctor_label_dir"], dossier or "(undefined)",
                         T["doctor_dir_fix"].format(name=name)))
        return results

    try:
        config = mc_config.load_config(dossier)
    except mc_servers.DataFileError as e:
        results.append(("err", T["doctor_label_config"], e.detail, T["data_file_fix"].format(path=e.path)))
        return results
    results.append(("ok", T["doctor_label_config"], T["doctor_config_ok"], None))
    config["dossier_serveur"] = dossier
    for path in (mc_config.config_path(dossier), mc_config.webhooks_path(dossier)):
        result = check_private_file(path)
        if result:
            results.append(result)

    drift = mc_core.sync_server_properties(config, apply=False)
    if drift:
        detail = ", ".join(
            f"{k}: {'***' if k == 'rcon.password' else old} -> {'***' if k == 'rcon.password' else new}"
            for k, old, new in drift)
        results.append(("warn", T["doctor_label_props"], detail, T["doctor_props_fix"]))
    else:
        results.append(("ok", T["doctor_label_props"], T["doctor_props_ok"], None))
    rcon_port = config.get("rcon_port")
    if rcon_port:
        clash = mc_servers.find_port_conflict(port=rcon_port, rcon_port=rcon_port, exclude_name=name)
        if clash:
            results.append(("warn", T["doctor_label_rcon_port"],
                            T["doctor_rcon_shared"].format(port=rcon_port, other=clash),
                            T["doctor_rcon_shared_fix"].format(name=name)))
    reg_port = info.get("port")
    if reg_port is not None and config.get("port") is not None and str(reg_port) != str(config.get("port")):
        results.append(("warn", T["doctor_label_registry"],
                         T["doctor_registry_port"].format(reg=reg_port, cfg=config.get("port")),
                         T["doctor_props_fix"]))

    rcon_configured = bool(config.get("mcrcon_pass"))
    results.append(("ok" if rcon_configured else "err", T["doctor_label_rcon_cfg"],
                     T["doctor_rcon_cfg_ok"] if rcon_configured else T["doctor_rcon_cfg_miss"],
                     None if rcon_configured else T["doctor_rcon_cfg_fix"].format(name=name)))
    if rcon_configured and len(str(config.get("mcrcon_pass"))) < 16:
        results.append(("warn", T["doctor_label_rcon_pass"], T["doctor_rcon_pass_short"],
                         T["doctor_rcon_pass_fix"].format(name=name)))

    running = mc_core.is_server_running(config)
    if running:
        pid = mc_core.get_server_pid(config)
        java = mc_core.server_java_pids(dossier) or ([pid] if pid else [])
        for jpid in java:
            cgroup = mc_core.proc_cgroup(jpid) or ""
            if cgroup and mc_config.SERVICE_NAME not in cgroup and mc_config.check_service_unit()[0] != "missing":
                results.append(("warn", T["doctor_label_cgroup"],
                                T["doctor_cgroup_outside"].format(pid=jpid, cgroup=cgroup),
                                T["doctor_cgroup_fix"]))
            _rss, swap = mc_core.proc_memory(jpid)
            if swap and swap > 100 * 1024:
                results.append(("warn", T["doctor_label_swap"],
                                T["doctor_swap_used"].format(pid=jpid, mb=swap // 1024),
                                T["doctor_swap_fix"]))
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
    backend = mc_firewall.detect()
    if port:
        if backend is None:
            results.append(("info", T["doctor_label_firewall"], T["doctor_fw_none"], None))
        else:
            is_open = mc_firewall.port_open(port, backend)
            if is_open is None:
                results.append(("info", T["doctor_label_firewall"],
                                T["doctor_fw_unreadable"].format(fw=backend), None))
            else:
                results.append(("ok" if is_open else "warn", T["doctor_label_firewall"],
                                T["doctor_fw_open"].format(port=port, fw=backend) if is_open
                                else T["doctor_fw_closed"].format(port=port, fw=backend),
                                None if is_open else mc_firewall.manual_command(port, name, backend)))
    rcon_port = config.get("rcon_port")
    if rcon_port and backend:
        exposed = mc_firewall.port_open(rcon_port, backend)
        if exposed:
            results.append(("err", T["doctor_label_rcon_fw"],
                            T["doctor_rcon_exposed"].format(port=rcon_port, fw=backend),
                            T["doctor_rcon_exposed_fix_ufw"].format(port=rcon_port) if backend == "ufw"
                            else T["doctor_rcon_exposed_fix_fwd"].format(port=rcon_port)))
        elif exposed is False:
            results.append(("ok", T["doctor_label_rcon_fw"], T["doctor_rcon_closed"].format(port=rcon_port), None))
    elif rcon_port and mc_core.listens_on_all_interfaces(rcon_port):
        # No firewall: RCON listening on every interface is reachable from outside.
        results.append(("err", T["doctor_label_rcon_fw"],
                        T["doctor_rcon_public_nofw"].format(port=rcon_port),
                        T["doctor_rcon_public_nofw_fix"].format(port=rcon_port)))

    if port and not running:
        occupant = mc_core.port_occupant(port)
        sleeping = config.get("mode_maintenance", 0) == 1 and config.get("stop_reason") == "sleep"
        daemon_pid = _daemon_pid()
        if occupant and occupant[0] and sleeping and occupant[0] == daemon_pid:
            results.append(("ok", T["doctor_label_port"], T["doctor_port_native_sleep"], None))
        elif occupant and occupant[0] and sleeping:
            # An external sleep tool holding the port is the expected state.
            results.append(("info", T["doctor_label_port"],
                            T["doctor_port_external_sleep"].format(prog=occupant[1], pid=occupant[0]), None))
        elif occupant and occupant[0]:
            results.append(("warn", T["doctor_label_port"],
                            T["status_port_held"].format(port=port, prog=occupant[1], pid=occupant[0]),
                            T["doctor_port_busy_fix"]))
        elif occupant:
            results.append(("warn", T["doctor_label_port"], T["doctor_port_busy"], T["doctor_port_busy_fix"]))
        else:
            results.append(("ok", T["doctor_label_port"], T["doctor_port_free"], None))

    return results


def print_doctor_report(name, info, results):
    print(f"\n\033[1m\033[96m[{info.get('id', '?')}] {name}\033[0m")
    for status, label, detail, fix in results:
        mc_deploy.pr(status, f"{label} : {detail}")
        if fix:
            print(f"      \033[90m-> {fix}\033[0m")


def run_doctor(target=None):
    """Print the report. Returns the exit code: 0 unless a check is in error
    (warnings alone keep 0), 3 if the target cannot be resolved."""
    try:
        servers = mc_servers.list_servers()
    except mc_servers.DataFileError as e:
        mc_deploy.pr("err", T["data_file_unreadable"].format(path=e.path, detail=e.detail))
        print(f"      \033[90m-> {T['data_file_fix'].format(path=e.path)}\033[0m")
        return 1
    if not servers:
        mc_deploy.pr("warn", T["no_server_cfg_doctor"])
        return 3

    if target is not None:
        resolved = mc_servers.resolve_target(target, require_folder=False)
        if not resolved:
            return 3
        name, _ = resolved
        servers = {name: servers[name]}

    host = check_host()
    print(f"\n\033[1m\033[96m{T['doctor_host_title']}\033[0m")
    for status, label, detail, fix in host:
        mc_deploy.pr(status, f"{label} : {detail}")
        if fix:
            print(f"      \033[90m-> {fix}\033[0m")
    any_issue = any(status in ("warn", "err") for status, *_ in host)
    any_error = any(status == "err" for status, *_ in host)
    for name, info in servers.items():
        results = check_server(name, info)
        print_doctor_report(name, info, results)
        if any(status in ("warn", "err") for status, *_ in results):
            any_issue = True
        if any(status == "err" for status, *_ in results):
            any_error = True

    print()
    if any_issue:
        mc_deploy.pr("warn", T["doctor_has_issues"])
    else:
        mc_deploy.pr("ok", T["doctor_all_ok"])
    return 1 if any_error else 0
