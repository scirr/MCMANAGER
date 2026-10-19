"""
test_httpapi.py - the local HTTP API: transport (Unix socket, loopback + token),
limits, errors, jobs, streams, resilience, and agreement with the contract and
with `mc ... --json`.
"""
import json
import os
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

import mc_api
import mc_apiops
import mc_core
import mc_httpapi
import mc_jobs
from apiclient import Client, api_environment, read_event
from test_openapi import OPERATIONS, SPEC, validate_strict, resolve

ERROR = resolve("#/components/schemas/Error")
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def started(env, mode=None, **kwargs):
    api = mc_httpapi.LocalApi(folder=env["run"], mode=mode, enabled=lambda: True, settle=0.3, **kwargs)
    api.sync()
    return api


class ApiCase(unittest.TestCase):
    mode = "unix"

    def setUp(self):
        manager = api_environment()
        self.env = manager.__enter__()
        self.addCleanup(manager.__exit__, None, None, None)
        self.api = started(self.env, self.mode)
        self.addCleanup(self.api.stop)
        self.client = Client(self.env["run"], self.mode)


class TestUnixSocket(ApiCase):

    @unittest.skipIf(sys.platform == "win32", "Unix sockets")
    def test_socket_is_private_and_removed_on_stop(self):
        path = os.path.join(self.env["run"], "api.sock")
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        self.api.stop()
        self.assertFalse(os.path.exists(path))

    def test_api_info_needs_no_token_and_lists_versions(self):
        status, body, _ = self.client.request("GET", "/v1")
        self.assertEqual((status, body["code"], body["api"]), (200, "api_info", "1"))
        self.assertEqual(validate_strict(body, resolve_response("getApiInfo")), [])

    def test_unknown_route_wrong_method_bad_json_big_body(self):
        self.assertEqual(self.client.request("GET", "/v1/nothing")[0], 404)
        status, body, response = self.client.request("DELETE", "/v1/servers/a/start")
        self.assertEqual(status, 405)
        self.assertIn("POST", response.getheader("Allow"))
        status, body, _ = self.client.request("POST", "/v1/servers/a/console", raw=b"{broken")
        self.assertEqual((status, body["code"]), (400, "invalid_json"))
        status, body, _ = self.client.request("POST", "/v1/servers/a/console", raw=b"[1]")
        self.assertEqual((status, body["code"]), (400, "invalid_json"))
        status, body, _ = self.client.request("POST", "/v1/servers/a/console", raw=b" " * (mc_httpapi.MAX_BODY + 1))
        self.assertEqual((status, body["code"]), (413, "payload_too_large"))

    def test_validation_errors_are_422(self):
        status, body, _ = self.client.request("POST", "/v1/servers/a/console", body={})
        self.assertEqual((status, body["code"]), (422, "missing_field"))
        status, body, _ = self.client.request("PUT", "/v1/servers/a/mode", body={"mode": "nope"})
        self.assertEqual((status, body["code"]), (422, "invalid_field"))
        status, body, _ = self.client.request("GET", "/v1/servers/a/logs?lines=0")
        self.assertEqual((status, body["code"]), (422, "invalid_parameter"))
        status, body, _ = self.client.request("GET", "/v1/servers/a/lists/nonsense")
        self.assertEqual(status, 422)
        self.assertTrue(body["message"])

    def test_unknown_server_is_404_with_the_available_list(self):
        status, body, _ = self.client.request("GET", "/v1/servers/zz")
        self.assertEqual((status, body["code"], body["available"]), (404, "not_found", ["1:a"]))
        self.assertEqual(validate_strict(body, ERROR), [])

    def test_active_alias_and_numeric_id(self):
        for ref in ("active", "1", "a"):
            status, body, _ = self.client.request("GET", f"/v1/servers/{ref}")
            self.assertEqual((status, body["name"]), (200, "a"), ref)

    def test_remote_operations_are_served_by_the_local_listener_too(self):
        for operation_id in mc_apiops.REMOTE_OPERATIONS:
            self.assertNotEqual(mc_apiops.HANDLERS[operation_id].__name__, "not_implemented", operation_id)
        status, body, _ = self.client.request("GET", "/v1/remote")
        self.assertEqual((status, body["code"], body["enabled"]), (200, "remote_status", False))
        self.assertEqual(validate_strict(body, resolve_response("getRemoteStatus")), [])

    def test_no_traceback_in_an_internal_error_and_the_server_goes_on(self):
        with mock.patch.object(mc_api, "status_document", side_effect=RuntimeError("secret detail")):
            status, body, _ = self.client.request("GET", "/v1/servers")
        self.assertEqual((status, body["code"]), (500, "internal_error"))
        self.assertNotIn("Traceback", json.dumps(body))
        self.assertNotIn("secret detail", json.dumps(body))
        self.assertEqual(self.client.request("GET", "/v1/servers")[0], 200)

    @unittest.skipIf(sys.platform == "win32", "POSIX-only behavior")
    def test_start_goes_through_the_release_hook(self):
        calls = []
        self.api.stop()
        self.api = started(self.env, "unix", release=lambda name, config: calls.append(name))
        self.client = Client(self.env["run"])
        with mock.patch.object(mc_api, "start", return_value=mc_api.result(True, "started", server="a")):
            status, body, _ = self.client.request("POST", "/v1/servers/a/start")
        self.assertEqual((status, body["code"], calls), (200, "started", ["a"]))

    def test_status_codes_follow_the_result_code(self):
        with mock.patch.object(mc_api, "start", return_value=mc_api.result(False, "rcon_failed", server="a")):
            self.assertEqual(self.client.request("POST", "/v1/servers/a/start")[0], 503)
        self.assertEqual(mc_httpapi.status_for("bad_anything"), 422)
        self.assertEqual(mc_httpapi.status_for("who_knows"), 500)
        self.assertEqual(mc_httpapi.status_for("server_running"), 409)

    def test_set_config_value_and_schedule(self):
        status, body, _ = self.client.request("PUT", "/v1/servers/a/config/backup_keep", body={"value": 5})
        self.assertEqual((status, body["code"], body["key"]), (200, "config_set", "backup_keep"))
        status, body, _ = self.client.request("PUT", "/v1/servers/a/config/backup_keep", body={"value": "x"})
        self.assertEqual((status, body["code"]), (422, "invalid_value"))
        status, body, _ = self.client.request("PUT", "/v1/servers/a/schedule", body={
            "open_hour": 20, "open_minute": 0, "close_hour": 3, "close_minute": 30})
        self.assertEqual((status, body["open"], body["close"]), (200, "20:00", "03:30"))
        status, body, _ = self.client.request("PUT", "/v1/servers/a/schedule", body={
            "open_hour": 3, "open_minute": 0, "close_hour": 3, "close_minute": 0})
        self.assertEqual(status, 422)

    def test_console_offline_is_409(self):
        status, body, _ = self.client.request("POST", "/v1/servers/a/console", body={"command": "list"})
        self.assertEqual((status, body["code"]), (409, "console_offline"))

    def test_task_lifecycle_201_then_200(self):
        status, body, _ = self.client.request("POST", "/v1/servers/a/tasks", body={
            "cron": "*/5 * * * *", "action": "backup"})
        self.assertEqual((status, body["code"]), (201, "task_added"))
        status, body, _ = self.client.request("PATCH", f"/v1/servers/a/tasks/{body['task']['id']}",
                                              body={"enabled": False})
        self.assertEqual(status, 200)
        status, body, _ = self.client.request("DELETE", "/v1/servers/a/tasks/zz")
        self.assertEqual((status, body["code"]), (404, "task_not_found"))


def resolve_response(operation_id, status="200"):
    response = OPERATIONS[operation_id]["responses"][status]
    if "$ref" in response:
        response = resolve(response["$ref"])
    return response["content"]["application/json"]["schema"]


class TestTcpWithToken(ApiCase):
    mode = "tcp"

    @unittest.skipIf(sys.platform == "win32", "POSIX-only behavior")
    def test_token_file_and_bearer(self):
        path = os.path.join(self.env["run"], "api.token")
        info = json.load(open(path))
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        self.assertGreaterEqual(len(info["token"]), 43)
        self.assertEqual(self.client.request("GET", "/v1/servers")[0], 200)
        self.assertEqual(self.client.request("GET", "/v1/servers", token=False)[0], 401)
        status, body, response = self.client.request("GET", "/v1/servers", token="wrong")
        self.assertEqual((status, body["code"], response.getheader("WWW-Authenticate")), (401, "unauthorized", "Bearer"))
        self.assertEqual(self.client.request("GET", "/v1/nothing", token=False)[0], 401)

    def test_api_info_is_public(self):
        self.assertEqual(self.client.request("GET", "/v1", token=False)[0], 200)

    def test_listens_on_loopback_only(self):
        self.assertEqual(self.client.found["host"], "127.0.0.1")
        self.assertEqual(self.api.server.server_address[0], "127.0.0.1")

    def test_token_files_vanish_on_stop(self):
        self.api.stop()
        self.assertFalse(os.path.exists(os.path.join(self.env["run"], "api.token")))


class TestJobs(ApiCase):

    def wait(self, job_id, states=("succeeded", "failed", "cancelled")):
        end = time.time() + 10
        while time.time() < end:
            status, body, _ = self.client.request("GET", f"/v1/jobs/{job_id}")
            self.assertEqual(status, 200)
            if body["state"] in states:
                return body
            time.sleep(0.05)
        self.fail("job did not finish")

    def test_202_then_followed_to_done(self):
        release = threading.Event()

        def slow(name, config):
            release.wait(5)
            return mc_api.result(True, "backup_created", server=name, backup="b1", path="/x", created_ts=1,
                                 message="ok")
        with mock.patch.object(mc_api, "backup_now", slow):
            status, body, response = self.client.request("POST", "/v1/servers/a/backups")
            self.assertEqual(status, 202)
            self.assertEqual(response.getheader("Location"), f"/v1/jobs/{body['id']}")
            self.assertEqual(validate_strict(body, resolve_response("createBackup", "202")), [])
            self.assertIn(body["state"], ("queued", "running"))
            release.set()
            done = self.wait(body["id"])
        self.assertEqual((done["state"], done["progress"], done["code"]), ("succeeded", 100, "backup_created"))
        self.assertEqual(validate_strict(done, resolve_response("getJob")), [])
        status, listing, _ = self.client.request("GET", "/v1/jobs?state=succeeded")
        self.assertEqual([j["id"] for j in listing["jobs"]], [body["id"]])
        self.assertEqual(validate_strict(listing, resolve_response("listJobs")), [])

    def test_quick_precondition_failure_is_a_plain_error(self):
        status, body, _ = self.client.request("POST", "/v1/servers/a/backups/latest/restore", body={"confirm": False})
        self.assertEqual((status, body["code"]), (422, "confirm_required"))
        status, body, _ = self.client.request("POST", "/v1/servers/a/backups/nothing/restore", body={"confirm": True})
        self.assertEqual((status, body["code"]), (404, "backup_not_found"))
        self.assertEqual(self.client.request("GET", "/v1/jobs")[1]["jobs"], [])

    def test_failure_and_exception_inside_a_job(self):
        def boom(name, config):
            time.sleep(0.6)
            raise RuntimeError("explosion")
        with mock.patch.object(mc_api, "backup_now", boom):
            status, body, _ = self.client.request("POST", "/v1/servers/a/backups")
            self.assertEqual(status, 202)
            done = self.wait(body["id"])
        self.assertEqual((done["state"], done["code"]), ("failed", "internal_error"))
        self.assertNotIn("explosion", json.dumps(done))

    def test_cancel_and_finished_conflict(self):
        release = threading.Event()
        with mock.patch.object(mc_api, "backup_now", lambda n, c: release.wait(5) or mc_api.result(True, "x")):
            _s, body, _ = self.client.request("POST", "/v1/servers/a/backups")
            status, cancelled, _ = self.client.request("DELETE", f"/v1/jobs/{body['id']}")
            self.assertEqual((status, cancelled["code"]), (200, "job_cancelled"))
            status, again, _ = self.client.request("DELETE", f"/v1/jobs/{body['id']}")
            self.assertEqual((status, again["code"]), (409, "job_finished"))
            release.set()
        self.assertEqual(self.client.request("GET", "/v1/jobs/zzz")[0], 404)

    def test_finished_jobs_are_purged_after_an_hour(self):
        clock = [1000.0]
        registry = mc_jobs.Registry(clock=lambda: clock[0])
        job = registry.submit("x", None, lambda progress: mc_api.result(True, "done"), settle=2)
        self.assertEqual(job.state, "succeeded")
        clock[0] += 3599
        self.assertEqual(len(registry.listing()), 1)
        clock[0] += 2
        self.assertEqual(registry.listing(), [])

    def test_progress_is_reported_and_published(self):
        events = []
        registry = mc_jobs.Registry(on_change=events.append)

        def work(progress):
            progress(50, 100)
            return mc_api.result(True, "done")
        job = registry.submit("x", "a", work, settle=2)
        self.assertIn(50, [e["progress"] for e in events])
        self.assertEqual(events[-1]["state"], "succeeded")
        self.assertEqual(job.document()["server"], "a")


class TestStreams(ApiCase):

    def setUp(self):
        super().setUp()
        self.api.app.ping_s = 0.2

    def test_events_receive_then_close_on_stop(self):
        conn, response = self.client.stream("/v1/events")
        self.assertEqual((response.status, response.getheader("Content-Type")), (200, "text/event-stream"))
        deadline = time.time() + 5
        while not self.api.app.hub.listening() and time.time() < deadline:
            time.sleep(0.02)
        self.api.app.hub.publish({"type": "state", "server": "a", "state": "running", "previous": "stopped",
                                  "at": "2026-10-18T10:00:00Z"})
        name, data = read_event(response)
        self.assertEqual(name, "state")
        event = json.loads(data)
        self.assertEqual(validate_strict(event, {"$ref": "#/components/schemas/Event"}), [])
        self.api.stop()
        end = time.time() + 5
        message = read_event(response, timeout=5)
        while message is not None and time.time() < end:
            message = read_event(response, timeout=5)
        self.assertIsNone(message)
        conn.close()

    def test_ping_comment_is_sent(self):
        conn, response = self.client.stream("/v1/events")
        seen = []
        end = time.time() + 5
        while time.time() < end and not any(l.startswith(b": ping") for l in seen):
            seen.append(response.fp.readline())
        self.assertTrue(any(l.startswith(b": ping") for l in seen))
        conn.close()

    def test_events_can_be_filtered_by_server(self):
        conn, response = self.client.stream("/v1/events?servers=other")
        while not self.api.app.hub.listening():
            time.sleep(0.02)
        hub = self.api.app.hub
        hub.publish({"type": "state", "server": "a", "state": "running", "at": "t"})
        hub.publish({"type": "state", "server": "other", "state": "stopped", "at": "t"})
        _name, data = read_event(response)
        self.assertEqual(json.loads(data)["server"], "other")
        conn.close()

    def test_job_changes_are_events(self):
        conn, response = self.client.stream("/v1/events")
        while not self.api.app.hub.listening():
            time.sleep(0.02)
        with mock.patch.object(mc_api, "backup_now", lambda n, c: mc_api.result(True, "backup_created")):
            self.client.request("POST", "/v1/servers/a/backups")
        names = set()
        for _ in range(4):
            message = read_event(response)
            if message:
                names.add((message[0], json.loads(message[1])["job"]["state"]))
        self.assertIn(("job", "succeeded"), names)
        conn.close()

    def test_console_stream_sends_lines_and_limits_to_three(self):
        log = os.path.join(self.env["folder"], "logs", "latest.log")
        with open(log, "w") as f:
            f.write("old one\nold two\n")
        conn, response = self.client.stream("/v1/servers/a/console?tail=1")
        self.assertEqual(read_event(response), ("line", "old two"))
        with open(log, "a") as f:
            f.write("fresh line\n")
        self.assertEqual(read_event(response), ("line", "fresh line"))
        others = [self.client.stream("/v1/servers/a/console") for _ in range(2)]
        for _c, r in others:
            self.assertEqual(r.status, 200)
        status, body, _ = self.client.request("GET", "/v1/servers/a/console")
        self.assertEqual((status, body["code"]), (429, "too_many_streams"))
        response.close()
        conn.close()
        for c, r in others:
            r.close()
            c.close()
        end = time.time() + 5
        while self.api.app.streams and time.time() < end:
            time.sleep(0.05)
        self.assertEqual(self.api.app.streams, 0)

    def test_state_and_player_changes_are_published_by_the_poller(self):
        app = self.api.app
        box = app.hub.subscribe()
        states = iter(["stopped", "running", "running"])
        with mock.patch.object(mc_api, "server_snapshot", lambda n, i, a=None: {"state": next(states)}), \
                mock.patch.object(mc_api, "query_players", return_value=(True, {"online": 1, "max": 20,
                                                                              "players": ["Steve"]})), \
                mock.patch("mc_config.load_config", return_value={}):
            app.poll_once(now=0)
            app.poll_once(now=100)
        kinds = []
        while not box.empty():
            kinds.append(box.get()[1]["type"])
        self.assertEqual(kinds, ["state"])

    def test_alert_events_reach_the_hub(self):
        box = self.api.app.hub.subscribe()
        config = {"dossier_serveur": self.env["folder"]}
        with mock.patch("mc_alert.notify"):
            mc_core._alert(config, "crash", detail="boom")
        _id, event = box.get(timeout=2)
        self.assertEqual((event["type"], event["server"], event["event"], event["detail"]),
                         ("alert", "a", "crash", "boom"))
        self.assertEqual(validate_strict(event, {"$ref": "#/components/schemas/Event"}), [])


class TestResilience(unittest.TestCase):

    def test_sync_never_raises_and_retries_later(self):
        with api_environment() as env:
            api = mc_httpapi.LocalApi(folder=env["run"], enabled=lambda: True)
            with mock.patch.object(mc_httpapi.ApiApp, "__init__", side_effect=OSError("boom")):
                api.sync()
            self.assertFalse(api.alive())
            api.retry_at = 0
            api.sync()
            self.assertTrue(api.alive())
            api.stop()

    def test_dead_listener_is_restarted(self):
        with api_environment() as env:
            api = mc_httpapi.LocalApi(folder=env["run"], enabled=lambda: True)
            api.sync()
            api.server.shutdown()
            api.thread.join(5)
            self.assertFalse(api.alive())
            api.retry_at = 0
            api.sync()
            self.assertTrue(api.alive())
            self.assertEqual(Client(env["run"]).request("GET", "/v1")[0], 200)
            api.stop()

    def test_disabled_option_stops_the_listener(self):
        with api_environment() as env:
            flag = [True]
            api = mc_httpapi.LocalApi(folder=env["run"], enabled=lambda: flag[0])
            api.sync()
            self.assertTrue(api.alive())
            flag[0] = False
            api.sync()
            self.assertFalse(api.alive())
            self.assertFalse(os.path.exists(os.path.join(env["run"], "api.sock")))

    def test_daemon_loop_survives_a_failing_api(self):
        import mc_daemon
        self.assertTrue(hasattr(mc_daemon, "mc_httpapi"))
        api = mc_httpapi.LocalApi(enabled=lambda: 1 / 0)
        api.sync()

    def test_default_is_enabled_and_option_is_persisted(self):
        with api_environment():
            self.assertTrue(mc_httpapi.local_enabled())
            mc_httpapi.set_local_enabled(False)
            self.assertFalse(mc_httpapi.local_enabled())
            mc_httpapi.set_local_enabled(True)
            self.assertTrue(mc_httpapi.local_enabled())


class TestContractConformity(unittest.TestCase):

    def test_every_operation_has_a_handler_and_every_handler_is_in_the_contract(self):
        self.assertEqual(set(mc_apiops.HANDLERS), set(OPERATIONS))

    def test_routes_cover_every_path_and_method_of_the_contract(self):
        routes = mc_httpapi.build_routes(SPEC)
        self.assertEqual({(r.method, r.template) for r in routes},
                         {(m.upper(), p) for p, item in SPEC["paths"].items() for m in item
                          if m in mc_httpapi.METHODS})
        self.assertEqual(len(routes), len(OPERATIONS))

    def test_job_operations_follow_the_202_of_the_contract(self):
        for route in mc_httpapi.build_routes(SPEC):
            self.assertEqual(route.success, min(int(c) for c in route.operation["responses"] if c[0] == "2"))

    def test_the_remote_group_is_listed(self):
        remote = {op["operationId"] for op in OPERATIONS.values() if op["tags"] == ["remote"]}
        self.assertEqual(remote, set(mc_apiops.REMOTE_OPERATIONS))
        self.assertEqual(len(OPERATIONS) - len(remote), 88)

    def test_build_package_ships_the_contract(self):
        sys.path.insert(0, os.path.join(ROOT, "Linux"))
        import build_release
        for name in ("openapi.json", "mc_httpapi.py", "mc_apiops.py", "mc_jobs.py", "mc_remote.py",
                     "mc_remoteserver.py", "mc_remoteclient.py"):
            self.assertIn(name, build_release.PACKAGE_FILES)
            self.assertTrue(os.path.exists(build_release.source_path(name)))
        self.assertTrue(os.path.exists(mc_httpapi.spec_path()))


class TestAgreementWithTheCli(unittest.TestCase):
    """The HTTP answer is the document `mc ... --json` prints, and fits the contract."""

    SAMPLE = (
        (("status",), "/v1/servers", "listServers", None),
        (("active",), "/v1/servers/a", "getServer", "code"),
        (("sleep", "status"), "/v1/servers/a/sleep", "getSleepSettings", None),
        (("mod", "list"), "/v1/servers/a/mods", "listMods", None),
        (("java", "list"), "/v1/java", "listJava", None),
        (("java", "list", "a"), "/v1/servers/a/java", "listServerJava", None),
        (("ban", "list"), "/v1/servers/a/lists/ban", "listPlayerList", None),
        (("op", "list"), "/v1/servers/a/lists/op", "listPlayerList", None),
        (("whitelist", "list"), "/v1/servers/a/lists/whitelist", "listPlayerList", None),
        (("router", "status"), "/v1/router", "getRouter", None),
        (("task", "list"), "/v1/servers/a/tasks", "listTasks", None),
        (("backup", "list"), "/v1/servers/a/backups", "listBackups", None),
        (("backup", "remote", "list"), "/v1/servers/a/backups/remotes", "listBackupRemotes", None),
        (("alert", "list"), "/v1/servers/a/alerts", "listAlertChannels", None),
        (("config", "get"), "/v1/servers/a/config", "getServerConfig", None),
        (("config", "get", "port"), "/v1/servers/a/config/port", "getConfigValue", None),
        (("config", "get", "mcrcon_pass"), "/v1/servers/a/config/mcrcon_pass", "getConfigValue", None),
        (("world", "list"), "/v1/servers/a/worlds", "listWorlds", None),
        (("datapack", "list"), "/v1/servers/a/datapacks", "listDatapacks", None),
        (("players", "history"), "/v1/servers/a/players/history", "getPlayerHistory", None),
        (("players",), "/v1/servers/a/players", "listOnlinePlayers", None),
    )

    def cli(self, env, *argv):
        res = subprocess.run([sys.executable, os.path.join(ROOT, "core", "mc_cli.py"), *argv, "--json"],
                             capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60,
                             env=dict(os.environ, MCMANAGER_DATA_DIR=env["data"], NO_COLOR="1"))
        return json.loads(res.stdout)

    def test_get_routes_equal_the_cli_documents(self):
        with api_environment({"alerts": [{"name": "wh", "type": "webhook", "events": ["*"],
                                          "url": "https://hook.example/x"}]}) as env:
            api = started(env)
            client = Client(env["run"])
            try:
                for argv, path, operation_id, ignore in self.SAMPLE:
                    with self.subTest(command=" ".join(argv)):
                        status, body, _ = client.request("GET", path)
                        expected = self.cli(env, *argv)
                        key = "200" if status == 200 else str(status)
                        schema = resolve_response(operation_id, key) if key in OPERATIONS[operation_id]["responses"] \
                            else ERROR
                        self.assertEqual(validate_strict(body, schema), [], path)
                        if ignore:
                            body, expected = dict(body), dict(expected)
                            body.pop(ignore), expected.pop(ignore)
                        if not expected["ok"]:
                            expected.pop("error", None)
                            body.pop("error", None)
                        self.assertEqual(body, expected)
            finally:
                api.stop()

    def test_every_get_route_answers_inside_the_contract(self):
        with api_environment() as env:
            api = started(env)
            client = Client(env["run"])
            try:
                for route in mc_httpapi.build_routes(SPEC):
                    if route.method != "GET" or route.operation_id in ("streamEvents", "streamConsole",
                                                                      "getMetrics") \
                            or route.operation_id in mc_apiops.REMOTE_OPERATIONS:
                        continue
                    path = route.template
                    for name, value in (("server", "a"), ("kind", "ban"), ("job", "j_none"), ("key", "port")):
                        path = path.replace("{" + name + "}", value)
                    query = "?source=https://example.invalid/x" if "{" not in path and route.operation_id == \
                        "getModpackInfo" else ""
                    if route.operation_id in ("getModpackInfo", "checkUpdate", "getDoctorReport",
                                              "getServerDoctorReport"):
                        continue
                    with self.subTest(route=route.operation_id):
                        status, body, _ = client.request("GET", path + query)
                        self.assertIn(str(status), route.operation["responses"])
                        self.assertIsInstance(body, dict)
                        self.assertIn("ok", body)
            finally:
                api.stop()

    def test_doctor_and_metrics(self):
        checks = [("ok", "Java", "21", None)]
        import mc_doctor
        with api_environment() as env:
            api = started(env)
            client = Client(env["run"])
            try:
                with mock.patch.object(mc_doctor, "check_host", return_value=checks), \
                        mock.patch.object(mc_doctor, "check_server", return_value=[("err", "Port", "bad", "fix")]):
                    status, body, _ = client.request("GET", "/v1/doctor")
                self.assertEqual((status, body["ok"], body["errors"]), (200, False, 1))
                self.assertEqual(validate_strict(body, resolve_response("getDoctorReport")), [])
                status, text, response = client.request("GET", "/v1/metrics")
                self.assertEqual(status, 200)
                self.assertIn("text/plain", response.getheader("Content-Type"))
            finally:
                api.stop()


class TestApiCommand(unittest.TestCase):

    def run_cli(self, data, *argv):
        res = subprocess.run([sys.executable, os.path.join(ROOT, "core", "mc_cli.py"), "api", *argv],
                             capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60,
                             env=dict(os.environ, MCMANAGER_DATA_DIR=data, NO_COLOR="1"))
        return res.returncode, res.stdout

    def test_status_enable_disable(self):
        data = tempfile.mkdtemp()
        rc, out = self.run_cli(data, "status", "--json")
        doc = json.loads(out)
        self.assertEqual((rc, doc["code"], doc["enabled"], doc["listening"]), (0, "api_status", True, False))
        rc, out = self.run_cli(data, "disable", "--json")
        self.assertEqual(json.loads(out)["code"], "api_disabled")
        self.assertFalse(json.loads(self.run_cli(data, "status", "--json")[1])["enabled"])
        self.assertEqual(self.run_cli(data, "enable")[0], 0)
        self.assertTrue(json.loads(self.run_cli(data, "status", "--json")[1])["enabled"])


if __name__ == "__main__":
    unittest.main()


class TestDocumentedStatuses(unittest.TestCase):
    """Every failure code the contract documents with an HTTP status gets that
    status from the server, never a 500."""

    def test_documented_codes_have_their_status(self):
        import re
        with open(os.path.join(os.path.dirname(__file__), "..", "..", "api", "openapi.json"), encoding="utf-8") as f:
            spec = json.load(f)
        found = {}

        def scan(text):
            pending, current = [], None
            for token in re.findall(r"`[a-z][a-z0-9_]+`|\(\d{3}\)|\b\d{3}:", text):
                if token.startswith("`"):
                    (found.__setitem__(token.strip("`"), current) if current else pending.append(token.strip("`")))
                elif token.startswith("("):
                    for code in pending:
                        found[code] = int(token[1:4])
                    pending, current = [], None
                else:
                    pending, current = [], int(token[:3])

        def walk(node):
            if isinstance(node, dict):
                for key, value in node.items():
                    scan(value) if key == "description" and isinstance(value, str) else walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)
        walk(spec)
        self.assertGreater(len(found), 50)
        from mc_lang import T
        wrong = {code: want for code, want in found.items()
                 if code not in ("ok", "java_present", "pack_deployed") and "res_" + code in T and mc_httpapi.status_for(code) == 500 and want != 500}
        self.assertEqual(wrong, {})
