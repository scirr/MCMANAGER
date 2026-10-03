"""
test_startup.py — a server is "running" only once RCON answers (F4): state,
stop during startup, short RCON retry.
"""
import os
import signal
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mc_api
import mc_core


def _server(log=None, **config):
    folder = tempfile.mkdtemp()
    cfg = {"dossier_serveur": folder, "port": 25999, "rcon_port": 25998,
           "mcrcon_pass": "x", "always_on": 1, **config}
    if log is not None:
        os.makedirs(os.path.join(folder, "logs"))
        with open(os.path.join(folder, "logs", "latest.log"), "w") as f:
            f.write(log)
    return cfg


class TestReadiness(unittest.TestCase):

    def test_ready_when_rcon_answers(self):
        cfg = _server()
        with mock.patch.object(mc_core, "rcon_responds", return_value=True):
            self.assertTrue(mc_core.server_ready(cfg))

    def test_not_ready_while_rcon_closed_and_no_done(self):
        cfg = _server(log="[10:00:00] [main/INFO] Loading\n")
        with mock.patch.object(mc_core, "rcon_responds", return_value=False), \
             mock.patch.object(mc_core, "get_server_pid", return_value=None):
            self.assertFalse(mc_core.server_ready(cfg))

    def test_done_in_log_counts_when_rcon_is_broken(self):
        cfg = _server(log="[10:00:09] [Server thread/INFO] Done (8.1s)! For help, type \"help\"\n")
        with mock.patch.object(mc_core, "rcon_responds", return_value=False), \
             mock.patch.object(mc_core, "get_server_pid", return_value=None):
            self.assertTrue(mc_core.server_ready(cfg))

    def test_log_of_a_previous_run_is_ignored(self):
        cfg = _server(log="Done (3s)!\n")
        path = os.path.join(cfg["dossier_serveur"], "logs", "latest.log")
        os.utime(path, (1000, 1000))
        self.assertFalse(mc_core.log_has_done(cfg, since=time.time()))
        self.assertTrue(mc_core.log_has_done(cfg, since=None))

    def test_rcon_refused_password_still_means_up(self):
        with mock.patch.object(mc_core, "rcon_handshake",
                               return_value=(False, mc_core.T["rcon_auth_failed"])):
            self.assertTrue(mc_core.rcon_responds({"mcrcon_pass": "x"}))
        with mock.patch.object(mc_core, "rcon_handshake",
                               return_value=(False, mc_core.T["rcon_conn_refused"])):
            self.assertFalse(mc_core.rcon_responds({"mcrcon_pass": "x"}))
        self.assertIsNone(mc_core.rcon_responds({}))


class TestRconRetry(unittest.TestCase):

    def test_retries_until_rcon_opens(self):
        answers = [(False, "refused"), (False, "refused"), (True, mock.MagicMock())]
        with mock.patch.object(mc_core, "rcon_handshake", side_effect=answers) as hs, \
             mock.patch.object(mc_core, "rcon_command", return_value="ok"), \
             mock.patch("time.sleep"):
            self.assertEqual(mc_api.rcon_exec({"mcrcon_pass": "x"}, "list", wait=5), (True, "ok"))
        self.assertEqual(hs.call_count, 3)

    def test_no_retry_by_default_and_none_on_bad_password(self):
        with mock.patch.object(mc_core, "rcon_handshake", return_value=(False, "refused")) as hs:
            self.assertEqual(mc_api.rcon_exec({}, "list"), (False, "refused"))
        self.assertEqual(hs.call_count, 1)
        with mock.patch.object(mc_core, "rcon_handshake",
                               return_value=(False, mc_core.T["rcon_auth_failed"])) as hs:
            mc_api.rcon_exec({}, "list", wait=5)
        self.assertEqual(hs.call_count, 1)


class TestStopDuringStartup(unittest.TestCase):

    def _stop(self, rcon_comes, alive_after_wait=True):
        cfg = _server()
        signals = []
        sent = []

        def send(config, command):
            sent.append(command)
            return True
        with mock.patch.object(mc_core, "is_server_running", return_value=True), \
             mock.patch.object(mc_core, "startup_in_progress", return_value=True), \
             mock.patch.object(mc_core, "wait_for_rcon", return_value=rcon_comes), \
             mock.patch.object(mc_core, "_server_alive", return_value=alive_after_wait), \
             mock.patch.object(mc_core, "send_rcon", side_effect=send), \
             mock.patch.object(mc_core, "_signal_server", side_effect=lambda c, s: signals.append(s)), \
             mock.patch.object(mc_core, "wait_for_exit", return_value=True), \
             mock.patch.object(mc_core, "_remove_pid_file"):
            res = mc_core.stop_server(cfg, manual=False)
        return res, sent, signals

    def test_waits_for_rcon_then_stops_cleanly(self):
        (ok, _msg), sent, signals = self._stop(rcon_comes=True)
        self.assertTrue(ok)
        self.assertIn("stop", sent)
        self.assertEqual(signals, [])

    def test_falls_back_to_sigterm_when_rcon_never_opens(self):
        (ok, msg), sent, signals = self._stop(rcon_comes=False)
        self.assertTrue(ok)
        self.assertEqual(msg, mc_core.T["stop_done_startup_term"])
        self.assertEqual(sent, [])
        self.assertEqual(signals, [signal.SIGTERM])

    def test_process_gone_while_waiting_is_a_success(self):
        (ok, _msg), sent, signals = self._stop(rcon_comes=False, alive_after_wait=False)
        self.assertTrue(ok)
        self.assertEqual((sent, signals), ([], []))


if __name__ == "__main__":
    unittest.main(verbosity=2)
