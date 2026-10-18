"""
test_tasks.py — task storage in config.json, execution of each action and the
daemon's launching of due tasks. Process, RCON and clock are simulated.
"""
import datetime
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mc_api
import mc_config
import mc_task

D = datetime.datetime


class Base(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.config = {"dossier_serveur": self.dir, "port": 1, "rcon_port": 2, "always_on": 1}
        mc_config.save_config(self.config)

    def reload(self):
        return mc_config.load_config(self.dir)


class TestStorage(Base):

    def test_add_persists_in_config_json(self):
        res = mc_task.add_task(self.config, "0 4 * * *", "restart", warn="10m,5m,1m", name="nuit")
        self.assertTrue(res["ok"])
        stored = self.reload()["tasks"][0]
        self.assertEqual((stored["id"], stored["name"], stored["action"]), (1, "nuit", "restart"))
        self.assertEqual(stored["warn"], [600, 300, 60])
        self.assertTrue(stored["enabled"])

    def test_ids_increase_and_names_default(self):
        mc_task.add_task(self.config, "0 4 * * *", "backup")
        mc_task.add_task(self.config, "0 5 * * *", "backup")
        mc_task.remove_task(self.config, "1")
        res = mc_task.add_task(self.config, "0 6 * * *", "backup")
        self.assertEqual(res["task"]["id"], 3)
        self.assertEqual(res["task"]["name"], "backup-3")

    def test_validation(self):
        cases = [
            (("nope", "backup"), "invalid_cron"),
            (("0 4 * * *", "reboot"), "invalid_action"),
            (("0 4 * * *", "command"), "command_required"),
            (("0 4 * * *", "backup"), None),
        ]
        for (cron, action), code in cases:
            res = mc_task.add_task(self.config, cron, action)
            if code:
                self.assertEqual(res["code"], code)
        self.assertEqual(mc_task.add_task(self.config, "0 4 * * *", "backup", command="x")["code"], "command_not_allowed")
        self.assertEqual(mc_task.add_task(self.config, "0 4 * * *", "backup", warn="5m")["code"], "warn_not_allowed")
        self.assertEqual(mc_task.add_task(self.config, "0 4 * * *", "stop", warn="soon")["code"], "invalid_warn")
        self.assertEqual(mc_task.add_task(self.config, "0 4 * * *", "stop", warn="0s")["code"], "invalid_warn")

    def test_duplicate_name_refused(self):
        mc_task.add_task(self.config, "0 4 * * *", "backup", name="x")
        self.assertEqual(mc_task.add_task(self.config, "0 5 * * *", "backup", name="X")["code"], "task_name_taken")

    def test_find_by_id_or_name_enable_disable_remove(self):
        mc_task.add_task(self.config, "0 4 * * *", "backup", name="b")
        self.assertEqual(mc_task.set_enabled(self.config, "b", False)["code"], "task_disabled")
        self.assertFalse(self.reload()["tasks"][0]["enabled"])
        self.assertEqual(mc_task.set_enabled(self.config, "1", True)["code"], "task_enabled")
        self.assertEqual(mc_task.remove_task(self.config, "zz")["code"], "task_not_found")
        self.assertTrue(mc_task.remove_task(self.config, "b")["ok"])
        self.assertEqual(self.reload()["tasks"], [])

    def test_list_has_next_run_and_none_when_disabled(self):
        mc_task.add_task(self.config, "0 4 * * *", "backup")
        mc_task.add_task(self.config, "0 5 * * *", "backup")
        mc_task.set_enabled(self.config, "2", False)
        tasks = mc_task.list_tasks(self.config, now=D(2026, 10, 3, 12, 0))["tasks"]
        self.assertEqual(tasks[0]["next_run"], "2026-10-04T04:00:00")
        self.assertIsNone(tasks[1]["next_run"])

    def test_record_run_keeps_other_changes(self):
        mc_task.add_task(self.config, "0 4 * * *", "backup")
        other = self.reload()
        other["dossier_serveur"] = self.dir
        other["port"] = 4242
        mc_config.save_config(other)
        mc_task.record_run(self.config, 1, False, "task_backup_failed", when=D(2026, 10, 3, 4, 0).timestamp())
        stored = self.reload()
        self.assertEqual(stored["port"], 4242)
        self.assertEqual(stored["tasks"][0]["last_result"], {"ok": False, "code": "task_backup_failed"})
        self.assertEqual(stored["tasks"][0]["last_run"], "2026-10-03T04:00:00")


class FakeClock:
    def __init__(self, start):
        self.now = start
        self.slept = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += datetime.timedelta(seconds=seconds)


class TestExecute(Base):

    def run_task(self, task, running=True, **kw):
        sent = []

        def rcon(cfg, cmd):
            sent.append(cmd)
            return True, "ok"

        clock = FakeClock(D(2026, 10, 3, 3, 50))
        with mock.patch("mc_core.is_server_running", return_value=running):
            res = mc_task.execute("srv", self.config, task, rcon=rcon, clock=clock, sleep=clock.sleep, **kw)
        return res, sent, clock

    def test_restart_warns_then_stops_with_reason_scheduled_then_releases_maintenance(self):
        task = {"id": 1, "name": "n", "action": "restart", "warn": [600, 300, 60]}
        stops = []

        def fake_stop(name, config, reason=None, **kw):
            stops.append((reason, config.get("mode_maintenance"), config.get("stop_reason")))
            return mc_api.result(True, "stopped")

        with mock.patch("mc_api.stop", side_effect=fake_stop), mock.patch("mc_api.IN_DAEMON", True):
            res, sent, clock = self.run_task(task, target=D(2026, 10, 3, 4, 0))
        self.assertTrue(res["ok"])
        self.assertEqual(res["code"], "task_restart_done")
        self.assertEqual(len(sent), 3)
        self.assertTrue(all(c.startswith("say ") for c in sent))
        self.assertIn("10 min", sent[0])
        self.assertIn("1 min", sent[2])
        self.assertEqual(clock.now, D(2026, 10, 3, 4, 0))
        self.assertEqual(stops, [("scheduled", 1, "scheduled")])
        after = self.reload()
        self.assertEqual(after.get("mode_maintenance"), 0)
        self.assertNotIn("stop_reason", after)

    def test_warnings_already_passed_are_skipped(self):
        task = {"id": 1, "name": "n", "action": "stop", "warn": [600, 60]}
        with mock.patch("mc_api.stop", return_value=mc_api.result(True, "stopped")):
            res, sent, clock = self.run_task(task, target=D(2026, 10, 3, 3, 55))
        self.assertEqual(len(sent), 1)
        self.assertIn("1 min", sent[0])

    def test_skip_warn_stops_immediately(self):
        task = {"id": 1, "name": "n", "action": "stop", "warn": [600]}
        with mock.patch("mc_api.stop", return_value=mc_api.result(True, "stopped")):
            res, sent, clock = self.run_task(task, skip_warn=True)
        self.assertEqual((sent, clock.slept), ([], []))
        self.assertEqual(res["code"], "task_stop_done")

    def test_stop_leaves_maintenance_with_reason(self):
        task = {"id": 1, "name": "n", "action": "stop"}
        with mock.patch("mc_api.stop", return_value=mc_api.result(True, "stopped")):
            res, _, _ = self.run_task(task)
        self.assertEqual(self.reload().get("stop_reason"), "scheduled")
        self.assertTrue(res["ok"])

    def test_failed_stop_releases_the_flag(self):
        task = {"id": 1, "name": "n", "action": "restart"}
        with mock.patch("mc_api.stop", return_value=mc_api.result(False, "stop_failed", message="x")):
            res, _, _ = self.run_task(task)
        self.assertFalse(res["ok"])
        self.assertEqual(self.reload().get("mode_maintenance"), 0)

    def test_command_needs_a_running_server(self):
        task = {"id": 1, "name": "n", "action": "command", "command": "say hello"}
        res, sent, _ = self.run_task(task, running=False)
        self.assertEqual((res["ok"], res["code"], sent), (False, "task_server_offline", []))
        res, sent, _ = self.run_task(task, running=True)
        self.assertEqual((res["ok"], sent), (True, ["say hello"]))

    def test_backup(self):
        task = {"id": 1, "name": "n", "action": "backup"}
        with mock.patch("mc_core.backup_server", return_value=(True, "done")) as backup:
            res, _, _ = self.run_task(task)
        backup.assert_called_once()
        self.assertEqual(res["code"], "task_backup_done")
        with mock.patch("mc_core.backup_server", return_value=(False, "disk full")):
            res, _, _ = self.run_task(task)
        self.assertEqual((res["ok"], res["code"]), (False, "task_backup_failed"))

    def test_start_lifts_a_scheduled_stop_but_not_a_user_stop(self):
        task = {"id": 1, "name": "n", "action": "start"}
        self.config.update(mode_maintenance=1, stop_reason="scheduled")
        with mock.patch("mc_api.IN_DAEMON", True):
            res, _, _ = self.run_task(task, running=False)
        self.assertEqual(res["code"], "task_resumed")
        self.assertEqual(self.reload().get("mode_maintenance"), 0)
        self.config.update(mode_maintenance=1, stop_reason="user")
        res, _, _ = self.run_task(task, running=False)
        self.assertEqual(res["code"], "blocked_by_maintenance")

    def test_start_when_running_is_a_noop(self):
        res, _, _ = self.run_task({"id": 1, "name": "n", "action": "start"}, running=True)
        self.assertEqual((res["ok"], res["code"]), (True, "already_running"))

    def test_unexpected_error_becomes_a_failed_result(self):
        with mock.patch("mc_core.backup_server", side_effect=RuntimeError("boom")):
            res, _, _ = self.run_task({"id": 1, "name": "n", "action": "backup"})
        self.assertEqual((res["ok"], res["code"]), (False, "task_error"))


class TestDaemonIntegration(Base):

    def state(self):
        import mc_daemon
        return mc_daemon._new_state()

    def test_due_task_is_launched_once_per_minute(self):
        import mc_daemon
        mc_task.add_task(self.config, "0 4 * * *", "backup")
        config = self.reload()
        config["dossier_serveur"] = self.dir
        state = self.state()
        with mock.patch("mc_daemon._launch_task") as launch:
            mc_daemon._run_tasks("srv", config, state, D(2026, 10, 3, 4, 0, 2))
            mc_daemon._run_tasks("srv", config, state, D(2026, 10, 3, 4, 0, 32))
        self.assertEqual(launch.call_count, 1)

    def test_busy_server_skips_and_records(self):
        import mc_daemon
        mc_task.add_task(self.config, "0 4 * * *", "backup")
        config = self.reload()
        config["dossier_serveur"] = self.dir
        state = self.state()
        state["task_thread"] = mock.Mock(is_alive=lambda: True)
        with mock.patch("mc_daemon._launch_task") as launch:
            mc_daemon._run_tasks("srv", config, state, D(2026, 10, 3, 4, 0))
        launch.assert_not_called()
        self.assertEqual(self.reload()["tasks"][0]["last_result"]["code"], "task_busy")

    def test_worker_records_the_outcome(self):
        import mc_daemon
        mc_task.add_task(self.config, "0 4 * * *", "backup")
        task = self.reload()["tasks"][0]
        with mock.patch("mc_task.execute", return_value=mc_api.result(True, "task_backup_done")):
            mc_daemon._task_worker("srv", self.dir, task, None)
        self.assertEqual(self.reload()["tasks"][0]["last_result"], {"ok": True, "code": "task_backup_done"})

    def test_tick_runs_tasks_even_in_maintenance(self):
        import mc_daemon
        self.config["mode_maintenance"] = 1
        mc_config.save_config(self.config)
        with mock.patch("mc_daemon._run_tasks") as run:
            mc_daemon.process_server_tick("srv", self.dir, self.state())
        run.assert_called_once()

    def test_scheduled_is_a_stop_reason_with_its_own_webhook(self):
        import mc_core
        self.assertIn("scheduled", mc_api.STOP_REASONS)
        self.assertIn("scheduled", mc_core.STOP_WEBHOOKS)
        self.config.update(mode_maintenance=1, stop_reason="scheduled")
        with mock.patch("mc_core.is_server_running", return_value=False):
            self.assertEqual(mc_api.server_state(self.config), "maintenance")


if __name__ == "__main__":
    unittest.main()
