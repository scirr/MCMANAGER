"""
test_update_signed.py — Signed updates: signature then hash verification,
refusal without touching anything, backup to previous/ and rollback.
"""
import io
import os
import shutil
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mc_update

TEST_PUB = bytes.fromhex("03a107bff3ce10be1d70dd18e74bc09967e4d6309ba50d5f1ddc8664125531b8")
SUMS = (b"045cf6b2f033939078b0ba0dabfd38e069ad05062d7eec73f8214d069cb8d49e  MCManager-Linux.zip\n"
        b"0000000000000000000000000000000000000000000000000000000000000000  MCManager.zip\n")
SIG = bytes.fromhex("4458f414efe9ee1b0236b4b8cee70067dc76cf8298c6a4a9dfdb8ebd938d646e"
                    "d028c7567166f841b7808cec0e33727cde0b83eab1b65fde6a9759b580d8e40b")


def build_package(version="9.9.9"):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in (("MCManager/mc_lang.py", f'VERSION = "{version}"\n'),
                           ("MCManager/mc_new.py", "X = 1\n"),
                           ("MCManager/install.sh", "#!/bin/sh\n")):
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.external_attr = 0o644 << 16
            z.writestr(info, data)
    return buf.getvalue()


class TestVerification(unittest.TestCase):

    def setUp(self):
        self.pkg = os.path.join(tempfile.mkdtemp(), "MCManager-Linux.zip")
        with open(self.pkg, "wb") as f:
            f.write(build_package())

    def _verify(self, sums=SUMS, sig=SIG, asset="MCManager-Linux.zip"):
        return mc_update.verify_package(self.pkg, sums, sig, asset, public_key=TEST_PUB)

    def test_valid(self):
        self.assertEqual(self._verify(), (True, "verified"))

    def test_signature_checked_before_anything(self):
        self.assertEqual(self._verify(sums=SUMS.replace(b"045c", b"145c")), (False, "bad_signature"))
        self.assertEqual(self._verify(sig=SIG[:-1] + b"\x00"), (False, "bad_signature"))

    def test_real_key_rejects_test_signature(self):
        self.assertEqual(mc_update.verify_package(self.pkg, SUMS, SIG)[1], "bad_signature")

    def test_tampered_package(self):
        with open(self.pkg, "ab") as f:
            f.write(b"!")
        self.assertEqual(self._verify(), (False, "bad_checksum"))

    def test_package_not_listed(self):
        self.assertEqual(self._verify(asset="Other.zip"), (False, "not_listed"))

    def test_sums_and_signature_formats(self):
        self.assertEqual(mc_update.parse_sums("ABCD" * 16 + " *a.zip\njunk\n"), {"a.zip": "abcd" * 16})
        self.assertEqual(mc_update.decode_signature(SIG.hex().encode() + b"\n"), SIG)
        self.assertEqual(mc_update.decode_signature(SIG), SIG)


class TestInstall(unittest.TestCase):

    def setUp(self):
        self.app = tempfile.mkdtemp()
        for name, data in (("mc_lang.py", 'VERSION = "2.6.0"\n'), ("mc_old.py", "OLD\n"),
                           ("servers.json", "{}")):
            with open(os.path.join(self.app, name), "w") as f:
                f.write(data)
        self.files = {"MCManager-Linux.zip": build_package(), "SHA256SUMS": SUMS, "SHA256SUMS.sig": SIG}
        self.patches = [
            mock.patch.object(mc_update, "BASE_DIR", self.app),
            mock.patch.object(mc_update, "PREVIOUS_DIR", os.path.join(self.app, "previous")),
            mock.patch.object(mc_update, "RELEASE_PUBLIC_KEY", TEST_PUB),
            mock.patch.object(mc_update, "VERSION", "2.6.0"),
            mock.patch.object(mc_update, "_fetch_release", side_effect=self._release),
            mock.patch.object(mc_update, "_download", side_effect=self._download),
            mock.patch.object(mc_update, "_restart_daemon", return_value=True),
            mock.patch.object(mc_update, "_after_install"),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.app, ignore_errors=True)

    def _release(self, version=None, timeout=None):
        return "9.9.9", {name: f"https://x/{name}" for name in self.files}

    def _download(self, url, dest):
        with open(dest, "wb") as f:
            f.write(self.files[url.rsplit("/", 1)[1]])

    def _read(self, *parts):
        with open(os.path.join(self.app, *parts)) as f:
            return f.read()

    def test_update_installs_and_keeps_previous(self):
        res = mc_update.perform_update()
        self.assertEqual((res["ok"], res["code"], res["version"]), (True, "updated", "9.9.9"))
        self.assertIn("9.9.9", self._read("mc_lang.py"))
        self.assertIn("2.6.0", self._read("previous", "mc_lang.py"))
        self.assertEqual(self._read("servers.json"), "{}")          # data untouched
        self.assertFalse(os.path.exists(os.path.join(self.app, "previous", "servers.json")))

    def test_tampered_package_changes_nothing(self):
        self.files["MCManager-Linux.zip"] += b"x"
        res = mc_update.perform_update()
        self.assertEqual((res["ok"], res["code"]), (False, "bad_checksum"))
        self.assertIn("2.6.0", self._read("mc_lang.py"))
        self.assertFalse(os.path.exists(os.path.join(self.app, "previous")))

    def test_unsigned_release_is_refused(self):
        del self.files["SHA256SUMS.sig"]
        self.assertEqual(mc_update.perform_update()["code"], "unsigned")
        self.assertIn("2.6.0", self._read("mc_lang.py"))

    def test_rollback_swaps_back_and_forth(self):
        self.assertEqual(mc_update.rollback()["code"], "no_previous")
        mc_update.perform_update()
        with mock.patch.object(mc_update, "VERSION", "9.9.9"):
            res = mc_update.rollback()
        self.assertEqual((res["code"], res["version"]), ("rolled_back", "2.6.0"))
        self.assertIn("2.6.0", self._read("mc_lang.py"))
        self.assertIn("9.9.9", self._read("previous", "mc_lang.py"))

    def test_same_version_is_up_to_date(self):
        with mock.patch.object(mc_update, "VERSION", "9.9.9"):
            self.assertEqual(mc_update.perform_update()["code"], "up_to_date")
            self.assertEqual(mc_update.perform_update("9.9.9")["code"], "up_to_date")


if __name__ == "__main__":
    unittest.main(verbosity=2)
