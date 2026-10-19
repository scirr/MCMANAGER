import re

from .i18n import error_text, t
from .models import Observable, Runner, format_size

TASK_ACTIONS = ("restart", "backup", "command", "stop", "start")
WARN_ACTIONS = ("restart", "stop")
MOD_SOURCES = ("", "modrinth", "curseforge", "hangar")
DATAPACK_PLACEMENTS = ("", "first", "last", "before_vanilla")
LOADERS = ("Vanilla", "Paper", "Folia", "Purpur", "Fabric", "Quilt", "Forge", "NeoForge",
           "Spigot", "Velocity", "Waterfall", "BungeeCord")
MODES = ("schedule", "always-on", "maintenance")
SETTING_GROUPS = (
    ("general", (("nom_serveur", "text"), ("domaine", "text"))),
    ("network", (("port", "int"), ("rcon_port", "int"))),
    ("performance", (("ram_allocation", "text"), ("cpu_affinity", "text"), ("jar_name", "text"),
                     ("stop_timeout", "int"))),
    ("backup", (("dossier_backup", "text"), ("backup_retention_days", "int"), ("backup_keep", "int"))),
)
SETTING_KINDS = {key: kind for _group, fields in SETTING_GROUPS for key, kind in fields}
SECRET_KEYS = ("mcrcon_pass", "webhook_url", "curseforge_api_key", "backup_encrypt_key_file")
RAM_PATTERN = re.compile(r"^\d+[MG]$", re.IGNORECASE)
CENTER_PATTERN = re.compile(r"^-?\d+,-?\d+$")
TIME_PATTERN = re.compile(r"^(\d{1,2}):(\d{2})$")


def describe(error):
    return error_text(error.code, error.message)


def format_duration(seconds):
    seconds = int(seconds)
    for size, unit in ((3600, "h"), (60, "m")):
        if seconds % size == 0:
            return "%d%s" % (seconds // size, unit)
    return "%ds" % seconds


def parse_time(text):
    found = TIME_PATTERN.match((text or "").strip())
    if not found:
        return None
    hour, minute = int(found.group(1)), int(found.group(2))
    return (hour, minute) if hour < 24 and minute < 60 else None


def clock(hour, minute):
    return "%02d:%02d" % (hour or 0, minute or 0)


class PanelModel(Observable):
    """Shared behaviour of the tabs: one operation at a time, jobs with progress, translated errors."""

    def __init__(self, client, runner=None):
        super().__init__()
        self.client, self.runner = client, runner or Runner()
        self.busy = None
        self.progress = 0
        self.error = None
        self.message = None
        self.read_only = False

    def _fail(self, error):
        self.error = describe(error)
        if error.code == "forbidden":
            self.read_only = True

    def _refuse(self, code):
        self.error = error_text(code)
        self.notify()
        return False

    def _fetch(self, work, apply):
        self.runner.run(work, lambda document, error: self._fetched(apply, document, error))

    def _fetched(self, apply, document, error):
        if error:
            self._fail(error)
        else:
            apply(document)
        self.notify()

    def _start(self, kind, work, message, job=False, then=None):
        if self.busy:
            return False
        self.busy, self.progress, self.error, self.message = kind, 0, None, None
        self.notify()
        self.runner.run(lambda: self._execute(work, job),
                        lambda result, error: self._finished(message, then, result, error))
        return True

    def _execute(self, work, job):
        document = work()
        if job:
            return self.client.wait_job(document["id"], on_progress=self._report)
        return document

    def _report(self, value):
        self.runner.dispatch(self._progressed, value)

    def _progressed(self, value):
        self.progress = max(0, min(100, int(value)))
        self.notify()

    def _finished(self, message, then, result, error):
        self.busy = None
        if error:
            self._fail(error)
            self.notify()
            return
        text = message(result) if callable(message) else t(message)
        if isinstance(result, dict) and result.get("restart_required"):
            text += " " + t("restart_required")
        self.message = text
        self.notify()
        if then:
            then(result)


class ModsModel(PanelModel):
    """Mods of one server: list, install by name or jar path, update, remove (moved to quarantine)."""

    def __init__(self, client, name, runner=None):
        super().__init__(client, runner)
        self.name = name
        self.mods = []
        self.blocks_pending = None
        self._removing = None

    def load(self):
        self._fetch(lambda: self.client.list_mods(self.name), self._loaded)

    def _loaded(self, document):
        self.mods = [mod_row(entry) for entry in document.get("mods") or []]

    def add(self, ref, source="", server_only=False):
        ref = ref.strip()
        if not ref:
            return False
        if source not in MOD_SOURCES:
            return False
        return self._start("add", lambda: self.client.add_mod(self.name, ref, source or None, server_only),
                           lambda _r: t("mod_added", name=ref), job=True, then=lambda _r: self.load())

    def update(self, name=None):
        return self._start("update", lambda: self.client.update_mods(self.name, name), "mod_updated",
                           job=True, then=lambda _r: self.load())

    def remove(self, file, confirmed=False, confirm_blocks=False):
        if not confirmed or not file:
            return False
        self.blocks_pending = None
        self._removing = file
        return self._start("remove", lambda: self.client.remove_mod(self.name, file, confirm_blocks),
                           lambda _r: t("mod_removed", name=file), then=lambda _r: self.load())

    def _fail(self, error):
        super()._fail(error)
        if error.code == "defines_blocks":
            self.blocks_pending = self._removing


def mod_row(entry):
    source = entry.get("source")
    return {
        "file": entry.get("file") or "",
        "name": entry.get("name") or entry.get("id") or entry.get("file") or "",
        "version": entry.get("version") or "",
        "loader": entry.get("loader") or "",
        "source": source,
        "source_text": source or t("mod_local"),
        "server": bool(entry.get("server")),
        "modpack": bool(entry.get("modpack")),
        "adds_blocks": bool(entry.get("adds_blocks")),
    }


def datapack_row(entry):
    enabled = entry.get("enabled")
    problem = entry.get("problem")
    if problem:
        state = t("pack_problem_" + problem)
    elif enabled is None:
        state = t("pack_unknown")
    else:
        state = t("pack_enabled") if enabled else t("pack_disabled")
    return {
        "id": entry.get("id") or "",
        "file": entry.get("file") or "",
        "enabled": enabled,
        "order": entry.get("order"),
        "worldgen": bool(entry.get("worldgen")),
        "problem": problem,
        "state_text": state,
    }


class DatapacksModel(PanelModel):
    """Datapacks of one server; enabling needs the server to run, disabling a stopped one moves the file away."""

    def __init__(self, client, name, runner=None):
        super().__init__(client, runner)
        self.name = name
        self.packs = []
        self.running = False

    def load(self):
        self._fetch(lambda: self.client.list_datapacks(self.name), self._loaded)

    def _loaded(self, document):
        self.running = bool(document.get("running"))
        self.packs = [datapack_row(entry) for entry in document.get("packs") or []]

    def can_toggle(self, row, enable):
        if self.busy or row["problem"]:
            return False
        return self.running if enable else True

    def toggle(self, file, enable, placement=""):
        if placement not in DATAPACK_PLACEMENTS:
            return False
        key = "pack_enabled_done" if enable else "pack_disabled_done"
        return self._start("toggle", lambda: self.client.set_datapack(self.name, file, enable, placement or None),
                           lambda _r: t(key, name=file), then=lambda _r: self.load())


class WorldModel(PanelModel):
    """Dimensions with their size, pre-generation and dimension reset (a job)."""

    def __init__(self, client, name, runner=None):
        super().__init__(client, runner)
        self.name = name
        self.dimensions = []
        self.total_text = ""
        self.pregen_text = ""
        self.pregen_note = None

    def load(self):
        self._fetch(lambda: self.client.list_worlds(self.name), self._loaded)
        self.refresh_pregen()

    def _loaded(self, document):
        self.dimensions = [{"id": entry.get("id") or "", "size_text": format_size(entry.get("size_bytes")),
                            "paths": entry.get("paths") or []} for entry in document.get("dimensions") or []]
        self.total_text = format_size(document.get("size_bytes"))

    def refresh_pregen(self):
        self.runner.run(lambda: self.client.pregen_status(self.name), self._pregen_loaded)

    def _pregen_loaded(self, document, error):
        if error:
            self.pregen_text, self.pregen_note = "", describe(error)
        else:
            self.pregen_text, self.pregen_note = document.get("progress") or "", None
        self.notify()

    def start_pregen(self, radius, center=""):
        radius, center = str(radius).strip(), center.strip()
        if not radius.isdigit() or int(radius) <= 0:
            return self._refuse("invalid_radius")
        if center and not CENTER_PATTERN.match(center):
            return self._refuse("invalid_center")
        return self._start("pregen", lambda: self.client.start_pregen(self.name, int(radius), center or None),
                           "pregen_started", then=self._pregen_started)

    def _pregen_started(self, document):
        self.pregen_text, self.pregen_note = document.get("progress") or "", None
        self.notify()

    def reset(self, dimension, confirmed=False):
        if not confirmed or not dimension:
            return False
        return self._start("reset", lambda: self.client.reset_dimension(self.name, dimension, dimension == "overworld"),
                           lambda _r: t("world_reset_done", name=dimension), job=True, then=lambda _r: self.load())


def format_warn(values):
    return ", ".join(format_duration(value) for value in values or [])


def task_row(entry):
    last = entry.get("last_result")
    if not last:
        outcome = ""
    elif last.get("ok"):
        outcome = t("task_last_ok")
    else:
        outcome = t("task_last_failed", code=last.get("code") or "")
    return {
        "id": entry.get("id"),
        "name": entry.get("name") or "",
        "cron": entry.get("cron") or "",
        "action": entry.get("action") or "",
        "action_text": t("task_action_" + (entry.get("action") or "")),
        "command": entry.get("command") or "",
        "enabled": bool(entry.get("enabled")),
        "warn_text": format_warn(entry.get("warn")),
        "next_text": (entry.get("next_run") or "").replace("T", " "),
        "last_text": outcome,
    }


class TasksModel(PanelModel):
    """Scheduled tasks of one server: create, enable, run now, delete."""

    def __init__(self, client, name, runner=None):
        super().__init__(client, runner)
        self.name = name
        self.tasks = []

    def load(self):
        self._fetch(lambda: self.client.list_tasks(self.name), self._loaded)

    def _loaded(self, document):
        self.tasks = [task_row(entry) for entry in document.get("tasks") or []]

    def create(self, action, cron, name="", command="", warn=""):
        cron, name, command, warn = cron.strip(), name.strip(), command.strip(), warn.strip()
        if action not in TASK_ACTIONS:
            return False
        if len(cron.split()) != 5:
            return self._refuse("invalid_cron")
        if action == "command" and not command:
            return self._refuse("command_required")
        command = command if action == "command" else ""
        warn = warn if action in WARN_ACTIONS else ""
        return self._start("create", lambda: self.client.create_task(self.name, action, cron, name, command, warn),
                           "task_created", then=lambda _r: self.load())

    def set_enabled(self, task_id, enabled):
        key = "task_enabled_done" if enabled else "task_disabled_done"
        return self._start("update", lambda: self.client.update_task(self.name, task_id, enabled), key,
                           then=lambda _r: self.load())

    def run(self, task_id, skip_warn=False):
        return self._start("run", lambda: self.client.run_task(self.name, task_id, skip_warn), "task_run_done",
                           job=True, then=lambda _r: self.load())

    def delete(self, task_id, confirmed=False):
        if not confirmed:
            return False
        return self._start("delete", lambda: self.client.delete_task(self.name, task_id), "task_deleted",
                           then=lambda _r: self.load())


def mode_of(config):
    if config.get("mode_maintenance"):
        return "maintenance"
    return "always-on" if config.get("always_on") else "schedule"


class SettingsModel(PanelModel):
    """Settings of one server. Secret keys are never shown, only replaced (an empty entry leaves them alone)."""

    def __init__(self, client, name, runner=None):
        super().__init__(client, runner)
        self.name = name
        self.values = {}
        self.secrets_set = []
        self.mode = "schedule"
        self.open_time = self.close_time = "00:00"
        self.java = ""
        self.java_choices = []

    def load(self):
        self._fetch(lambda: self.client.config(self.name), self._loaded)
        self._fetch(lambda: self.client.server_java(self.name), self._java_loaded)

    def _loaded(self, document):
        config = document.get("config") or {}
        self.values = {key: "" if config.get(key) is None else str(config[key]) for key in SETTING_KINDS}
        self.secrets_set = [key for key in document.get("secrets_set") or [] if key in SECRET_KEYS]
        self.mode = mode_of(config)
        self.open_time = clock(config.get("heure_ouverture"), config.get("minute_ouverture"))
        self.close_time = clock(config.get("heure_fermeture"), config.get("minute_fermeture"))
        if not self.java and config.get("java_major"):
            self.java = str(config["java_major"])

    def _java_loaded(self, document):
        self.java_choices = ["system"] + sorted(document.get("runtimes") or {}, key=lambda v: (len(v), v))
        for entry in document.get("servers") or []:
            if entry.get("server") == self.name:
                self.java = str(entry.get("java"))

    def set_value(self, key, text):
        kind = SETTING_KINDS.get(key)
        if kind is None:
            return False
        text = text.strip()
        if text == self.values.get(key, ""):
            return False
        value = text
        if kind == "int":
            if not text.lstrip("-").isdigit():
                return self._refuse("invalid_value")
            value = int(text)
        elif key == "ram_allocation" and not RAM_PATTERN.match(text):
            return self._refuse("invalid_value")
        return self._save(key, value)

    def set_secret(self, key, text):
        if key not in SECRET_KEYS or not text:
            return False
        return self._save(key, text)

    def _save(self, key, value):
        return self._start("config", lambda: self.client.set_config_value(self.name, key, value), "setting_saved",
                           then=lambda _r: self.load())

    def set_mode(self, mode):
        if mode not in MODES or mode == self.mode:
            return False
        return self._start("mode", lambda: self.client.set_mode(self.name, mode), "mode_saved",
                           then=lambda _r: self.load())

    def set_schedule(self, opening, closing):
        first, second = parse_time(opening), parse_time(closing)
        if first is None or second is None:
            return self._refuse("invalid_time")
        return self._start("schedule", lambda: self.client.set_schedule(self.name, *first, *second),
                           "schedule_saved", then=lambda _r: self.load())

    def set_java(self, choice):
        if choice not in self.java_choices or choice == self.java:
            return False
        return self._start("java", lambda: self.client.set_server_java(self.name, choice), "java_saved",
                           then=lambda _r: self.load())


class CreateServerModel(PanelModel):
    """Server creation assistant: validates the form locally, then follows the creation job."""

    def __init__(self, client, runner=None):
        super().__init__(client, runner)
        self.created = None

    def create(self, name, loader, version="", ram="", eula=False, port="", rcon_port=""):
        name, version, ram = name.strip(), version.strip(), ram.strip().upper()
        if not name:
            return self._refuse("name_required")
        if loader not in LOADERS:
            return self._refuse("unknown_loader")
        if not eula:
            return self._refuse("eula_required")
        if ram and not RAM_PATTERN.match(ram):
            return self._refuse("invalid_value")
        ports = []
        for text in (port, rcon_port):
            text = text.strip()
            if text and not (text.isdigit() and 0 < int(text) < 65536):
                return self._refuse("invalid_value")
            ports.append(int(text) if text else None)
        self.created = None
        return self._start("create", lambda: self.client.create_server(name, loader, True, version or None,
                                                                       ram or None, ports[0], ports[1]),
                           lambda _r: t("server_created", name=name), job=True, then=lambda _r: self._done(name))

    def _done(self, name):
        self.created = name
        self.notify()
