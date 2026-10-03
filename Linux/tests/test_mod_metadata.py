"""
test_mod_metadata.py — mod list shows id, name, version, loader and whether a
mod adds blocks; mod remove accepts a file, an id or a display name.
"""
import json
import os
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mc_content

FORGE_TOML = '''modLoader="javafml"
license="MIT"
[[mods]]
modId="forgeblocks"
version="2.1"
displayName="Forge Blocks"
'''


def _jar(path, files):
    with zipfile.ZipFile(path, "w") as z:
        for name, text in files.items():
            z.writestr(name, text)


class TestJarMetadata(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def _meta(self, files):
        path = os.path.join(self.dir, "x.jar")
        _jar(path, files)
        return mc_content.jar_metadata(path)

    def test_fabric(self):
        meta = self._meta({"fabric.mod.json": json.dumps({"id": "labo_blocs", "name": "Labo", "version": "1.2"})})
        self.assertEqual(meta, {"id": "labo_blocs", "name": "Labo", "version": "1.2", "loader": "fabric"})

    def test_quilt(self):
        meta = self._meta({"quilt.mod.json": json.dumps({"quilt_loader": {
            "id": "q", "version": "3", "metadata": {"name": "Quilty"}}})})
        self.assertEqual((meta["id"], meta["name"], meta["version"], meta["loader"]), ("q", "Quilty", "3", "quilt"))

    def test_forge_and_neoforge(self):
        forge = self._meta({"META-INF/mods.toml": FORGE_TOML})
        self.assertEqual((forge["id"], forge["name"], forge["version"], forge["loader"]),
                         ("forgeblocks", "Forge Blocks", "2.1", "forge"))
        neo = self._meta({"META-INF/neoforge.mods.toml": FORGE_TOML})
        self.assertEqual(neo["loader"], "neoforge")

    def test_toml_version_placeholder_uses_the_manifest(self):
        text = FORGE_TOML.replace('"2.1"', '"${file.jarVersion}"')
        meta = self._meta({"META-INF/mods.toml": text, "META-INF/MANIFEST.MF": "Implementation-Version: 9.9\n"})
        self.assertEqual(meta["version"], "9.9")

    def test_plugin(self):
        meta = self._meta({"plugin.yml": "name: Essentials\nversion: '2.20'\nmain: a.B\n"})
        self.assertEqual((meta["id"], meta["name"], meta["version"], meta["loader"]),
                         ("Essentials", "Essentials", "2.20", "bukkit"))

    def test_unknown_or_broken_jar(self):
        self.assertEqual(self._meta({"readme.txt": "x"})["id"], None)
        path = os.path.join(self.dir, "bad.jar")
        with open(path, "w") as f:
            f.write("not a zip")
        self.assertEqual(mc_content.jar_metadata(path)["loader"], None)


class TestModLookup(unittest.TestCase):

    def setUp(self):
        self.server = tempfile.mkdtemp()
        mods = os.path.join(self.server, "mods")
        os.makedirs(mods)
        _jar(os.path.join(mods, "mod_blocs.jar"), {
            "fabric.mod.json": json.dumps({"id": "labo_blocs", "name": "Labo Blocs", "version": "1.0"}),
            "assets/labo_blocs/models/block/b.json": "{}"})
        _jar(os.path.join(mods, "tools-3.jar"), {
            "fabric.mod.json": json.dumps({"id": "tools", "name": "Tools", "version": "3"})})
        self.config = {"dossier_serveur": self.server}

    def test_list_carries_the_metadata(self):
        mods = {m["file"]: m for m in mc_content.mod_list(self.config)["mods"]}
        blocs = mods["mod_blocs.jar"]
        self.assertEqual((blocs["id"], blocs["name"], blocs["version"], blocs["loader"], blocs["adds_blocks"]),
                         ("labo_blocs", "Labo Blocs", "1.0", "fabric", True))
        self.assertFalse(mods["tools-3.jar"]["adds_blocks"])

    def test_remove_by_id_name_and_file(self):
        for ref in ("labo_blocs", "Labo Blocs", "mod_blocs.jar", "mod_blocs"):
            with self.subTest(ref=ref):
                found = mc_content._find_mod(self.config, ref)
                self.assertEqual([m["file"] for m in found], ["mod_blocs.jar"])
        res = mc_content.mod_remove(self.config, "labo_blocs", confirm_blocks=True)
        self.assertEqual((res["ok"], res["file"]), (True, "mod_blocs.jar"))

    def test_id_beats_a_fragment_of_another_file(self):
        self.assertEqual([m["file"] for m in mc_content._find_mod(self.config, "tools")], ["tools-3.jar"])

    def test_not_found(self):
        self.assertEqual(mc_content.mod_remove(self.config, "absent")["code"], "mod_not_found")


if __name__ == "__main__":
    unittest.main(verbosity=2)
