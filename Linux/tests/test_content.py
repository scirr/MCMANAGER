"""
test_content.py — Datapacks, mods (2.6.0) and the daemon request channel.
"""
import os
import sys
import tempfile
import threading
import time
import unittest
import zipfile
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import mc_content
import mc_ipc


def _zip(path, files):
    with zipfile.ZipFile(path, "w") as z:
        for name in files:
            z.writestr(name, "{}")


class TestDatapacks(unittest.TestCase):

    def setUp(self):
        self.server = tempfile.mkdtemp()
        self.dp = os.path.join(self.server, "world", "datapacks")
        os.makedirs(os.path.join(self.dp, "extra", "inner"))
        os.makedirs(os.path.join(self.dp, "plain"))
        open(os.path.join(self.dp, "extra", "inner", "pack.mcmeta"), "w").close()
        open(os.path.join(self.dp, "plain", "pack.mcmeta"), "w").close()
        _zip(os.path.join(self.dp, "terra.zip"), ["pack.mcmeta", "data/terra/worldgen/biome/a.json"])
        self.config = {"dossier_serveur": self.server}

    def test_parse_list(self):
        text = "There are 3 data pack(s) enabled: [vanilla (built-in)], [fabric (built-in)], [file/plain (world)]"
        self.assertEqual(mc_content.parse_datapack_list(text), ["vanilla", "fabric", "file/plain"])
        self.assertEqual(mc_content.parse_datapack_list("There are no data packs enabled"), [])

    def test_inspect(self):
        self.assertEqual(mc_content.inspect_pack(os.path.join(self.dp, "terra.zip")),
                         {"is_pack": True, "worldgen": True, "nested": False})
        self.assertEqual(mc_content.inspect_pack(os.path.join(self.dp, "extra")),
                         {"is_pack": False, "worldgen": False, "nested": True})

    def test_offline_listing(self):
        with mock.patch("mc_core.is_server_running", return_value=False):
            res = mc_content.datapack_list(self.config)
        packs = {p["file"]: p for p in res["packs"]}
        self.assertEqual(packs["extra"]["problem"], "nested")
        self.assertIsNone(packs["plain"]["enabled"])
        self.assertTrue(packs["terra.zip"]["worldgen"])

    def _set(self, enabled_reply, *args, **kwargs):
        sent = []

        def rcon(config, cmd):
            sent.append(cmd)
            return True, enabled_reply if cmd.startswith("datapack list") else ""
        with mock.patch("mc_core.is_server_running", return_value=True), \
             mock.patch.object(mc_content, "_rcon", side_effect=rcon):
            res = mc_content.datapack_set(self.config, *args, **kwargs)
        return res, [c for c in sent if not c.startswith("datapack list")]

    def test_moving_an_enabled_pack_disables_it_first(self):
        reply = "enabled: [vanilla (built-in)], [file/plain (world)], [file/terra.zip (world)]"
        res, sent = self._set(reply, "plain", after="terra")
        self.assertTrue(res["ok"])
        self.assertEqual(sent, ['datapack disable "file/plain"',
                                'datapack enable "file/plain" after "file/terra.zip"'])

    def test_worldgen_pack_requires_restart(self):
        res, sent = self._set("enabled: [vanilla (built-in)]", "terra")
        self.assertEqual((res["code"], res["restart_required"]), ("enabled", True))
        self.assertEqual(sent, ['datapack enable "file/terra.zip"'])

    def test_nested_pack_is_refused(self):
        res, sent = self._set("enabled: [vanilla (built-in)]", "extra")
        self.assertEqual((res["ok"], res["code"], sent), (False, "pack_nested", []))

    def test_offline_enable_is_refused(self):
        with mock.patch("mc_core.is_server_running", return_value=False):
            self.assertEqual(mc_content.datapack_set(self.config, "terra")["code"], "server_offline")


class TestMods(unittest.TestCase):

    def setUp(self):
        self.server = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.server, "mods"))
        os.makedirs(os.path.join(self.server, mc_content.HOST_MODPACK_MODS))
        self.src = tempfile.mkdtemp()
        _zip(os.path.join(self.src, "blocky-1.0.jar"), ["fabric.mod.json", "assets/blocky/models/block/x.json"])
        _zip(os.path.join(self.src, "util-2.0.jar"), ["fabric.mod.json"])
        self.config = {"dossier_serveur": self.server}

    def test_add_goes_to_both_copies_unless_server_only(self):
        self.assertEqual(len(mc_content.mod_add(self.config, os.path.join(self.src, "blocky-1.0.jar"))["copies"]), 2)
        self.assertEqual(len(mc_content.mod_add(self.config, os.path.join(self.src, "util-2.0.jar"), server_only=True)["copies"]), 1)
        mods = {m["file"]: m for m in mc_content.mod_list(self.config)["mods"]}
        self.assertTrue(mods["blocky-1.0.jar"]["modpack"])
        self.assertFalse(mods["util-2.0.jar"]["modpack"])
        self.assertEqual(mc_content.mod_add(self.config, os.path.join(self.src, "util-2.0.jar"))["code"], "mod_exists")

    def test_remove_quarantines_both_copies_and_guards_blocks(self):
        mc_content.mod_add(self.config, os.path.join(self.src, "blocky-1.0.jar"))
        self.assertEqual(mc_content.mod_remove(self.config, "blocky")["code"], "defines_blocks")
        res = mc_content.mod_remove(self.config, "blocky", confirm_blocks=True)
        self.assertEqual((res["code"], len(res["moved"])), ("removed", 2))
        self.assertEqual(mc_content.mod_list(self.config)["mods"], [])
        kept = [f for _, _, files in os.walk(res["quarantine"]) for f in files]
        self.assertEqual(kept, ["blocky-1.0.jar", "blocky-1.0.jar"])

    def test_ambiguous_and_missing(self):
        mc_content.mod_add(self.config, os.path.join(self.src, "blocky-1.0.jar"))
        mc_content.mod_add(self.config, os.path.join(self.src, "util-2.0.jar"))
        self.assertEqual(mc_content.mod_remove(self.config, ".jar")["code"], "mod_ambiguous")
        self.assertEqual(mc_content.mod_remove(self.config, "nothing")["code"], "mod_not_found")

    def test_non_jar_is_refused(self):
        path = os.path.join(self.src, "readme.txt")
        open(path, "w").close()
        self.assertEqual(mc_content.mod_add(self.config, path)["code"], "not_a_jar")


class TestIpc(unittest.TestCase):

    def setUp(self):
        run = tempfile.mkdtemp()
        self.patches = [mock.patch.object(mc_ipc, "REQUESTS_DIR", os.path.join(run, "req")),
                        mock.patch.object(mc_ipc, "RESPONSES_DIR", os.path.join(run, "resp")),
                        mock.patch.object(mc_ipc, "HEARTBEAT_FILE", os.path.join(run, "hb"))]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_heartbeat(self):
        self.assertFalse(mc_ipc.daemon_listening())
        mc_ipc.beat()
        self.assertTrue(mc_ipc.daemon_listening())

    def test_round_trip(self):
        def daemon():
            for _ in range(50):
                for rid, req in mc_ipc.pending_requests():
                    mc_ipc.respond(rid, {"ok": True, "echo": req["params"]})
                    return
                time.sleep(0.05)
        t = threading.Thread(target=daemon)
        t.start()
        self.assertEqual(mc_ipc.call("start", timeout=5, server="a"), {"ok": True, "echo": {"server": "a"}})
        t.join()

    def test_unanswered_request_is_withdrawn(self):
        self.assertIsNone(mc_ipc.call("start", timeout=0.3, server="a"))
        self.assertEqual(mc_ipc.pending_requests(), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
