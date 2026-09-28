"""
test_content_sources.py — 2.9 content layer against a simulated network:
server software (PaperMC Fill v3, Purpur, Fabric, NeoForge), Temurin Java,
mods by name with dependencies (Modrinth), modpacks (.mrpack), upgrades.
"""
import hashlib
import io
import json
import os
import sys
import tarfile
import tempfile
import unittest
import zipfile
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import mc_api
import mc_http
import mc_java
import mc_modpack
import mc_modsources
import mc_software


class FakeNet:
    """URL -> JSON / text / bytes. Downloads write the bytes and check hashes
    like the real mc_http.download."""

    def __init__(self):
        self.json, self.text, self.blobs, self.fetched = {}, {}, {}, []

    def _find(self, table, address):
        base = address.split("?")[0]
        if address in table:
            return table[address]
        if base in table:
            return table[base]
        raise mc_http.HttpError(address, "HTTP 404", 404)

    def get_json(self, address, headers=None, timeout=None):
        return json.loads(json.dumps(self._find(self.json, address)))

    def get_text(self, address, headers=None, timeout=None):
        return self._find(self.text, address)

    def download(self, address, dest, hashes=None, headers=None, progress=None, timeout=None):
        data = self._find(self.blobs, address)
        for algo in ("sha512", "sha256", "sha1", "md5"):
            expected = (hashes or {}).get(algo)
            if expected:
                if hashlib.new(algo, data).hexdigest() != expected:
                    raise mc_http.HttpError(address, f"{algo} mismatch")
                break
        os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
        with open(dest, "wb") as f:
            f.write(data)
        self.fetched.append(address)
        return dest

    def patch(self):
        return [mock.patch.object(mc_http, "get_json", self.get_json),
                mock.patch.object(mc_http, "get_text", self.get_text),
                mock.patch.object(mc_http, "download", self.download)]


def sha(algo, data):
    return hashlib.new(algo, data).hexdigest()


class NetCase(unittest.TestCase):

    def setUp(self):
        self.net = FakeNet()
        for p in self.net.patch():
            p.start()
            self.addCleanup(p.stop)
        self.net.json[mc_software.MOJANG_MANIFEST] = {
            "latest": {"release": "1.21.4"},
            "versions": [{"id": v, "url": f"https://piston-meta.mojang.com/v/{v}.json"}
                         for v in ("1.21.4", "1.21.1", "1.20.1")]}
        for v, java in (("1.21.4", 21), ("1.21.1", 21), ("1.20.1", 17)):
            self.net.json[f"https://piston-meta.mojang.com/v/{v}.json"] = {
                "javaVersion": {"majorVersion": java},
                "downloads": {"server": {"url": f"https://piston-data.mojang.com/{v}/server.jar",
                                         "sha1": sha("sha1", b"vanilla " + v.encode())}}}
            self.net.blobs[f"https://piston-data.mojang.com/{v}/server.jar"] = b"vanilla " + v.encode()


class TestSoftware(NetCase):

    def test_paper_fill_v3_prefers_stable(self):
        jar = b"paper 133"
        self.net.json[f"{mc_software.PAPER_FILL}/paper/versions/1.21.1/builds"] = [
            {"id": 140, "channel": "BETA", "downloads": {"server:default": {
                "name": "paper-1.21.1-140.jar", "url": "https://fill-data.papermc.io/140.jar"}}},
            {"id": 133, "channel": "STABLE", "downloads": {"server:default": {
                "name": "paper-1.21.1-133.jar", "url": "https://fill-data.papermc.io/133.jar",
                "checksums": {"sha256": sha("sha256", jar)}}}}]
        self.net.blobs["https://fill-data.papermc.io/133.jar"] = jar
        folder = tempfile.mkdtemp()
        res = mc_software.install(folder, "paper", "1.21.1")
        self.assertEqual((res["ok"], res["jar_name"], res["loader_version"], res["unstable"]),
                         (True, "paper-1.21.1-133.jar", "133", False))
        self.assertEqual(mc_software.available("Paper", "1.21.1"), (True, "133"))
        self.assertEqual(mc_software.available("Paper", "1.20.1"), (False, "loader_unavailable"))

    def test_vanilla_sha1_and_unknown_version(self):
        folder = tempfile.mkdtemp()
        res = mc_software.install(folder, "Vanilla", "1.21.1")
        self.assertTrue(res["ok"])
        self.assertEqual(mc_software.install(folder, "Vanilla", "9.9")["code"], "unknown_minecraft_version")
        self.net.blobs["https://piston-data.mojang.com/1.20.1/server.jar"] = b"tampered"
        self.assertEqual(mc_software.install(folder, "Vanilla", "1.20.1")["code"], "download_failed")

    def test_purpur_and_fabric_availability(self):
        self.net.json[f"{mc_software.PURPUR}/1.21.1"] = {"builds": {"latest": "2329", "all": ["2329"]}}
        self.assertEqual(mc_software.available("Purpur", "1.21.1"), (True, "2329"))
        self.assertEqual(mc_software.available("Purpur", "1.20.1"), (False, "loader_unavailable"))
        self.net.json[f"{mc_software.FABRIC_META}/loader/1.21.1"] = [
            {"loader": {"version": "0.16.10", "stable": True}}]
        self.assertEqual(mc_software.available("fabric", "1.21.1"), (True, "0.16.10"))
        self.net.json[f"{mc_software.FABRIC_META}/loader/1.20.1"] = []
        self.assertEqual(mc_software.available("Fabric", "1.20.1"), (False, "loader_unavailable"))

    def test_names_and_prefixes(self):
        self.assertEqual(mc_software.canonical("quilt-loader"), "Quilt")
        self.assertEqual(mc_software.canonical("NEOFORGE"), "NeoForge")
        self.assertIsNone(mc_software.canonical("bukkit"))
        self.assertEqual(mc_software.neoforge_prefix("1.21.1"), "21.1.")
        self.assertEqual(mc_software.neoforge_prefix("1.21"), "21.0.")
        self.assertEqual(mc_software.neoforge_prefix("26.1"), "26.1.")
        self.assertLess(mc_software.version_key("1.20.6"), mc_software.version_key("1.21"))


class TestJava(NetCase):

    def setUp(self):
        super().setUp()
        self.java_dir = tempfile.mkdtemp()
        p = mock.patch.object(mc_java, "JAVA_DIR", self.java_dir)
        p.start()
        self.addCleanup(p.stop)

    def _tarball(self, entries):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            for name, data, mode in entries:
                info = tarfile.TarInfo(name)
                info.size, info.mode = len(data), mode
                tar.addfile(info, io.BytesIO(data))
        return buf.getvalue()

    def _publish(self, major, archive):
        self.net.json[mc_java.ADOPTIUM.format(major=major)] = [{
            "binary": {"package": {"name": f"OpenJDK{major}.tar.gz", "link": f"https://github.com/adoptium/{major}.tgz",
                                   "checksum": sha("sha256", archive)}},
            "version": {"semver": f"{major}.0.5+11"}}]
        self.net.blobs[f"https://github.com/adoptium/{major}.tgz"] = archive

    def test_required_java_from_mojang(self):
        self.assertEqual(mc_java.required_java("1.21.1"), 21)
        self.assertEqual(mc_java.required_java("1.20.1"), 17)
        self.assertEqual(mc_java.required_java("1.16.5"), 8)        # offline fallback table
        self.assertEqual(mc_java.fallback_java("26.1"), 25)

    def test_install_and_use(self):
        self._publish(21, self._tarball([("jdk-21.0.5+11-jre/bin/java", b"#!/bin/sh\n", 0o755),
                                         ("jdk-21.0.5+11-jre/release", b"JAVA_VERSION=21", 0o644)]))
        res = mc_java.install(21)
        self.assertEqual((res["ok"], res["code"]), (True, "java_installed"))
        self.assertEqual(mc_java.installed(), {21: os.path.join(self.java_dir, "21", "bin", "java")})
        self.assertEqual(mc_java.install(21)["code"], "java_present")
        config = {"mc_version": "1.21.1"}
        self.assertTrue(mc_java.use(config, "auto")["ok"])
        self.assertEqual(config["java_major"], 21)
        mc_java.use(config, "system")
        self.assertNotIn("java_path", config)
        self.assertEqual(mc_java.use(config, "banana")["code"], "java_bad_choice")

    def test_malicious_archive_is_refused(self):
        self._publish(17, self._tarball([("../../evil", b"x", 0o755)]))
        res = mc_java.install(17)
        self.assertEqual(res["code"], "java_download_failed")
        self.assertFalse(os.path.exists(os.path.join(self.java_dir, "..", "..", "evil")))


class TestModsByName(NetCase):

    def setUp(self):
        super().setUp()
        self.folder = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.folder, "mods"))
        self.config = {"dossier_serveur": self.folder, "loader": "Fabric", "mc_version": "1.21.1"}
        self._project("sodium-extra", "p1", client_side="required", deps=[("p2", "required"), ("p9", "optional")])
        self._project("fabric-api", "p2")
        self._project("iris", "p3", server_side="unsupported")

    def _project(self, slug, pid, client_side="optional", server_side="required", deps=(), version="1.0"):
        jar = f"{slug}-{version}.jar".encode()
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("fabric.mod.json", "{}")
            z.writestr("id", jar)
        data = buf.getvalue()
        project = {"id": pid, "slug": slug, "title": slug.title(), "project_type": "mod",
                   "client_side": client_side, "server_side": server_side}
        for key in (slug, pid):
            self.net.json[f"{mc_modsources.MODRINTH}/project/{key}"] = project
        self.net.json[f"{mc_modsources.MODRINTH}/project/{pid}/version"] = [{
            "id": f"{pid}-v{version}", "version_number": version, "version_type": "release",
            "files": [{"primary": True, "filename": f"{slug}-{version}.jar", "url": f"https://cdn.modrinth.com/{slug}-{version}.jar",
                       "hashes": {"sha512": sha("sha512", data)}}],
            "dependencies": [{"project_id": d, "dependency_type": t} for d, t in deps]}]
        self.net.blobs[f"https://cdn.modrinth.com/{slug}-{version}.jar"] = data

    def test_add_installs_required_dependencies_only(self):
        res = mc_modsources.add(self.config, "sodium-extra")
        self.assertTrue(res["ok"], res)
        self.assertEqual(sorted(res["installed"]), ["fabric-api-1.0.jar", "sodium-extra-1.0.jar"])
        self.assertEqual(sorted(os.listdir(os.path.join(self.folder, "mods"))), sorted(res["installed"]))
        entries = mc_modsources.load_manifest(self.config)["entries"]
        self.assertEqual(entries["modrinth:p2"]["required_by"], "Sodium-Extra")
        self.assertEqual(mc_modsources.add(self.config, "sodium-extra")["code"], "already_installed")

    def test_client_only_and_missing(self):
        self.assertEqual(mc_modsources.add(self.config, "iris")["code"], "client_only")
        self.assertEqual(mc_modsources.add(self.config, "nothing-here")["code"], "content_not_found")

    def test_vanilla_has_no_content(self):
        self.assertEqual(mc_modsources.add(dict(self.config, loader="Vanilla"), "sodium-extra")["code"],
                         "no_content_loader")

    def test_update_replaces_and_quarantines(self):
        mc_modsources.add(self.config, "fabric-api")
        self._project("fabric-api", "p2", version="2.0")
        res = mc_modsources.update(self.config)
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["updated"], ["fabric-api-1.0.jar -> fabric-api-2.0.jar"])
        self.assertEqual(os.listdir(os.path.join(self.folder, "mods")), ["fabric-api-2.0.jar"])
        self.assertTrue(os.path.isdir(os.path.join(self.folder, "mods_quarantine")))
        self.assertEqual(mc_modsources.update(self.config)["current"], ["fabric-api-2.0.jar"])


class TestModpack(NetCase):

    def _mrpack(self, files, overrides=None, server_overrides=None, deps=None):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("modrinth.index.json", json.dumps({
                "formatVersion": 1, "game": "minecraft", "name": "Test Pack", "versionId": "1.2.0",
                "dependencies": deps or {"minecraft": "1.21.1", "fabric-loader": "0.16.10"}, "files": files}))
            for name, data in (overrides or {}).items():
                z.writestr(f"overrides/{name}", data)
            for name, data in (server_overrides or {}).items():
                z.writestr(f"server-overrides/{name}", data)
        path = os.path.join(tempfile.mkdtemp(), "pack.mrpack")
        with open(path, "wb") as f:
            f.write(buf.getvalue())
        return path

    def _file(self, path, data, env=None):
        url = f"https://cdn.modrinth.com/{os.path.basename(path)}"
        self.net.blobs[url] = data
        entry = {"path": path, "hashes": {"sha512": sha("sha512", data)}, "downloads": [url]}
        if env:
            entry["env"] = env
        return entry

    def test_plan_skips_client_only_files(self):
        pack = self._mrpack([self._file("mods/a.jar", b"a"),
                             self._file("mods/shaders.jar", b"s", {"client": "required", "server": "unsupported"})])
        p = mc_modpack.plan_from_mrpack(pack)
        self.assertEqual((p["loader"], p["mc_version"], p["loader_version"]), ("Fabric", "1.21.1", "0.16.10"))
        self.assertEqual([f["path"] for f in p["files"]], ["mods/a.jar"])

    def test_install_into(self):
        pack = self._mrpack([self._file("mods/a.jar", b"a")], overrides={"config/a.toml": "x=1"},
                            server_overrides={"config/a.toml": "x=2", "server.properties": "motd=pack"})
        folder = os.path.join(tempfile.mkdtemp(), "srv")
        with mock.patch.object(mc_software, "install", return_value={
                "ok": True, "code": "installed", "jar_name": "fabric-server-launch.jar", "loader_version": "0.16.10"}) as inst:
            res = mc_modpack.install_into(folder, pack)
        self.assertTrue(res["ok"], res)
        inst.assert_called_once()
        self.assertEqual(inst.call_args[0][1:4], ("Fabric", "1.21.1", "0.16.10"))
        with open(os.path.join(folder, "config", "a.toml")) as f:
            self.assertEqual(f.read(), "x=2")                 # server-overrides win
        self.assertIn("mods/a.jar", res["modpack"]["files"])

    def test_path_escape_is_refused(self):
        pack = self._mrpack([self._file("../../escape.jar", b"e")])
        folder = os.path.join(tempfile.mkdtemp(), "srv")
        with mock.patch.object(mc_software, "install", return_value={"ok": True, "code": "installed", "jar_name": "x.jar"}):
            self.assertEqual(mc_modpack.install_into(folder, pack)["code"], "unsafe_path")

    def test_bad_hash_is_refused(self):
        entry = self._file("mods/a.jar", b"a")
        entry["hashes"]["sha512"] = "0" * 128
        folder = os.path.join(tempfile.mkdtemp(), "srv")
        with mock.patch.object(mc_software, "install", return_value={"ok": True, "code": "installed", "jar_name": "x.jar"}):
            self.assertEqual(mc_modpack.install_into(folder, self._mrpack([entry]))["code"], "source_unreachable")


class TestUpgrade(NetCase):

    def setUp(self):
        super().setUp()
        self.folder = tempfile.mkdtemp()
        self.config = {"dossier_serveur": self.folder, "loader": "Paper", "mc_version": "1.21.1",
                       "jar_name": "paper-1.21.1-133.jar", "java": "system"}
        with open(os.path.join(self.folder, "paper-1.21.1-133.jar"), "w") as f:
            f.write("old")
        self.patches = [mock.patch("mc_core.is_server_running", return_value=False),
                        mock.patch("mc_core.backup_server", return_value=(True, "ok")),
                        mock.patch("mc_config.save_config"),
                        mock.patch("mc_core.sync_server_properties")]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def test_refusals(self):
        self.assertEqual(mc_api.upgrade("s", dict(self.config), "1.20.1")["code"], "downgrade_refused")
        self.assertEqual(mc_api.upgrade("s", dict(self.config), "1.21.1")["code"], "already_on_version")
        self.net.json[f"{mc_software.PAPER_FILL}/paper/versions/1.21.4/builds"] = []
        self.assertEqual(mc_api.upgrade("s", dict(self.config), "latest")["code"], "loader_unavailable")
        with mock.patch("mc_core.is_server_running", return_value=True):
            self.assertEqual(mc_api.upgrade("s", dict(self.config), "1.21.4")["code"], "server_running")

    def test_upgrade_backs_up_installs_and_keeps_old_jar(self):
        jar = b"paper 1.21.4"
        self.net.json[f"{mc_software.PAPER_FILL}/paper/versions/1.21.4/builds"] = [
            {"id": 10, "channel": "STABLE", "downloads": {"server:default": {
                "name": "paper-1.21.4-10.jar", "url": "https://fill-data.papermc.io/10.jar",
                "checksums": {"sha256": sha("sha256", jar)}}}}]
        self.net.blobs["https://fill-data.papermc.io/10.jar"] = jar
        import mc_core
        config = dict(self.config)
        res = mc_api.upgrade("s", config, "latest")
        self.assertEqual((res["ok"], res["code"], res["version"]), (True, "upgraded", "1.21.4"))
        mc_core.backup_server.assert_called_once()
        self.assertEqual(config["jar_name"], "paper-1.21.4-10.jar")
        self.assertTrue(os.path.exists(os.path.join(self.folder, ".mcmanager", "previous-jars", "paper-1.21.1-133.jar")))


if __name__ == "__main__":
    unittest.main(verbosity=2)
