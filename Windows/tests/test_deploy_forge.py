"""
test_deploy_forge.py — Forge deployment: maven.minecraftforge.net, version
choice through promotions_slim.json, visible network errors.
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mc_deploy

METADATA = """<metadata><versioning><versions>
<version>1.21.1-52.1.16</version><version>1.21.1-52.1.0</version>
<version>1.21.1-52.0.9</version><version>1.21-51.0.33</version>
</versions></versioning></metadata>"""


class TestPickForgeVersion(unittest.TestCase):

    def test_recommended_wins(self):
        promos = {"promos": {"1.21.1-recommended": "52.1.0", "1.21.1-latest": "52.1.16"}}
        v = mc_deploy.pick_forge_version(
            "1.21.1", promos, ["1.21.1-52.1.16", "1.21.1-52.1.0"])
        self.assertEqual(v, "1.21.1-52.1.0")

    def test_falls_back_to_latest(self):
        promos = {"promos": {"1.21.1-latest": "52.1.16"}}
        v = mc_deploy.pick_forge_version("1.21.1", promos, ["1.21.1-52.1.16"])
        self.assertEqual(v, "1.21.1-52.1.16")

    def test_falls_back_to_highest_maven_version(self):
        v = mc_deploy.pick_forge_version(
            "1.21.1", None, ["1.21.1-52.1.16", "1.21.1-52.1.0", "1.21.1-52.0.9"])
        self.assertEqual(v, "1.21.1-52.1.16")

    def test_nothing_available(self):
        self.assertIsNone(mc_deploy.pick_forge_version("1.21.1", {}, []))


class TestDeployForge(unittest.TestCase):

    def setUp(self):
        self.folder = tempfile.mkdtemp()

    def test_urls_and_version(self):
        urls = []

        def fake_download(url, dest, label=""):
            urls.append(url)
            return False

        promos = {"promos": {"1.21.1-recommended": "52.1.0"}}
        with mock.patch.object(mc_deploy, "fetch_text", return_value=METADATA) as ft, \
             mock.patch.object(mc_deploy, "fetch_json", return_value=promos) as fj, \
             mock.patch.object(mc_deploy, "download", side_effect=fake_download), \
             mock.patch.object(mc_deploy, "pr"):
            self.assertIsNone(mc_deploy.deploy_forge(self.folder, "1.21.1"))
        ft.assert_called_once_with(
            "https://maven.minecraftforge.net/net/minecraftforge/forge/maven-metadata.xml")
        fj.assert_called_once_with(
            "https://files.minecraftforge.net/net/minecraftforge/forge/promotions_slim.json")
        self.assertEqual(urls, [
            "https://maven.minecraftforge.net/net/minecraftforge/forge/"
            "1.21.1-52.1.0/forge-1.21.1-52.1.0-installer.jar"])

    def test_network_error_is_reported_not_hidden(self):
        with mock.patch("urllib.request.urlopen", side_effect=OSError("HTTP Error 404")), \
             mock.patch.object(mc_deploy, "pr") as pr:
            self.assertIsNone(mc_deploy.deploy_forge(self.folder, "1.21.1"))
        shown = " ".join(str(c.args[1]) for c in pr.call_args_list)
        self.assertIn("404", shown)
        self.assertNotIn(mc_deploy.T["no_forge_versions"].format(ver="1.21.1"), shown)

    def test_unknown_mc_version(self):
        with mock.patch.object(mc_deploy, "fetch_text", return_value=METADATA), \
             mock.patch.object(mc_deploy, "fetch_json", return_value={"promos": {}}), \
             mock.patch.object(mc_deploy, "pr") as pr:
            self.assertIsNone(mc_deploy.deploy_forge(self.folder, "1.99"))
        self.assertTrue(any("1.99" in str(c.args[1]) for c in pr.call_args_list))


if __name__ == "__main__":
    unittest.main()
