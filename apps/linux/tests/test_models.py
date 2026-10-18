import json
import unittest

from tests.support import FakeClient, sync_runner

from mcmanager_app import i18n
from mcmanager_app.client import ApiError
from mcmanager_app.models import (ConnectionModel, ConsoleModel, ServerDetailModel, ServerListModel, format_ram,
                                  players_text)


def snapshot(name, state="running", **extra):
    return dict({"name": name, "state": state, "rss_kb": 2 * 1024 * 1024, "active": True}, **extra)


class ModelCase(unittest.TestCase):
    def setUp(self):
        i18n.set_language("en")
        self.addCleanup(i18n.set_language, "en")
        self.client = FakeClient()
        self.runner = sync_runner()


class TestServerList(ModelCase):
    def test_refresh_builds_rows_with_players_and_ram(self):
        self.client.servers = [snapshot("a"), snapshot("b", "stopped")]
        self.client.player_docs["a"] = {"online": 2, "max": 20, "players": ["Steve", "Alex"]}
        model = ServerListModel(self.client, self.runner)
        calls = []
        model.subscribe(lambda: calls.append(1))
        model.refresh()
        self.assertEqual(list(model.rows), ["a", "b"])
        self.assertEqual(model.rows["a"]["players"], ["Steve", "Alex"])
        self.assertEqual(players_text(model.rows["a"]), "2/20 online")
        self.assertEqual(model.rows["a"]["ram_text"], "2.0 GB")
        self.assertEqual(model.rows["b"]["state_text"], "Stopped")
        self.assertIsNone(model.rows["b"]["online"])
        self.assertTrue(calls)
        self.assertFalse(model.loading)

    def test_refresh_error_is_translated_and_keeps_nothing(self):
        self.client.fail["list"] = "daemon_unreachable"
        model = ServerListModel(self.client, self.runner)
        model.refresh()
        self.assertIn("daemon_unreachable", model.error)

    def test_state_event_updates_the_row_and_clears_players(self):
        self.client.servers = [snapshot("a")]
        self.client.player_docs["a"] = {"online": 1, "max": 20, "players": ["Steve"]}
        model = ServerListModel(self.client, self.runner)
        model.refresh()
        model.apply_event({"type": "state", "server": "a", "state": "stopped"})
        self.assertEqual(model.rows["a"]["state"], "stopped")
        self.assertEqual(model.rows["a"]["players"], [])
        self.assertIsNone(model.rows["a"]["online"])

    def test_players_event_updates_counts(self):
        self.client.servers = [snapshot("a")]
        model = ServerListModel(self.client, self.runner)
        model.refresh()
        model.apply_event({"type": "players", "server": "a", "online": 3, "players": ["x", "y", "z"], "max": 10})
        self.assertEqual((model.rows["a"]["online"], model.rows["a"]["max"]), (3, 10))

    def test_event_for_an_unknown_server_refreshes(self):
        model = ServerListModel(self.client, self.runner)
        model.refresh()
        self.client.servers = [snapshot("new")]
        model.apply_event({"type": "state", "server": "new", "state": "running"})
        self.assertIn("new", model.rows)

    def test_raw_event_json_is_parsed_and_garbage_ignored(self):
        self.client.servers = [snapshot("a")]
        model = ServerListModel(self.client, self.runner)
        model.refresh()
        model.on_raw_event("state", "not json")
        model.on_raw_event("state", json.dumps({"type": "state", "server": "a", "state": "crashed"}))
        self.assertEqual(model.rows["a"]["state"], "crashed")

    def test_reconnect_resynchronises(self):
        self.client.servers = [snapshot("a")]
        model = ServerListModel(self.client, self.runner)
        model.refresh()
        model.stream_state("lost")
        self.assertFalse(model.connected)
        self.client.servers = [snapshot("a"), snapshot("b")]
        model.stream_state("open")
        self.assertTrue(model.connected)
        self.assertIn("b", model.rows)

    def test_events_start_and_stop(self):
        model = ServerListModel(self.client, self.runner)
        model.start_events()
        stream = self.client.streams[0]
        self.assertTrue(stream.started)
        model.stop_events()
        self.assertTrue(stream.stopped)

    def test_format_ram(self):
        self.assertEqual(format_ram(None), "")
        self.assertEqual(format_ram(512 * 1024), "512 MB")


class TestServerDetail(ModelCase):
    def test_action_goes_busy_then_done(self):
        model = ServerDetailModel(self.client, "a", self.runner)
        seen = []
        model.subscribe(lambda: seen.append(model.busy))
        self.assertTrue(model.run_action("start"))
        self.assertEqual(seen, ["start", None])
        self.assertEqual(model.message, "Server started")
        self.assertIsNone(model.error)
        self.assertEqual(self.client.calls, [("a", "start")])

    def test_job_actions_wait_for_the_job(self):
        self.client.action_status = 202
        model = ServerDetailModel(self.client, "a", self.runner)
        model.run_action("restart")
        self.assertIn(("wait", "j1"), self.client.calls)
        self.assertEqual(model.message, "Server restarted")

    def test_error_is_translated_in_both_languages(self):
        self.client.fail["start"] = "server_running"
        model = ServerDetailModel(self.client, "a", self.runner)
        model.run_action("start")
        self.assertEqual(model.error, "The server is already running")
        i18n.set_language("fr")
        model.run_action("start")
        self.assertEqual(model.error, "Le serveur tourne déjà")

    def test_unknown_code_falls_back_to_generic_text(self):
        self.client.fail["stop"] = "weird_code"
        model = ServerDetailModel(self.client, "a", self.runner)
        model.run_action("stop")
        self.assertIn("weird_code", model.error)

    def test_second_action_while_busy_is_refused(self):
        model = ServerDetailModel(self.client, "a", sync_runner())
        model.busy = "start"
        self.assertFalse(model.run_action("stop"))
        self.assertFalse(any(model.can("running").values()))

    def test_unknown_action_is_a_programming_error(self):
        with self.assertRaises(ValueError):
            ServerDetailModel(self.client, "a", self.runner).run_action("explode")

    def test_available_actions_by_state(self):
        model = ServerDetailModel(self.client, "a", self.runner)
        self.assertEqual({k for k, v in model.can("running").items() if v}, {"stop", "restart"})
        self.assertEqual({k for k, v in model.can("stopped").items() if v}, {"start"})
        self.assertEqual({k for k, v in model.can("sleeping").items() if v}, {"wake"})

    def test_config_is_loaded_read_only(self):
        model = ServerDetailModel(self.client, "a", self.runner)
        model.load_config()
        self.assertEqual(model.config, {"port": 25565})
        self.assertEqual(model.secrets_set, ["mcrcon_pass"])


class TestConsole(ModelCase):
    def test_buffer_is_bounded(self):
        model = ConsoleModel(self.client, "a", self.runner, limit=5)
        for index in range(12):
            model.on_raw_line("line", "l%d" % index)
        self.assertEqual(list(model.lines), ["l7", "l8", "l9", "l10", "l11"])

    def test_default_buffer_is_2000_lines(self):
        model = ConsoleModel(self.client, "a", self.runner)
        for index in range(2100):
            model.add_line(str(index))
        self.assertEqual((len(model.lines), model.lines[0]), (2000, "100"))

    def test_other_events_are_ignored(self):
        model = ConsoleModel(self.client, "a", self.runner)
        model.on_raw_line("ping", "x")
        self.assertEqual(len(model.lines), 0)

    def test_send_command(self):
        model = ConsoleModel(self.client, "a", self.runner)
        self.assertFalse(model.send("   "))
        self.assertTrue(model.send(" list "))
        self.assertEqual(self.client.calls, [("a", "cmd", "list")])
        self.assertFalse(model.sending)

    def test_send_error(self):
        self.client.fail["cmd"] = "console_offline"
        model = ConsoleModel(self.client, "a", self.runner)
        model.send("list")
        self.assertEqual(model.error, "The server is not running")

    def test_refused_stream_reports_the_cause(self):
        model = ConsoleModel(self.client, "a", self.runner)
        model.set_state("refused:403")
        self.assertEqual(model.error, "Your role does not allow this action")

    def test_stream_lifecycle(self):
        model = ConsoleModel(self.client, "a", self.runner)
        model.start()
        stream = self.client.streams[0]
        model.stop()
        self.assertTrue(stream.started and stream.stopped)


class TestConnection(ModelCase):
    def make(self, local=True, pair_error=None):
        self.paired = []

        def pair(address, fingerprint, code, name, profile):
            if pair_error:
                raise ApiError(pair_error)
            self.paired.append((address, fingerprint, code, name, profile))

        return ConnectionModel(lambda: object() if local else None, lambda name: object() if self.paired else None,
                               pair, lambda address: "AA:BB", self.runner)

    def test_local_choice(self):
        model = self.make()
        self.assertIsNotNone(model.use_local())
        self.assertIsNone(model.error)

    def test_local_missing_daemon(self):
        model = self.make(local=False)
        self.assertIsNone(model.use_local())
        self.assertIn("daemon", model.error)

    def test_pairing_needs_the_fingerprint_first(self):
        model = self.make()
        self.assertFalse(model.submit_pairing("h:1", "12345678", "pc"))
        model.fetch_fingerprint("h:1")
        self.assertEqual(model.fingerprint, "AA:BB")
        self.assertTrue(model.submit_pairing("h:1", " 12345678 ", "pc"))
        self.assertEqual(self.paired, [("h:1", "AA:BB", "12345678", "pc", "default")])
        self.assertIsNotNone(model.client)

    def test_pairing_error_is_translated(self):
        model = self.make(pair_error="bad_pair_code")
        model.fetch_fingerprint("h:1")
        model.submit_pairing("h:1", "00000000", "pc")
        self.assertEqual(model.error, "Wrong or expired pairing code")
        self.assertIsNone(model.client)
        self.assertFalse(model.busy)


if __name__ == "__main__":
    unittest.main()
