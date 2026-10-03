"""
test_api_ops.py — the player, world and task functions of mc_api (what a
network API will call) and the announcements of a scheduled stop.
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mc_api
import mc_config
import mc_core
import mc_players
import mc_task
import mc_world


def _config(**extra):
    folder = tempfile.mkdtemp()
    cfg = {"dossier_serveur": folder, "port": 1, "rcon_port": 2, "always_on": 1, **extra}
    mc_config.save_config(cfg)
    return cfg


class TestScheduledStopAnnouncements(unittest.TestCase):

    def _stop(self, reason, maintenance):
        cfg = _config(mode_maintenance=maintenance, webhook_url="https://example.invalid/h")
        discord, alerts = [], []
        with mock.patch.object(mc_core, "is_server_running", return_value=True), \
             mock.patch.object(mc_core, "startup_in_progress", return_value=False), \
             mock.patch.object(mc_core, "send_rcon", return_value=True), \
             mock.patch.object(mc_core, "wait_for_exit", return_value=True), \
             mock.patch.object(mc_core, "_remove_pid_file"), \
             mock.patch.object(mc_core, "send_discord_webhook",
                               side_effect=lambda c, p, force=False: discord.append(force)), \
             mock.patch.object(mc_core, "_alert",
                               side_effect=lambda c, e, **i: alerts.append((e, i))):
            ok, _ = mc_core.stop_server(cfg, reason=reason)
        self.assertTrue(ok)
        return discord, alerts

    def test_scheduled_stop_is_announced_despite_maintenance(self):
        discord, alerts = self._stop("scheduled", 1)
        self.assertEqual(discord, [True])
        self.assertEqual(alerts, [("stop", {"force": True, "reason": "scheduled"})])

    def test_other_reasons_stay_subject_to_maintenance(self):
        discord, alerts = self._stop("user", 0)
        self.assertEqual(discord, [False])
        self.assertEqual(alerts, [("stop", {"force": False, "reason": "user"})])


class TestApiThinLayer(unittest.TestCase):

    def setUp(self):
        self.cfg = _config()

    def test_players(self):
        with mock.patch.object(mc_players, "list_entries", return_value={"ok": True, "code": "x"}) as f:
            self.assertEqual(mc_api.player_list("s", self.cfg, "ban")["server"], "s")
        f.assert_called_once_with(self.cfg, "ban")
        with mock.patch.object(mc_players, "edit_list", return_value={"ok": True, "code": "x"}) as f:
            res = mc_api.player_edit("s", self.cfg, "ban", "add", "Steve", reason="r")
        f.assert_called_once_with(self.cfg, "ban", "add", "Steve", reason="r")
        self.assertEqual(res["server"], "s")
        with mock.patch.object(mc_players, "set_whitelist_enabled", return_value={"ok": True, "code": "x"}) as f:
            mc_api.whitelist_enable("s", self.cfg, True)
        f.assert_called_once_with(self.cfg, True)
        with mock.patch.object(mc_players, "kick", return_value={"ok": True, "code": "x"}) as f:
            mc_api.player_kick("s", self.cfg, "Steve", reason="bye")
        f.assert_called_once_with(self.cfg, "Steve", reason="bye")

    def test_history_clamps_days_and_reports_them(self):
        with mock.patch.object(mc_players, "history", return_value=[]) as f:
            res = mc_api.player_history("s", self.cfg, days=0)
        f.assert_called_once_with(self.cfg["dossier_serveur"], days=1)
        self.assertEqual((res["ok"], res["code"], res["days"], res["sessions"]), (True, "history", 0, []))

    def test_world(self):
        ok = {"ok": True, "code": "x"}
        with mock.patch.object(mc_world, "list_worlds", return_value=ok):
            self.assertEqual(mc_api.world_list("s", self.cfg)["server"], "s")
        with mock.patch.object(mc_world, "export_world", return_value=ok) as f:
            mc_api.world_export("s", self.cfg, "a.zip")
        f.assert_called_once_with(self.cfg, "a.zip")
        with mock.patch.object(mc_world, "import_world", return_value=ok) as f:
            mc_api.world_import("s", self.cfg, "w.zip", confirmed=True)
        f.assert_called_once_with(self.cfg, "w.zip", confirmed=True)
        with mock.patch.object(mc_world, "reset_dimension", return_value=ok) as f:
            mc_api.world_reset("s", self.cfg, "nether", confirmed=True, include_overworld=False)
        f.assert_called_once_with(self.cfg, "nether", confirmed=True, include_overworld=False)

    def test_pregen_parses_radius_and_center(self):
        ok = {"ok": True, "code": "x"}
        with mock.patch.object(mc_world, "pregen", return_value=ok) as f:
            mc_api.world_pregen("s", self.cfg, "500", "10,-20")
        f.assert_called_once_with(self.cfg, 500, mc_world.parse_center("10,-20"))
        with mock.patch.object(mc_world, "pregen") as f:
            res = mc_api.world_pregen("s", self.cfg, "abc")
            none = mc_api.world_pregen("s", self.cfg, None)
        f.assert_not_called()
        self.assertEqual((res["ok"], res["code"], res["radius"]), (False, "invalid_radius", "abc"))
        self.assertEqual(none["code"], "invalid_radius")
        with mock.patch.object(mc_world, "pregen_progress", return_value=ok):
            self.assertEqual(mc_api.world_pregen_status("s", self.cfg)["server"], "s")

    def test_tasks_round_trip(self):
        res = mc_api.task_add("s", self.cfg, "0 4 * * *", "backup", task_name="b")
        self.assertTrue(res["ok"])
        self.assertEqual(len(mc_api.task_list("s", self.cfg)["tasks"]), 1)
        self.assertTrue(mc_api.task_enable("s", self.cfg, "b", False)["ok"])
        task = mc_api.task_find(self.cfg, "b")
        self.assertEqual(task["name"], "b")
        with mock.patch.object(mc_task, "execute", return_value={"ok": True, "code": "task_backup_done"}) as ex:
            ran = mc_api.task_run("s", self.cfg, task, skip_warn=True)
        ex.assert_called_once_with("s", self.cfg, task, skip_warn=True)
        self.assertEqual((ran["ok"], ran["server"]), (True, "s"))
        self.assertEqual(mc_config.load_config(self.cfg["dossier_serveur"])["tasks"][0]["last_result"]["ok"], True)
        self.assertTrue(mc_api.task_remove("s", self.cfg, "b")["ok"])
        self.assertIsNone(mc_api.task_find(self.cfg, "b"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
