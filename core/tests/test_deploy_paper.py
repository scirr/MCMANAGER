"""
test_deploy_paper.py — Paper installation through the PaperMC Fill v3 API
(v2 was retired): build choice, download URL, SHA-256 check.
"""
import hashlib
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mc_http
import mc_software

JAR = b"paper jar bytes"
MANIFEST = {"versions": [{"id": "1.21.1"}]}


def _build(build_id, channel, sha=None):
    return {"id": build_id, "channel": channel, "downloads": {"server:default": {
        "name": f"paper-1.21.1-{build_id}.jar",
        "url": f"https://fill-data.papermc.io/v1/objects/x/paper-1.21.1-{build_id}.jar",
        "checksums": {"sha256": sha or hashlib.sha256(JAR).hexdigest()}}}}


class TestPaperBuilds(unittest.TestCase):

    def _builds(self, builds):
        with mock.patch.object(mc_http, "get_json", return_value=builds):
            return mc_software._paper_builds("paper", "1.21.1")

    def test_newest_stable_wins(self):
        best = self._builds([_build(133, "STABLE"), _build(135, "BETA"), _build(120, "STABLE")])[0]
        self.assertEqual((best[0], best[4]), (133, True))

    def test_falls_back_to_newest_unstable(self):
        best = self._builds([_build(10, "ALPHA"), _build(12, "BETA")])[0]
        self.assertEqual((best[0], best[4]), (12, False))

    def test_nothing_usable(self):
        self.assertEqual(self._builds([]), [])
        self.assertEqual(self._builds([{"id": 1, "downloads": {}}]), [])


class TestInstallPaper(unittest.TestCase):

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.urls = []

    def _download(self, address, dest, hashes=None, headers=None, progress=None, timeout=120):
        self.urls.append(address)
        with open(dest, "wb") as f:
            f.write(JAR)
        expected = (hashes or {}).get("sha256")
        if expected and expected != hashlib.sha256(JAR).hexdigest():
            os.remove(dest)
            raise mc_http.HttpError(address, "sha256 mismatch")

    def _install(self, builds):
        calls = []

        def fake_json(address, *a, **k):
            calls.append(address)
            return MANIFEST if address == mc_software.MOJANG_MANIFEST else builds

        with mock.patch.object(mc_http, "get_json", side_effect=fake_json), \
             mock.patch.object(mc_http, "download", side_effect=self._download):
            return mc_software.install(self.folder, "Paper", "1.21.1"), calls

    def test_uses_fill_v3_and_verifies_sha256(self):
        res, calls = self._install([_build(133, "STABLE")])
        self.assertTrue(res["ok"])
        self.assertEqual(res["jar_name"], "paper-1.21.1-133.jar")
        self.assertIn("https://fill.papermc.io/v3/projects/paper/versions/1.21.1/builds", calls)
        self.assertTrue(self.urls[0].startswith("https://fill-data.papermc.io/"))
        self.assertTrue(os.path.exists(os.path.join(self.folder, res["jar_name"])))

    def test_hash_mismatch_is_refused_and_deleted(self):
        res, _ = self._install([_build(133, "STABLE", sha="0" * 64)])
        self.assertFalse(res["ok"])
        self.assertFalse(os.path.exists(os.path.join(self.folder, "paper-1.21.1-133.jar")))

    def test_unknown_version(self):
        self.assertFalse(self._install([])[0]["ok"])

    def test_unstable_build_is_flagged(self):
        res, _ = self._install([_build(12, "BETA")])
        self.assertTrue(res["unstable"])

    def test_user_agent_identifies_the_tool(self):
        self.assertRegex(mc_http.USER_AGENT, r"^MCManager \(github.com/scirr/MCMANAGER\)$")


if __name__ == "__main__":
    unittest.main(verbosity=2)
