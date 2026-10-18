import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(BASE_DIR)
import mc_servers
import mc_lang
from mc_lang import T
from mc_validate import valid_port, valid_ram, valid_cpu, valid_bool
from mc_platform import plat

WEBHOOK_TEMPLATES_FILE = os.path.join(BASE_DIR, "webhook_templates.json")

SERVICE_NAME = "mc_manager"

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
        },
        "stop_sleep": {
            "title": "💤 {nom} est en veille",
            "color": 9807270,
            "description": "Personne n'est connecté : le serveur se repose. Il se réveille dès qu'un joueur se connecte."
        },
        "stop_update": {
            "title": "🛠️ {nom} : mise à jour en cours",
            "color": 15105570,
            "description": "Le serveur redémarre après une mise à jour. Il revient dans quelques minutes."
        },
        "stop_maintenance": {
            "title": "🛠️ {nom} est en maintenance",
            "color": 15105570,
            "description": "Le serveur est temporairement arrêté pour maintenance."
        },
        "stop_switch": {
            "title": "🔁 {nom} laisse la place",
            "color": 3447003,
            "description": "Le serveur s'arrête pour laisser place à un autre serveur."
        },
        "crash_loop": {
            "title": "🚨 {nom} ne démarre plus",
            "color": 15158332,
            "description": "Le serveur s'est arrêté de lui-même ({count} échec(s) récents) : les relances automatiques sont suspendues.\n```\n{errors}\n```"
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
        },
        "stop_sleep": {
            "title": "💤 {nom} is sleeping",
            "color": 9807270,
            "description": "Nobody is online, so the server is resting. It wakes up as soon as a player connects."
        },
        "stop_update": {
            "title": "🛠️ {nom}: update in progress",
            "color": 15105570,
            "description": "The server is restarting after an update. It will be back in a few minutes."
        },
        "stop_maintenance": {
            "title": "🛠️ {nom} is under maintenance",
            "color": 15105570,
            "description": "The server is temporarily stopped for maintenance."
        },
        "stop_switch": {
            "title": "🔁 {nom} makes way",
            "color": 3447003,
            "description": "The server is stopping to make way for another server."
        },
        "crash_loop": {
            "title": "🚨 {nom} no longer starts",
            "color": 15158332,
            "description": "The server stopped on its own ({count} recent failure(s)): automatic restarts are suspended.\n```\n{errors}\n```"
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
    config = mc_servers.read_json(config_path(dossier_serveur), {})
    if not isinstance(config, dict):
        raise mc_servers.DataFileError(config_path(dossier_serveur), "not a JSON object")
    return config

def save_config(config):
    dossier_serveur = config["dossier_serveur"]
    mc_servers._atomic_write_json(config_path(dossier_serveur), config)
    internal = config.get("internal_port") if config.get("sleep_join_mode") == "hold" or config.get("router_backend") else None
    mc_servers.update_cached_ports(dossier_serveur, port=config.get("port"), rcon_port=config.get("rcon_port"),
                                   internal_port=internal)

def _load_templates():
    lang = mc_lang.current_language()
    try:
        data = mc_servers.read_json(WEBHOOK_TEMPLATES_FILE)
    except mc_servers.DataFileError:
        data = None
    if data:
        # Bilingual file: {"fr": {...}, "en": {...}}
        if isinstance(data, dict) and ("fr" in data or "en" in data):
            return data.get(lang) or data.get("fr") or {}
        return data  # legacy single-language file
    return _FALLBACK_WEBHOOKS.get(lang, _FALLBACK_WEBHOOKS["fr"])

def load_webhooks(dossier_serveur):
    templates = _load_templates()
    path = webhooks_path(dossier_serveur)
    try:
        webhooks = mc_servers.read_json(path)
    except mc_servers.DataFileError:
        # A hand-edited webhooks.json with a typo must not block a start or a
        # stop: fall back to the built-in templates and leave the file alone.
        return templates
    if webhooks is None:
        mc_servers._atomic_write_json(path, templates)
        return templates
    if not isinstance(webhooks, dict):
        return templates

    updated = False
    for key, default_val in templates.items():
        if key not in webhooks:
            webhooks[key] = default_val
            updated = True

    if updated:
        mc_servers._atomic_write_json(path, webhooks)

    return webhooks

def detect_default_jar(dossier):
    fallback = "fabric-server-launch.jar"
    if not dossier or not os.path.exists(dossier):
        return fallback
    try:
        # Forge/NeoForge servers launch through a run script (no single runnable
        # jar), so 'mc add' must suggest the script, not a jar.
        script = plat.server_script_name()
        if os.path.exists(os.path.join(dossier, script)):
            return script
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
    print("\n\033[96m=========================================")
    print(f"   {T['install_mc_header']}")
    print("=========================================\033[0m")

    ok, detail = plat.install_launcher()
    if ok:
        print(f"\033[92m[{T['icon_ok']}]\033[0m {T['install_mc_ok']}")
        print(f"\033[90m[{T['icon_info']}]\033[0m {T['install_mc_new_term']}\033[0m")
    elif detail.startswith("permission:"):
        _tag, src, dst = detail.split(":", 2)
        print(f"\033[93m[{T['icon_warn']}]\033[0m {T['install_mc_perms']}")
        print(f"\033[90m[{T['icon_info']}]\033[0m {T['install_mc_manual'].format(src=src, dst=dst)}\033[0m")
    else:
        print(f"\033[91m[{T['icon_err']}]\033[0m {detail}")

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

    config["dossier_serveur"] = os.path.expanduser(smart_ask(T["prompt_dir"], "dossier_serveur", config, default_dir))
    config["dossier_backup"] = os.path.expanduser(smart_ask(T["prompt_backup_dir"], "dossier_backup", config, default_backup))
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
    config["stop_reason"] = "maintenance"
    return config

def resume_mode(config):
    config["mode_maintenance"] = 0
    config.pop("stop_reason", None)
    # Leaving maintenance is a reopening: the restart the daemon is about to
    # perform must be announced. One-shot flag, because the always-on restart
    # path is otherwise silent on purpose (a flapping server would spam Discord
    # every 30 s). Consumed by mc_daemon on the first successful start.
    config["announce_next_start"] = 1
    return config

# Keys 'mc config set' may change, with their validation. Anything else goes
# through 'mc configure' or 'mc edit config'.
def _on_off(value):
    text = str(value).strip().lower()
    if text in ("1", "on", "true", "yes", "oui"):
        return 1
    if text in ("0", "off", "false", "no", "non"):
        return 0
    raise ValueError(value)

def _int_min(minimum):
    def check(v):
        try:
            return int(v) >= minimum
        except (TypeError, ValueError):
            return False
    return check

def _valid_bind(v):
    import mc_metrics
    if v == "":
        return True
    try:
        mc_metrics.parse_bind(v)
        return True
    except ValueError:
        return False

SETTABLE_KEYS = {
    #  key                     (converter, validator)
    "port":                  (int, valid_port),
    "rcon_port":             (int, valid_port),
    "mcrcon_pass":           (str, lambda v: bool(str(v).strip())),
    "ram_allocation":        (str, valid_ram),
    "cpu_affinity":          (str, valid_cpu),
    "jar_name":              (str, lambda v: bool(str(v).strip())),
    "nom_serveur":           (str, lambda v: bool(str(v).strip())),
    "domaine":               (str, lambda v: True),
    "webhook_url":           (str, lambda v: v == "" or str(v).startswith("https://")),
    "dossier_backup":        (str, lambda v: bool(str(v).strip())),
    "backup_retention_days": (int, _int_min(0)),
    "backup_keep":           (int, _int_min(0)),
    "backup_encrypt_key_file": (str, lambda v: v == "" or os.path.isfile(os.path.expanduser(str(v)))),
    "stop_timeout":          (int, _int_min(10)),
    "curseforge_api_key":    (str, lambda v: len(str(v).strip()) >= 20),
    "metrics_bind":          (str, _valid_bind),
    "metrics_allow_remote":  (int, lambda v: v in (0, 1)),
    "sleep_join_mode":       (lambda v: v.lower(), lambda v: v in ("kick", "hold")),
    "sleep_hold_timeout":    (int, lambda v: 10 <= int(v) <= 600),
    "sleep_freeze":          (lambda v: _on_off(v), lambda v: v in (0, 1)),
    "sleep_proxy_protocol":  (lambda v: v.lower(), lambda v: v in ("auto", "on", "off")),
    "internal_port":         (int, valid_port),
}
SECRET_KEYS = ("mcrcon_pass", "webhook_url", "curseforge_api_key", "backup_encrypt_key_file",
               "alerts", "backup_remotes")


def redacted(config):
    """(copy of the config that is safe to print, names of the secret keys
    that are set). Structured secrets keep their shape through
    mc_alert.public / mc_backup.masked; scalar ones become '***'."""
    import mc_alert
    import mc_backup
    shown = {k: v for k, v in config.items() if k != "dossier_serveur"}
    names = []
    for key in SECRET_KEYS:
        if not shown.get(key):
            continue
        names.append(key)
        if key == "alerts":
            shown[key] = [mc_alert.public(c) for c in mc_alert.channels(config)]
        elif key == "backup_remotes":
            shown[key] = [mc_backup.masked(r) for r in shown[key] if isinstance(r, dict)]
        else:
            shown[key] = "***"
    return shown, names


# Changes that only take effect when the server restarts.
RESTART_KEYS = {"port", "rcon_port", "mcrcon_pass", "ram_allocation", "cpu_affinity", "jar_name",
                "sleep_join_mode", "internal_port", "sleep_freeze"}

PAPER_FAMILY = ("paper", "purpur", "folia", "pufferfish")
DEFAULT_MAX_TICK_TIME = "60000"
DEFAULT_SPIGOT_TIMEOUT = "60"

def _paper_like(config):
    return str(config.get("loader") or "").lower() in PAPER_FAMILY

def _fmt_changes(changes):
    return [T["config_updated_file"].format(file="server.properties")] if changes else []

def apply_join_mode(config, name, mode):
    """Switch between 'kick' and 'hold' and move everything that depends on it:
    the server's own port and bind address, the PROXY protocol setting of
    Paper-family servers, the cached ports. Returns (status, detail)."""
    import mc_core
    import mc_servers
    lines = []
    if mc_core.is_suspended(config):
        return "conflict", T["sleep_wake_before_config"]
    if mode == "hold":
        if config.get("sleep_enabled", 0) != 1:
            return "conflict", T["join_mode_needs_sleep"]
        if mc_core.is_proxy(config):
            return "conflict", T["join_mode_not_for_proxy"]
        internal = int(config.get("internal_port") or mc_core.default_internal_port(config.get("port") or 25565))
        for _ in range(20):
            if not 1 <= internal <= 65535:
                return "conflict", T["config_invalid_value"].format(key="internal_port", val=internal)
            clash = (mc_servers.find_port_conflict(port=internal, rcon_port=internal, exclude_name=name)
                     or (name if internal in (int(config.get("port") or 0), int(config.get("rcon_port") or 0)) else None))
            if not clash:
                break
            internal += 1
        else:
            return "conflict", T["config_port_taken"].format(port=internal, name=clash)
        config["internal_port"] = internal
        config["sleep_join_mode"] = "hold"
        save_config(config)
        lines.append(T["config_updated_file"].format(file="config.json"))
        lines += _fmt_changes(mc_core.sync_server_properties(config))
        lines.append(T["join_mode_hold_on"].format(public=config.get("port"), internal=internal))
        yaml = os.path.join(config.get("dossier_serveur", ""), "config", "paper-global.yml")
        if _paper_like(config) and mc_core.paper_proxy_protocol(config) is False \
                and str(config.get("sleep_proxy_protocol", "auto")).lower() != "off":
            mc_core.edit_yaml_scalar(yaml, "proxy-protocol", "true")
            config["proxy_protocol_yaml_managed"] = 1
            save_config(config)
            lines.append(T["join_mode_proxy_enabled"])
        elif not mc_core.use_proxy_protocol(config):
            lines.append(T["join_mode_proxy_unsupported"])
        return "ok", lines

    config["sleep_join_mode"] = "kick"
    if config.get("sleep_freeze"):
        config["sleep_freeze"] = 0
        lines += _release_tick_watchdog(config)
    save_config(config)
    lines.append(T["config_updated_file"].format(file="config.json"))
    lines += _fmt_changes(mc_core.sync_server_properties(config))
    props = os.path.join(config.get("dossier_serveur", ""), "server.properties")
    if not config.get("router_backend") and _read_property(props, "server-ip") == "127.0.0.1":
        lines += _fmt_changes(mc_core.set_properties(config, {"server-ip": ""}))
    if config.pop("proxy_protocol_yaml_managed", None):
        yaml = os.path.join(config.get("dossier_serveur", ""), "config", "paper-global.yml")
        mc_core.edit_yaml_scalar(yaml, "proxy-protocol", "false")
        save_config(config)
        lines.append(T["join_mode_proxy_restored"])
    if not config.get("router_backend"):
        lines.append(T["join_mode_kick_on"])
    return "ok", lines

def _read_property(props, key):
    try:
        with open(props, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                k, sep, v = line.lstrip("\ufeff").partition("=")
                if sep and k.strip() == key:
                    return v.strip()
    except OSError:
        pass
    return None

def _release_tick_watchdog(config):
    """Give back the server's watchdog settings changed for sleep_freeze."""
    import mc_core
    previous = config.pop("sleep_watchdog_previous", None)
    if previous is None:
        return []
    lines = _fmt_changes(mc_core.set_properties(config, {"max-tick-time": previous["max-tick-time"]}))
    spigot = os.path.join(config.get("dossier_serveur", ""), "spigot.yml")
    if previous.get("timeout-time") is not None:
        mc_core.edit_yaml_scalar(spigot, "timeout-time", previous["timeout-time"])
    save_config(config)
    return lines

def apply_freeze(config, name, enabled):
    """sleep_freeze needs hold mode (the JVM keeps its port while stopped, so
    the listener must own the public one) and a server whose watchdog will
    not kill it when it wakes up after hours without a tick."""
    import mc_core
    if mc_core.is_suspended(config):
        return "conflict", T["sleep_wake_before_config"]
    if enabled and not mc_core.freeze_supported():
        return "conflict", T["res_unsupported_on_windows"]
    if enabled and config.get("sleep_join_mode") != "hold":
        return "conflict", T["freeze_needs_hold"]
    if enabled and config.get("sleep_enabled", 0) != 1:
        return "conflict", T["join_mode_needs_sleep"]
    config["sleep_freeze"] = 1 if enabled else 0
    lines = [T["config_updated_file"].format(file="config.json")]
    if enabled:
        props = os.path.join(config.get("dossier_serveur", ""), "server.properties")
        tick = _read_property(props, "max-tick-time") or DEFAULT_MAX_TICK_TIME
        spigot = os.path.join(config.get("dossier_serveur", ""), "spigot.yml")
        timeout = mc_core.edit_yaml_scalar(spigot, "timeout-time", "-1")
        config.setdefault("sleep_watchdog_previous", {"max-tick-time": tick, "timeout-time": timeout})
        lines += _fmt_changes(mc_core.set_properties(config, {"max-tick-time": "-1"}))
        if timeout is not None:
            lines.append(T["config_updated_file"].format(file="spigot.yml"))
        lines.append(T["freeze_watchdog_off"])
    else:
        lines += _release_tick_watchdog(config)
    save_config(config)
    return "ok", lines

def set_value(config, name, key, raw):
    """Validate and apply one setting, then propagate it everywhere it lives:
    config.json (atomic), servers.json (ports), server.properties (ports,
    RCON) and the firewall (game port). Returns (status, detail): status 'ok'
    with a list of what was updated, or 'unknown' / 'invalid' / 'conflict'
    with a message."""
    import mc_core
    import mc_firewall
    if key not in SETTABLE_KEYS:
        return "unknown", T["config_unknown_key"].format(key=key, keys=", ".join(sorted(SETTABLE_KEYS)))
    convert, validate = SETTABLE_KEYS[key]
    try:
        value = convert(str(raw).strip())
    except (TypeError, ValueError):
        return "invalid", T["config_invalid_value"].format(key=key, val=raw)
    if not validate(value):
        return "invalid", T["config_invalid_value"].format(key=key, val=raw)
    if key == "dossier_backup":
        value = os.path.abspath(os.path.expanduser(value))
    if key == "sleep_join_mode":
        return apply_join_mode(config, name, value)
    if key == "sleep_freeze":
        return apply_freeze(config, name, value)
    if key == "internal_port":
        if value in (config.get("port"), config.get("rcon_port")):
            return "conflict", T["config_port_same"].format(port=value)
        clash = mc_servers.find_port_conflict(port=value, rcon_port=value, exclude_name=name)
        if clash:
            return "conflict", T["config_port_taken"].format(port=value, name=clash)

    if key in ("port", "rcon_port"):
        other_key = "rcon_port" if key == "port" else "port"
        if str(config.get(other_key)) == str(value) or str(config.get("internal_port")) == str(value):
            return "conflict", T["config_port_same"].format(port=value)
        # A port must be free among every other server's game AND RCON ports.
        clash = mc_servers.find_port_conflict(port=value, rcon_port=value, exclude_name=name)
        if clash:
            return "conflict", T["config_port_taken"].format(port=value, name=clash)

    old = config.get(key)
    config[key] = value
    save_config(config)
    updated = [T["config_updated_file"].format(file="config.json")]
    if key in ("port", "rcon_port"):
        updated.append(T["config_updated_file"].format(file="servers.json"))
    if key in ("port", "rcon_port", "mcrcon_pass", "internal_port"):
        if mc_core.sync_server_properties(config):
            updated.append(T["config_updated_file"].format(file="server.properties"))
    if key == "port" and old != value:
        ok, manual = mc_firewall.ensure_game_port_rule(value, old_port=old, name=name)
        if ok:
            updated.append(T["firewall_ok"].format(port=value, backend=mc_firewall.detect()))
        else:
            updated.append(_firewall_failure(mc_firewall) + " " + manual)
    return "ok", updated

def run_setup_performance(config):
    print("\n\033[96m=========================================")
    print(f"   {T['section_performance']}")
    print("=========================================\033[0m")
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
    if mc_core.is_run_script(config.get("jar_name", "")):
        print(f"\033[90m[{T['icon_info']}]\033[0m {T['forge_sh_note']}")
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

def _firewall_failure(mc_firewall):
    backend = mc_firewall.detect()
    if backend is None:
        return T["firewall_none"]
    return T["firewall_failed"].format(backend=backend)

def ensure_provisioning(config, dossier_serveur):
    import mc_deploy
    import mc_firewall

    previous_port = load_config(dossier_serveur).get("port")

    print(f"\n\033[93m--- {T['section_prereq']} ---\033[0m")

    import mc_core
    if mc_core.is_proxy(config):
        # Velocity/Waterfall/BungeeCord: no RCON, no server.properties; the
        # port goes into their own config file at every start.
        config["activer_automodpack"] = 0
    elif not config.get("mcrcon_pass"):
        print(f"\033[90m[{T['icon_info']}]\033[0m {T['rcon_not_configured']}")
        config, rcon_pass, rcon_port = mc_deploy.setup_rcon(dossier_serveur, config)
        mc_deploy.generate_server_properties(dossier_serveur, config, rcon_pass, rcon_port)
    else:
        print(f"\033[92m[{T['icon_ok']}]\033[0m {T['rcon_already_ok']}")
        rcon_pass = config.get("mcrcon_pass", "")
        rcon_port = config.get("rcon_port", 25575)
        mc_deploy.generate_server_properties(dossier_serveur, config, rcon_pass, rcon_port)

    print(f"\n\033[93m--- {T['section_firewall']} ---\033[0m")
    port = config.get("port")
    ok, manual_cmd = mc_firewall.ensure_game_port_rule(
        port, old_port=previous_port if previous_port != port else None,
        name=config.get("nom_serveur")
    )
    if ok:
        print(f"\033[92m[{T['icon_ok']}]\033[0m {T['firewall_ok'].format(port=port, backend=mc_firewall.detect())}")
    else:
        print(f"\033[93m[{T['icon_warn']}]\033[0m {_firewall_failure(mc_firewall)}")
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

    print("\033[96m=========================================")
    print(f"   {T['setup_header']}")
    print("=========================================\033[0m")
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

def check_service_unit():
    """Compare the installed service definition with the one this version would
    write. 'mc update' only replaces program files, never the service, so a
    release that changes it is not applied until the installer is re-run.
    Returns (state, differing_directives) with state in 'missing' / 'ok' /
    'outdated'."""
    return plat.service_unit_drift()

def print_unit_check():
    state, diffs = check_service_unit()
    if state == "ok":
        print(f"\033[92m[{T['icon_ok']}]\033[0m {T['unit_ok']}")
        return 0
    if state == "missing":
        print(f"\033[93m[{T['icon_warn']}]\033[0m {T['unit_missing']}")
        return 1
    print(f"\033[93m[{T['icon_warn']}]\033[0m {T['unit_outdated']}")
    for key, have, want in diffs:
        print(f"      {key}: {have if have is not None else '-'} -> {want}")
    print(f"\033[90m[{T['icon_info']}]\033[0m {T['unit_reinstall_hint'].format(path=BASE_DIR)}")
    return 1

def install_daemon_service(user=None):
    print("\n\033[96m=========================================")
    print(f"   {T['daemon_inst_header']}")
    print("=========================================\033[0m")

    os.makedirs(os.path.join(BASE_DIR, "logs"), exist_ok=True)

    ok, detail = plat.service_install(user)
    if detail == "polkit":
        print(f"\033[92m[{T['icon_ok']}]\033[0m {T['polkit_ok'].format(user=user or plat.current_user())}")
    if ok:
        print(f"\033[92m[{T['icon_ok']}]\033[0m {T['daemon_inst_ok'].format(name=SERVICE_NAME)}")
        print(f"\033[92m[{T['icon_ok']}]\033[0m {T['daemon_inst_silent']}")
    else:
        print(f"\033[91m[{T['icon_err']}]\033[0m {T['daemon_inst_failed']}")
        print(f"\033[90m[{T['icon_info']}]\033[0m {T['daemon_inst_rerun']}\033[0m")

if __name__ == "__main__":
    if "--install-only" in sys.argv:
        install_mc_command()
    elif "--install-daemon" in sys.argv:
        install_daemon_service()
    elif "--check-unit" in sys.argv:
        sys.exit(print_unit_check())
    else:
        run_setup()
