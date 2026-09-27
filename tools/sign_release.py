#!/usr/bin/env python3
"""
sign_release.py — Write SHA256SUMS and SHA256SUMS.sig for a release.

    python tools/sign_release.py dist        # sign every .zip in dist/
    python tools/sign_release.py --generate  # create a new key pair

The Ed25519 private key comes from the RELEASE_SIGNING_KEY environment
variable (64 hex characters). It is only ever set in CI, from a GitHub
secret. Before signing, the script checks that the key matches the public
key embedded in both builds: a mismatch would publish updates that every
installation refuses.
"""
import hashlib
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "Linux"))

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import mc_sig


def _raw_public(key):
    return key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def embedded_public_keys():
    keys = set()
    for platform in ("Linux", "Windows"):
        with open(os.path.join(ROOT, platform, "mc_update.py"), encoding="utf-8") as f:
            m = re.search(r'RELEASE_PUBLIC_KEY = bytes\.fromhex\("([0-9a-f]{64})"\)', f.read())
        if not m:
            sys.exit(f"{platform}/mc_update.py: RELEASE_PUBLIC_KEY not found")
        keys.add(m.group(1))
    if len(keys) != 1:
        sys.exit("Linux and Windows embed different release public keys")
    return keys.pop()


def generate():
    key = Ed25519PrivateKey.generate()
    seed = key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                             serialization.NoEncryption())
    print("Public key (RELEASE_PUBLIC_KEY in Linux/ and Windows/mc_update.py):")
    print(_raw_public(key).hex())
    print("Private key (GitHub secret RELEASE_SIGNING_KEY, never commit it):")
    print(seed.hex())


def sign(dist):
    secret = os.environ.get("RELEASE_SIGNING_KEY", "").strip()
    if not re.fullmatch(r"[0-9a-fA-F]{64}", secret):
        sys.exit("RELEASE_SIGNING_KEY is missing or is not 64 hex characters")
    key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(secret))
    public = _raw_public(key)
    if public.hex() != embedded_public_keys():
        sys.exit("RELEASE_SIGNING_KEY does not match the public key embedded in the code")

    packages = sorted(f for f in os.listdir(dist) if f.endswith(".zip"))
    if not packages:
        sys.exit(f"no .zip in {dist}")
    lines = []
    for name in packages:
        with open(os.path.join(dist, name), "rb") as f:
            lines.append(f"{hashlib.sha256(f.read()).hexdigest()}  {name}\n")
    sums = "".join(lines).encode()
    signature = key.sign(sums)
    if not mc_sig.verify(public, sums, signature) or not mc_sig._verify_pure(public, sums, signature):
        sys.exit("signature self-check failed")

    with open(os.path.join(dist, "SHA256SUMS"), "wb") as f:
        f.write(sums)
    with open(os.path.join(dist, "SHA256SUMS.sig"), "wb") as f:
        f.write(signature)
    sys.stdout.write(sums.decode())
    print("Signed with", public.hex())


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--generate":
        generate()
    elif len(sys.argv) == 2:
        sign(sys.argv[1])
    else:
        sys.exit(__doc__)
