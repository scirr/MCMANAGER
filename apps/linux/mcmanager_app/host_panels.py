from .i18n import t
from .models import Observable
from .panels import PanelModel

ALERT_TYPES = ("email", "telegram", "ntfy", "webhook", "discord")
ALERT_FIELDS = {
    "email": (("host", "text"), ("port", "text"), ("user", "text"), ("password", "secret"), ("sender", "text"),
              ("to", "text")),
    "telegram": (("token", "secret"), ("chat_id", "text")),
    "ntfy": (("server", "text"), ("topic", "text"), ("token", "secret")),
    "webhook": (("url", "secret"), ("secret", "secret")),
    "discord": (("url", "secret"),),
}
ALERT_EVENTS = ("start", "stop", "crash", "crash_loop", "backup_failed", "update", "sleep", "wake")
ROLES = ("viewer", "operator", "admin")
JAVA_MAJORS = ("8", "11", "17", "21", "25")
NOTIFY_KINDS = ("crash", "backup_failed", "join")
NOTIFY_ALERTS = {"crash": ("crash", "crash_loop"), "backup_failed": ("backup_failed",)}


def alert_row(entry):
    events = entry.get("events") or []
    return {
        "name": entry.get("name") or "",
        "type": entry.get("type") or "",
        "type_text": t("alert_type_" + (entry.get("type") or "")),
        "events_text": ", ".join(t("alert_event_" + event) if event != "*" else t("alert_event_all") for event in events),
        "legacy": bool(entry.get("legacy")),
        "target": entry.get("topic") or entry.get("host") or entry.get("chat_id") or "",
    }


class AlertsModel(PanelModel):
    """Alert channels of one server: list, add, test, remove. Secret values are only ever sent, never shown."""

    def __init__(self, client, name, runner=None):
        super().__init__(client, runner)
        self.name = name
        self.channels = []

    def load(self):
        self._fetch(lambda: self.client.alert_channels(self.name), self._loaded)

    def _loaded(self, document):
        self.channels = [alert_row(entry) for entry in document.get("channels") or []]

    def add(self, kind, fields, events=(), channel_name=""):
        if kind not in ALERT_TYPES:
            return False
        events = [event for event in events if event in ALERT_EVENTS]
        wanted = {key: (fields.get(key) or "").strip() for key, _kind in ALERT_FIELDS[kind]}
        port = wanted.get("port")
        if port and not (port.isdigit() and 0 < int(port) < 65536):
            return self._refuse("bad_port")
        if port:
            wanted["port"] = int(port)
        return self._start("add", lambda: self.client.add_alert(self.name, kind, ",".join(events) or None,
                                                                channel_name.strip() or None, **wanted),
                           lambda result: t("alert_added", name=result.get("channel") or kind),
                           then=lambda _r: self.load())

    def test(self, channel=None):
        return self._start("test", lambda: self.client.send_alert_test(self.name, channel), "alert_test_done")

    def remove(self, channel, confirmed=False):
        if not confirmed or not channel:
            return False
        return self._start("remove", lambda: self.client.remove_alert(self.name, channel),
                           lambda _r: t("alert_removed", name=channel), then=lambda _r: self.load())

    def _fail(self, error):
        super()._fail(error)
        if error.code == "alert_test_failed":
            failed = (error.document or {}).get("failed")
            if failed:
                self.error = t("alert_test_failed_for", name=failed)


def runtime_rows(document):
    runtimes = document.get("runtimes") or {}
    used = {}
    for entry in document.get("servers") or []:
        used.setdefault(str(entry.get("java")), []).append(entry.get("server"))
    return [{"major": major, "path": str(runtimes[major]), "servers": used.get(major, [])}
            for major in sorted(runtimes, key=lambda value: (len(value), value))]


class JavaModel(PanelModel):
    """Java runtimes installed by MC Manager: install (a job) and remove."""

    def __init__(self, client, runner=None):
        super().__init__(client, runner)
        self.runtimes = []

    def load(self):
        self._fetch(self.client.java_runtimes, self._loaded)

    def _loaded(self, document):
        self.runtimes = runtime_rows(document)

    def installable(self):
        installed = {row["major"] for row in self.runtimes}
        return [major for major in JAVA_MAJORS if major not in installed]

    def install(self, major):
        if not str(major).isdigit() or int(major) < 8:
            return self._refuse("java_unknown_version")
        return self._start("install", lambda: self.client.install_java(major),
                           lambda _r: t("java_installed", major=major), job=True, then=lambda _r: self.load())

    def remove(self, major, confirmed=False):
        if not confirmed or not str(major).isdigit():
            return False
        return self._start("remove", lambda: self.client.remove_java(major),
                           lambda _r: t("java_removed", major=major), then=lambda _r: self.load())


def device_row(entry):
    roles = entry.get("roles") or {}
    scope = entry.get("servers")
    return {
        "id": entry.get("id") or "",
        "name": entry.get("name") or entry.get("id") or "",
        "role": roles.get("default") or "viewer",
        "role_text": t("role_" + (roles.get("default") or "viewer")),
        "servers": list(scope) if scope else [],
        "last_seen": (entry.get("last_seen") or "").replace("T", " "),
        "last_ip": entry.get("last_ip") or "",
        "revoked": bool(entry.get("revoked")),
    }


def audit_row(entry):
    return {
        "at": (entry.get("at") or "").replace("T", " "),
        "action": entry.get("action") or "",
        "device": entry.get("device") or "",
        "server": entry.get("server") or "",
        "ok": bool(entry.get("ok")),
        "result": entry.get("result") or "",
    }


class DevicesModel(PanelModel):
    """Remote access: status, paired devices (roles, revocation), pairing codes and the audit log."""

    def __init__(self, client, runner=None):
        super().__init__(client, runner)
        self.devices = []
        self.audit = []
        self.remote = {}
        self.code = None

    def load(self):
        self._fetch(self.client.devices, self._devices_loaded)
        self._fetch(self.client.remote_status, self._remote_loaded)
        self._fetch(lambda: self.client.audit_log(50), self._audit_loaded)

    def _devices_loaded(self, document):
        self.devices = [device_row(entry) for entry in document.get("devices") or [] if not entry.get("revoked")]

    def _remote_loaded(self, document):
        self.remote = {"enabled": bool(document.get("enabled")), "bind": document.get("bind") or "",
                       "fingerprint": document.get("fingerprint") or ""}

    def _audit_loaded(self, document):
        self.audit = [audit_row(entry) for entry in document.get("entries") or []]

    def set_remote(self, enabled):
        if bool(enabled) == self.remote.get("enabled"):
            return False
        return self._start("remote", lambda: self.client.set_remote_access(enabled),
                           "remote_enabled" if enabled else "remote_disabled", then=lambda _r: self.load())

    def new_code(self, name="", role="operator"):
        if role not in ROLES:
            return False
        self.code = None
        return self._start("code", lambda: self.client.pairing_code(name.strip() or None, role), "pair_code_ready",
                           then=self._code_ready)

    def _code_ready(self, document):
        self.code = {"code": document.get("pairing_code") or "", "minutes": max(1, int(document.get("expires_in_s") or 0) // 60)}
        self.notify()

    def set_role(self, device, role):
        if role not in ROLES:
            return False
        return self._start("role", lambda: self.client.set_device_roles(device, role), "device_role_saved",
                           then=lambda _r: self.load())

    def revoke(self, device, confirmed=False):
        if not confirmed or not device:
            return False
        return self._start("revoke", lambda: self.client.revoke_device(device), "device_revoked",
                           then=lambda _r: self.load())


class UpdateModel(PanelModel):
    """MC Manager updates: check, install (a job), roll back."""

    def __init__(self, client, runner=None):
        super().__init__(client, runner)
        self.info = {}

    def load(self):
        self._fetch(self.client.check_update, self._loaded)

    def _loaded(self, document):
        self.info = {"current": document.get("current") or "", "latest": document.get("latest") or "",
                     "available": bool(document.get("update_available")),
                     "rollback": bool(document.get("rollback_available"))}

    def apply(self, confirmed=False):
        if not confirmed or not self.info.get("available"):
            return False
        return self._start("update", lambda: self.client.apply_update(), lambda _r: t("update_done"), job=True,
                           then=lambda _r: self.load())

    def rollback(self, confirmed=False):
        if not confirmed or not self.info.get("rollback"):
            return False
        return self._start("rollback", self.client.rollback_update, lambda _r: t("update_rolled_back"),
                           then=lambda _r: self.load())


def check_row(entry):
    level = entry.get("level") or ("ok" if entry.get("ok") else "err")
    return {"server": entry.get("server") or "", "name": entry.get("name") or "", "level": level,
            "detail": entry.get("detail") or "", "fix": entry.get("fix") or ""}


class DoctorModel(PanelModel):
    """Diagnostics of the host and of every server."""

    def __init__(self, client, runner=None):
        super().__init__(client, runner)
        self.checks = []
        self.errors = self.warnings = 0

    def load(self):
        self._start("doctor", self.client.doctor, lambda _r: t("doctor_done"), then=None)

    def _finished(self, message, then, result, error):
        self.busy = None
        if error:
            self._fail(error)
        else:
            self.checks = [check_row(entry) for entry in result.get("checks") or []]
            self.errors, self.warnings = result.get("errors") or 0, result.get("warnings") or 0
        self.notify()

    def summary(self):
        if self.errors:
            return t("doctor_errors", count=self.errors)
        return t("doctor_warnings", count=self.warnings) if self.warnings else t("doctor_clean")


def router_state(document):
    config = document.get("config") or {}
    return {
        "enabled": bool(config.get("enabled")),
        "port": config.get("port"),
        "default": config.get("default") or "",
        "routes": sorted((config.get("routes") or {}).items()),
        "allow": list(config.get("allow") or []),
        "deny": list(config.get("deny") or []),
        "pending": list(document.get("pending_restart") or []),
    }


class RouterModel(PanelModel):
    """Hostname router in front of several servers."""

    def __init__(self, client, runner=None):
        super().__init__(client, runner)
        self.state = router_state({})
        self.servers = []

    def load(self):
        self._fetch(self.client.router, self._loaded)
        self._fetch(self.client.list_servers_names, self._servers_loaded)

    def _loaded(self, document):
        self.state = router_state(document)

    def _servers_loaded(self, names):
        self.servers = list(names)

    def _change(self, kind, work, message):
        return self._start(kind, work, message, then=lambda _r: self.load())

    def toggle(self, enabled):
        if bool(enabled) == self.state["enabled"]:
            return False
        if enabled:
            return self._change("router", self.client.enable_router, "router_enabled")
        return self._change("router", self.client.disable_router, "router_disabled")

    def add_route(self, host, server):
        host = host.strip().lower()
        if not host or server not in self.servers:
            return self._refuse("invalid_value")
        return self._change("route", lambda: self.client.set_route(host, server), "route_saved")

    def remove_route(self, host, confirmed=False):
        if not confirmed or not host:
            return False
        return self._change("route", lambda: self.client.remove_route(host), "route_removed")

    def set_default(self, server):
        if server not in self.servers or server == self.state["default"]:
            return False
        return self._change("default", lambda: self.client.set_router_default(server), "router_default_saved")

    def edit_access(self, kind, action, cidr):
        cidr = cidr.strip()
        if kind not in ("allow", "deny") or action not in ("add", "remove") or not cidr:
            return False
        return self._change("access", lambda: self.client.edit_router_access(kind, action, cidr), "router_access_saved")


class NotificationPrefs(Observable):
    """Which events raise a desktop notification; persisted through the `store` callbacks."""

    def __init__(self, load=None, save=None):
        super().__init__()
        self.save = save
        saved = (load() if load else None) or {}
        self.enabled = {kind: bool(saved.get(kind, True)) for kind in NOTIFY_KINDS}

    def set(self, kind, value):
        if kind not in self.enabled or self.enabled[kind] == bool(value):
            return
        self.enabled[kind] = bool(value)
        if self.save:
            self.save(dict(self.enabled))
        self.notify()


def notification_for(event, prefs):
    """Maps an /v1/events payload to (id, title, body), or None when it should stay silent."""
    kind = event.get("type")
    server = event.get("server") or ""
    if kind == "alert":
        name = event.get("event")
        for pref, names in NOTIFY_ALERTS.items():
            if name in names and prefs.enabled.get(pref):
                return ("%s-%s" % (name, server), t("notify_" + name, server=server), event.get("detail") or "")
    elif kind == "players" and prefs.enabled.get("join"):
        joined = event.get("joined") or []
        if joined:
            return ("join-" + server, t("notify_join", server=server), ", ".join(joined))
    return None


class NotificationsModel:
    """Turns the event stream of the server list into notifications, one system notification per event."""

    def __init__(self, prefs, send):
        self.prefs, self.send = prefs, send

    def on_event(self, event):
        found = notification_for(event, self.prefs)
        if found:
            self.send(*found)
