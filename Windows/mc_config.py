import json
import os
import subprocess
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(BASE_DIR)
import mc_servers
import mc_lang
from mc_lang import T
from mc_validate import valid_port, valid_ram, valid_cpu, valid_bool

WEBHOOK_TEMPLATES_FILE = os.path.join(BASE_DIR, "webhook_templates.json")

_FALLBACK_WEBHOOKS = {
    "fr": {
        "start_automod": {
            "title": "🟢 {nom} démarre !",
            "color": 3066993,
            "description": "Empreinte de sécurité AutoModpack (à confirmer une seule fois) : `{cle}`",
            "show_ip": True,
            "show_version": True
        },
        "start_normal": {
            "title": "🟢 {nom} démarre !",
            "color": 3066993,
            "description": "Le serveur est en ligne.",
            "show_ip": True,
            "show_version": True
        },
        "stop": {
            "title": "🔴 {nom} s'arrête",
            "color": 15158332,
            "description": "Le serveur est hors ligne."
        },
        "fermeture_nuit": {
            "title": "🔴 Le serveur {nom} est fermé",
            "color": 16711680,
            "description": "Le serveur est hors ligne jusqu'à la prochaine ouverture."
        }
    },
    "en": {
        "start_automod": {
            "title": "🟢 {nom} is starting!",
            "color": 3066993,
            "description": "AutoModpack security fingerprint (confirm once): `{cle}`",
            "show_ip": True,
            "show_version": True
        },
        "start_normal": {
            "title": "🟢 {nom} is starting!",
            "color": 3066993,
            "description": "The server is online.",
            "show_ip": True,
            "show_version": True
        },
        "stop": {
            "title": "🔴 {nom} stopped",
            "color": 15158332,
            "description": "The server is offline."
        },
        "fermeture_nuit": {
            "title": "🔴 {nom} is now closed",
            "color": 16711680,
            "description": "The server is offline until the next scheduled opening."
        }
    }
}

def get_fallback_webhook(key):
    lang = mc_lang.current_language()
    return _FALLBACK_WEBHOOKS.get(lang, _FALLBACK_WEBHOOKS["fr"]).get(key, {})

def config_path(dossier_serveur):
    return os.path.join(dossier_serveur, "config.json")

def webhooks_path(dossier_serveur):
    return os.path.join(dossier_serveur, "webhooks.json")

def load_config(dossier_serveur):
    path = config_path(dossier_serveur)
    if not os.path.exists(path):
        return {}
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_config(config):
    dossier_serveur = config["dossier_serveur"]
    path = config_path(dossier_serveur)
    tmp_path = path + ".tmp"
    with open(tmp_path, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=4, ensure_ascii=False)
    os.replace(tmp_path, path)
    mc_servers.update_cached_ports(dossier_serveur, port=config.get("port"), rcon_port=config.get("rcon_port"))

def _load_templates():
    lang = mc_lang.current_language()
    if os.path.exists(WEBHOOK_TEMPLATES_FILE):
        with open(WEBHOOK_TEMPLATES_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        # Bilingual file: {"fr": {...}, "en": {...}}
        if isinstance(data, dict) and ("fr" in data or "en" in data):
            return data.get(lang) or data.get("fr") or {}
        return data  # legacy single-language file
    return _FALLBACK_WEBHOOKS.get(lang, _FALLBACK_WEBHOOKS["fr"])

def load_webhooks(dossier_serveur):
    templates = _load_templates()
    path = webhooks_path(dossier_serveur)
    if not os.path.exists(path):
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(templates, f, indent=4, ensure_ascii=False)
        return templates

    with open(path, 'r', encoding='utf-8') as f:
        webhooks = json.load(f)

    updated = False
    for key, default_val in templates.items():
        if key not in webhooks:
            webhooks[key] = default_val
            updated = True

    if updated:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(webhooks, f, indent=4, ensure_ascii=False)

    return webhooks

def detect_default_jar(dossier):
    fallback = "fabric-server-launch.jar"
    if not dossier or not os.path.exists(dossier):
        return fallback
    try:
        # Forge/NeoForge servers launch through run.bat (no single runnable
        # jar), so 'mc add' must suggest the script, not a jar.
        if os.path.exists(os.path.join(dossier, "run.bat")):
            return "run.bat"
        jars = [f for f in os.listdir(dossier) if f.endswith('.jar')]
        if not jars: return fallback
        if len(jars) == 1: return jars[0]
        mots_cles = ['server', 'launch', 'paper', 'forge', 'neoforge', 'purpur']
        for j in jars:
            if any(mot in j.lower() for mot in mots_cles):
                return j
        return jars[0]
    except Exception:
        return fallback

def smart_ask(prompt_text, key, config, default_val, is_int=False):
    current_val = config.get(key)
    if current_val is not None and str(current_val) != "":
        hint = f"\033[93m{T['hint_current'].format(val=current_val, default=default_val)}\033[0m"
    else:
        hint = f"\033[90m{T['hint_default'].format(val=default_val)}\033[0m"

    while True:
        ans = input(f"{prompt_text} {hint} : ").strip()
        if not ans:
            return current_val if (current_val is not None and str(current_val) != "") else default_val
        if ans.upper() == "RESET":
            return int(default_val) if is_int else default_val
        if is_int:
            try: return int(ans)
            except ValueError:
                print(T["enter_valid_number"])
                continue
        return ans

def install_mc_command():
    print(f"\n\033[96m=========================================")
    print(f"   {T['install_mc_header']}")
    print(f"=========================================\033[0m")

    bat_content = f'@echo off\npython "{BASE_DIR}\\mc_cli.py" %*\n'
    bat_path = os.path.join(BASE_DIR, "mc.bat")

    with open(bat_path, 'w', encoding='utf-8') as f:
        f.write(bat_content)

    sys32_path = r"C:\Windows\System32\mc.bat"
    try:
        import shutil
        shutil.copy(bat_path, sys32_path)
        print(f"\033[92m[{T['icon_ok']}]\033[0m {T['install_mc_ok']}")
        print(f"\033[90m[{T['icon_info']}]\033[0m {T['install_mc_new_term']}\033[0m")
    except PermissionError:
        print(f"\033[93m[{T['icon_warn']}]\033[0m {T['install_mc_perms']}")
        print(f"\033[90m[{T['icon_info']}]\033[0m {T['install_mc_manual'].format(src=bat_path, dst=sys32_path)}\033[0m")
    except Exception as e:
        print(f"\033[91m[{T['icon_err']}]\033[0m {e}")

def _smart_ask_nonempty(prompt_text, key, config, default_val):
    while True:
        val = smart_ask(prompt_text, key, config, default_val)
        if val and str(val).strip():
            return str(val).strip()
        print(f"\033[93m[{T['icon_warn']}]\033[0m {T['name_empty']}")
        config.pop(key, None)

def _smart_ask_port(prompt_text, key, config, default_val):
    while True:
        val = smart_ask(prompt_text, key, config, default_val, is_int=True)
        if valid_port(val):
            return int(val)
        print(f"\033[93m[{T['icon_warn']}]\033[0m {T['invalid_port'].format(val=val)}")
        config.pop(key, None)

def _smart_ask_bool(prompt_text, key, config, default_val):
    while True:
        val = smart_ask(prompt_text, key, config, default_val, is_int=True)
        if valid_bool(val):
            return int(val)
        print(f"\033[93m[{T['icon_warn']}]\033[0m {T['invalid_bool'].format(val=val)}")
        config.pop(key, None)

def _smart_ask_ram(prompt_text, key, config, default_val):
    while True:
        val = smart_ask(prompt_text, key, config, default_val)
        if valid_ram(val):
            return str(val).strip()
        print(f"\033[93m[{T['icon_warn']}]\033[0m {T['invalid_ram'].format(val=val)}")
        config.pop(key, None)

def _smart_ask_cpu(prompt_text, key, config, default_val):
    while True:
        val = smart_ask(prompt_text, key, config, default_val)
        if valid_cpu(val):
            return str(val).strip()
        print(f"\033[93m[{T['icon_warn']}]\033[0m {T['invalid_cpu'].format(val=val)}")
        config.pop(key, None)

def run_setup_base(config, current_key=None):
    print(f"\n\033[93m--- {T['section_base']} ---\033[0m")
    config["nom_serveur"] = _smart_ask_nonempty(T["prompt_server_name"], "nom_serveur", config, "Minecraft")
    config["description_serveur"] = smart_ask(T["prompt_motd"], "description_serveur", config, f"Serveur {config['nom_serveur']}")

    existing_slugs = [k for k in mc_servers.list_servers().keys() if k != current_key]
    slug = mc_servers.slugify(config["nom_serveur"], existing_slugs)
    default_dir = os.path.join(mc_servers.DATA_ROOT, slug, "Server")
    default_backup = os.path.join(mc_servers.DATA_ROOT, slug, "Backup")

    config["dossier_serveur"] = smart_ask(T["prompt_dir"], "dossier_serveur", config, default_dir)
    config["dossier_backup"] = smart_ask(T["prompt_backup_dir"], "dossier_backup", config, default_backup)
    config["port"] = _smart_ask_port(T["prompt_port"], "port", config, 25565)
    return config

def _ask_hour(prompt_key, config_key, config, default):
    while True:
        val = smart_ask(T[prompt_key], config_key, config, default, is_int=True)
        if 0 <= int(val) <= 23:
            return int(val)
        print(f"\033[93m[{T['icon_warn']}]\033[0m {T['invalid_hour'].format(val=val)}")
        config.pop(config_key, None)

def _ask_minute(prompt_key, config_key, config, default):
    while True:
        val = smart_ask(T[prompt_key], config_key, config, default, is_int=True)
        if 0 <= int(val) <= 59:
            return int(val)
        print(f"\033[93m[{T['icon_warn']}]\033[0m {T['invalid_minute'].format(val=val)}")
        config.pop(config_key, None)

def run_setup_schedule(config):
    print(f"\n\033[93m--- {T['section_schedule']} ---\033[0m")
    config["always_on"] = _smart_ask_bool(T["prompt_always_on"], "always_on", config, 1)
    if config["always_on"] == 0:
        while True:
            config["heure_ouverture"] = _ask_hour("prompt_open_hour", "heure_ouverture", config, 20)
            config["minute_ouverture"] = _ask_minute("prompt_open_min", "minute_ouverture", config, 0)
            config["heure_fermeture"] = _ask_hour("prompt_close_hour", "heure_fermeture", config, 3)
            config["minute_fermeture"] = _ask_minute("prompt_close_min", "minute_fermeture", config, 0)
            if (config["heure_ouverture"], config["minute_ouverture"]) == \
               (config["heure_fermeture"], config["minute_fermeture"]):
                print(f"\033[93m[{T['icon_warn']}]\033[0m {T['schedule_same_time']}")
                for key in ["heure_ouverture", "minute_ouverture", "heure_fermeture", "minute_fermeture"]:
                    config.pop(key, None)
                continue
            break
    else:
        for key in ["heure_ouverture", "minute_ouverture", "heure_fermeture", "minute_fermeture"]:
            if key in config: del config[key]

    while True:
        val = smart_ask(T["prompt_retention"], "backup_retention_days", config, 0, is_int=True)
        if int(val) >= 0:
            config["backup_retention_days"] = int(val)
            break
        print(f"\033[93m[{T['icon_warn']}]\033[0m {T['invalid_retention'].format(val=val)}")
        config.pop("backup_retention_days", None)
    return config

SCHEDULE_FIELDS = ["heure_ouverture", "minute_ouverture", "heure_fermeture", "minute_fermeture"]
SCHEDULE_DEFAULTS = {"heure_ouverture": 20, "minute_ouverture": 0, "heure_fermeture": 3, "minute_fermeture": 0}

def set_mode_schedule(config):
    config["always_on"] = 0
    for key in SCHEDULE_FIELDS:
        config.setdefault(key, SCHEDULE_DEFAULTS[key])
    return config

def set_mode_always_on(config):
    config["always_on"] = 1
    for key in SCHEDULE_FIELDS:
        if key in config:
            del config[key]
    return config

def set_mode_maintenance(config):
    config["mode_maintenance"] = 1
    return config

def resume_mode(config):
    config["mode_maintenance"] = 0
    return config

def run_setup_performance(config):
    print(f"\n\033[96m=========================================")
    print(f"   {T['section_performance']}")
    print(f"=========================================\033[0m")
    detected_jar = detect_default_jar(config.get("dossier_serveur", ""))
    nb_cores = os.cpu_count()
    default_cpu_str = f"0-{nb_cores - 1}" if nb_cores else "0-3"
    print(f"\033[90m{T['cpu_info'].format(count=nb_cores)}\033[0m")
    print(f"\033[90m{T['cpu_format_hint']}\033[0m")
    config["cpu_affinity"] = _smart_ask_cpu(T["prompt_cpu"], "cpu_affinity", config, default_cpu_str)
    config["ram_allocation"] = _smart_ask_ram(T["prompt_ram"], "ram_allocation", config, "4G")
    config["jar_name"] = smart_ask(T["prompt_jar"], "jar_name", config, detected_jar)

    import mc_core
    config["java_flags"] = config.get("java_flags", mc_core.DEFAULT_JAVA_FLAGS)
    # Forge/NeoForge get their heap from user_jvm_args.txt, which mc_core
    # rewrites at start time — tell the user so the value does not look ignored.
    if str(config.get("jar_name", "")).endswith(".bat"):
        print(f"\033[90m[{T['icon_info']}]\033[0m {T['forge_bat_note']}")
    return config

_AUTOMOD_LOADERS = {"Fabric", "Forge", "NeoForge"}

def run_setup_integrations(config):
    print(f"\n\033[93m--- {T['section_integrations']} ---\033[0m")
    config["domaine"] = smart_ask(T["prompt_domain"], "domaine", config, "")
    config["webhook_url"] = smart_ask(T["prompt_webhook_url"], "webhook_url", config, "")

    loader = config.get("loader", "")
    already_enabled = config.get("activer_automodpack", 0) == 1
    automod_possible = loader in _AUTOMOD_LOADERS or already_enabled

    if automod_possible:
        config["activer_automodpack"] = _smart_ask_bool(T["prompt_automodpack"], "activer_automodpack", config, 0)
        if config["activer_automodpack"] == 1:
            import mc_core
            fingerprint = mc_core.get_automodpack_fingerprint(config.get("dossier_serveur", ""))
            if fingerprint:
                config["cle_automodpack"] = fingerprint
                print(f"\033[92m[{T['icon_ok']}]\033[0m {T['automod_fp_detected'].format(fp=fingerprint)}")
            else:
                config.setdefault("cle_automodpack", "")
                print(f"\033[90m[{T['icon_info']}]\033[0m {T['automod_fp_pending']}")
        else:
            config.pop("cle_automodpack", None)
    else:
        config.pop("activer_automodpack", None)
        config.pop("cle_automodpack", None)

    return config

def ensure_provisioning(config, dossier_serveur):
    import mc_deploy
    import mc_firewall

    previous_port = load_config(dossier_serveur).get("port")

    print(f"\n\033[93m--- {T['section_prereq']} ---\033[0m")

    if not config.get("mcrcon_pass"):
        print(f"\033[90m[{T['icon_info']}]\033[0m {T['rcon_not_configured']}")
        config, rcon_pass, rcon_port = mc_deploy.setup_rcon(dossier_serveur, config)
    else:
        print(f"\033[92m[{T['icon_ok']}]\033[0m {T['rcon_already_ok']}")
        rcon_pass = config.get("mcrcon_pass", "")
        rcon_port = config.get("rcon_port", 25575)

    mc_deploy.generate_server_properties(dossier_serveur, config, rcon_pass, rcon_port)

    print(f"\n\033[93m--- {T['section_firewall']} ---\033[0m")
    port = config.get("port")
    ok, manual_cmd = mc_firewall.ensure_game_port_rule(
        port, old_port=previous_port if previous_port != port else None
    )
    if ok:
        print(f"\033[92m[{T['icon_ok']}]\033[0m {T['firewall_ok'].format(port=port)}")
    else:
        print(f"\033[93m[{T['icon_warn']}]\033[0m {T['firewall_failed']}")
        print(f"\033[90m[{T['icon_info']}]\033[0m {T['firewall_manual_hint']}")
        print(f"\033[96m{manual_cmd}\033[0m")

    if "activer_automodpack" not in config:
        loader = config.get("loader")
        mc_version = config.get("mc_version")
        if not loader or not mc_version:
            import mc_core
            loader, mc_version = mc_core.guess_loader_and_version(config)
        # Only enter setup if the loader can support AutoModpack
        compatible = {"Fabric", "Forge", "NeoForge"}
        if loader in compatible and mc_version:
            config = mc_deploy.setup_automodpack(dossier_serveur, config, mc_version, loader)
        else:
            # Loader not compatible — mark so we never ask again
            config["activer_automodpack"] = 0

    return config

def run_setup(target=None):
    resolved = mc_servers.resolve_target(target)
    if not resolved:
        return
    name, dossier_serveur = resolved

    print(f"\033[96m=========================================")
    print(f"   {T['setup_header']}")
    print(f"=========================================\033[0m")
    config = load_config(dossier_serveur)
    config["dossier_serveur"] = dossier_serveur

    config = run_setup_base(config, current_key=name)
    if config["dossier_serveur"] != dossier_serveur:
        mc_servers.set_dossier(name, config["dossier_serveur"])
    config = ensure_provisioning(config, config["dossier_serveur"])
    config = run_setup_schedule(config)
    config = run_setup_performance(config)
    config = run_setup_integrations(config)

    save_config(config)
    load_webhooks(config["dossier_serveur"])
    print(f"\n\033[92m[{T['icon_ok']}]\033[0m {T['setup_success']}")
    print(f"\033[90m[{T['icon_info']}]\033[0m {T['webhooks_edit_hint']}")

NSSM_URL = "https://nssm.cc/release/nssm-2.24.zip"

def ensure_nssm():
    nssm_exe = os.path.join(BASE_DIR, "nssm", "nssm.exe")
    if os.path.exists(nssm_exe):
        return nssm_exe

    print(f"\033[90m[{T['icon_info']}]\033[0m {T['nssm_downloading']}\033[0m")
    import urllib.request
    import zipfile
    import tempfile
    import platform
    import shutil

    arch = "win64" if platform.machine().endswith("64") else "win32"
    try:
        with tempfile.TemporaryDirectory() as tmp:
            zip_path = os.path.join(tmp, "nssm.zip")
            urllib.request.urlretrieve(NSSM_URL, zip_path)
            with zipfile.ZipFile(zip_path) as zf:
                member = next(n for n in zf.namelist() if n.endswith(f"{arch}/nssm.exe"))
                zf.extract(member, tmp)
                os.makedirs(os.path.dirname(nssm_exe), exist_ok=True)
                shutil.copy(os.path.join(tmp, member), nssm_exe)
        print(f"\033[92m[{T['icon_ok']}]\033[0m {T['nssm_ok']}\033[0m")
        return nssm_exe
    except Exception as e:
        print(f"\033[91m[{T['icon_err']}]\033[0m {T['nssm_failed'].format(e=e)}")
        print(f"\033[90m[{T['icon_info']}]\033[0m {T['nssm_manual'].format(path=os.path.join(BASE_DIR, 'nssm'))}\033[0m")
        return None

def install_daemon_task():
    print(f"\n\033[96m=========================================")
    print(f"   {T['daemon_inst_header']}")
    print(f"=========================================\033[0m")

    nssm_exe = ensure_nssm()
    if not nssm_exe:
        print(f"\033[91m[{T['icon_err']}]\033[0m {T['daemon_inst_aborted']}")
        return

    python_exe = sys.executable.replace("python.exe", "pythonw.exe")
    if not os.path.exists(python_exe):
        python_exe = sys.executable

    daemon_path = os.path.join(BASE_DIR, "mc_daemon.py")
    service_name = "MCManagerDaemon"
    logs_dir = os.path.join(BASE_DIR, "logs")
    os.makedirs(logs_dir, exist_ok=True)

    subprocess.run([nssm_exe, "stop", service_name], capture_output=True)
    subprocess.run([nssm_exe, "remove", service_name, "confirm"], capture_output=True)

    subprocess.run([nssm_exe, "install", service_name, python_exe, daemon_path], capture_output=True)
    subprocess.run([nssm_exe, "set", service_name, "AppDirectory", BASE_DIR], capture_output=True)
    subprocess.run([nssm_exe, "set", service_name, "Start", "SERVICE_AUTO_START"], capture_output=True)
    subprocess.run([nssm_exe, "set", service_name, "AppStderr", os.path.join(logs_dir, "daemon_error.log")], capture_output=True)
    subprocess.run([nssm_exe, "set", service_name, "AppRotateFiles", "0"], capture_output=True)

    shared = os.environ.get("MCMANAGER_DATA_DIR", "").strip()
    if shared:
        subprocess.run([nssm_exe, "set", service_name, "AppEnvironmentExtra",
                        f"MCMANAGER_DATA_DIR={shared}"], capture_output=True)

    result = subprocess.run([nssm_exe, "start", service_name], capture_output=True, text=True)
    if result.returncode == 0:
        print(f"\033[92m[{T['icon_ok']}]\033[0m {T['daemon_inst_ok'].format(name=service_name)}")
        print(f"\033[92m[{T['icon_ok']}]\033[0m {T['daemon_inst_silent']}")
    else:
        print(f"\033[91m[{T['icon_err']}]\033[0m {T['daemon_inst_failed']}")
        print(f"\033[90m[{T['icon_info']}]\033[0m {T['daemon_inst_rerun']}\033[0m")

if __name__ == "__main__":
    if "--install-only" in sys.argv:
        install_mc_command()
    else:
        run_setup()
