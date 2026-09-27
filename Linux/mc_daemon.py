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
import mc_api
import mc_ipc
import mc_sleep
import threading
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

is_open_hours = mc_core.is_open_hours

def _reap_children():
    """Collect every server JVM this daemon spawned and that has exited.

    Without it they stay zombies (state Z) for hours: 'kill -0', 'pgrep java'
    and third-party scripts then believe a JVM is still running."""
    while True:
        try:
            pid, _ = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            return
        except Exception:
            return
        if pid == 0:
            return

def _new_state():
    return {
        "idle_since": None,
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

    # A world frozen by 'mc freeze' whose owner never thawed it (script killed,
    # machine rebooted...) is thawed once its deadline passes — even in
    # maintenance, where saving must work again as soon as the server runs.
    if mc_api.is_frozen(config) and mc_api.freeze_expired(config):
        ok, code = mc_api.thaw(config)
        if ok:
            logging.warning(f"[{name}] World freeze expired: saving re-enabled ({code}).")

    if config.get("mode_maintenance", 0) == 1:
        return

    maintenant = datetime.now()
    current_mins = maintenant.hour * 60 + maintenant.minute
    en_ligne = mc_core.is_server_running(config)
    always_on = config.get("always_on", 1)

    if en_ligne and _put_to_sleep_if_idle(name, config, state):
        return
    if not en_ligne:
        state["idle_since"] = None

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
        start_mins, end_mins = mc_core.schedule_minutes(config)

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

            # stop_server waits for the JVM to be really gone and escalates to
            # SIGTERM/SIGKILL itself if the shutdown hangs.
            ok, msg = mc_core.stop_server(config, manual=False)
            logging.info(f"[{name}] {msg}")
            if not ok and mc_core.is_server_running(config):
                logging.warning(f"[{name}] Clean stop impossible (RCON unreachable). Force killing.")
                mc_core.force_kill_server(config)

            mc_core.backup_server(config, "fermeture")

            nom = config.get("nom_serveur", "Minecraft")
            templates = mc_config.load_webhooks(dossier_serveur)
            tpl = templates.get("fermeture_nuit") or mc_config.get_fallback_webhook("fermeture_nuit")
            payload = {"embeds": [mc_core._build_embed(tpl, {"nom": nom})]}
            mc_core.send_discord_webhook(config, payload)
            logging.info(f"[{name}] Server stopped and backed up successfully.")


def _put_to_sleep_if_idle(name, config, state, now=None):
    """Sleep mode: stop a server nobody has played on for sleep_after seconds.
    Returns True if the server was put to sleep. Never during a world freeze,
    never outside opening hours (the nightly close handles those), never when
    the player count is unknown (RCON down)."""
    info = mc_api.sleep_info(config)
    if not info["enabled"]:
        state["idle_since"] = None
        return False
    if config.get("always_on", 1) != 1 and not mc_core.is_open_now(config):
        return False
    ok, players = mc_api.query_players(config)
    if not ok:
        return False
    now = now or time.time()
    if players["online"] > 0:
        state["idle_since"] = None
        return False
    if state["idle_since"] is None:
        state["idle_since"] = now
        return False
    if now - state["idle_since"] < info["after_s"] or mc_api.is_frozen(config):
        return False
    logging.info(f"[{name}] No player for {int(now - state['idle_since']) // 60} min: going to sleep.")
    result = mc_api.stop(name, config, reason="sleep")
    logging.info(f"[{name}] Sleep: {result['code']} {result.get('message') or ''}".rstrip())
    state["idle_since"] = None
    return result["ok"]


class SleepManager:
    """Owns one SleepListener per sleeping server and the wake queue."""

    KNOWN_REFRESH = 60

    def __init__(self):
        self.listeners = {}
        self.wakes = []
        self.lock = threading.Lock()
        self.retry_after = {}
        self._known = set()
        self._known_at = 0

    def known(self):
        if time.time() - self._known_at > self.KNOWN_REFRESH:
            dirs, extra = [], []
            try:
                for info in mc_servers.list_servers().values():
                    dossier = info.get("dossier_serveur", "")
                    dirs.append(dossier)
                    try:
                        extra += mc_config.load_config(dossier).get("sleep_allow", [])
                    except Exception:
                        pass
            except Exception:
                pass
            self._known = mc_sleep.known_players(dirs, extra)
            self._known_at = time.time()
        return self._known

    @staticmethod
    def should_listen(config):
        return (mc_api.sleep_info(config)["enabled"]
                and config.get("mode_maintenance", 0) == 1
                and config.get("stop_reason") == "sleep"
                and not mc_core.is_server_running(config))

    def sync(self, servers):
        for name, info in servers.items():
            dossier = info.get("dossier_serveur", "")
            try:
                config = mc_config.load_config(dossier)
            except Exception:
                continue
            config["dossier_serveur"] = dossier
            listener = self.listeners.get(name)
            wanted = self.should_listen(config)
            if listener and (not wanted or not listener.is_alive()
                             or listener.port != int(config.get("port") or 0)):
                self.release(name)
                listener = None
            if wanted and not listener and config.get("port") \
                    and time.time() >= self.retry_after.get(name, 0):
                self._listen(name, dossier, config)
        for name in list(self.listeners):
            if name not in servers:
                self.release(name)

    def release(self, name):
        listener = self.listeners.pop(name, None)
        if listener:
            listener.stop()
            logging.info(f"[{name}] Sleep listener closed (port {listener.port}).")

    def release_port(self, port):
        for name, listener in list(self.listeners.items()):
            if listener.port == int(port or 0):
                self.release(name)

    def _listen(self, name, dossier, config):
        def status():
            fresh = mc_config.load_config(dossier)
            nom = fresh.get("nom_serveur", name)
            return (T["sleep_motd"].format(name=nom), _max_players(dossier),
                    fresh.get("mc_version") or "Minecraft", mc_sleep.server_favicon(dossier))

        def on_login(player):
            return self.decide(name, dossier, player)

        def on_error(msg):
            logging.warning(f"[{name}] Sleep listener cannot hold port {config.get('port')}: {msg}. Retrying in 60 s.")
            self.retry_after[name] = time.time() + 60

        listener = mc_sleep.SleepListener(name, config["port"], status, on_login, on_error)
        listener.start()
        self.listeners[name] = listener
        logging.info(f"[{name}] Sleeping: listener on port {config['port']}.")

    def decide(self, name, dossier, player):
        """Runs in a listener thread: may this player wake the server?"""
        try:
            config = mc_config.load_config(dossier)
        except Exception:
            return T["sleep_kick_unavailable"]
        config["dossier_serveur"] = dossier
        if player.lower() not in self.known():
            logging.info(f"[{name}] Wake refused: unknown player '{player}'.")
            return T["sleep_kick_unknown"]
        if mc_api.is_frozen(config):
            logging.info(f"[{name}] Wake postponed for '{player}': world frozen (backup running).")
            return T["sleep_kick_backup"]
        if config.get("always_on", 1) != 1 and not mc_core.is_open_now(config):
            start, _end = mc_core.schedule_minutes(config)
            return T["sleep_kick_closed"].format(time="%02d:%02d" % divmod(start, 60))
        if config.get("stop_reason") != "sleep":
            return T["sleep_kick_starting"]
        with self.lock:
            if name not in self.wakes:
                self.wakes.append(name)
                logging.info(f"[{name}] Wake requested by '{player}'.")
        return T["sleep_kick_waking"]

    def pop_wakes(self):
        with self.lock:
            wakes, self.wakes = self.wakes, []
        return wakes


def _max_players(dossier):
    try:
        with open(os.path.join(dossier, "server.properties"), encoding="utf-8-sig", errors="replace") as f:
            for line in f:
                if line.startswith("max-players="):
                    return int(line.split("=", 1)[1].strip())
    except Exception:
        pass
    return 20


def _handle_request(sleep, request):
    """Serve one request from the CLI (see mc_ipc)."""
    action, params = request.get("action"), request.get("params") or {}
    if action == "start":
        loaded, error = mc_api.load_server(params.get("server"))
        if error:
            return error
        name, config = loaded
        sleep.release(name)
        sleep.release_port(config.get("port"))
        res = mc_api.start(name, config)
        if res["ok"] and config.pop("announce_next_start", None):
            mc_config.save_config(config)
        logging.info(f"[{name}] Start requested from the command line: {res['code']}.")
        return res
    return mc_api.result(False, "unknown_action", action=action)


def _process_wakes(sleep):
    for name in sleep.pop_wakes():
        loaded, error = mc_api.load_server(name)
        if error:
            continue
        _, config = loaded
        sleep.release(name)
        res = mc_api.wake(name, config)
        logging.info(f"[{name}] Wake: {res['code']}.")

def main():
    logging.info("MC Manager service starting (Linux)...")
    mc_api.IN_DAEMON = True
    mc_servers.migrate_legacy_single_server()
    states = {}
    servers = {}
    registry_error = None
    sleep = SleepManager()
    next_tick = time.time() + 30
    next_sync = 0

    # One-second loop: requests from the command line and wakes are served
    # promptly; supervision still runs every 30 seconds.
    while True:
        time.sleep(1)
        mc_ipc.beat()
        _reap_children()

        for request_id, request in mc_ipc.pending_requests():
            try:
                answer = _handle_request(sleep, request)
            except Exception as e:
                logging.error(f"Request {request.get('action')} failed: {e}")
                answer = mc_api.result(False, "daemon_error", detail=str(e))
            mc_ipc.respond(request_id, answer)

        try:
            _process_wakes(sleep)
        except Exception as e:
            logging.error(f"Wake failed: {e}")

        now = time.time()
        if now >= next_sync or now >= next_tick:
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

        if now >= next_sync:
            next_sync = now + 5
            try:
                sleep.sync(servers)
            except Exception as e:
                logging.error(f"Sleep listeners: {e}")

        if now < next_tick:
            continue
        next_tick = now + 30
        for name, info in servers.items():
            state = states.setdefault(name, _new_state())
            try:
                process_server_tick(name, info.get("dossier_serveur", ""), state)
            except Exception as e:
                logging.error(f"[{name}] Unexpected error, server skipped this tick: {e}")

if __name__ == "__main__":
    main()
