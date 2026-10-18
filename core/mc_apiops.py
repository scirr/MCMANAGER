"""
mc_apiops.py — One handler per operation of the HTTP contract (api/openapi.json).

A handler receives a Context and returns a result dict (the same functions the
CLI --json uses), a Reply, or raises Failure. The HTTP layer (mc_httpapi) maps
the result code to a status.
"""
import os

import mc_api
import mc_config
import mc_core
import mc_servers
from mc_lang import T

HANDLERS = {}
REMOTE_OPERATIONS = ("listAuditLog", "listDevices", "revokeDevice", "setDeviceRoles", "pairDevice",
                     "createPairingCode", "getRemoteStatus", "setRemoteAccess")
# Operations that answer 200 with ok:false when the work was done and reported a failure.
REPORTED_FAILURES = {"getDoctorReport": ("doctor",), "getServerDoctorReport": ("doctor",),
                     "testAlertChannels": ("alert_test_failed",),
                     "testBackupRemotes": ("backup_remote_test_failed",)}


class Failure(Exception):
    def __init__(self, res):
        super().__init__(res.get("code"))
        self.res = res


class Reply:
    def __init__(self, status, body=None, headers=None, raw=None, content_type=None):
        self.status = status
        self.body = body
        self.headers = headers or {}
        self.raw = raw
        self.content_type = content_type


class Stream:
    def __init__(self, chunks, on_close=None):
        self.chunks = chunks
        self.on_close = on_close
        self.status = 200


def fail(code, **data):
    raise Failure(mc_api.result(False, code, **data))


def op(operation_id):
    def register(function):
        HANDLERS[operation_id] = function
        return function
    return register


class Context:
    def __init__(self, app, route, params, query, body, headers=None):
        self.app = app
        self.route = route
        self.params = params
        self.query = query
        self.body = body if isinstance(body, dict) else {}
        self.headers = headers or {}
        self._server = None

    def server(self):
        if self._server is None:
            target = self.params["server"]
            if target == "active":
                if not mc_servers.load_registry().get("active"):
                    fail("no_active_server")
                target = None
            loaded, error = mc_api.load_server(target)
            if error:
                raise Failure(error)
            self._server = loaded
        return self._server

    def job(self, function, name=None):
        return self.app.start_job(self.route.operation_id, name, function)

    def release(self, name, config):
        if self.app.release:
            self.app.release(name, config)


def _flag(value):
    return value is True


def _with_server(handler):
    def wrapped(ctx):
        name, config = ctx.server()
        return handler(ctx, name, config)
    wrapped.__name__ = handler.__name__
    return wrapped


def server_op(operation_id):
    def register(handler):
        HANDLERS[operation_id] = _with_server(handler)
        return handler
    return register


# ── api ─────────────────────────────────────────────────────────────────────

@op("getApiInfo")
def get_api_info(ctx):
    from mc_lang import VERSION
    return mc_api.result(True, "api_info", api="1", daemon=VERSION, remote=False)


def not_implemented(ctx):
    return mc_api.result(False, "not_implemented", message="Remote access is not available in this version.")


for _name in REMOTE_OPERATIONS:
    HANDLERS[_name] = not_implemented


# ── servers ─────────────────────────────────────────────────────────────────

@op("listServers")
def list_servers(ctx):
    return mc_api.status_document()


@server_op("getServer")
def get_server(ctx, name, config):
    registry = mc_servers.load_registry()
    return mc_api.result(True, "status", **mc_api.server_snapshot(name, registry["servers"][name], registry.get("active")))


@op("createServer")
def create_server(ctx):
    import mc_deploy
    body = ctx.body

    def run(progress):
        return mc_deploy.run_deploy_auto(body["name"], body["loader"], body.get("version"), body.get("folder"),
                                         body.get("port"), body.get("rcon_port"), body.get("ram", "6G"),
                                         body.get("accept_eula", False))
    if not body.get("accept_eula"):
        fail("eula_required")
    return ctx.job(run)


@op("unregisterServer")
def unregister_server(ctx):
    name, _config = ctx.server()
    return mc_api.remove(name, confirmed=_flag(ctx.query.get("confirm")))


@op("activateServer")
def activate_server(ctx):
    name, _config = ctx.server()
    return mc_api.use(name)


@server_op("startServer")
def start_server(ctx, name, config):
    ctx.release(name, config)
    return mc_api.start(name, config)


@server_op("stopServer")
def stop_server(ctx, name, config):
    body = ctx.body
    return mc_api.stop(name, config, reason=body.get("reason"), quiet=_flag(body.get("quiet")),
                       force=_flag(body.get("force")))


@server_op("restartServer")
def restart_server(ctx, name, config):
    import mc_task
    task = {"name": "restart", "action": "restart"}
    return ctx.job(lambda progress: mc_task.execute(name, config, task, skip_warn=True), name)


@server_op("resumeServer")
def resume_server(ctx, name, config):
    ctx.release(name, config)
    return mc_api.resume(name, config)


@server_op("wakeServer")
def wake_server(ctx, name, config):
    ctx.release(name, config)
    return mc_api.wake(name, config)


@server_op("switchServer")
def switch_server(ctx, name, config):
    force = _flag(ctx.body.get("force"))
    return ctx.job(lambda progress: mc_api.switch(name, force=force), name)


@server_op("upgradeServer")
def upgrade_server(ctx, name, config):
    version = ctx.body.get("version") or "latest"
    return ctx.job(lambda progress: mc_api.upgrade(name, config, version, progress), name)


@server_op("freezeServer")
def freeze_server(ctx, name, config):
    return mc_api.freeze_op(name, config, int(ctx.body.get("max_s") or mc_api.DEFAULT_FREEZE_MAX))


@server_op("thawServer")
def thaw_server(ctx, name, config):
    return mc_api.thaw_op(name, config)


@server_op("setServerMode")
def set_server_mode(ctx, name, config):
    return mc_api.set_mode(name, config, ctx.body["mode"])


@server_op("setServerSchedule")
def set_server_schedule(ctx, name, config):
    body = ctx.body
    opening = (body["open_hour"], body["open_minute"])
    closing = (body["close_hour"], body["close_minute"])
    if opening == closing:
        fail("invalid_schedule", server=name)
    config = mc_config.set_mode_schedule(config)
    config.update(heure_ouverture=opening[0], minute_ouverture=opening[1],
                  heure_fermeture=closing[0], minute_fermeture=closing[1])
    mc_config.save_config(config)
    return mc_api.result(True, "schedule_updated", server=name, open="%02d:%02d" % opening,
                         close="%02d:%02d" % closing)


@server_op("getSleepSettings")
def get_sleep_settings(ctx, name, config):
    return mc_api.sleep_status(name, config)


@server_op("setSleepSettings")
def set_sleep_settings(ctx, name, config):
    body = ctx.body
    return mc_api.sleep_configure(name, config, enabled=body.get("enabled"), after_s=body.get("after_s"),
                                  allow_add=body.get("allow_add") or (), allow_remove=body.get("allow_remove") or (),
                                  join_mode=body.get("join_mode"), freeze=body.get("freeze"),
                                  hold_timeout_s=body.get("hold_timeout_s"))


@server_op("announceServer")
def announce_server(ctx, name, config):
    ok, detail = mc_core.send_start_webhook(config)
    if ok:
        return mc_api.result(True, "announced", server=name)
    return mc_api.result(False, "announce_failed", server=name, message=T["announce_failed"].format(e=detail),
                         detail=str(detail))


@server_op("getServerLogs")
def get_server_logs(ctx, name, config):
    return mc_api.log_lines(name, int(ctx.query.get("lines") or 30))


@server_op("enableStatusPage")
def enable_status_page(ctx, name, config):
    body = ctx.body
    return mc_api.statuspage_enable(name, config, body.get("dir"), body.get("interval_s"),
                                    True if body.get("show_players") else None)


@server_op("disableStatusPage")
def disable_status_page(ctx, name, config):
    return mc_api.statuspage_disable(name, config)


# ── router ──────────────────────────────────────────────────────────────────

@op("getRouter")
def get_router(ctx):
    return mc_api.router_command("status")


@op("enableRouter")
def enable_router(ctx):
    body = ctx.body
    return mc_api.router_command("enable", port=body.get("port"), proxy_in=body.get("proxy_in"),
                                 proxy_out=body.get("proxy_out"), trusted_proxies=body.get("trusted_proxies"),
                                 per_ip=body.get("per_ip"), per_second=body.get("per_second"))


@op("disableRouter")
def disable_router(ctx):
    return mc_api.router_command("disable")


@op("setRouterDefault")
def set_router_default(ctx):
    return mc_api.router_command("default", [ctx.body["server"]])


@op("setRouterRoute")
def set_router_route(ctx):
    return mc_api.router_command("route", ["add", ctx.params["host"], ctx.body["server"]])


@op("removeRouterRoute")
def remove_router_route(ctx):
    return mc_api.router_command("route", ["remove", ctx.params["host"]])


@op("editRouterAccess")
def edit_router_access(ctx):
    body = ctx.body
    return mc_api.router_command(body["list"], [body["action"], body["cidr"]])


# ── players ─────────────────────────────────────────────────────────────────

@server_op("listOnlinePlayers")
def list_online_players(ctx, name, config):
    return mc_api.players_document(name, config)


@server_op("getPlayerHistory")
def get_player_history(ctx, name, config):
    res = mc_api.player_history(name, config, days=int(ctx.query.get("days") or 7))
    if not _flag(ctx.query.get("include_ip")) and res.get("ok"):
        res = dict(res, sessions=[dict(s, ip=None) for s in res["sessions"]])
    return res


@server_op("listPlayerList")
def list_player_list(ctx, name, config):
    return mc_api.player_list(name, config, ctx.params["kind"])


@server_op("addPlayerListEntry")
def add_player_list_entry(ctx, name, config):
    return mc_api.player_edit(name, config, ctx.params["kind"], "add", ctx.body["subject"],
                              reason=ctx.body.get("reason"))


@server_op("removePlayerListEntry")
def remove_player_list_entry(ctx, name, config):
    return mc_api.player_edit(name, config, ctx.params["kind"], "remove", ctx.params["subject"])


@server_op("setWhitelistEnabled")
def set_whitelist_enabled(ctx, name, config):
    return mc_api.whitelist_enable(name, config, ctx.body["enabled"])


@server_op("kickPlayer")
def kick_player(ctx, name, config):
    return mc_api.player_kick(name, config, ctx.body["player"], reason=ctx.body.get("reason"))


# ── console ─────────────────────────────────────────────────────────────────

@server_op("sendConsoleCommand")
def send_console_command(ctx, name, config):
    if not mc_core.is_server_running(config):
        return mc_api.result(False, "console_offline", server=name, message=T["console_offline"])
    ok, reply = mc_api.rcon_exec(config, ctx.body["command"], wait=mc_api.RCON_RETRY)
    if not ok:
        return mc_api.result(False, "rcon_failed", server=name, detail=reply,
                             message=T["rcon_failed"].format(detail=reply))
    return mc_api.result(True, "console_reply", server=name, output=reply or "")


@server_op("streamConsole")
def stream_console(ctx, name, config):
    return ctx.app.console_stream(name, config, int(ctx.query.get("tail", 50)), ctx.headers.get("last-event-id"))


@op("streamEvents")
def stream_events(ctx):
    return ctx.app.event_stream(ctx.query.get("servers"), ctx.headers.get("last-event-id"))


# ── world ───────────────────────────────────────────────────────────────────

@server_op("listWorlds")
def list_worlds(ctx, name, config):
    return mc_api.world_list(name, config)


@server_op("exportWorld")
def export_world(ctx, name, config):
    output = ctx.body.get("output")
    return ctx.job(lambda progress: mc_api.world_export(name, config, output), name)


@server_op("importWorld")
def import_world(ctx, name, config):
    source, confirmed = ctx.body["source"], _flag(ctx.body.get("confirmed"))
    return ctx.job(lambda progress: mc_api.world_import(name, config, source, confirmed=confirmed), name)


@server_op("resetDimension")
def reset_dimension(ctx, name, config):
    body, dimension = ctx.body, ctx.params["dimension"]
    return ctx.job(lambda progress: mc_api.world_reset(
        name, config, dimension, confirmed=_flag(body.get("confirmed")),
        include_overworld=_flag(body.get("include_overworld"))), name)


@server_op("startPregen")
def start_pregen(ctx, name, config):
    return mc_api.world_pregen(name, config, ctx.body["radius"], ctx.body.get("center"))


@server_op("getPregenStatus")
def get_pregen_status(ctx, name, config):
    return mc_api.world_pregen_status(name, config)


# ── content ─────────────────────────────────────────────────────────────────

@server_op("listDatapacks")
def list_datapacks(ctx, name, config):
    import mc_content
    return mc_content.datapack_list(config)


@server_op("setDatapackEnabled")
def set_datapack_enabled(ctx, name, config):
    import mc_content
    body = ctx.body
    return mc_content.datapack_set(config, ctx.params["pack"], enable=body["enabled"], before=body.get("before"),
                                   after=body.get("after"), first=_flag(body.get("first")),
                                   last=_flag(body.get("last")), before_vanilla=_flag(body.get("before_vanilla")))


@server_op("listMods")
def list_mods(ctx, name, config):
    return mc_api.mod_listing(config)


@server_op("addMod")
def add_mod(ctx, name, config):
    import mc_content
    import mc_modsources
    body = ctx.body
    ref = body["ref"]

    def run(progress):
        if ref.endswith(".jar") and os.path.isfile(os.path.expanduser(ref)):
            return mc_content.mod_add(config, ref, server_only=_flag(body.get("server_only")))
        return mc_modsources.add(config, ref, source=body.get("source"))
    return ctx.job(run, name)


@server_op("updateMods")
def update_mods(ctx, name, config):
    import mc_modsources
    mod = ctx.body.get("name")
    return ctx.job(lambda progress: mc_modsources.update(config, mod), name)


@server_op("removeMod")
def remove_mod(ctx, name, config):
    import mc_content
    import mc_modsources
    res = mc_content.mod_remove(config, ctx.params["mod"], confirm_blocks=_flag(ctx.query.get("confirm_blocks")))
    if res["ok"]:
        mc_modsources.forget(config, res["file"])
    return res


@op("getModpackInfo")
def get_modpack_info(ctx):
    import mc_modpack
    return mc_modpack.info(ctx.query["source"], mc_api.curseforge_key())


@op("installModpack")
def install_modpack(ctx):
    body = ctx.body
    key = body.get("curseforge_api_key") or mc_api.curseforge_key()
    return ctx.job(lambda progress: mc_api.modpack_install(
        body["source"], body.get("name"), body.get("folder"), body.get("port"), body.get("rcon_port"),
        body.get("ram") or "6G", _flag(body.get("accept_eula")), key, progress))


@server_op("updateModpack")
def update_modpack(ctx, name, config):
    key = ctx.body.get("curseforge_api_key") or mc_api.curseforge_key(config)
    return ctx.job(lambda progress: mc_api.modpack_update(name, config, key, progress), name)


# ── backups ─────────────────────────────────────────────────────────────────

@server_op("listBackups")
def list_backups(ctx, name, config):
    return mc_api.backup_list(name, config)


@server_op("createBackup")
def create_backup(ctx, name, config):
    return ctx.job(lambda progress: mc_api.backup_now(name, config), name)


@server_op("restoreBackup")
def restore_backup(ctx, name, config):
    if not _flag(ctx.body.get("confirm")):
        fail("confirm_required", server=name)
    ref = ctx.params["backup"]
    return ctx.job(lambda progress: mc_api.backup_restore(name, config, ref), name)


@server_op("listBackupRemotes")
def list_backup_remotes(ctx, name, config):
    return mc_api.backup_remote_list(name, config)


@server_op("addBackupRemote")
def add_backup_remote(ctx, name, config):
    body = ctx.body
    return mc_api.backup_remote_add(
        name, config, body["name"], body["url"], key=body.get("key"), endpoint=body.get("endpoint"),
        region=body.get("region"), access_key=body.get("access_key"), secret_key=body.get("secret_key"),
        path_style=body.get("path_style"), password=body.get("password"), password_file=body.get("password_file"))


@server_op("testBackupRemotes")
def test_backup_remotes(ctx, name, config):
    return mc_api.backup_remote_test(name, config, ctx.body.get("remote"))


@server_op("removeBackupRemote")
def remove_backup_remote(ctx, name, config):
    return mc_api.backup_remote_remove(name, config, ctx.params["remote"])


# ── alerts ──────────────────────────────────────────────────────────────────

ALERT_FIELDS = {"email": ("host", "port", "user", "password", "sender", "to"),
                "telegram": ("token", "chat_id"), "ntfy": ("topic", "server", "token"),
                "webhook": ("url", "headers", "secret"), "discord": ("url", "headers", "secret")}


@server_op("listAlertChannels")
def list_alert_channels(ctx, name, config):
    return mc_api.alert_list(name, config)


@server_op("addAlertChannel")
def add_alert_channel(ctx, name, config):
    body = ctx.body
    kind = body["type"]
    params = {key: body.get(key) for key in ALERT_FIELDS[kind]}
    return mc_api.alert_add(name, config, kind, params, body.get("events"), body.get("name"))


@server_op("testAlertChannels")
def test_alert_channels(ctx, name, config):
    return mc_api.alert_test(name, config, ctx.body.get("channel"))


@server_op("removeAlertChannel")
def remove_alert_channel(ctx, name, config):
    return mc_api.alert_remove(name, config, ctx.params["channel"])


# ── tasks ───────────────────────────────────────────────────────────────────

@server_op("listTasks")
def list_tasks(ctx, name, config):
    return mc_api.task_list(name, config)


@server_op("createTask")
def create_task(ctx, name, config):
    body = ctx.body
    return mc_api.task_add(name, config, body["cron"], body["action"], command=body.get("command"),
                           warn=body.get("warn"), task_name=body.get("name"))


@server_op("deleteTask")
def delete_task(ctx, name, config):
    return mc_api.task_remove(name, config, ctx.params["task"])


@server_op("updateTask")
def update_task(ctx, name, config):
    return mc_api.task_enable(name, config, ctx.params["task"], ctx.body["enabled"])


@server_op("runTask")
def run_task(ctx, name, config):
    task = mc_api.task_find(config, ctx.params["task"])
    if not task:
        fail("task_not_found", ref=ctx.params["task"])
    skip_warn = _flag(ctx.body.get("skip_warn"))
    return ctx.job(lambda progress: mc_api.task_run(name, config, task, skip_warn=skip_warn), name)


# ── system ──────────────────────────────────────────────────────────────────

@server_op("getServerConfig")
def get_server_config(ctx, name, config):
    return mc_api.config_document(name, config)


@server_op("getConfigValue")
def get_config_value(ctx, name, config):
    return mc_api.config_value(name, config, ctx.params["key"])


@server_op("setConfigValue")
def set_config_value(ctx, name, config):
    key = ctx.params["key"]
    status, detail = mc_config.set_value(config, name, key, ctx.body["value"])
    if status != "ok":
        code = {"unknown": "key_not_found", "invalid": "invalid_value", "conflict": "config_conflict"}.get(
            status, "config_error")
        return mc_api.result(False, code, server=name, key=key, message=str(detail))
    return mc_api.result(True, "config_set", server=name, key=key, updated=list(detail),
                         restart_required=mc_core.is_server_running(config) and key in mc_config.RESTART_KEYS)


@op("getDoctorReport")
def get_doctor_report(ctx):
    import mc_doctor
    return mc_doctor.doctor_document()[0]


@server_op("getServerDoctorReport")
def get_server_doctor_report(ctx, name, config):
    import mc_doctor
    return mc_doctor.doctor_document(name)[0]


@op("getMetrics")
def get_metrics(ctx):
    import mc_metrics
    return Reply(200, raw=mc_metrics.render().encode("utf-8"), content_type="text/plain; version=0.0.4; charset=utf-8")


@op("listJava")
def list_java(ctx):
    return mc_api.java_listing()


@server_op("listServerJava")
def list_server_java(ctx, name, config):
    return mc_api.java_listing(name)


@server_op("setServerJava")
def set_server_java(ctx, name, config):
    import mc_java
    res = mc_java.use(config, ctx.body["choice"])
    if res["ok"]:
        mc_config.save_config(config)
        if mc_core.is_server_running(config):
            res = dict(res, restart_required=True)
    return dict(res, server=name)


@op("installJava")
def install_java(ctx):
    import mc_java
    major = str(ctx.params["major"])
    return ctx.job(lambda progress: mc_java.install(major))


@op("removeJava")
def remove_java(ctx):
    import mc_java
    return mc_java.remove(str(ctx.params["major"]))


@op("checkUpdate")
def check_update(ctx):
    import mc_update
    return mc_update.check()


@op("applyUpdate")
def apply_update(ctx):
    import mc_update
    version = ctx.body.get("version")
    return ctx.job(lambda progress: mc_update.perform_update(version))


@op("rollbackUpdate")
def rollback_update(ctx):
    import mc_update
    return mc_update.rollback()


# ── jobs ────────────────────────────────────────────────────────────────────

@op("listJobs")
def list_jobs(ctx):
    return mc_api.result(True, "jobs", jobs=ctx.app.jobs.listing(ctx.query.get("state")))


@op("getJob")
def get_job(ctx):
    job = ctx.app.jobs.get(ctx.params["job"])
    if job is None:
        fail("job_not_found", id=ctx.params["job"], message="No such job.")
    return Reply(200, job.document())


@op("cancelJob")
def cancel_job(ctx):
    job_id = ctx.params["job"]
    cancelled = ctx.app.jobs.cancel(job_id)
    if cancelled is None:
        fail("job_not_found", id=job_id, message="No such job.")
    if not cancelled:
        fail("job_finished", id=job_id)
    return mc_api.result(True, "job_cancelled", id=job_id)
