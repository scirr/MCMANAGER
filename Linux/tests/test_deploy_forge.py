"""
test_deploy_forge.py — Forge installation: maven.minecraftforge.net, version
choice through promotions_slim.json, visible network errors.
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mc_http
import mc_software

METADATA = """<metadata><versioning><versions>
<version>1.21.1-52.1.16</version><version>1.21.1-52.1.0</version>
<version>1.21.1-52.0.9</version><version>1.21-51.0.33</version>
</versions></versioning></metadata>"""
MANIFEST = {"versions": [{"id": "1.21.1"}, {"id": "1.99"}]}


class TestPickForgeVersion(unittest.TestCase):

    def test_recommended_wins(self):
        promos = {"promos": {"1.21.1-recommended": "52.1.0", "1.21.1-latest": "52.1.16"}}
        v = mc_software.pick_forge_version("1.21.1", promos, ["1.21.1-52.1.16", "1.21.1-52.1.0"])
        self.assertEqual(v, "1.21.1-52.1.0")

    def test_falls_back_to_latest(self):
        promos = {"promos": {"1.21.1-latest": "52.1.16"}}
        self.assertEqual(mc_software.pick_forge_version("1.21.1", promos, ["1.21.1-52.1.16"]),
                         "1.21.1-52.1.16")

    def test_falls_back_to_highest_maven_version(self):
        v = mc_software.pick_forge_version(
            "1.21.1", None, ["1.21.1-52.1.16", "1.21.1-52.1.0", "1.21.1-52.0.9"])
        self.assertEqual(v, "1.21.1-52.1.16")

    def test_nothing_available(self):
        self.assertIsNone(mc_software.pick_forge_version("1.21.1", {}, []))


class TestInstallForge(unittest.TestCase):

    def setUp(self):
        self.folder = tempfile.mkdtemp()

    def _json(self, address, *a, **k):
        if address == mc_software.MOJANG_MANIFEST:
            return MANIFEST
        if address == mc_software.FORGE_PROMOS:
            return {"promos": {"1.21.1-recommended": "52.1.0"}}
        raise AssertionError(address)

    def test_urls_and_version(self):
        urls = []
        texts = []

        def fake_text(address, *a, **k):
            texts.append(address)
            return METADATA

        def fake_download(address, dest, *a, **k):
            urls.append(address)
            open(dest, "wb").close()

        def fake_installer(args, folder, timeout):
            open(os.path.join(folder, "run.sh"), "w").close()
            return True, ""

        with mock.patch.object(mc_http, "get_json", side_effect=self._json), \
             mock.patch.object(mc_http, "get_text", side_effect=fake_text), \
             mock.patch.object(mc_http, "download", side_effect=fake_download), \
             mock.patch.object(mc_software, "_run_installer", side_effect=fake_installer):
            res = mc_software.install(self.folder, "Forge", "1.21.1")
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["loader_version"], "52.1.0")
        self.assertEqual(texts, ["https://maven.minecraftforge.net/net/minecraftforge/forge/maven-metadata.xml"])
        self.assertEqual(urls, ["https://maven.minecraftforge.net/net/minecraftforge/forge/"
                                "1.21.1-52.1.0/forge-1.21.1-52.1.0-installer.jar"])

    def test_network_error_is_reported_not_hidden(self):
        with mock.patch.object(mc_http, "get_json", side_effect=self._json), \
             mock.patch.object(mc_http, "get_text",
                               side_effect=mc_http.HttpError("https://x", "HTTP 404", 404)):
            res = mc_software.install(self.folder, "Forge", "1.21.1")
        self.assertFalse(res["ok"])
        self.assertEqual(res["code"], "download_failed")
        self.assertIn("404", res["detail"])

    def test_unknown_mc_version(self):
        with mock.patch.object(mc_http, "get_json", side_effect=self._json), \
             mock.patch.object(mc_http, "get_text", return_value=METADATA):
            res = mc_software.install(self.folder, "Forge", "1.99")
        self.assertEqual(res["code"], "loader_unavailable")


if __name__ == "__main__":
    unittest.main()
