import time
from datetime import datetime
import os
import sys
import logging
from logging.handlers import RotatingFileHandler

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(BASE_DIR)

import mc_config
import mc_core
import mc_servers
from mc_lang import T

LOGS_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOGS_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[RotatingFileHandler(
        os.path.join(LOGS_DIR, "daemon.log"),
        maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )]
)

# In-game warning thresholds before a scheduled close (minutes).
WARN_THRESHOLDS = (10, 5, 2, 1)

def is_open_hours(current_m, start_m, end_m):
    if start_m < end_m:
        return start_m <= current_m < end_m
    return current_m >= start_m or current_m < end_m

def _new_state():
    return {
        "last_error": None,
        "backup_milieu_fait": False,
        "noon_backup_date": None,
        "midnight_backup_date": None,
        "warned": set(),
        "missing_logged": False,
    }

def process_server_tick(name, dossier_serveur, state):
    config_file = mc_config.config_path(dossier_serveur)
    if not os.path.exists(config_file):
        if not state["missing_logged"]:
            logging.warning(f"[{name}] config.json not found in {dossier_serveur}, server skipped.")
            state["missing_logged"] = True
        return
    state["missing_logged"] = False

    try:
        config = mc_config.load_config(dossier_serveur)
    except mc_servers.DataFileError as e:
        # Only this server is skipped; log once per distinct error, not every tick.
        if state["last_error"] != str(e):
            logging.error(f"[{name}] config.json unreadable, server skipped until fixed: {e}")
            state["last_error"] = str(e)
        return
    if state["last_error"]:
        logging.info(f"[{name}] config.json readable again, supervision resumed.")
        state["last_error"] = None
    config["dossier_serveur"] = dossier_serveur
    if config.get("mode_maintenance", 0) == 1:
        return

    maintenant = datetime.now()
    current_mins = maintenant.hour * 60 + maintenant.minute
    en_ligne = mc_core.is_server_running(config)
    always_on = config.get("always_on", 1)

    if always_on == 1:
        if not en_ligne:
            # Routine restarts stay silent (a flapping server would spam Discord
            # every 30 s), but the first start after 'mc resume' is a reopening
            # and must be announced.
            announce = config.get("announce_next_start", 0) == 1
            logging.info(f"[{name}] Server offline in 24/7 mode. Restarting...")
            ok, _ = mc_core.start_server(config, send_webhook=announce)
            if ok and announce:
                config.pop("announce_next_start", None)
                mc_config.save_config(config)
            return

        # Date-based triggers with a one-hour window: a tick delayed past the
        # exact minute (long backup of another server, clock drift) must not
        # skip the daily backup for the whole day.
        today = maintenant.strftime("%Y-%m-%d")
        if maintenant.hour == 12 and state["noon_backup_date"] != today:
            logging.info(f"[{name}] Noon backup.")
            mc_core.backup_server(config, "midi")
            state["noon_backup_date"] = today

        if maintenant.hour == 0 and state["midnight_backup_date"] != today:
            logging.info(f"[{name}] Midnight backup.")
            mc_core.backup_server(config, "minuit")
            state["midnight_backup_date"] = today

    else:
        start_mins = int(config.get("heure_ouverture", 20)) * 60 + int(config.get("minute_ouverture", 0))
        end_mins = int(config.get("heure_fermeture", 3)) * 60 + int(config.get("minute_fermeture", 0))

        ouvert = is_open_hours(current_mins, start_mins, end_mins)

        if not ouvert:
            state["backup_milieu_fait"] = False
            state["warned"].clear()

        if ouvert and not en_ligne:
            logging.info(f"[{name}] Open time reached. Starting server...")
            ok, _ = mc_core.start_server(config)
            # This path already announces; just consume the one-shot resume flag
            # so it cannot fire again after a later switch to always-on.
            if ok and config.pop("announce_next_start", None):
                mc_config.save_config(config)

        if ouvert and en_ligne and not state["backup_milieu_fait"]:
            # Elapsed-based trigger: still fires if the tick that matched the
            # exact midpoint minute was missed.
            duree = (end_mins - start_mins) % 1440
            elapsed = (current_mins - start_mins) % 1440
            if elapsed >= duree // 2:
                logging.info(f"[{name}] Mid-session backup.")
                mc_core.backup_server(config, "milieu")
                state["backup_milieu_fait"] = True

        if en_ligne and ouvert:
            mins_restantes = (end_mins - current_mins) % 1440
            if 0 < mins_restantes <= WARN_THRESHOLDS[0]:
                # Warn when a threshold is crossed, not on an exact minute:
                # a delayed tick then warns with the real remaining time.
                bucket = min(b for b in WARN_THRESHOLDS if mins_restantes <= b)
                if bucket not in state["warned"]:
                    msg = T["ingame_closing"].format(mins=mins_restantes)
                    mc_core.send_rcon(config, f"say {msg}")
                    logging.info(f"[{name}] Closing warning sent: {mins_restantes} min.")
                    state["warned"].update(b for b in WARN_THRESHOLDS if b >= bucket)
            else:
                state["warned"].clear()

        if not ouvert and en_ligne:
            logging.info(f"[{name}] Starting nightly shutdown...")

            mc_core.stop_server(config, manual=False)

            patience = 0
            while mc_core.is_server_running(config) and patience < 24:
                time.sleep(5)
                patience += 1

            if mc_core.is_server_running(config):
                logging.warning(f"[{name}] Server did not stop in time. Force killing.")
                mc_core.force_kill_server(config)
                time.sleep(5)

            mc_core.backup_server(config, "fermeture")

            nom = config.get("nom_serveur", "Minecraft")
            templates = mc_config.load_webhooks(dossier_serveur)
            tpl = templates.get("fermeture_nuit") or mc_config.get_fallback_webhook("fermeture_nuit")
            payload = {"embeds": [mc_core._build_embed(tpl, {"nom": nom})]}
            mc_core.send_discord_webhook(config, payload)
            logging.info(f"[{name}] Server stopped and backed up successfully.")

def main():
    logging.info("MC Manager service starting (Windows)...")
    mc_servers.migrate_legacy_single_server()
    states = {}
    servers = {}
    registry_error = None

    while True:
        time.sleep(30)
        # An unreadable servers.json must not make every server disappear:
        # keep supervising the last known list and say so once.
        try:
            servers = mc_servers.list_servers()
            if registry_error:
                logging.info("servers.json readable again.")
                registry_error = None
        except mc_servers.DataFileError as e:
            if registry_error != str(e):
                logging.error(f"servers.json unreadable, keeping the last known server list: {e}")
                registry_error = str(e)
        for name, info in servers.items():
            state = states.setdefault(name, _new_state())
            try:
                process_server_tick(name, info.get("dossier_serveur", ""), state)
            except Exception as e:
                logging.error(f"[{name}] Unexpected error, server skipped this tick: {e}")

if __name__ == "__main__":
    main()
