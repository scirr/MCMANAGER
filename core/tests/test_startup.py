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


class _Clock:
    def __init__(self):
        self.now = 1_000_000.0
        self.slept = 0

    def time(self):
        return self.now

    def sleep(self, secs):
        self.now += secs
        self.slept += secs


class TestStopWithRconRefused(unittest.TestCase):
    """A live JVM whose RCON refuses must be waited for, then terminated."""

    def _run(self, log, port_open, rcon_opens_after=None, entry=mc_core.stop_server):
        cfg = _server(log=log)
        clock = _Clock()
        signals = []
        state = {"alive": True}

        def handshake(host, port, password, ping_only=False, timeout=5):
            if rcon_opens_after is not None and clock.slept >= rcon_opens_after:
                return True, mock.MagicMock()
            return False, "refused"

        def signal_server(config, sig):
            signals.append(sig)
            state["alive"] = False
            return True

        with mock.patch.object(mc_core.time, "time", clock.time), \
             mock.patch.object(mc_core.time, "sleep", clock.sleep), \
             mock.patch.object(mc_core, "is_server_running", return_value=True), \
             mock.patch.object(mc_core, "_server_alive", side_effect=lambda c: state["alive"]), \
             mock.patch.object(mc_core, "get_server_pid", return_value=4242), \
             mock.patch.object(mc_core, "proc_uptime", return_value=3), \
             mock.patch.object(mc_core, "server_java_pids", return_value=[4242]), \
             mock.patch.object(mc_core, "_port_in_use", return_value=port_open), \
             mock.patch.object(mc_core, "rcon_handshake", side_effect=handshake), \
             mock.patch.object(mc_core, "rcon_send_packet",
                               side_effect=lambda s, i, t, body: state.update(alive=state["alive"] and body != "stop")), \
             mock.patch.object(mc_core, "rcon_recv_packet"), \
             mock.patch.object(mc_core, "_signal_server", side_effect=signal_server), \
             mock.patch.object(mc_core, "_remove_pid_file"):
            res = entry(cfg, manual=False)
        return res, signals, clock

    def test_waits_then_sigterm_when_log_is_empty(self):
        for port_open in (True, False):
            (ok, msg), signals, clock = self._run("[10:00:00] [main/INFO] Loading\n", port_open)
            self.assertTrue(ok, port_open)
            self.assertEqual(signals, [signal.SIGTERM])
            self.assertGreaterEqual(clock.slept, mc_core.STARTUP_WAIT)
            self.assertNotEqual(msg, mc_core.T["stop_rcon_unreachable"])

    def test_stale_done_line_does_not_make_the_server_ready(self):
        cfg = _server(log="Done (3s)!\n")
        path = os.path.join(cfg["dossier_serveur"], "logs", "latest.log")
        os.utime(path, (time.time() - 3, time.time() - 3))
        with mock.patch.object(mc_core, "rcon_responds", return_value=False), \
             mock.patch.object(mc_core, "get_server_pid", return_value=4242), \
             mock.patch.object(mc_core, "proc_uptime", return_value=1):
            self.assertFalse(mc_core.server_ready(cfg))

    def test_stale_done_line_with_unknown_pid_file_uses_the_jvm_start(self):
        cfg = _server(log="Done (3s)!\n")
        path = os.path.join(cfg["dossier_serveur"], "logs", "latest.log")
        os.utime(path, (time.time() - 3, time.time() - 3))
        with mock.patch.object(mc_core, "rcon_responds", return_value=False), \
             mock.patch.object(mc_core, "get_server_pid", return_value=None), \
             mock.patch.object(mc_core, "server_java_pids", return_value=[4242]), \
             mock.patch.object(mc_core, "proc_uptime", return_value=1):
            self.assertFalse(mc_core.server_ready(cfg))

    def test_server_judged_ready_but_rcon_refuses_still_ends_in_sigterm(self):
        (ok, msg), signals, clock = self._run("Done (3s)!\n", True)
        self.assertTrue(ok)
        self.assertEqual(signals, [signal.SIGTERM])
        self.assertNotEqual(msg, mc_core.T["stop_rcon_unreachable"])

    def test_rcon_opening_late_gets_a_clean_stop(self):
        (ok, msg), signals, clock = self._run("[10:00:00] [main/INFO] Loading\n", True,
                                              rcon_opens_after=20)
        self.assertTrue(ok)
        self.assertEqual(signals, [])
        self.assertLess(clock.slept, mc_core.STARTUP_WAIT)

    def test_api_stop_goes_through_the_same_wait(self):
        cfg = _server(log="[10:00:00] [main/INFO] Loading\n")
        clock = _Clock()
        signals = []
        with mock.patch.object(mc_core.time, "time", clock.time), \
             mock.patch.object(mc_core.time, "sleep", clock.sleep), \
             mock.patch.object(mc_core, "is_server_running", return_value=True), \
             mock.patch.object(mc_core, "_server_alive", side_effect=lambda c: not signals), \
             mock.patch.object(mc_core, "get_server_pid", return_value=4242), \
             mock.patch.object(mc_core, "proc_uptime", return_value=3), \
             mock.patch.object(mc_core, "rcon_handshake", return_value=(False, "refused")), \
             mock.patch.object(mc_core, "_signal_server",
                               side_effect=lambda c, s: signals.append(s) or True), \
             mock.patch.object(mc_core, "_remove_pid_file"), \
             mock.patch.object(mc_api.mc_config, "save_config"), \
             mock.patch.object(mc_api, "is_frozen", return_value=False):
            res = mc_api.stop("srv", cfg, quiet=True)
        self.assertTrue(res["ok"], res)
        self.assertEqual(signals, [signal.SIGTERM])


if __name__ == "__main__":
    unittest.main(verbosity=2)
