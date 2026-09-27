"""
test_sig.py — Ed25519 verification (RFC 8032 section 7.1 test vectors), pure
Python and through 'cryptography' when available.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import mc_sig

VECTORS = [
    ("d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a", "",
     "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"),
    ("3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c", "72",
     "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00"),
    ("fc51cd8e6218a1a38da47ed00230f0580816ed13ba3303ac5deb911548908025", "af82",
     "6291d657deec24024827e69c3abe01a30ce548a284743a445e3680d7db5ac3ac18ff9b538d16f290ae67f760984dc6594a7c15e9716ed28dc027beceea1ec40a"),
]


class TestEd25519(unittest.TestCase):

    def _all(self, check):
        for pk, msg, sig in VECTORS:
            check(bytes.fromhex(pk), bytes.fromhex(msg), bytes.fromhex(sig))

    def test_rfc_vectors_pure(self):
        self._all(lambda pk, m, s: self.assertTrue(mc_sig._verify_pure(pk, m, s)))

    def test_rfc_vectors_public_api(self):
        self._all(lambda pk, m, s: self.assertTrue(mc_sig.verify(pk, m, s)))

    def test_tampering_is_rejected(self):
        def check(pk, m, s):
            self.assertFalse(mc_sig._verify_pure(pk, m + b"x", s))
            bad = bytearray(s)
            bad[10] ^= 1
            self.assertFalse(mc_sig._verify_pure(pk, m, bytes(bad)))
            self.assertFalse(mc_sig.verify(pk, m + b"x", s))
        self._all(check)

    def test_wrong_key_and_malformed_input(self):
        pk1, m, s = (bytes.fromhex(x) for x in VECTORS[0])
        pk2 = bytes.fromhex(VECTORS[1][0])
        self.assertFalse(mc_sig._verify_pure(pk2, m, s))
        self.assertFalse(mc_sig._verify_pure(pk1[:31], m, s))
        self.assertFalse(mc_sig._verify_pure(pk1, m, s[:63]))
        # s >= L must be rejected (malleability)
        big = s[:32] + (2 ** 253).to_bytes(32, "little")
        self.assertFalse(mc_sig._verify_pure(pk1, m, big))

    def test_pure_matches_cryptography_on_random_keys(self):
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            from cryptography.hazmat.primitives import serialization
        except BaseException:
            self.skipTest("cryptography not usable here")
        for i in range(5):
            key = Ed25519PrivateKey.generate()
            pub = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
            msg = os.urandom(i * 37)
            self.assertTrue(mc_sig._verify_pure(pub, msg, key.sign(msg)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
