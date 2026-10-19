import json
import unittest
from unittest import mock

from tests.support import api_environment, local_client, start_api, wait_for

import mc_api
from mcmanager_app.client import ApiClient, ApiError, EventStream, LocalTransport, sse_messages


class TestAgainstLocalApi(unittest.TestCase):
    def setUp(self):
        manager = api_environment()
        self.env = manager.__enter__()
        self.addCleanup(manager.__exit__, None, None, None)
        self.api = start_api(self.env)
        self.addCleanup(self.api.stop)
        self.client = local_client(self.env)

    def test_discover_finds_the_socket(self):
        self.assertIsNotNone(LocalTransport.discover(self.env["run"]))
        self.assertIsNone(LocalTransport.discover(self.env["data"]))

    def test_info_and_server_list(self):
        self.assertEqual(self.client.info()["api"], "1")
        servers = self.client.list_servers()
        self.assertEqual([s["name"] for s in servers], ["a"])

    def test_server_detail_by_name_and_active(self):
        self.assertEqual(self.client.get_server("a")["name"], "a")
        self.assertEqual(self.client.get_server("active")["name"], "a")

    def test_unknown_server_raises_a_typed_error(self):
        with self.assertRaises(ApiError) as caught:
            self.client.get_server("zz")
        self.assertEqual((caught.exception.code, caught.exception.status), ("not_found", 404))

    def test_start_action_returns_the_result(self):
        with mock.patch.object(mc_api, "start", return_value=mc_api.result(True, "started", server="a")):
            status, document = self.client.action("a", "start")
        self.assertEqual((status, document["code"]), (200, "started"))

    def test_failed_action_raises_with_the_code(self):
        failure = mc_api.result(False, "server_running", server="a")
        with mock.patch.object(mc_api, "start", return_value=failure):
            with self.assertRaises(ApiError) as caught:
                self.client.action("a", "start")
        self.assertEqual((caught.exception.code, caught.exception.status), ("server_running", 409))

    def test_console_command_on_a_stopped_server_is_refused(self):
        with self.assertRaises(ApiError) as caught:
            self.client.send_command("a", "list")
        self.assertEqual(caught.exception.status, 409)

    def test_players_of_a_stopped_server_fail(self):
        with self.assertRaises(ApiError) as caught:
            self.client.players("a")
        self.assertEqual(caught.exception.code, "server_offline")

    def test_lists_add_and_remove_round_trip(self):
        for kind in ("whitelist", "op", "ban"):
            self.assertEqual(self.client.player_list("a", kind)["entries"], [])
        try:
            self.client.add_to_list("a", "whitelist", "Notch")
        except ApiError as exc:
            self.fail(exc.code)
        names = [e["name"] for e in self.client.player_list("a", "whitelist")["entries"]]
        self.assertEqual(names, ["Notch"])
        self.client.remove_from_list("a", "whitelist", "Notch")
        self.assertEqual(self.client.player_list("a", "whitelist")["entries"], [])

    def test_invalid_name_and_offline_kick_are_typed_errors(self):
        with self.assertRaises(ApiError) as caught:
            self.client.add_to_list("a", "ban", "bad name!", "grief")
        self.assertEqual(caught.exception.code, "invalid_name")
        with self.assertRaises(ApiError) as caught:
            self.client.kick("a", "Steve")
        self.assertGreaterEqual(caught.exception.status, 409)

    def test_job_is_followed_to_its_end(self):
        with mock.patch.object(mc_api, "backup_now", lambda n, c: mc_api.result(True, "backup_created")):
            status, document = self.client.call("POST", "/v1/servers/a/backups")
        self.assertEqual(status, 202)
        result = self.client.wait_job(document["id"], step=0.05)
        self.assertEqual(result["code"], "backup_created")

    def test_failed_job_raises(self):
        with mock.patch.object(mc_api, "backup_now", lambda n, c: mc_api.result(False, "backup_failed")):
            _status, document = self.client.call("POST", "/v1/servers/a/backups")
        with self.assertRaises(ApiError) as caught:
            self.client.wait_job(document["id"], step=0.05)
        self.assertEqual(caught.exception.code, "backup_failed")

    def test_backup_list_create_and_restore(self):
        entry = {"id": "a_midi", "file": "a_midi.zip", "path": "/x/a_midi.zip", "size": 10, "type": "midi",
                 "created": "2026-10-08T12:00:03", "encrypted": False, "created_ts": 1}
        listing = mc_api.result(True, "backup_list", server="a", backups=[entry], count=1)
        with mock.patch.object(mc_api, "backup_list", lambda n, c: listing):
            self.assertEqual(self.client.list_backups("a")["backups"][0]["id"], "a_midi")
        with mock.patch.object(mc_api, "backup_now", lambda n, c: mc_api.result(True, "backup_created")):
            document = self.client.create_backup("a")
        seen = []
        result = self.client.wait_job(document["id"], step=0.05, on_progress=seen.append)
        self.assertEqual(result["code"], "backup_created")
        self.assertTrue(seen)
        with mock.patch.object(mc_api, "backup_restore", lambda n, c, ref: mc_api.result(True, "backup_restored", backup=ref)):
            document = self.client.restore_backup("a", "a_midi")
        self.assertEqual(self.client.wait_job(document["id"], step=0.05)["backup"], "a_midi")

    def test_restore_errors_are_typed(self):
        missing = mc_api.result(False, "backup_not_found", server="a")
        with mock.patch.object(mc_api, "backup_restore", lambda n, c, ref: missing):
            with self.assertRaises(ApiError) as caught:
                self.client.restore_backup("a", "zz")
        self.assertIn(caught.exception.code, ("backup_not_found", "job_failed"))
        with self.assertRaises(ApiError) as caught:
            self.client.call("POST", "/v1/servers/a/backups/zz/restore", {})
        self.assertIn(caught.exception.code, ("confirm_required", "confirmation_required", "missing_field"))

    def test_event_stream_receives_then_stops_cleanly(self):
        received, states = [], []
        stream = self.client.events(lambda name, data: received.append((name, json.loads(data))), states.append)
        stream.start()
        self.assertTrue(wait_for(lambda: self.api.app.hub.listening() and "open" in states))
        self.api.app.hub.publish({"type": "state", "server": "a", "state": "running", "previous": "stopped",
                                  "at": "2026-10-18T10:00:00Z"})
        self.assertTrue(wait_for(lambda: received))
        self.assertEqual(received[0][0], "state")
        self.assertEqual(received[0][1]["state"], "running")
        stream.stop()
        self.assertFalse(stream.thread.is_alive())
        self.assertEqual(states[-1], "closed")

    def test_event_stream_reconnects_after_the_server_restarts(self):
        states = []
        stream = EventStream(self.client.transport, "/v1/events", lambda n, d: None, states.append, retry_s=0.1)
        stream.start()
        self.assertTrue(wait_for(lambda: "open" in states))
        self.api.stop()
        self.assertTrue(wait_for(lambda: "lost" in states))
        self.api = start_api(self.env)
        self.addCleanup(self.api.stop)
        self.assertTrue(wait_for(lambda: states.count("open") >= 2, timeout=10))
        stream.stop()

    def test_console_stream_delivers_lines(self):
        import os
        log = os.path.join(self.env["folder"], "logs", "latest.log")
        with open(log, "w") as handle:
            handle.write("hello\n")
        lines = []
        stream = self.client.console("a", lambda name, data: lines.append((name, data)), tail=5)
        stream.start()
        self.assertTrue(wait_for(lambda: ("line", "hello") in lines))
        stream.stop()

    def test_stream_refused_status_is_reported(self):
        states = []
        stream = self.client.console("zz", lambda n, d: None, states.append, max_retries=1, retry_s=0.05)
        stream.start()
        self.assertTrue(wait_for(lambda: "failed" in states))
        self.assertIn("refused:404", states)
        stream.stop()

    def test_unreachable_daemon_is_an_error_not_a_crash(self):
        client = ApiClient(LocalTransport("/nonexistent/api.sock"))
        with self.assertRaises(ApiError) as caught:
            client.list_servers()
        self.assertEqual(caught.exception.code, "daemon_unreachable")


class TestSse(unittest.TestCase):
    def test_parser_handles_comments_ids_and_multiline_data(self):
        class Fp:
            def __init__(self, text):
                self.lines = iter(text.encode().splitlines(True))

            def readline(self):
                return next(self.lines, b"")

        class Response:
            fp = Fp(": ping\n\nid: 7\nevent: state\ndata: {\"a\":\ndata: 1}\n\ndata: bare\n\n")

        messages = list(sse_messages(Response()))
        self.assertEqual(messages, [("7", "state", '{"a":\n1}'), ("7", "message", "bare")])


if __name__ == "__main__":
    unittest.main()
