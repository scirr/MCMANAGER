import collections
import json
import threading

from .client import ApiError
from .i18n import error_text, t

CONSOLE_LIMIT = 2000
BUSY_STATES = ("starting",)
ACTIONS = ("start", "stop", "restart", "wake")


def thread_spawn(function):
    threading.Thread(target=function, daemon=True).start()


def direct(function, *args):
    function(*args)


class Observable:
    def __init__(self):
        self._observers = []

    def subscribe(self, callback):
        self._observers.append(callback)
        return lambda: self._observers.remove(callback)

    def notify(self, *args):
        for callback in list(self._observers):
            callback(*args)


class Runner:
    """Background work with results marshalled back through `dispatch` (the GTK main loop in the app)."""

    def __init__(self, spawn=thread_spawn, dispatch=direct):
        self.spawn, self.dispatch = spawn, dispatch

    def run(self, work, done):
        def body():
            try:
                outcome = (work(), None)
            except ApiError as exc:
                outcome = (None, exc)
            self.dispatch(done, *outcome)
        self.spawn(body)


def format_ram(rss_kb):
    if not rss_kb:
        return ""
    megabytes = rss_kb / 1024
    return "%.1f GB" % (megabytes / 1024) if megabytes >= 1024 else "%d MB" % megabytes


def row_from(snapshot):
    state = snapshot.get("state") or "unknown"
    return {
        "name": snapshot.get("name") or snapshot.get("server") or "",
        "state": state,
        "state_text": t("state_" + state),
        "online": None,
        "max": None,
        "players": [],
        "rss_kb": snapshot.get("rss_kb"),
        "ram_text": format_ram(snapshot.get("rss_kb")),
        "active": bool(snapshot.get("active")),
        "mode": snapshot.get("mode"),
        "error": snapshot.get("error"),
    }


def players_text(row):
    if row["online"] is None:
        return ""
    if row["max"]:
        return t("players_count_max", online=row["online"], max=row["max"])
    return t("players_count", online=row["online"])


class ServerListModel(Observable):
    """The dashboard: servers with state, players and RAM, kept fresh by /v1/events."""

    def __init__(self, client, runner=None):
        super().__init__()
        self.client, self.runner = client, runner or Runner()
        self.rows = collections.OrderedDict()
        self.error = None
        self.connected = True
        self.loading = False
        self._stream = None

    def refresh(self):
        self.loading = True
        self.notify()
        self.runner.run(self.client.list_servers, self._loaded)

    def _loaded(self, servers, error):
        self.loading = False
        if error:
            self.error = error_text(error.code)
            self.notify()
            return
        self.error = None
        previous = self.rows
        self.rows = collections.OrderedDict()
        for snapshot in servers:
            row = row_from(snapshot)
            old = previous.get(row["name"])
            if old:
                row.update(online=old["online"], max=old["max"], players=old["players"])
            self.rows[row["name"]] = row
            if row["state"] == "running":
                self._fetch_players(row["name"])
        self.notify()

    def _fetch_players(self, name):
        self.runner.run(lambda: self.client.players(name), lambda doc, error: self._players_loaded(name, doc, error))

    def _players_loaded(self, name, document, error):
        row = self.rows.get(name)
        if error or row is None:
            return
        row.update(online=document.get("online"), max=document.get("max"), players=document.get("players") or [])
        self.notify()

    def start_events(self):
        self._stream = self.client.events(self.on_raw_event, self.on_stream_state)
        self._stream.start()

    def stop_events(self):
        if self._stream:
            self._stream.stop()
            self._stream = None

    def on_raw_event(self, name, data):
        try:
            event = json.loads(data)
        except ValueError:
            return
        self.runner.dispatch(self.apply_event, event)

    def on_stream_state(self, state):
        self.runner.dispatch(self.stream_state, state)

    def stream_state(self, state):
        connected = state == "open"
        if connected and not self.connected:
            self.refresh()
        if state in ("lost", "failed"):
            self.connected = False
        elif connected:
            self.connected = True
        self.notify()

    def apply_event(self, event):
        kind = event.get("type")
        row = self.rows.get(event.get("server"))
        if kind == "state":
            if row is None:
                self.refresh()
                return
            row["state"] = event.get("state") or "unknown"
            row["state_text"] = t("state_" + row["state"])
            if row["state"] != "running":
                row.update(online=None, max=None, players=[])
            else:
                self._fetch_players(row["name"])
        elif kind == "players" and row is not None:
            row.update(online=event.get("online"), players=list(event.get("players") or []))
            if event.get("max") is not None:
                row["max"] = event["max"]
        else:
            return
        self.notify()


class ServerDetailModel(Observable):
    """One server: actions with an in-progress state and translated errors."""

    def __init__(self, client, name, runner=None):
        super().__init__()
        self.client, self.name, self.runner = client, name, runner or Runner()
        self.busy = None
        self.error = None
        self.message = None
        self.config = {}
        self.secrets_set = []

    def run_action(self, action):
        if action not in ACTIONS:
            raise ValueError(action)
        if self.busy:
            return False
        self.busy, self.error, self.message = action, None, None
        self.notify()
        self.runner.run(lambda: self._execute(action), lambda _result, error: self._finished(action, error))
        return True

    def _execute(self, action):
        status, document = self.client.action(self.name, action)
        if status == 202:
            self.client.wait_job(document["id"])
        return document

    def _finished(self, action, error):
        self.busy = None
        if error:
            self.error = error_text(error.code)
        else:
            self.message = t("action_%s_done" % action)
        self.notify()

    def load_config(self):
        self.runner.run(lambda: self.client.config(self.name), self._config_loaded)

    def _config_loaded(self, document, error):
        if error:
            self.error = error_text(error.code)
        else:
            self.config = document.get("config") or {}
            self.secrets_set = document.get("secrets_set") or []
        self.notify()

    def can(self, state):
        if self.busy:
            return {action: False for action in ACTIONS}
        return {
            "start": state in ("stopped", "stopped-by-user", "crashed", "closed", "maintenance"),
            "stop": state in ("running", "starting"),
            "restart": state == "running",
            "wake": state == "sleeping",
        }


PLAYER_LISTS = ("whitelist", "op", "ban")


def format_size(size):
    size = float(size or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return "%d %s" % (size, unit) if unit == "B" else "%.1f %s" % (size, unit)
        size /= 1024


def backup_row(entry):
    kind = entry.get("type") or "manual"
    key = "backup_origin_" + kind
    return {
        "id": entry.get("id") or entry.get("file") or "",
        "date": (entry.get("created") or "").replace("T", " "),
        "size": entry.get("size") or 0,
        "size_text": format_size(entry.get("size")),
        "origin": kind,
        "origin_text": t(key) if t(key) != key else kind,
        "encrypted": bool(entry.get("encrypted")),
    }


class BackupsModel(Observable):
    """Backups of one server: list, create and restore as jobs with progress and translated errors."""

    def __init__(self, client, name, runner=None):
        super().__init__()
        self.client, self.name, self.runner = client, name, runner or Runner()
        self.backups = []
        self.busy = None
        self.progress = 0
        self.error = None
        self.message = None

    def load(self):
        self.runner.run(lambda: self.client.list_backups(self.name), self._loaded)

    def _loaded(self, document, error):
        if error:
            self.error = error_text(error.code)
        else:
            self.backups = [backup_row(entry) for entry in document.get("backups") or []]
        self.notify()

    def create(self):
        return self._start("create", lambda: self.client.create_backup(self.name))

    def restore(self, backup_id, confirmed=False):
        if not confirmed or not backup_id:
            return False
        return self._start("restore", lambda: self.client.restore_backup(self.name, backup_id))

    def _start(self, kind, work):
        if self.busy:
            return False
        self.busy, self.progress, self.error, self.message = kind, 0, None, None
        self.notify()
        self.runner.run(lambda: self._execute(work), lambda _result, error: self._finished(kind, error))
        return True

    def _execute(self, work):
        document = work()
        return self.client.wait_job(document["id"], on_progress=self._report)

    def _report(self, value):
        self.runner.dispatch(self._progressed, value)

    def _progressed(self, value):
        self.progress = max(0, min(100, int(value)))
        self.notify()

    def _finished(self, kind, error):
        self.busy = None
        if error:
            self.error = error_text(error.code)
            self.notify()
            return
        self.message = t("backup_%s_done" % kind)
        self.notify()
        self.load()


class PlayersModel(Observable):
    """Whitelist, operators and bans of one server, plus kicking: edits with an in-progress state."""

    def __init__(self, client, name, runner=None):
        super().__init__()
        self.client, self.name, self.runner = client, name, runner or Runner()
        self.lists = {kind: [] for kind in PLAYER_LISTS}
        self.busy = None
        self.error = None
        self.message = None

    def load(self):
        for kind in PLAYER_LISTS:
            self.runner.run(lambda kind=kind: self.client.player_list(self.name, kind),
                            lambda document, error, kind=kind: self._loaded(kind, document, error))

    def _loaded(self, kind, document, error):
        if error:
            self.error = error_text(error.code)
        else:
            self.lists[kind] = [entry for entry in (document.get("entries") or []) if entry.get("name")]
        self.notify()

    def add(self, kind, subject):
        subject = subject.strip()
        if kind not in PLAYER_LISTS or not subject:
            return False
        return self._start((kind, "add", subject), lambda: self.client.add_to_list(self.name, kind, subject),
                           "player_added", subject, kind)

    def remove(self, kind, subject):
        if kind not in PLAYER_LISTS:
            return False
        return self._start((kind, "remove", subject), lambda: self.client.remove_from_list(self.name, kind, subject),
                           "player_removed", subject, kind)

    def kick(self, player):
        return self._start(("kick", "kick", player), lambda: self.client.kick(self.name, player),
                           "player_kicked", player, None)

    def _start(self, busy, work, message, subject, reload_kind):
        if self.busy:
            return False
        self.busy, self.error, self.message = busy, None, None
        self.notify()
        self.runner.run(work, lambda _document, error: self._finished(error, message, subject, reload_kind))
        return True

    def _finished(self, error, message, subject, reload_kind):
        self.busy = None
        if error:
            self.error = error_text(error.code)
            self.notify()
            return
        self.message = t(message, name=subject)
        self.notify()
        if reload_kind:
            self.runner.run(lambda: self.client.player_list(self.name, reload_kind),
                            lambda document, err: self._loaded(reload_kind, document, err))


class ConsoleModel(Observable):
    """Console lines of one server (bounded buffer) and command sending."""

    def __init__(self, client, name, runner=None, limit=CONSOLE_LIMIT):
        super().__init__()
        self.client, self.name, self.runner = client, name, runner or Runner()
        self.lines = collections.deque(maxlen=limit)
        self.error = None
        self.sending = False
        self.state = "idle"
        self._stream = None

    def start(self):
        self._stream = self.client.console(self.name, self.on_raw_line, self.on_stream_state, max_retries=5)
        self._stream.start()

    def stop(self):
        if self._stream:
            self._stream.stop()
            self._stream = None

    def on_raw_line(self, name, data):
        if name == "line":
            self.runner.dispatch(self.add_line, data)

    def on_stream_state(self, state):
        self.runner.dispatch(self.set_state, state)

    def set_state(self, state):
        self.state = state
        if state.startswith("refused:"):
            self.error = error_text("forbidden" if state.endswith("403") else "console_offline")
        self.notify()

    def add_line(self, line):
        self.lines.append(line)
        self.notify()

    def send(self, command):
        command = command.strip()
        if not command or self.sending:
            return False
        self.sending, self.error = True, None
        self.notify()
        self.runner.run(lambda: self.client.send_command(self.name, command), self._sent)
        return True

    def _sent(self, _document, error):
        self.sending = False
        if error:
            self.error = error_text(error.code)
        self.notify()


class ConnectionModel(Observable):
    """First launch: this machine, or a remote server paired with a code."""

    def __init__(self, local_factory, remote_factory, pair, probe, runner=None):
        super().__init__()
        self.local_factory, self.remote_factory = local_factory, remote_factory
        self.pair, self.probe = pair, probe
        self.runner = runner or Runner()
        self.fingerprint = None
        self.error = None
        self.client = None
        self.busy = False

    def use_local(self):
        transport = self.local_factory()
        if transport is None:
            self.error = t("connect_failed")
            self.notify()
            return None
        return self._adopt(transport)

    def use_profile(self, name):
        transport = self.remote_factory(name)
        if transport is None:
            self.error = error_text("not_found")
            self.notify()
            return None
        return self._adopt(transport)

    def _adopt(self, transport):
        from .client import ApiClient
        self.client = ApiClient(transport)
        self.error = None
        self.notify()
        return self.client

    def fetch_fingerprint(self, address):
        self.busy, self.error = True, None
        self.notify()
        self.runner.run(lambda: self.probe(address), self._fingerprint_ready)

    def _fingerprint_ready(self, fingerprint, error):
        self.busy = False
        if error:
            self.error = error_text(error.code)
        else:
            self.fingerprint = fingerprint
        self.notify()

    def submit_pairing(self, address, code, device_name, profile="default"):
        if not self.fingerprint:
            return False
        self.busy, self.error = True, None
        self.notify()
        fingerprint = self.fingerprint
        self.runner.run(lambda: self.pair(address, fingerprint, code.strip(), device_name, profile),
                        lambda remote, error: self._paired(profile, error))
        return True

    def _paired(self, profile, error):
        self.busy = False
        if error:
            self.error = error_text(error.code)
            self.notify()
            return
        self.use_profile(profile)
