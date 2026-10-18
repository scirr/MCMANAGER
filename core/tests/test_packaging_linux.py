import os
import shutil
import subprocess
import sys
import tempfile
import unittest

if sys.platform == "win32":
    raise unittest.SkipTest("Linux packaging")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "packaging", "linux"))
sys.path.insert(0, os.path.join(ROOT, "core"))
import build_packages
import platform_linux


class PackagingTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.tmp = cls._tmp.name
        cls.zip = build_packages.build_app_zip(cls.tmp)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()


class ControlTests(unittest.TestCase):
    def test_version_matches_the_application(self):
        import mc_lang
        self.assertEqual(build_packages.read_version(), mc_lang.VERSION)

    def test_control_fields(self):
        text = build_packages.control_text("3.0.0", 42)
        fields = dict(line.split(": ", 1) for line in text.splitlines() if line and not line.startswith(" "))
        self.assertEqual(fields["Package"], "mcmanager")
        self.assertEqual(fields["Version"], "3.0.0")
        self.assertEqual(fields["Architecture"], "all")
        self.assertEqual(fields["Depends"], "python3 (>= 3.10)")
        self.assertEqual(fields["Recommends"], "python3-pil")
        self.assertNotIn("java", text.split("Description:")[0].lower())

    def test_deb_scripts_are_shell_and_keep_servers(self):
        scripts = build_packages.deb_scripts()
        self.assertEqual(set(scripts), {"postinst", "prerm", "postrm"})
        for body in scripts.values():
            self.assertTrue(body.startswith("#!/bin/sh\n"))
        self.assertIn("mcmanager-setup", scripts["postinst"])
        self.assertIn("daemon-reload", scripts["postinst"])
        self.assertIn("systemctl stop mc_manager", scripts["prerm"])
        for body in scripts.values():
            self.assertNotIn("rm -rf /opt/mcmanager\n", body)
            self.assertNotIn("servers.json", body)

    def test_purge_never_removes_the_application_data(self):
        for body in list(build_packages.deb_scripts().values()) + list(build_packages.rpm_scripts().values()):
            for line in body.splitlines():
                if "rm " in line:
                    self.assertNotIn("Servers", line)
                    self.assertNotIn("servers.json", line)
                    self.assertNotIn("rm -rf /opt/mcmanager ", line + " ")


class UnitTests(unittest.TestCase):
    def test_unit_is_the_one_the_code_writes(self):
        unit = build_packages.render_unit()
        saved = (platform_linux.BASE_DIR, sys.executable)
        platform_linux.BASE_DIR, sys.executable = build_packages.APP_DIR, build_packages.PYTHON
        try:
            expected = platform_linux._service_unit_content(build_packages.USER_PLACEHOLDER)
        finally:
            platform_linux.BASE_DIR, sys.executable = saved
        self.assertEqual(unit, expected)
        self.assertIn("KillMode=process", unit)
        self.assertIn(f"User={build_packages.USER_PLACEHOLDER}", unit)
        self.assertIn("WorkingDirectory=/opt/mcmanager", unit)
        self.assertIn("ExecStart=/usr/bin/python3 /opt/mcmanager/mc_daemon.py", unit)

    def test_unit_ignores_the_builder_data_dir(self):
        old = os.environ.get("MCMANAGER_DATA_DIR")
        os.environ["MCMANAGER_DATA_DIR"] = "/somewhere/else"
        try:
            self.assertNotIn("somewhere", build_packages.render_unit())
            self.assertEqual(os.environ["MCMANAGER_DATA_DIR"], "/somewhere/else")
        finally:
            if old is None:
                del os.environ["MCMANAGER_DATA_DIR"]
            else:
                os.environ["MCMANAGER_DATA_DIR"] = old

    def test_setup_script_uses_the_installing_code(self):
        self.assertIn("mc_config.install_daemon_service", build_packages.SETUP_SCRIPT)


class StageTests(PackagingTestCase):
    def stage(self, kind):
        root = os.path.join(self.tmp, "stage-" + kind)
        build_packages.stage_tree(root, self.zip, kind)
        self.addCleanup(shutil.rmtree, root, True)
        return root

    def test_layout_and_modes(self):
        root = self.stage("deb")
        files = dict(build_packages.staged_files(root))
        self.assertEqual(files["/usr/bin/mc"], 0o755)
        self.assertEqual(files["/usr/sbin/mcmanager-setup"], 0o755)
        self.assertEqual(files["/lib/systemd/system/mc_manager.service"], 0o644)
        self.assertEqual(files["/opt/mcmanager/mc_cli.py"], 0o755)
        self.assertEqual(files["/opt/mcmanager/mc_core.py"], 0o644)
        self.assertIn("/opt/mcmanager/mc_daemon.py", files)

    def test_no_installer_and_no_user_data(self):
        files = [p for p, _m in build_packages.staged_files(self.stage("rpm"))]
        for path in files:
            self.assertTrue(path.startswith(("/opt/mcmanager/", "/usr/bin/", "/usr/sbin/", "/usr/lib/systemd/")), path)
            name = os.path.basename(path)
            self.assertNotIn(name, ("install.sh", "uninstall.sh", "servers.json", "config.json", "language.txt"))
        self.assertIn("/usr/lib/systemd/system/mc_manager.service", files)

    def test_marker_names_the_package_manager(self):
        for kind, manager in (("deb", "apt"), ("rpm", "dnf")):
            with open(os.path.join(self.stage(kind), "opt/mcmanager/installed-by-package"), encoding="utf-8") as f:
                self.assertEqual(f.read().strip(), manager)

    def test_marker_blocks_the_updater(self):
        import mc_update
        root = self.stage("deb")
        marker = os.path.join(root, "opt/mcmanager/installed-by-package")
        saved = mc_update.PACKAGE_MARKER
        mc_update.PACKAGE_MARKER = marker
        try:
            self.assertEqual(mc_update.package_manager(), "apt")
        finally:
            mc_update.PACKAGE_MARKER = saved


class SpecTests(PackagingTestCase):
    def spec(self):
        root = os.path.join(self.tmp, "stage-spec")
        build_packages.stage_tree(root, self.zip, "rpm")
        self.addCleanup(shutil.rmtree, root, True)
        return build_packages.spec_text("3.0.0", build_packages.staged_files(root))

    def test_header_fields(self):
        spec = self.spec()
        self.assertIn("Name:           mcmanager\n", spec)
        self.assertIn("Version:        3.0.0\n", spec)
        self.assertIn("Release:        1\n", spec)
        self.assertIn("BuildArch:      noarch\n", spec)
        self.assertIn("Requires:       python3 >= 3.10\n", spec)
        self.assertIn("Recommends:     python3-pillow\n", spec)
        self.assertNotIn("java", spec.split("%description")[0].lower())

    def test_files_and_scriptlets(self):
        spec = self.spec()
        self.assertIn('%attr(0755,root,root) "/usr/bin/mc"', spec)
        self.assertIn('%attr(0644,root,root) "/usr/lib/systemd/system/mc_manager.service"', spec)
        self.assertIn('%attr(0755,root,root) "/opt/mcmanager/mc_cli.py"', spec)
        self.assertIn("%dir %attr(0755,root,root) /opt/mcmanager", spec)
        for section in ("%post", "%preun", "%postun", "%files", "%changelog"):
            self.assertIn("\n" + section + "\n", spec)
        self.assertIn("mcmanager-setup", spec)
        self.assertNotIn(build_packages.USER_PLACEHOLDER, spec.split("%files")[0])


@unittest.skipUnless(shutil.which("dpkg-deb"), "dpkg-deb is not installed")
class DebBuildTests(PackagingTestCase):
    def test_real_build(self):
        out = os.path.join(self.tmp, "out")
        os.makedirs(out)
        deb = build_packages.build_deb(self.zip, out, "3.0.0")
        self.assertEqual(os.path.basename(deb), "mcmanager_3.0.0_all.deb")
        info = subprocess.run(["dpkg-deb", "--info", deb], capture_output=True, text=True, check=True).stdout
        self.assertIn("Package: mcmanager", info)
        self.assertIn("Depends: python3 (>= 3.10)", info)
        listing = subprocess.run(["dpkg-deb", "--contents", deb], capture_output=True, text=True, check=True).stdout
        self.assertIn("-rwxr-xr-x root/root", listing)
        self.assertIn("./lib/systemd/system/mc_manager.service", listing)
        self.assertIn("./opt/mcmanager/mc_cli.py", listing)
        self.assertIn("./usr/bin/mc", listing)
        for forbidden in ("servers.json", "install.sh", "language.txt"):
            self.assertNotIn(forbidden, listing)
        extract = os.path.join(self.tmp, "extract")
        control = os.path.join(self.tmp, "control")
        subprocess.run(["dpkg-deb", "--control", deb, control], check=True)
        subprocess.run(["dpkg-deb", "--extract", deb, extract], check=True)
        for script in ("postinst", "prerm", "postrm"):
            self.assertEqual(os.stat(os.path.join(control, script)).st_mode & 0o777, 0o755)
            subprocess.run(["sh", "-n", os.path.join(control, script)], check=True)
        with open(os.path.join(extract, "lib/systemd/system/mc_manager.service"), encoding="utf-8") as f:
            self.assertEqual(f.read(), build_packages.render_unit())


@unittest.skipUnless(shutil.which("rpmbuild"), "rpmbuild is not installed here; the .rpm is built and checked in CI")
class RpmBuildTests(PackagingTestCase):
    def test_real_build(self):
        out = os.path.join(self.tmp, "rpm-out")
        os.makedirs(out)
        rpm = build_packages.build_rpm(self.zip, out, "3.0.0")
        self.assertEqual(os.path.basename(rpm), "mcmanager-3.0.0-1.noarch.rpm")


if __name__ == "__main__":
    unittest.main()
