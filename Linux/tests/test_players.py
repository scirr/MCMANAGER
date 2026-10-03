"""
test_players.py — whitelist, operators, bans, kicks, UUIDs and the connection
history read from logs. RCON, Mojang and the clock are simulated.
"""
import datetime
import gzip
import json
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mc_http
import mc_players

D = datetime.datetime


class Base(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.config = {"dossier_serveur": self.dir, "rcon_port": 2}
        self.props(**{"online-mode": "false"})

    def props(self, **values):
        with open(os.path.join(self.dir, "server.properties"), "w") as f:
            f.writelines(f"{k}={v}\n" for k, v in values.items())

    def read(self, name):
        with open(os.path.join(self.dir, name)) as f:
            return json.load(f)


class TestUuid(Base):

    def test_offline_uuid_is_the_version_3_one_minecraft_uses(self):
        self.assertEqual(mc_players.offline_uuid("Steve"), "5627dd98-e6be-3c21-b8a8-e92344183641")
        self.assertEqual(mc_players.offline_uuid("Notch"), "b50ad385-829d-3141-a216-7e7d7539ba7f")

    def test_names(self):
        for good in ("abc", "Steve_1", "A" * 16):
            self.assertTrue(mc_players.valid_name(good))
        for bad in ("ab", "A" * 17, "a b", "é_é", "", "a;b", "a-b"):
            self.assertFalse(mc_players.valid_name(bad), bad)

    def test_online_mode_asks_mojang(self):
        self.props(**{"online-mode": "true"})
        with mock.patch("mc_http.get_json", return_value={"id": "069a79f444e94726a5befca90e38aaf5", "name": "Notch"}) as get:
            ident, error = mc_players.resolve_uuid("Notch", self.config)
        self.assertEqual(ident, "069a79f4-44e9-4726-a5be-fca90e38aaf5")
        self.assertTrue(get.call_args[0][0].endswith("/users/profiles/minecraft/Notch"))

    def test_mojang_errors(self):
        self.props(**{"online-mode": "true"})
        with mock.patch("mc_http.get_json", side_effect=mc_http.HttpError("u", "HTTP 404", 404)):
            self.assertEqual(mc_players.resolve_uuid("Nobody", self.config), (None, "player_unknown"))
        with mock.patch("mc_http.get_json", side_effect=mc_http.HttpError("u", "timeout")):
            self.assertEqual(mc_players.resolve_uuid("Nobody", self.config), (None, "mojang_unreachable"))

    def test_offline_mode_never_touches_the_network(self):
        with mock.patch("mc_http.get_json", side_effect=AssertionError("network")):
            ident, error = mc_players.resolve_uuid("Steve", self.config)
        self.assertIsNone(error)


class TestStoppedServer(Base):

    def edit(self, kind, action, subject, **kw):
        with mock.patch("mc_core.is_server_running", return_value=False):
            return mc_players.edit_list(self.config, kind, action, subject, **kw)

    def test_whitelist_add_remove_file(self):
        res = self.edit("whitelist", "add", "Steve")
        self.assertEqual((res["ok"], res["code"], res["via"]), (True, "whitelist_added", "file"))
        self.assertEqual(self.read("whitelist.json"), [{"uuid": mc_players.offline_uuid("Steve"), "name": "Steve"}])
        self.assertEqual(self.edit("whitelist", "add", "steve")["code"], "whitelist_already_add")
        self.assertEqual(self.edit("whitelist", "remove", "STEVE")["code"], "whitelist_removed")
        self.assertEqual(self.read("whitelist.json"), [])
        self.assertEqual(self.edit("whitelist", "remove", "Steve")["code"], "whitelist_already_remove")

    def test_removal_needs_no_network(self):
        self.props(**{"online-mode": "true"})
        with open(os.path.join(self.dir, "ops.json"), "w") as f:
            json.dump([{"uuid": "x", "name": "Boss", "level": 4}], f)
        with mock.patch("mc_http.get_json", side_effect=AssertionError("network")):
            self.assertTrue(self.edit("op", "remove", "Boss")["ok"])

    def test_op_entry(self):
        self.edit("op", "add", "Alex")
        entry = self.read("ops.json")[0]
        self.assertEqual((entry["name"], entry["level"], entry["bypassesPlayerLimit"]), ("Alex", 4, False))

    def test_ban_with_reason_and_pardon(self):
        self.edit("ban", "add", "Griefer", reason="griefing")
        entry = self.read("banned-players.json")[0]
        self.assertEqual((entry["name"], entry["reason"], entry["expires"]), ("Griefer", "griefing", "forever"))
        self.assertRegex(entry["created"], r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d [+-]\d{4}$")
        self.assertTrue(self.edit("ban", "remove", "Griefer")["ok"])

    def test_ban_ip(self):
        self.assertEqual(self.edit("banip", "add", "203.0.113.9", reason="spam")["code"], "banip_added")
        self.assertEqual(self.read("banned-ips.json")[0]["ip"], "203.0.113.9")
        self.assertEqual(self.edit("banip", "add", "::1")["code"], "banip_added")
        self.assertEqual(self.edit("banip", "add", "not-an-ip")["code"], "invalid_ip")
        self.assertEqual(self.edit("banip", "remove", "203.0.113.9")["code"], "banip_removed")

    def test_invalid_name_changes_nothing(self):
        self.assertEqual(self.edit("ban", "add", "a b")["code"], "invalid_name")
        self.assertFalse(os.path.exists(os.path.join(self.dir, "banned-players.json")))

    def test_unresolvable_player_changes_nothing(self):
        self.props(**{"online-mode": "true"})
        with mock.patch("mc_http.get_json", side_effect=mc_http.HttpError("u", "HTTP 204", 204)):
            res = self.edit("whitelist", "add", "Ghost")
        self.assertEqual(res["code"], "player_unknown")
        self.assertFalse(os.path.exists(os.path.join(self.dir, "whitelist.json")))

    def test_write_is_atomic_and_keeps_existing_entries(self):
        with open(os.path.join(self.dir, "whitelist.json"), "w") as f:
            json.dump([{"uuid": "1", "name": "Old"}], f)
        self.edit("whitelist", "add", "New")
        self.assertEqual([e["name"] for e in self.read("whitelist.json")], ["Old", "New"])
        self.assertEqual([n for n in os.listdir(self.dir) if n.endswith(".tmp")], [])

    def test_whitelist_toggle_edits_server_properties(self):
        with mock.patch("mc_core.is_server_running", return_value=False):
            self.assertEqual(mc_players.set_whitelist_enabled(self.config, True)["code"], "whitelist_on")
        self.assertEqual(mc_players.read_properties(self.dir)["white-list"], "true")
        self.assertEqual(mc_players.read_properties(self.dir)["online-mode"], "false")
        listing = mc_players.list_entries(self.config, "whitelist")
        self.assertTrue(listing["enabled"])


class TestRunningServer(Base):

    def put(self, name, data):
        with open(os.path.join(self.dir, name), "w") as f:
            json.dump(data, f)

    def run_edit(self, kind, action, subject, apply=None, **kw):
        sent = []

        def rcon(cfg, command):
            sent.append(command)
            if apply:
                apply()
            return True, "done"

        with mock.patch("mc_core.is_server_running", return_value=True), \
                mock.patch("mc_players.CONFIRM_WAIT", 0):
            return mc_players.edit_list(self.config, kind, action, subject, rcon=rcon, **kw), sent

    def test_commands_per_list(self):
        def writes(kind_file, entries):
            return lambda: self.put(kind_file, entries)
        res, sent = self.run_edit("whitelist", "add", "Steve", writes("whitelist.json", [{"name": "Steve"}]))
        self.assertEqual((res["ok"], res["via"], sent), (True, "rcon", ["whitelist add Steve"]))
        res, sent = self.run_edit("op", "add", "Steve", writes("ops.json", [{"name": "Steve"}]))
        self.assertEqual(sent, ["op Steve"])
        res, sent = self.run_edit("ban", "add", "Steve", writes("banned-players.json", [{"name": "Steve"}]), reason="bye")
        self.assertEqual(sent, ["ban Steve bye"])
        res, sent = self.run_edit("banip", "add", "1.2.3.4", writes("banned-ips.json", [{"ip": "1.2.3.4"}]))
        self.assertEqual(sent, ["ban-ip 1.2.3.4"])
        res, sent = self.run_edit("banip", "remove", "1.2.3.4", writes("banned-ips.json", []))
        self.assertEqual(sent, ["pardon-ip 1.2.3.4"])

    def test_remove_commands(self):
        for kind, file, command in (("op", "ops.json", "deop Steve"), ("ban", "banned-players.json", "pardon Steve"),
                                    ("whitelist", "whitelist.json", "whitelist remove Steve")):
            with open(os.path.join(self.dir, file), "w") as f:
                json.dump([{"name": "Steve"}], f)
            res, sent = self.run_edit(kind, "remove", "Steve", lambda f=file: self.put(f, []))
            self.assertEqual((res["ok"], sent), (True, [command]))

    def test_command_ignored_by_server_is_reported(self):
        res, _ = self.run_edit("whitelist", "add", "Ghost")
        self.assertEqual((res["ok"], res["code"]), (False, "not_confirmed"))

    def test_rcon_failure(self):
        with mock.patch("mc_core.is_server_running", return_value=True):
            res = mc_players.edit_list(self.config, "op", "add", "Steve", rcon=lambda c, cmd: (False, "refused"))
        self.assertEqual((res["ok"], res["code"]), (False, "rcon_failed"))

    def test_whitelist_toggle_over_rcon(self):
        sent = []
        with mock.patch("mc_core.is_server_running", return_value=True):
            mc_players.set_whitelist_enabled(self.config, False, rcon=lambda c, cmd: (sent.append(cmd), (True, ""))[1])
        self.assertEqual(sent, ["whitelist off"])


class TestKick(Base):

    def test_kick_online_player(self):
        sent = []
        with mock.patch("mc_core.is_server_running", return_value=True):
            res = mc_players.kick(self.config, "steve", reason="afk",
                                  query=lambda c, wait=0: (True, {"online": 1, "max": 20, "players": ["Steve"]}),
                                  rcon=lambda c, cmd: (sent.append(cmd), (True, "Kicked"))[1])
        self.assertEqual((res["ok"], sent), (True, ["kick steve afk"]))

    def test_kick_refusals(self):
        with mock.patch("mc_core.is_server_running", return_value=False):
            self.assertEqual(mc_players.kick(self.config, "Steve")["code"], "kick_offline")
        with mock.patch("mc_core.is_server_running", return_value=True):
            res = mc_players.kick(self.config, "Steve",
                                  query=lambda c, wait=0: (True, {"online": 0, "max": 20, "players": []}))
            self.assertEqual(res["code"], "player_not_online")
            self.assertEqual(mc_players.kick(self.config, "a b")["code"], "invalid_name")


LOG_A = """\
[10:00:00] [Server thread/INFO]: Starting minecraft server version 1.21.1
[10:05:00] [Server thread/INFO]: Steve[/203.0.113.5:50000] logged in with entity id 12 at (0.0, 64.0, 0.0)
[10:05:01] [Server thread/INFO]: Steve joined the game
[10:35:01] [Server thread/INFO]: Steve left the game
[11:00:00] [Server thread/INFO]: <Steve> Alex left the game
[23:50:00] [Server thread/INFO]: Alex[/[0:0:0:0:0:0:0:1]:50001] logged in with entity id 13 at (0.0, 64.0, 0.0)
[00:10:00] [Server thread/INFO]: Alex left the game
"""

LOG_B = """\
[08:00:00] [Server thread/INFO]: Starting minecraft server version 1.21.1
[08:01:00] [Server thread/INFO]: Crash[/198.51.100.7:1] logged in with entity id 1 at (0.0, 64.0, 0.0)
"""


class TestHistory(Base):

    def make_logs(self):
        logs = os.path.join(self.dir, "logs")
        os.makedirs(logs)
        with gzip.open(os.path.join(logs, "2026-10-01-1.log.gz"), "wt") as f:
            f.write(LOG_A)
        with open(os.path.join(logs, "latest.log"), "w") as f:
            f.write(LOG_B)
        stamp = D(2026, 10, 2, 9, 0).timestamp()
        os.utime(os.path.join(logs, "latest.log"), (stamp, stamp))

    def test_sessions_from_gz_and_latest(self):
        self.make_logs()
        sessions = mc_players.history(self.dir, days=30, now=D(2026, 10, 3, 12, 0))
        self.assertEqual([s["player"] for s in sessions], ["Steve", "Alex", "Crash"])
        steve, alex, crash = sessions
        self.assertEqual((steve["ip"], steve["join"], steve["leave"], steve["duration_s"]),
                         ("203.0.113.5", "2026-10-01T10:05:00", "2026-10-01T10:35:01", 1801))
        self.assertEqual((alex["ip"], alex["duration_s"]), ("0:0:0:0:0:0:0:1", 1200))
        self.assertEqual(alex["leave"], "2026-10-02T00:10:00")
        self.assertEqual((crash["leave"], crash["duration_s"]), (None, None))

    def test_a_restart_closes_open_sessions(self):
        self.make_logs()
        logs = os.path.join(self.dir, "logs")
        with gzip.open(os.path.join(logs, "2026-10-01-2.log.gz"), "wt") as f:
            f.write(LOG_B.replace("08:", "12:"))
        sessions = mc_players.history(self.dir, days=30, now=D(2026, 10, 3, 12, 0))
        self.assertEqual(len([s for s in sessions if s["player"] == "Crash"]), 2)
        self.assertIsNone(sessions[-1]["leave"])

    def test_days_window(self):
        self.make_logs()
        sessions = mc_players.history(self.dir, days=1, now=D(2026, 10, 3, 12, 0))
        self.assertEqual(sessions, [])
        sessions = mc_players.history(self.dir, days=2, now=D(2026, 10, 3, 12, 0))
        self.assertEqual([s["player"] for s in sessions], ["Alex", "Crash"])

    def test_no_logs(self):
        self.assertEqual(mc_players.history(self.dir), [])


if __name__ == "__main__":
    unittest.main()
