"""
test_deploy_paper.py — Paper deployment through the PaperMC Fill v3 API
(v2 was retired): build choice, download URL, SHA-256 check.
"""
import hashlib
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mc_deploy

JAR = b"paper jar bytes"


def _build(build_id, channel, sha=None):
    return {"id": build_id, "channel": channel, "downloads": {"server:default": {
        "name": f"paper-1.21.1-{build_id}.jar",
        "url": f"https://fill-data.papermc.io/v1/objects/x/paper-1.21.1-{build_id}.jar",
        "checksums": {"sha256": sha or hashlib.sha256(JAR).hexdigest()}}}}


class TestPickBuild(unittest.TestCase):

    def test_newest_stable_wins(self):
        builds = [_build(133, "STABLE"), _build(135, "BETA"), _build(120, "STABLE")]
        build, warn = mc_deploy.pick_paper_build(builds)
        self.assertEqual((build["id"], warn), (133, False))

    def test_falls_back_to_newest_with_warning(self):
        build, warn = mc_deploy.pick_paper_build([_build(10, "ALPHA"), _build(12, "BETA")])
        self.assertEqual((build["id"], warn), (12, True))

    def test_nothing_usable(self):
        self.assertEqual(mc_deploy.pick_paper_build([]), (None, False))
        self.assertEqual(mc_deploy.pick_paper_build([{"id": 1, "downloads": {}}]), (None, False))


class TestDeployPaper(unittest.TestCase):

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.urls = []

    def _download(self, url, dest, label=""):
        self.urls.append(url)
        with open(dest, "wb") as f:
            f.write(JAR)
        return True

    def _deploy(self, builds):
        with mock.patch.object(mc_deploy, "fetch_json", return_value=builds) as fetch, \
             mock.patch.object(mc_deploy, "download", side_effect=self._download), \
             mock.patch.object(mc_deploy, "pr"):
            jar = mc_deploy.deploy_paper(self.folder, "1.21.1")
        return jar, fetch

    def test_uses_fill_v3_and_verifies_sha256(self):
        jar, fetch = self._deploy([_build(133, "STABLE")])
        self.assertEqual(jar, "paper-1.21.1-133.jar")
        self.assertEqual(fetch.call_args[0][0], "https://fill.papermc.io/v3/projects/paper/versions/1.21.1/builds")
        self.assertTrue(self.urls[0].startswith("https://fill-data.papermc.io/"))
        self.assertTrue(os.path.exists(os.path.join(self.folder, jar)))

    def test_hash_mismatch_is_refused_and_deleted(self):
        jar, _ = self._deploy([_build(133, "STABLE", sha="0" * 64)])
        self.assertIsNone(jar)
        self.assertFalse(os.path.exists(os.path.join(self.folder, "paper-1.21.1-133.jar")))

    def test_unknown_version(self):
        self.assertIsNone(self._deploy(None)[0])
        self.assertIsNone(self._deploy([])[0])

    def test_user_agent_identifies_the_tool(self):
        self.assertRegex(mc_deploy.USER_AGENT, r"^MCManager/\d+\.\d+\.\d+ \(https://github.com/scirr/MCMANAGER\)$")


if __name__ == "__main__":
    unittest.main(verbosity=2)
