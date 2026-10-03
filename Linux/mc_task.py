"""
mc_task.py — Scheduled tasks: a five-field cron evaluator, the task list kept
in config.json ("tasks") and the execution of each action. The daemon calls
due_tasks() every tick and runs what it returns; 'mc task run' runs one task
by hand. Nothing here prints.
"""
import datetime
import logging
import time

import mc_config
import mc_core
from mc_lang import T

ACTIONS = ("restart", "backup", "command", "stop", "start")
WARN_ACTIONS = ("restart", "stop")
MAX_WARN = 24 * 3600

_MONTHS = {n: i for i, n in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}
_DAYS = {n: i for i, n in enumerate(("sun", "mon", "tue", "wed", "thu", "fri", "sat"))}
_FIELDS = (
    ("minute", 0, 59, {}),
    ("hour", 0, 23, {}),
    ("day", 1, 31, {}),
    ("month", 1, 12, _MONTHS),
    ("weekday", 0, 7, _DAYS),
)


def result(ok, code, **data):
    return {"ok": ok, "code": code, **data}


class CronError(ValueError):
    pass


def _number(text, names, low, high):
    value = names.get(text.lower()) if text.lower() in names else None
    if value is None:
        if not text.isdigit():
            raise CronError(text)
        value = int(text)
    if not low <= value <= high:
        raise CronError(text)
    return value


def _parse_field(text, low, high, names):
    values = set()
    if not text:
        raise CronError(text)
    for part in text.split(","):
        base, _, step_text = part.partition("/")
        if step_text:
            if not step_text.isdigit() or int(step_text) < 1:
                raise CronError(part)
            step = int(step_text)
        else:
            step = 1
        if base == "*":
            start, end = low, high
        elif "-" in base:
            first, _, last = base.partition("-")
            start, end = _number(first, names, low, high), _number(last, names, low, high)
            if start > end:
                raise CronError(part)
        else:
            start = _number(base, names, low, high)
            end = high if step_text else start
        values.update(range(start, end + 1, step))
    return values


class Cron:
    """A parsed expression. Like classic cron, when both the day-of-month and
    the day-of-week fields are restricted, a day matching either one runs."""

    def __init__(self, text):
        fields = str(text).split()
        if len(fields) != 5:
            raise CronError(text)
        parsed = [_parse_field(f, low, high, names) for f, (_n, low, high, names) in zip(fields, _FIELDS)]
        self.text = " ".join(fields)
        self.minutes, self.hours, self.days, self.months, weekdays = parsed
        self.weekdays = {d % 7 for d in weekdays}
        self.any_day = fields[2].startswith("*")
        self.any_weekday = fields[4].startswith("*")

    def day_matches(self, date):
        weekday = (date.weekday() + 1) % 7
        in_days, in_weekdays = date.day in self.days, weekday in self.weekdays
        if self.any_day or self.any_weekday:
            return in_days and in_weekdays
        return in_days or in_weekdays

    def matches(self, when):
        return (when.minute in self.minutes and when.hour in self.hours
                and when.month in self.months and self.day_matches(when.date()))

    def next_after(self, when):
        """First matching minute strictly after `when`, or None within 5 years."""
        start = when.replace(second=0, microsecond=0) + datetime.timedelta(minutes=1)
        day = start.date()
        for offset in range(366 * 5):
            date = day + datetime.timedelta(days=offset)
            if date.month not in self.months or not self.day_matches(date):
                continue
            for hour in sorted(self.hours):
                for minute in sorted(self.minutes):
                    candidate = datetime.datetime.combine(date, datetime.time(hour, minute))
                    if candidate >= start:
                        return candidate
        return None


def parse_cron(text):
    return Cron(text)


# ── stored tasks ─────────────────────────────────────────────────────────────

def tasks_of(config):
    tasks = config.get("tasks")
    return [t for t in tasks if isinstance(t, dict)] if isinstance(tasks, list) else []


def parse_warn(text):
    """'10m,5m,1m' -> [600, 300, 60] (largest first). ValueError if invalid."""
    import mc_api
    if not text:
        return []
    values = sorted({mc_api.parse_duration(p) for p in str(text).split(",") if p.strip()}, reverse=True)
    if not values or values[-1] < 1 or values[0] > MAX_WARN:
        raise ValueError(text)
    return values


def find_task(config, ref):
    ref = str(ref)
    tasks = tasks_of(config)
    for task in tasks:
        if str(task.get("id")) == ref:
            return task
    named = [t for t in tasks if str(t.get("name", "")).lower() == ref.lower()]
    return named[0] if len(named) == 1 else None


def _describe(task, now=None):
    try:
        nxt = Cron(task["cron"]).next_after(now or datetime.datetime.now()) if task.get("enabled", True) else None
    except CronError:
        nxt = None
    return dict(task, next_run=nxt.strftime("%Y-%m-%dT%H:%M:%S") if nxt else None)


def list_tasks(config, now=None):
    return result(True, "task_list", tasks=[_describe(t, now) for t in tasks_of(config)])


def add_task(config, cron, action, command=None, warn=None, name=None):
    try:
        Cron(cron)
    except CronError:
        return result(False, "invalid_cron", cron=cron)
    if action not in ACTIONS:
        return result(False, "invalid_action", action=action)
    if action == "command" and not (command or "").strip():
        return result(False, "command_required")
    if action != "command" and command:
        return result(False, "command_not_allowed", action=action)
    try:
        warnings = parse_warn(warn)
    except ValueError:
        return result(False, "invalid_warn", warn=warn)
    if warnings and action not in WARN_ACTIONS:
        return result(False, "warn_not_allowed", action=action)
    tasks = tasks_of(config)
    if name and any(str(t.get("name", "")).lower() == name.lower() for t in tasks):
        return result(False, "task_name_taken", name=name)
    new_id = max([int(t.get("id", 0)) for t in tasks] + [0]) + 1
    task = {"id": new_id, "name": name or f"{action}-{new_id}", "cron": Cron(cron).text, "action": action,
            "enabled": True, "last_run": None, "last_result": None}
    if command:
        task["command"] = command.strip()
    if warnings:
        task["warn"] = warnings
    config["tasks"] = tasks + [task]
    mc_config.save_config(config)
    return result(True, "task_added", task=_describe(task))


def remove_task(config, ref):
    task = find_task(config, ref)
    if not task:
        return result(False, "task_not_found", ref=ref)
    config["tasks"] = [t for t in tasks_of(config) if t is not task]
    mc_config.save_config(config)
    return result(True, "task_removed", task=task)


def set_enabled(config, ref, enabled):
    task = find_task(config, ref)
    if not task:
        return result(False, "task_not_found", ref=ref)
    task["enabled"] = bool(enabled)
    mc_config.save_config(config)
    return result(True, "task_enabled" if enabled else "task_disabled", task=task)


def record_run(config, task_id, ok, code, when=None):
    """Store the outcome in the task. Reloads the file first: a task can run
    for minutes and the config may have changed meanwhile."""
    fresh = mc_config.load_config(config["dossier_serveur"])
    fresh["dossier_serveur"] = config["dossier_serveur"]
    for task in tasks_of(fresh):
        if task.get("id") == task_id:
            when = when or time.time()
            task["last_run"] = datetime.datetime.fromtimestamp(when).strftime("%Y-%m-%dT%H:%M:%S")
            task["last_result"] = {"ok": bool(ok), "code": code}
            mc_config.save_config(fresh)
            return


# ── scheduling ───────────────────────────────────────────────────────────────

def lead_seconds(task):
    warn = task.get("warn") or []
    return max(warn) if warn else 0


def due_tasks(config, fired, now):
    """[(task, target_datetime)] to start now.

    The cron expression gives the moment the action happens; with warnings,
    the task starts early enough to announce them, so it is due when the
    minute `lead` seconds ahead matches. `fired` maps task id -> target
    minute already started (kept by the caller). A minute the daemon was not
    running for is never caught up."""
    due = []
    for task in tasks_of(config):
        if not task.get("enabled", True):
            continue
        try:
            cron = Cron(task.get("cron", ""))
        except CronError:
            continue
        target = (now + datetime.timedelta(seconds=lead_seconds(task))).replace(second=0, microsecond=0)
        if not cron.matches(target) or fired.get(task.get("id")) == target:
            continue
        fired[task.get("id")] = target
        due.append((task, target))
    return due


def _human(seconds):
    if seconds % 3600 == 0:
        return f"{seconds // 3600} h"
    if seconds % 60 == 0:
        return f"{seconds // 60} min"
    return f"{seconds} s"


def _announce(config, task, seconds, rcon):
    key = "task_warn_restart" if task["action"] == "restart" else "task_warn_stop"
    rcon(config, "say " + T[key].format(time=_human(seconds)))


def _wait_and_warn(config, task, target, rcon, clock, sleep):
    for seconds in task.get("warn") or []:
        moment = target - datetime.timedelta(seconds=seconds)
        remaining = (moment - clock()).total_seconds()
        if remaining < -5:
            continue
        if remaining > 0:
            sleep(remaining)
        _announce(config, task, seconds, rcon)
    remaining = (target - clock()).total_seconds()
    if remaining > 0:
        sleep(remaining)


def execute(name, config, task, target=None, skip_warn=False, rcon=None, clock=None, sleep=None):
    """Run one task now and return a result dict. Never raises."""
    import mc_api
    rcon = rcon or (lambda cfg, cmd: mc_api.rcon_exec(cfg, cmd))
    clock = clock or datetime.datetime.now
    sleep = sleep or time.sleep
    action = task.get("action")
    try:
        res = _run(name, config, task, target, skip_warn, rcon, clock, sleep)
    except Exception as e:
        logging.exception("task %s failed", task.get("name"))
        res = result(False, "task_error", detail=str(e))
    res.setdefault("task", task.get("name"))
    res["action"] = action
    return res


def _run(name, config, task, target, skip_warn, rcon, clock, sleep):
    import mc_api
    action = task.get("action")
    running = mc_core.is_server_running(config)

    if action == "backup":
        ok, message = mc_core.backup_server(config, "task")
        return result(ok, "task_backup_done" if ok else "task_backup_failed", message=message)

    if action == "command":
        if not running:
            return result(False, "task_server_offline")
        ok, reply = rcon(config, task.get("command", ""))
        return result(ok, "task_command_done" if ok else "rcon_failed", reply=reply)

    if action == "start":
        if running:
            return result(True, "already_running")
        if config.get("mode_maintenance", 0) == 1 and config.get("stop_reason") not in (None, "scheduled", "sleep"):
            return result(False, "blocked_by_maintenance", reason=config.get("stop_reason"))
        return _resume(name, config)

    if action in WARN_ACTIONS:
        if running and task.get("warn") and not skip_warn:
            if target is None:
                target = clock() + datetime.timedelta(seconds=lead_seconds(task))
            _wait_and_warn(config, task, target, rcon, clock, sleep)
        config["mode_maintenance"] = 1
        config["stop_reason"] = "scheduled"
        mc_config.save_config(config)
        stopped = mc_api.stop(name, config, reason="scheduled")
        if not stopped["ok"]:
            config["mode_maintenance"] = 0
            config.pop("stop_reason", None)
            mc_config.save_config(config)
            return result(False, "stop_failed", message=stopped.get("message"))
        if action == "stop":
            return result(True, "task_stop_done")
        resumed = _resume(name, config)
        return result(resumed["ok"], "task_restart_done" if resumed["ok"] else resumed["code"])

    return result(False, "invalid_action", action=action)


def _resume(name, config):
    """Leave maintenance. The daemon relaunches on its next tick; outside the
    daemon the server is started right away."""
    import mc_api
    config["mode_maintenance"] = 0
    config.pop("stop_reason", None)
    mc_config.save_config(config)
    if mc_api.IN_DAEMON:
        return result(True, "task_resumed")
    started = mc_api.start(name, config)
    return result(started["ok"], "task_started" if started["ok"] else started["code"])
