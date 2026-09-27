"""
test_api.py — Machine-facing API (2.5.0): player list parsing, durations,
explicit states, freeze/thaw markers, 'mc config set' propagation.
"""
import datetime
import json
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import mc_api
import mc_config
import mc_core
import mc_servers


class TestPlayerList(unittest.TestCase):

    def test_vanilla_modern(self):
        self.assertEqual(
            mc_api.parse_player_list("There are 2 of a max of 20 players online: Steve, Alex"),
            (2, 20, ["Steve", "Alex"]))

    def test_vanilla_nobody(self):
        self.assertEqual(mc_api.parse_player_list("There are 0 of a max of 20 players online: "),
                         (0, 20, []))

    def test_slash_format(self):
        self.assertEqual(mc_api.parse_player_list("There are 1/20 players online:\nSteve"),
                         (1, 20, ["Steve"]))

    def test_essentials_like_with_colours_and_groups(self):
        text = "§6Online players (§c1§6/§c20§6):\n§6default§r: §fSteve"
        self.assertEqual(mc_api.parse_player_list(text), (1, 20, ["Steve"]))

    def test_unrecognised(self):
        self.assertEqual(mc_api.parse_player_list("Unknown command"), (None, None, []))


class TestDurations(unittest.TestCase):

    def test_values(self):
        self.assertEqual(mc_api.parse_duration("90"), 90)
        self.assertEqual(mc_api.parse_duration("30m"), 1800)
        self.assertEqual(mc_api.parse_duration("2h"), 7200)
        self.assertEqual(mc_api.parse_duration("1h30m"), 5400)

    def test_invalid(self):
        for bad in ("", "abc", "2x", "1h foo"):
            with self.assertRaises(ValueError):
                mc_api.parse_duration(bad)


class TestStates(unittest.TestCase):

    def _state(self, config, running=False, listening=False, now=None):
        with mock.patch.object(mc_core, "is_server_running", return_value=running), \
             mock.patch.object(mc_api, "_is_listening", return_value=listening):
            return mc_api.server_state(config, now)

    def test_running_and_starting(self):
        self.assertEqual(self._state({}, running=True, listening=True), "running")
        self.assertEqual(self._state({}, running=True, listening=False), "starting")

    def test_maintenance_flavours(self):
        self.assertEqual(self._state({"mode_maintenance": 1}), "stopped-by-user")
        self.assertEqual(self._state({"mode_maintenance": 1, "stop_reason": "user"}), "stopped-by-user")
        self.assertEqual(self._state({"mode_maintenance": 1, "stop_reason": "sleep"}), "sleeping")
        self.assertEqual(self._state({"mode_maintenance": 1, "stop_reason": "update"}), "maintenance")

    def test_stopped_vs_closed(self):
        self.assertEqual(self._state({"always_on": 1}), "stopped")
        sched = {"always_on": 0, "heure_ouverture": 20, "minute_ouverture": 0,
                 "heure_fermeture": 3, "minute_fermeture": 0}
        self.assertEqual(self._state(sched, now=datetime.datetime(2026, 1, 1, 12, 0)), "closed")
        self.assertEqual(self._state(sched, now=datetime.datetime(2026, 1, 1, 22, 0)), "stopped")

    def test_every_state_has_a_label(self):
        import mc_lang
        for lang in (mc_lang._FR, mc_lang._EN):
            for state in mc_api.STATES:
                if state not in ("running", "starting"):
                    self.assertIn(f"state_{state.replace('-', '_')}", lang)

    def test_every_stop_reason_has_a_template(self):
        for lang in ("fr", "en"):
            for reason in mc_api.STOP_REASONS:
                key = mc_core.STOP_WEBHOOKS[reason]
                self.assertIn(key, mc_config._FALLBACK_WEBHOOKS[lang])
        with open(os.path.join(os.path.dirname(__file__), "..", "webhook_templates.json"), encoding="utf-8") as f:
            shipped = json.load(f)
        for lang in ("fr", "en"):
            for key in set(mc_core.STOP_WEBHOOKS.values()):
                self.assertIn(key, shipped[lang])


class TestFreeze(unittest.TestCase):

    def setUp(self):
        self.config = {"dossier_serveur": tempfile.mkdtemp()}

    def test_offline_freeze_is_exclusive_and_thaw_releases(self):
        with mock.patch.object(mc_core, "is_server_running", return_value=False):
            self.assertEqual(mc_api.freeze(self.config, 60), (True, "offline"))
            self.assertTrue(mc_api.is_frozen(self.config))
            self.assertEqual(mc_api.freeze(self.config, 60), (False, "already_frozen"))
            self.assertEqual(mc_api.thaw(self.config), (True, "offline"))
            self.assertFalse(mc_api.is_frozen(self.config))

    def test_running_freeze_sends_save_off_then_flush(self):
        sent = []
        with mock.patch.object(mc_core, "is_server_running", return_value=True), \
             mock.patch.object(mc_core, "send_rcon", side_effect=lambda c, cmd: sent.append(cmd) or True):
            self.assertEqual(mc_api.freeze(self.config, 60), (True, "frozen"))
            self.assertEqual(sent, ["save-off", "save-all flush"])
            self.assertEqual(mc_api.thaw(self.config), (True, "thawed"))
            self.assertEqual(sent[-1], "save-on")

    def test_rcon_failure_leaves_no_marker(self):
        with mock.patch.object(mc_core, "is_server_running", return_value=True), \
             mock.patch.object(mc_core, "send_rcon", return_value=False):
            self.assertEqual(mc_api.freeze(self.config, 60), (False, "rcon_error"))
            self.assertFalse(mc_api.is_frozen(self.config))

    def test_thaw_keeps_marker_if_rcon_fails(self):
        with mock.patch.object(mc_core, "is_server_running", return_value=False):
            mc_api.freeze(self.config, 60)
        with mock.patch.object(mc_core, "is_server_running", return_value=True), \
             mock.patch.object(mc_core, "send_rcon", return_value=False):
            self.assertEqual(mc_api.thaw(self.config), (False, "rcon_error"))
        self.assertTrue(mc_api.is_frozen(self.config))

    def test_expiry(self):
        with mock.patch.object(mc_core, "is_server_running", return_value=False):
            mc_api.freeze(self.config, 60)
        self.assertFalse(mc_api.freeze_expired(self.config))
        self.assertTrue(mc_api.freeze_expired(self.config, now=time.time() + 61))


class TestConfigSet(unittest.TestCase):

    def setUp(self):
        self.data = tempfile.mkdtemp()
        self.server = os.path.join(self.data, "a")
        other = os.path.join(self.data, "b")
        os.makedirs(self.server)
        os.makedirs(other)
        with open(os.path.join(self.server, "server.properties"), "w") as f:
            f.write("server-port=25565\n")
        self.registry = os.path.join(self.data, "servers.json")
        self.patches = [mock.patch.object(mc_servers, "REGISTRY_FILE", self.registry),
                        mock.patch.object(mc_servers, "REGISTRY_DIR", self.data)]
        for p in self.patches:
            p.start()
        mc_servers.save_registry({"active": "a", "servers": {
            "a": {"id": 1, "dossier_serveur": self.server, "port": 25565, "rcon_port": 25575},
            "b": {"id": 2, "dossier_serveur": other, "port": 25566, "rcon_port": 25576},
        }})
        self.config = {"dossier_serveur": self.server, "port": 25565, "rcon_port": 25575, "mcrcon_pass": "pw"}

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def _set(self, key, value):
        with mock.patch("mc_firewall.ensure_game_port_rule", return_value=(True, None)):
            return mc_config.set_value(self.config, "a", key, value)

    def test_port_is_propagated_everywhere(self):
        status, _ = self._set("port", "25570")
        self.assertEqual(status, "ok")
        self.assertEqual(mc_config.load_config(self.server)["port"], 25570)
        self.assertEqual(mc_servers.list_servers()["a"]["port"], 25570)
        with open(os.path.join(self.server, "server.properties")) as f:
            self.assertIn("server-port=25570\n", f.read())

    def test_port_used_by_another_server_is_refused(self):
        self.assertEqual(self._set("port", "25566")[0], "conflict")
        self.assertEqual(self._set("rcon_port", "25565")[0], "conflict")

    def test_invalid_and_unknown(self):
        self.assertEqual(self._set("port", "99999")[0], "invalid")
        self.assertEqual(self._set("ram_allocation", "lots")[0], "invalid")
        self.assertEqual(self._set("mode_maintenance", "1")[0], "unknown")



class TestPackaging(unittest.TestCase):
    """Every mc_* module imported by the app must ship in the release ZIP —
    a missing one breaks every install that updates."""

    def test_all_imported_modules_are_packaged(self):
        import re
        import build_release
        here = os.path.join(os.path.dirname(__file__), "..")
        shipped = set(build_release.PACKAGE_FILES)
        for fname in shipped:
            if not fname.endswith(".py"):
                continue
            with open(os.path.join(here, fname), encoding="utf-8") as f:
                for mod in re.findall(r"^\s*import (mc_\w+)|^\s*from (mc_\w+) import", f.read(), re.M):
                    name = (mod[0] or mod[1]) + ".py"
                    self.assertIn(name, shipped, f"{fname} imports {name}, which is not packaged")


if __name__ == "__main__":
    unittest.main(verbosity=2)
