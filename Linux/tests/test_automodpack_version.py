"""
test_automodpack_version.py — AutoModpack: release builds only unless a
pre-release is explicitly accepted; the version is shown.
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mc_deploy


def _v(number, kind):
    return {"version_number": number, "version_type": kind,
            "files": [{"url": f"https://cdn.modrinth.com/data/x/versions/{number}/automodpack-{number}.jar"}]}


class TestAutomodpackVersion(unittest.TestCase):

    def test_release_preferred_over_newer_prerelease(self):
        data = [_v("5.0.0-rc.1", "beta"), _v("4.9.0", "release")]
        with mock.patch.object(mc_deploy, "fetch_json", return_value=data):
            self.assertEqual(mc_deploy.check_automodpack_availability("1.21.1", "fabric")["version_number"], "4.9.0")

    def test_prerelease_only_on_explicit_request(self):
        data = [_v("5.0.0-rc.1", "beta")]
        with mock.patch.object(mc_deploy, "fetch_json", return_value=data):
            self.assertIsNone(mc_deploy.check_automodpack_availability("1.21.1", "fabric"))
            found = mc_deploy.check_automodpack_availability("1.21.1", "fabric", allow_prerelease=True)
        self.assertEqual(found["version_number"], "5.0.0-rc.1")

    def _setup(self, data, answer):
        folder = tempfile.mkdtemp()
        out = []
        with mock.patch.object(mc_deploy, "fetch_json", return_value=data), \
             mock.patch.object(mc_deploy, "ask_yn", return_value=answer) as ask, \
             mock.patch.object(mc_deploy, "download", return_value=True) as dl, \
             mock.patch.object(mc_deploy, "pr", side_effect=lambda level, msg: out.append(msg)):
            config = mc_deploy.setup_automodpack(folder, {}, "1.21.1", "Fabric")
        return config, ask, dl, out

    def test_declined_prerelease_installs_nothing(self):
        config, ask, dl, _ = self._setup([_v("5.0.0-rc.1", "beta")], False)
        self.assertEqual(config["activer_automodpack"], 0)
        dl.assert_not_called()
        self.assertIn("5.0.0-rc.1", ask.call_args[0][0])

    def test_release_installed_and_version_shown(self):
        config, ask, dl, out = self._setup([_v("5.0.0-rc.1", "beta"), _v("4.9.0", "release")], True)
        self.assertEqual(config["activer_automodpack"], 1)
        self.assertIn("automodpack-4.9.0.jar", dl.call_args[0][0])
        self.assertTrue(any("4.9.0" in m for m in out))


if __name__ == "__main__":
    unittest.main(verbosity=2)
