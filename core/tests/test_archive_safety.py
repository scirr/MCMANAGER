import io
import os
import sys
import tarfile
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mc_java
import mc_modpack


def _tar(path, *entries):
    with tarfile.open(path, "w") as t:
        for name, kind, extra in entries:
            ti = tarfile.TarInfo(name)
            ti.type = kind
            data = None
            if kind == tarfile.REGTYPE:
                data = b"x"
                ti.size = 1
            elif kind in (tarfile.SYMTYPE, tarfile.LNKTYPE):
                ti.linkname = extra
            elif kind == tarfile.CHRTYPE:
                ti.devmajor, ti.devminor = 1, 3
            t.addfile(ti, io.BytesIO(data) if data else None)


class TarSafety(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.archive = os.path.join(self.tmp.name, "a.tar")
        self.dest = os.path.join(self.tmp.name, "out")
        os.makedirs(self.dest)

    def _refused(self, *entries):
        _tar(self.archive, *entries)
        with self.assertRaises(ValueError):
            mc_java._extract_tar(self.archive, self.dest)
        self.assertEqual(os.listdir(self.dest), [])

    def test_parent_traversal(self):
        self._refused(("../evil", tarfile.REGTYPE, None))

    def test_absolute_path(self):
        self._refused(("/tmp/evil", tarfile.REGTYPE, None))

    def test_symlink_outside(self):
        self._refused(("l", tarfile.SYMTYPE, "/etc"))

    def test_symlink_relative_escape(self):
        self._refused(("d/l", tarfile.SYMTYPE, "../../etc"))

    def test_hardlink_outside(self):
        self._refused(("h", tarfile.LNKTYPE, "../../etc/passwd"))

    def test_hardlink_absolute(self):
        self._refused(("h", tarfile.LNKTYPE, "/etc/passwd"))

    def test_device(self):
        self._refused(("dev", tarfile.CHRTYPE, None))

    def test_fifo(self):
        self._refused(("f", tarfile.FIFOTYPE, None))

    def test_valid(self):
        _tar(self.archive, ("jdk/bin/java", tarfile.REGTYPE, None),
             ("jdk/bin/j", tarfile.SYMTYPE, "java"))
        mc_java._extract_tar(self.archive, self.dest)
        self.assertTrue(os.path.exists(os.path.join(self.dest, "jdk", "bin", "java")))


class ZipSafety(unittest.TestCase):
    def _zip(self, name):
        path = os.path.join(self.tmp.name, "a.zip")
        with zipfile.ZipFile(path, "w") as z:
            z.writestr(name, "x")
        return path

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dest = os.path.join(self.tmp.name, "out")
        os.makedirs(self.dest)

    def test_java_zip(self):
        for name in ("../evil", "/tmp/evil"):
            with self.assertRaises(ValueError):
                mc_java._extract_zip(self._zip(name), self.dest)

    def test_modpack_zip(self):
        for name in ("../evil", "/tmp/evil"):
            with self.assertRaises(Exception):
                mc_modpack._extract(self._zip(name), self.dest)
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "evil")))


if __name__ == "__main__":
    unittest.main()
