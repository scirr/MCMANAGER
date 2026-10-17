"""
test_crash.py — crash-loop detection (F7): marker, daemon supervision, webhook.
"""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mc_core
import mc_crash
import mc_daemon


def _server(log=None, **config):
    folder = tempfile.mkdtemp()
    cfg = {"dossier_serveur": folder, "port": 25999, "rcon_port": 25998,
           "mcrcon_pass": "x", "always_on": 1, **config}
    with open(os.path.join(folder, "config.json"), "w") as f:
        json.dump({k: v for k, v in cfg.items() if k != "dossier_serveur"}, f)
    if log is not None:
        os.makedirs(os.path.join(folder, "logs"))
        with open(os.path.join(folder, "logs", "latest.log"), "w") as f:
            f.write(log)
    return cfg


class TestCrashMarker(unittest.TestCase):

    def setUp(self):
        self.cfg = _server()

    def test_startup_failure_trips_at_once(self):
        marker, newly = mc_crash.record_failure(self.cfg, startup=True, now=1000)
        self.assertTrue(newly)
        self.assertTrue(mc_crash.is_crashed(self.cfg))
        self.assertFalse(mc_crash.may_start(self.cfg, now=99999))

    def test_three_late_failures_in_ten_minutes_trip(self):
        self.assertFalse(mc_crash.record_failure(self.cfg, False, now=1000)[1])
        self.assertTrue(mc_crash.may_start(self.cfg, now=1000))
        self.assertFalse(mc_crash.record_failure(self.cfg, False, now=1100)[1])
        self.assertFalse(mc_crash.may_start(self.cfg, now=1110))   # backoff
        self.assertTrue(mc_crash.may_start(self.cfg, now=1200))
        self.assertTrue(mc_crash.record_failure(self.cfg, False, now=1300)[1])
        self.assertFalse(mc_crash.may_start(self.cfg, now=5000))

    def test_old_failures_age_out(self):
        mc_crash.record_failure(self.cfg, False, now=1000)
        mc_crash.record_failure(self.cfg, False, now=1100)
        marker, newly = mc_crash.record_failure(self.cfg, False, now=1100 + mc_crash.WINDOW + 5)
        self.assertFalse(newly)
        self.assertEqual(len(marker["failures"]), 1)

    def test_clear_resets_everything(self):
        mc_crash.record_failure(self.cfg, True)
        self.assertTrue(mc_crash.clear(self.cfg))
        self.assertTrue(mc_crash.may_start(self.cfg))
        self.assertFalse(mc_crash.clear(self.cfg))

    def test_recent_errors_keeps_the_last_error_lines(self):
        lines = [f"[10:00:{i:02d}] [main/ERROR] failure {i}" for i in range(15)]
        lines.insert(3, "[10:00:03] [main/INFO] fine")
        cfg = _server(log="\n".join(lines) + "\n")
        errors = mc_crash.recent_errors(cfg["dossier_serveur"])
        self.assertEqual(len(errors), 10)
        self.assertTrue(errors[-1].endswith("failure 14"))
        self.assertTrue(all("ERROR" in e for e in errors))


class TestDaemonCrashLoop(unittest.TestCase):

    def setUp(self):
        self.cfg = _server(log="[10:00:01] [main/ERROR] (Minecraft) Failed to load registries\n")
        self.state = mc_daemon._new_state()
        self.announced = []
        patch = mock.patch.object(mc_daemon, "_announce_crash",
                                  side_effect=lambda *a: self.announced.append(a))
        patch.start()
        self.addCleanup(patch.stop)

    def _tick(self, running, start_result=(True, "ok")):
        started = []

        def start(config, send_webhook=True):
            started.append(1)
            return start_result
        with mock.patch.object(mc_core, "is_server_running", return_value=running), \
             mock.patch.object(mc_core, "start_server", side_effect=start), \
             mock.patch.object(mc_core, "server_ready", return_value=running), \
             mock.patch("mc_api.is_frozen", return_value=False), \
             mock.patch("mc_api.sleep_info", return_value={"enabled": False, "after_s": 0, "allow": []}):
            mc_daemon.process_server_tick("a", self.cfg["dossier_serveur"], self.state)
        return started

    def test_server_dying_before_done_stops_the_restarts(self):
        self.assertEqual(self._tick(False), [1])          # first launch
        self.assertEqual(self._tick(False), [])           # died before "Done": not relaunched
        self.assertTrue(mc_crash.is_crashed(self.cfg))
        self.assertEqual(len(self.announced), 1)
        for _ in range(5):
            self.assertEqual(self._tick(False), [])
        self.assertEqual(len(self.announced), 1)          # announced once

    def test_exit_after_done_is_relaunched(self):
        self.assertEqual(self._tick(False), [1])
        with open(os.path.join(self.cfg["dossier_serveur"], "logs", "latest.log"), "a") as f:
            f.write("[10:00:09] [Server thread/INFO] Done (8s)!\n")
        self.assertEqual(self._tick(False), [1])
        self.assertFalse(mc_crash.is_crashed(self.cfg))

    def test_immediate_jvm_death_is_reported_once(self):
        mc_crash.record_failure(self.cfg, startup=True)
        self.assertEqual(self._tick(False), [])
        self.assertEqual(self.announced, [])

    def test_maintenance_stop_is_not_a_failure(self):
        self.state["expected_up"] = True
        self.cfg["mode_maintenance"] = 1
        with open(os.path.join(self.cfg["dossier_serveur"], "config.json"), "w") as f:
            json.dump({"mode_maintenance": 1, "always_on": 1}, f)
        self._tick(False)
        self.assertIsNone(mc_crash.read(self.cfg))

    def test_coming_back_up_clears_the_crash(self):
        mc_crash.record_failure(self.cfg, startup=True)
        self._tick(True)
        self.assertFalse(mc_crash.is_crashed(self.cfg))


class TestShippedTemplates(unittest.TestCase):

    def test_crash_loop_template_everywhere(self):
        import mc_config
        root = os.path.join(os.path.dirname(__file__), "..")
        with open(os.path.join(root, "webhook_templates.json"), encoding="utf-8") as f:
            shipped = json.load(f)
        for lang in ("fr", "en"):
            self.assertIn("crash_loop", shipped[lang])
            self.assertIn("crash_loop", mc_config._FALLBACK_WEBHOOKS[lang])

    def test_user_templates_are_not_overwritten(self):
        import mc_config
        folder = tempfile.mkdtemp()
        custom = {"stop": {"title": "mine", "color": 1, "description": "x"}}
        with open(os.path.join(folder, "webhooks.json"), "w") as f:
            json.dump(custom, f)
        loaded = mc_config.load_webhooks(folder)
        self.assertEqual(loaded["stop"]["title"], "mine")
        self.assertIn("crash_loop", loaded)


if __name__ == "__main__":
    unittest.main(verbosity=2)
