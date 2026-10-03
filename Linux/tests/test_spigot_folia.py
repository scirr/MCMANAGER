"""
test_spigot_folia.py — Spigot through BuildTools (heap, full log, error lines,
cache wiped after a failure, git and disk checks) and Folia's missing
Minecraft versions reported with the ones that exist.
"""
import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mc_cli
import mc_deploy
import mc_http
import mc_servers
import mc_software

MANIFEST = {"versions": [{"id": "1.21.1"}, {"id": "1.21.8"}]}


class TestSpigot(unittest.TestCase):

    def setUp(self):
        self.folder = os.path.join(tempfile.mkdtemp(), "srv")
        self.cache = os.path.join(tempfile.mkdtemp(), "buildtools")
        self.calls = []
        self.behaviour = "ok"
        for p in (mock.patch.object(mc_software, "_buildtools_cache", return_value=self.cache),
                  mock.patch.object(mc_software, "_free_bytes", return_value=50 * 1024 ** 3),
                  mock.patch("shutil.which", return_value="/usr/bin/git"),
                  mock.patch.object(mc_http, "download", side_effect=self._download),
                  mock.patch("subprocess.run", side_effect=self._run)):
            p.start()
            self.addCleanup(p.stop)

    def _download(self, address, dest, *a, **k):
        open(dest, "wb").close()

    def _run(self, args, cwd=None, stdout=None, stderr=None, timeout=None, **k):
        self.calls.append({"args": list(args), "cwd": cwd, "timeout": timeout})
        stdout.write("openjdk version \"21\"\nLoading BuildTools\n")
        if self.behaviour == "timeout":
            raise subprocess.TimeoutExpired(args, timeout)
        if self.behaviour == "fail":
            stdout.write("Error patching\n[ERROR] Failed to execute goal\nCaused by: FileNotFoundException work/decompile\n")
            os.makedirs(os.path.join(cwd, "work"), exist_ok=True)
            return subprocess.CompletedProcess(args, 1)
        out = args[args.index("--output-dir") + 1]
        open(os.path.join(out, "spigot-1.21.1.jar"), "wb").close()
        os.makedirs(os.path.join(cwd, "work"), exist_ok=True)
        return subprocess.CompletedProcess(args, 0)

    def _install(self):
        with mock.patch.object(mc_software, "minecraft_exists", return_value=True):
            return mc_software.install(self.folder, "Spigot", "1.21.1", java="/j/java")

    def test_success_sets_the_heap_and_keeps_the_cache(self):
        res = self._install()
        self.assertTrue(res["ok"], res)
        call = self.calls[0]
        self.assertEqual(call["args"][:3], ["/j/java", "-Xmx1500M", "-jar"])
        self.assertEqual((call["cwd"], call["timeout"]), (self.cache, 45 * 60))
        self.assertTrue(os.path.isdir(os.path.join(self.cache, "work")))
        self.assertTrue(os.path.exists(os.path.join(self.folder, "spigot-1.21.1.jar")))

    def test_failure_reports_the_error_lines_and_wipes_the_cache(self):
        self.behaviour = "fail"
        res = self._install()
        self.assertFalse(res["ok"])
        self.assertEqual(res["code"], "installer_failed")
        self.assertIn("[ERROR] Failed to execute goal", res["detail"])
        self.assertIn("Caused by: FileNotFoundException", res["detail"])
        self.assertNotIn("openjdk", res["detail"])
        self.assertFalse(os.path.exists(self.cache))
        log = os.path.join(self.folder, "logs", "buildtools.log")
        self.assertEqual(res["log"], log)
        with open(log, encoding="utf-8") as f:
            self.assertIn("openjdk version", f.read())
        self.assertIn(log, res["detail"])

    def test_timeout_wipes_the_cache(self):
        self.behaviour = "timeout"
        res = self._install()
        self.assertEqual(res["code"], "installer_failed")
        self.assertIn("timed out", res["detail"])
        self.assertFalse(os.path.exists(self.cache))

    def test_git_is_required(self):
        with mock.patch("shutil.which", return_value=None):
            self.assertEqual(self._install()["code"], "git_required")
        self.assertEqual(self.calls, [])

    def test_disk_space_is_checked_first(self):
        with mock.patch.object(mc_software, "_free_bytes", return_value=1024 ** 3):
            res = self._install()
        self.assertEqual((res["code"], res["needed_gb"], res["free_gb"]), ("disk_space", 3, 1.0))
        self.assertEqual(self.calls, [])
        self.assertIn("3", mc_cli.render(res))


class TestFolia(unittest.TestCase):

    def _json(self, address, *a, **k):
        if address == mc_software.MOJANG_MANIFEST:
            return MANIFEST
        if address.endswith("/folia"):
            return {"versions": {"1.20": ["1.20.1", "1.20.4"], "1.21": ["1.21.4", "1.21.8"]}}
        raise mc_http.HttpError(address, "HTTP 404", 404)

    def test_missing_build_lists_the_available_versions(self):
        with mock.patch.object(mc_http, "get_json", side_effect=self._json):
            res = mc_software.install(tempfile.mkdtemp(), "Folia", "1.21.1")
        self.assertEqual(res["code"], "loader_unavailable")
        self.assertEqual(res["versions"], ["1.21.8", "1.21.4", "1.20.4", "1.20.1"])
        text = mc_cli.render(res)
        self.assertIn("1.21.8", text)
        self.assertIn("Folia", text)

    def test_bad_request_is_the_same_as_not_found(self):
        def fake(address, *a, **k):
            if "/builds" in address:
                raise mc_http.HttpError(address, "HTTP 400", 400)
            return self._json(address)
        with mock.patch.object(mc_http, "get_json", side_effect=fake):
            res = mc_software.install(tempfile.mkdtemp(), "Folia", "1.21.1")
        self.assertEqual(res["code"], "loader_unavailable")

    def test_deploy_surfaces_the_reason_instead_of_download_failed(self):
        data = tempfile.mkdtemp()
        failure = {"ok": False, "code": "loader_unavailable", "loader": "Folia", "mc_version": "1.21.1",
                   "versions": ["1.21.8"]}
        with mock.patch.object(mc_servers, "REGISTRY_FILE", os.path.join(data, "servers.json")), \
             mock.patch.object(mc_servers, "REGISTRY_DIR", data), \
             mock.patch.object(mc_servers, "DATA_ROOT", os.path.join(data, "Servers")), \
             mock.patch("mc_core._port_in_use", return_value=False), \
             mock.patch("mc_java.install", return_value={"ok": False, "code": "java_download_failed"}), \
             mock.patch("mc_core.find_java", return_value="java"), \
             mock.patch.object(mc_software, "install", return_value=failure), \
             contextlib.redirect_stdout(io.StringIO()):
            res = mc_deploy.run_deploy_auto(name="F", loader="Folia", version="1.21.1", accept_eula=True)
        self.assertFalse(res["ok"])
        self.assertEqual(res["code"], "loader_unavailable")
        self.assertEqual(res["versions"], ["1.21.8"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
