"""
test_world.py — dimensions, export, import, reset and Chunky pregeneration,
on throwaway folders. No server is started.
"""
import os
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mc_world


def touch(path, content=b"x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(content)


class Base(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.out = tempfile.mkdtemp()
        self.config = {"dossier_serveur": self.dir, "dossier_backup": os.path.join(self.out, "bk")}
        with open(os.path.join(self.dir, "server.properties"), "w") as f:
            f.write("level-name=world\n")
        w = os.path.join(self.dir, "world")
        touch(os.path.join(w, "level.dat"))
        touch(os.path.join(w, "session.lock"))
        touch(os.path.join(w, "region", "r.0.0.mca"), b"o" * 100)
        touch(os.path.join(w, "entities", "r.0.0.mca"))
        touch(os.path.join(w, "poi", "r.0.0.mca"))
        touch(os.path.join(w, "data", "DistantHorizons.sqlite"))
        touch(os.path.join(w, "data", "DistantHorizons.sqlite-wal"))
        touch(os.path.join(w, "DIM-1", "region", "r.0.0.mca"), b"n" * 50)
        touch(os.path.join(w, "DIM1", "region", "r.0.0.mca"))
        touch(os.path.join(w, "dimensions", "mw", "temp", "region", "r.0.0.mca"))

    def exists(self, *parts):
        return os.path.exists(os.path.join(self.dir, *parts))


class TestList(Base):

    def test_dimensions_and_sizes(self):
        dims = {d["id"]: d for d in mc_world.dimensions(self.config)}
        self.assertEqual(set(dims), {"overworld", "nether", "end", "mw:temp"})
        self.assertEqual(dims["nether"]["size_bytes"], 50)
        self.assertGreaterEqual(dims["overworld"]["size_bytes"], 100)
        self.assertNotIn("n" * 50, str(dims["overworld"]))

    def test_bukkit_layout(self):
        touch(os.path.join(self.dir, "world_nether", "DIM-1", "region", "r.0.0.mca"))
        ids = [d["id"] for d in mc_world.dimensions(self.config)]
        self.assertEqual(ids.count("nether"), 1)
        nether = [d for d in mc_world.dimensions(self.config) if d["id"] == "nether"][0]
        self.assertEqual(len(nether["paths"]), 2)

    def test_no_world(self):
        self.config["dossier_serveur"] = tempfile.mkdtemp()
        self.assertEqual(mc_world.dimensions(self.config), [])


class TestExport(Base):

    def test_excludes_lock_and_sqlite(self):
        out = os.path.join(self.out, "w.zip")
        with mock.patch("mc_core.is_server_running", return_value=False):
            res = mc_world.export_world(self.config, out)
        self.assertTrue(res["ok"])
        names = zipfile.ZipFile(out).namelist()
        self.assertIn("world/level.dat", names)
        self.assertIn("world/region/r.0.0.mca", names)
        self.assertFalse([n for n in names if n.endswith("session.lock") or ".sqlite" in n])
        self.assertFalse(os.path.exists(out + ".part"))

    def test_running_server_must_be_frozen(self):
        out = os.path.join(self.out, "w.zip")
        with mock.patch("mc_core.is_server_running", return_value=True), \
                mock.patch("mc_api.is_frozen", return_value=False):
            self.assertEqual(mc_world.export_world(self.config, out)["code"], "server_running_not_frozen")
        self.assertFalse(os.path.exists(out))
        with mock.patch("mc_core.is_server_running", return_value=True), \
                mock.patch("mc_api.is_frozen", return_value=True):
            self.assertTrue(mc_world.export_world(self.config, out)["ok"])

    def test_never_overwrites(self):
        out = os.path.join(self.out, "w.zip")
        touch(out)
        with mock.patch("mc_core.is_server_running", return_value=False):
            self.assertEqual(mc_world.export_world(self.config, out)["code"], "output_exists")


def make_zip(path, files):
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)


class TestImport(Base):

    def run_import(self, source, **kw):
        with mock.patch("mc_core.is_server_running", return_value=False), \
                mock.patch("mc_core.backup_server", return_value=(True, "ok")) as backup:
            res = mc_world.import_world(self.config, source, **kw)
        return res, backup

    def test_requires_confirmation_before_touching_anything(self):
        src = os.path.join(self.out, "new.zip")
        make_zip(src, {"level.dat": "n", "region/r.1.1.mca": "new"})
        res, backup = self.run_import(src)
        self.assertEqual(res["code"], "confirmation_required")
        backup.assert_not_called()
        self.assertTrue(self.exists("world", "region", "r.0.0.mca"))

    def test_zip_with_world_at_root_replaces_and_backs_up_first(self):
        src = os.path.join(self.out, "new.zip")
        make_zip(src, {"level.dat": "n", "region/r.1.1.mca": "new"})
        res, backup = self.run_import(src, confirmed=True)
        self.assertTrue(res["ok"])
        backup.assert_called_once()
        self.assertTrue(self.exists("world", "region", "r.1.1.mca"))
        self.assertFalse(self.exists("world", "region", "r.0.0.mca"))
        self.assertFalse(self.exists("world", "DIM-1"))
        self.assertEqual([n for n in os.listdir(self.dir) if n.startswith(".mcmanager_import")], [])

    def test_zip_with_a_folder_and_bukkit_siblings(self):
        src = os.path.join(self.out, "new.zip")
        make_zip(src, {"MyWorld/level.dat": "n", "MyWorld_nether/DIM-1/region/r.0.0.mca": "nn",
                       "MyWorld_the_end/DIM1/region/r.0.0.mca": "ee"})
        res, _ = self.run_import(src, confirmed=True)
        self.assertTrue(res["ok"])
        self.assertTrue(self.exists("world", "level.dat"))
        self.assertTrue(self.exists("world_nether", "DIM-1", "region", "r.0.0.mca"))
        self.assertTrue(self.exists("world_the_end", "DIM1", "region", "r.0.0.mca"))

    def test_folder_source_is_copied_not_moved(self):
        src = os.path.join(self.out, "folder")
        touch(os.path.join(src, "level.dat"))
        touch(os.path.join(src, "region", "r.9.9.mca"))
        res, _ = self.run_import(src, confirmed=True)
        self.assertTrue(res["ok"])
        self.assertTrue(os.path.exists(os.path.join(src, "level.dat")))
        self.assertTrue(self.exists("world", "region", "r.9.9.mca"))

    def test_no_level_dat(self):
        src = os.path.join(self.out, "bad.zip")
        make_zip(src, {"readme.txt": "x"})
        res, _ = self.run_import(src, confirmed=True)
        self.assertEqual(res["code"], "no_level_dat")
        self.assertTrue(self.exists("world", "region", "r.0.0.mca"))

    def test_unsafe_archive(self):
        src = os.path.join(self.out, "evil.zip")
        make_zip(src, {"level.dat": "n", "../escape.txt": "x"})
        res, _ = self.run_import(src, confirmed=True)
        self.assertEqual(res["code"], "unsafe_archive")
        self.assertFalse(os.path.exists(os.path.join(self.dir, "..", "escape.txt")))

    def test_running_server_refused(self):
        with mock.patch("mc_core.is_server_running", return_value=True):
            self.assertEqual(mc_world.import_world(self.config, self.out, confirmed=True)["code"], "server_running")

    def test_failed_backup_aborts(self):
        src = os.path.join(self.out, "new.zip")
        make_zip(src, {"level.dat": "n"})
        with mock.patch("mc_core.is_server_running", return_value=False), \
                mock.patch("mc_core.backup_server", return_value=(False, "disk full")):
            res = mc_world.import_world(self.config, src, confirmed=True)
        self.assertEqual(res["code"], "backup_failed")
        self.assertTrue(self.exists("world", "region", "r.0.0.mca"))

    def test_missing_and_not_archive(self):
        self.assertEqual(self.run_import(os.path.join(self.out, "nope.zip"), confirmed=True)[0]["code"], "source_missing")
        txt = os.path.join(self.out, "a.txt")
        touch(txt)
        self.assertEqual(self.run_import(txt, confirmed=True)[0]["code"], "not_an_archive")


class TestReset(Base):

    def reset(self, dimension, **kw):
        with mock.patch("mc_core.is_server_running", return_value=kw.pop("running", False)), \
                mock.patch("mc_core.backup_server", return_value=(True, "ok")) as backup:
            return mc_world.reset_dimension(self.config, dimension, **kw), backup

    def test_nether_reset_keeps_the_rest(self):
        res, backup = self.reset("nether", confirmed=True)
        self.assertTrue(res["ok"])
        backup.assert_called_once()
        self.assertFalse(self.exists("world", "DIM-1", "region"))
        self.assertTrue(self.exists("world", "region", "r.0.0.mca"))
        self.assertTrue(self.exists("world", "DIM1", "region"))

    def test_overworld_needs_the_flag(self):
        res, backup = self.reset("overworld", confirmed=True)
        self.assertEqual(res["code"], "overworld_protected")
        backup.assert_not_called()
        res, _ = self.reset("overworld", confirmed=True, include_overworld=True)
        self.assertTrue(res["ok"])
        for folder in ("region", "entities", "poi"):
            self.assertFalse(self.exists("world", folder))
        self.assertTrue(self.exists("world", "level.dat"))
        self.assertTrue(self.exists("world", "DIM-1", "region"))

    def test_custom_dimension(self):
        res, _ = self.reset("mw:temp", confirmed=True)
        self.assertTrue(res["ok"])
        self.assertFalse(self.exists("world", "dimensions", "mw", "temp", "region"))

    def test_unknown_confirmation_and_running(self):
        self.assertEqual(self.reset("moon", confirmed=True)[0]["code"], "unknown_dimension")
        res, backup = self.reset("nether")
        self.assertEqual(res["code"], "confirmation_required")
        backup.assert_not_called()
        self.assertEqual(self.reset("nether", confirmed=True, running=True)[0]["code"], "server_running")
        self.assertTrue(self.exists("world", "DIM-1", "region"))


class TestPregen(Base):

    def test_without_chunky_points_to_mc_mod_add(self):
        res = mc_world.pregen(self.config, 1000)
        self.assertEqual(res["code"], "chunky_missing")
        import mc_lang
        self.assertIn("mc mod add chunky", mc_lang._FR["res_chunky_missing"])
        self.assertIn("mc mod add chunky", mc_lang._EN["res_chunky_missing"])

    def test_detection_by_file_name(self):
        touch(os.path.join(self.dir, "plugins", "Chunky-Bukkit-1.4.jar"))
        self.assertTrue(mc_world.chunky_installed(self.config))
        other = {"dossier_serveur": tempfile.mkdtemp()}
        touch(os.path.join(other["dossier_serveur"], "mods", "chunky-fabric.jar"))
        self.assertTrue(mc_world.chunky_installed(other))

    def test_commands_sent(self):
        touch(os.path.join(self.dir, "mods", "chunky.jar"))
        sent = []
        with mock.patch("mc_core.is_server_running", return_value=True):
            res = mc_world.pregen(self.config, 2000, (100, -200),
                                  rcon=lambda c, cmd: (sent.append(cmd), (True, "50%"))[1])
        self.assertEqual(sent, ["chunky center 100 -200", "chunky radius 2000", "chunky start", "chunky progress"])
        self.assertEqual((res["ok"], res["progress"]), (True, "50%"))

    def test_offline_and_bad_radius(self):
        touch(os.path.join(self.dir, "mods", "chunky.jar"))
        with mock.patch("mc_core.is_server_running", return_value=False):
            self.assertEqual(mc_world.pregen(self.config, 10)["code"], "pregen_offline")
        with mock.patch("mc_core.is_server_running", return_value=True):
            self.assertEqual(mc_world.pregen(self.config, 0)["code"], "invalid_radius")

    def test_center_parsing(self):
        self.assertEqual(mc_world.parse_center("10,-20"), (10, -20))
        self.assertEqual(mc_world.parse_center("10 20"), (10, 20))
        with self.assertRaises(ValueError):
            mc_world.parse_center("abc")


if __name__ == "__main__":
    unittest.main()
