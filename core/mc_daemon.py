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
import mc_crash
import mc_servers
import mc_api
import mc_ipc
import mc_proxy
import mc_router
import mc_sleep
import mc_task
import mc_metrics
import mc_statuspage
import threading
from mc_lang import T
from mc_platform import plat

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
    plat.reap_children()

def _new_state():
    return {
        "idle_since": None,
        "last_error": None,
        "backup_milieu_fait": False,
        "noon_backup_date": None,
        "midnight_backup_date": None,
        "warned": set(),
        "missing_logged": False,
        "expected_up": False,
        "launched_at": None,
        "crash_logged": False,
        "tasks_fired": {},
        "task_thread": None,
    }


def _watch_crash(name, config, state, en_ligne, now=None):
    """Track whether the server stays up. An exit nobody asked for is recorded;
    a startup failure, or repeated exits in a short time, mark it crashed so
    the daemon stops relaunching it."""
    now = now or time.time()
    if en_ligne:
        state["expected_up"] = True
        if mc_crash.is_crashed(config) and mc_core.server_ready(config):
            mc_crash.clear(config)
            state["crash_logged"] = False
            logging.info(f"[{name}] Server is up again, crash state cleared.")
        return
    if not state["expected_up"]:
        return
    state["expected_up"] = False
    since = state["launched_at"]
    startup = not mc_core.log_has_done(config, since)
    state["launched_at"] = None
    marker, newly = mc_crash.record_failure(config, startup, now)
    logging.error(f"[{name}] Server exited unexpectedly "
                  f"({'before startup finished' if startup else 'after startup'}); "
                  f"{len(marker['failures'])} failure(s) in the last {mc_crash.WINDOW // 60} min.")
    if newly:
        logging.error(f"[{name}] Crash loop: automatic restarts stopped. Fix the cause, then run 'mc resume'.")
        state["crash_logged"] = True
        _announce_crash(name, config, marker)
    else:
        mc_core._alert(config, "crash", detail="\n".join(mc_crash.recent_errors(config["dossier_serveur"], 3)))


def _announce_crash(name, config, marker):
    try:
        nom = config.get("nom_serveur", name)
        errors = mc_crash.recent_errors(config["dossier_serveur"], 5)
        detail = "\n".join(errors)[-900:] or "-"
        templates = mc_config.load_webhooks(config["dossier_serveur"])
        tpl = templates.get("crash_loop") or mc_config.get_fallback_webhook("crash_loop")
        variables = {"nom": nom, "count": len(marker.get("failures", [])), "errors": detail}
        mc_core.send_discord_webhook(config, {"embeds": [mc_core._build_embed(tpl, variables)]})
        mc_core._alert(config, "crash_loop", detail=detail)
    except Exception as e:
        logging.warning(f"[{name}] Crash announcement failed: {e}")


def _task_worker(name, dossier, task, target):
    try:
        config = mc_config.load_config(dossier)
        config["dossier_serveur"] = dossier
        res = mc_task.execute(name, config, task, target=target)
        level = logging.INFO if res["ok"] else logging.WARNING
        logging.log(level, f"[{name}] Task '{task.get('name')}' ({task.get('action')}): {res['code']}")
        mc_task.record_run(config, task.get("id"), res["ok"], res["code"])
    except Exception as e:
        logging.error(f"[{name}] Task '{task.get('name')}' crashed: {e}")


def _launch_task(name, dossier, task, target):
    thread = threading.Thread(target=_task_worker, args=(name, dossier, task, target), daemon=True)
    thread.start()
    return thread


def _run_tasks(name, config, state, now=None):
    """Start the scheduled tasks that are due. One task at a time per server:
    a task can wait minutes (in-game warnings) without blocking the loop."""
    if not mc_task.tasks_of(config):
        return
    for task, target in mc_task.due_tasks(config, state["tasks_fired"], now or datetime.now()):
        thread = state.get("task_thread")
        if thread is not None and thread.is_alive():
            logging.warning(f"[{name}] Task '{task.get('name')}' skipped: another task is still running.")
            mc_task.record_run(config, task.get("id"), False, "task_busy")
            continue
        logging.info(f"[{name}] Task '{task.get('name')}' ({task.get('action')}) due at {target:%H:%M}.")
        state["task_thread"] = _launch_task(name, config["dossier_serveur"], task, target)


def _may_start(name, config, state):
    if mc_crash.may_start(config):
        state["crash_logged"] = False
        return True
    if not state["crash_logged"] and mc_crash.is_crashed(config):
        logging.warning(f"[{name}] Server is marked crashed: not restarting it. Run 'mc resume' once fixed.")
        state["crash_logged"] = True
    return False


def _launch(name, config, state, **kwargs):
    state["launched_at"] = time.time()
    ok, message = mc_core.start_server(config, **kwargs)
    if ok:
        state["expected_up"] = True
    else:
        state["launched_at"] = None
        marker = mc_crash.read(config)
        if marker and marker.get("crashed") and not state["crash_logged"]:
            logging.error(f"[{name}] Server died while starting: automatic restarts stopped. Fix the cause, then run 'mc resume'.")
            state["crash_logged"] = True
            _announce_crash(name, config, marker)
    return ok, message

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

    _run_tasks(name, config, state)

    if config.get("mode_maintenance", 0) == 1:
        state["expected_up"] = False
        return

    if mc_core.is_suspended(config):
        state["idle_since"] = None
        return

    maintenant = datetime.now()
    current_mins = maintenant.hour * 60 + maintenant.minute
    en_ligne = mc_core.is_server_running(config)
    always_on = config.get("always_on", 1)

    _watch_crash(name, config, state, en_ligne)

    if en_ligne and _put_to_sleep_if_idle(name, config, state):
        return
    if not en_ligne:
        state["idle_since"] = None

    if always_on == 1:
        if not en_ligne:
            # Routine restarts stay silent (a flapping server would spam Discord
            # every 30 s), but the first start after 'mc resume' is a reopening
            # and must be announced.
            if not _may_start(name, config, state):
                return
            announce = config.get("announce_next_start", 0) == 1
            logging.info(f"[{name}] Server offline in 24/7 mode. Restarting...")
            ok, _ = _launch(name, config, state, send_webhook=announce)
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

        if ouvert and not en_ligne and _may_start(name, config, state):
            logging.info(f"[{name}] Open time reached. Starting server...")
            ok, _ = _launch(name, config, state)
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
            state["expected_up"] = False

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
            mc_core._alert(config, "stop", reason="closing")
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
    if info["freeze"] and info["join_mode"] == "hold":
        result = mc_api.suspend(name, config)
        logging.info(f"[{name}] Sleep (frozen): {result['code']}")
        state["idle_since"] = None
        return result["ok"]
    state["expected_up"] = False
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
        if config.get("router_backend") or not mc_api.sleep_info(config)["enabled"]:
            return False
        if mc_core.is_hold_mode(config):
            return config.get("mode_maintenance", 0) != 1 or config.get("stop_reason") == "sleep"
        return (config.get("mode_maintenance", 0) == 1
                and config.get("stop_reason") == "sleep"
                and not mc_core.is_server_running(config))

    @staticmethod
    def signature(config):
        if not mc_core.is_hold_mode(config):
            return (int(config.get("port") or 0), None)
        return (int(config.get("port") or 0), mc_core.game_port(config), mc_core.use_proxy_protocol(config),
                int(config.get("sleep_hold_timeout", mc_api.DEFAULT_HOLD_TIMEOUT)))

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
                             or listener.signature != self.signature(config)):
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

        hold = self._hold_policy(name, dossier, config)
        listener = mc_sleep.SleepListener(name, config["port"], status, on_login, on_error, hold=hold,
                                          banned=mc_proxy.BannedIPs(os.path.join(dossier, "banned-ips.json")))
        listener.signature = self.signature(config)
        listener.start()
        self.listeners[name] = listener
        mode = "hold" if hold else "sleep"
        logging.info(f"[{name}] Listener ({mode}) on port {config['port']}.")

    def _hold_policy(self, name, dossier, config, routed=False):
        if not routed and not mc_core.is_hold_mode(config):
            return None

        def fresh():
            cfg = mc_config.load_config(dossier)
            cfg["dossier_serveur"] = dossier
            return cfg

        policy = mc_sleep.HoldPolicy(
            mc_core.game_port(config),
            timeout=int(config.get("sleep_hold_timeout", mc_api.DEFAULT_HOLD_TIMEOUT)),
            proxy_protocol=mc_core.use_proxy_protocol(config),
            on_hold=lambda player: self.evaluate(name, dossier, player))
        plain_probe = policy.probe
        ready_until = [0.0]

        def probe():
            try:
                cfg = fresh()
                if mc_core.is_suspended(cfg):
                    return mc_sleep.BACKEND_SUSPENDED
                if cfg.get("mode_maintenance") == 1 or not mc_core.is_server_running(cfg):
                    return mc_sleep.BACKEND_DOWN
            except Exception:
                return mc_sleep.BACKEND_DOWN
            return plain_probe()

        def ready():
            if time.time() < ready_until[0]:
                return True
            try:
                ok = mc_core.server_ready(fresh())
            except Exception:
                return False
            if ok:
                ready_until[0] = time.time() + 10
            return ok

        policy.probe, policy.ready = probe, ready
        return policy

    def decide(self, name, dossier, player):
        """Runs in a listener thread: may this player wake the server?
        Returns the text shown to the player."""
        return self.evaluate(name, dossier, player)[1]

    def evaluate(self, name, dossier, player):
        """(accepted, text): accepted when the server is waking or starting up
        for this player, so that hold mode keeps the connection."""
        try:
            config = mc_config.load_config(dossier)
        except Exception:
            return False, T["sleep_kick_unavailable"]
        config["dossier_serveur"] = dossier
        if player.lower() not in self.known():
            logging.info(f"[{name}] Wake refused: unknown player '{player}'.")
            return False, T["sleep_kick_unknown"]
        if mc_api.is_frozen(config):
            logging.info(f"[{name}] Wake postponed for '{player}': world frozen (backup running).")
            return False, T["sleep_kick_backup"]
        if config.get("always_on", 1) != 1 and not mc_core.is_open_now(config):
            start, _end = mc_core.schedule_minutes(config)
            return False, T["sleep_kick_closed"].format(time="%02d:%02d" % divmod(start, 60))
        if config.get("mode_maintenance") == 1 and config.get("stop_reason") != "sleep":
            return False, T["sleep_kick_unavailable"]
        if config.get("stop_reason") != "sleep" and not mc_core.is_suspended(config):
            return mc_core.is_server_running(config), T["sleep_kick_starting"]
        with self.lock:
            if name not in self.wakes:
                self.wakes.append(name)
                logging.info(f"[{name}] Wake requested by '{player}'.")
        return True, T["sleep_kick_waking"]

    def pop_wakes(self):
        with self.lock:
            wakes, self.wakes = self.wakes, []
        return wakes


class RouterManager:
    def __init__(self, sleep):
        self.sleep = sleep
        self.listener = None
        self.config = None
        self.retry_at = 0

    def resolve(self, name):
        loaded, error = mc_api.load_server(name)
        if error:
            return None
        name, config = loaded
        dossier = config["dossier_serveur"]
        if not config.get("router_backend"):
            return None
        policy = self.sleep._hold_policy(name, dossier, config, routed=True)
        return mc_router.Target(
            policy, lambda: (T["sleep_motd"].format(name=config.get("nom_serveur", name)),
                             _max_players(dossier), config.get("mc_version", "Minecraft"),
                             mc_sleep.server_favicon(dossier)),
            mc_proxy.BannedIPs(os.path.join(dossier, "banned-ips.json")))

    def sync(self):
        config = mc_router.load()
        if self.listener and (config != self.config or not self.listener.is_alive()):
            self.listener.stop()
            self.listener = None
        if not config["enabled"] or self.listener or time.monotonic() < self.retry_at:
            return
        self.config = config
        self.retry_at = time.monotonic() + 5
        self.listener = mc_router.RouterListener(
            config, self.resolve, lambda message: logging.warning(T["router_listener_error"].format(message=message)))
        self.listener.start()


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
        if not mc_core.is_hold_mode(config):
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
        if not mc_core.is_hold_mode(config):
            sleep.release(name)
        res = mc_api.wake(name, config)
        logging.info(f"[{name}] Wake: {res['code']}.")

def main():
    logging.info(f"MC Manager service starting ({plat.os_name()})...")
    mc_api.IN_DAEMON = True
    mc_servers.migrate_legacy_single_server()
    states = {}
    servers = {}
    registry_error = None
    sleep = SleepManager()
    metrics = mc_metrics.DaemonEndpoint()
    status_pages = mc_statuspage.Publisher()
    router = RouterManager(sleep)
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
                router.sync()
            except Exception as e:
                logging.error(f"Sleep listeners: {e}")
            try:
                metrics.sync(servers)
            except Exception as e:
                logging.error(f"Metrics endpoint: {e}")
            try:
                status_pages.run(servers)
            except Exception as e:
                logging.error(f"Status pages: {e}")

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
