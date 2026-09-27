# Releasing MC Manager

Maintainer procedure. Users receive a release through `mc update`, which
installs the **latest GitHub release** only after verifying its signature.

Releases are built, signed and published by GitHub Actions
(`.github/workflows/release.yml`). Every release is kept; the newest one is
marked *latest*.

## Quick path

1. Bump `VERSION` in both `mc_lang.py` files and add `release-notes/vX.Y.Z.md`
   (steps 1 and 2 below), merged into `main`.
2. **Actions → Release → Run workflow** (branch `main`).

That is all: the workflow reads the version, tests, builds, signs, then
creates the tag on `main` and publishes. It refuses if the tag already
exists; a failed run creates nothing and can simply be run again.

---

## One-time setup

The release signing key is an Ed25519 key pair:

- the **public key** is embedded in `Linux/mc_update.py` and
  `Windows/mc_update.py` (`RELEASE_PUBLIC_KEY`, identical in both);
- the **private key** exists only as the repository secret
  `RELEASE_SIGNING_KEY` (Settings → Secrets and variables → Actions →
  New repository secret), 64 hexadecimal characters. It is never committed
  and never stored on a user's machine.

To replace the key pair (lost or leaked private key):

```bash
pip install cryptography
python tools/sign_release.py --generate
```

Put the printed public key in both `mc_update.py` files and the private key
in the secret. Installations that still carry the old public key refuse
updates signed with the new one: they must be updated once by hand
(download the release ZIP and run the installer).

---

## Publishing a version

### 1. Bump the version — same value in both files

| File | Field | Example |
|---|---|---|
| `Windows/mc_lang.py` | `VERSION` | `"2.7.0"` |
| `Linux/mc_lang.py` | `VERSION` | `"2.7.0"` |

Bug fix → bump the last digit. New feature → bump the middle one.

### 2. Write the release notes

In `release-notes/vX.Y.Z.md`, following the previous files: what is fixed,
improved or deprecated, the behaviour changes, and **what updating requires**
(`mc update` alone, or `sudo ./install.sh` when the systemd unit or the
installer changed). The file becomes the release description as is.

### 3. Test locally

```bash
cd Linux && python3 -m unittest discover tests
cd ../Windows && python -m unittest discover tests
```

CI runs the same suites on Linux and Windows, plus `ruff`, `bandit` and
`pip-audit`, on every push.

### 4. Publish

**Actions → Release → Run workflow**, on `main`. The workflow creates the
tag `vX.Y.Z` on `main`'s current commit at the very end, only if every step
succeeded (and refuses to start if the tag already exists).

Alternative, from a terminal:

```bash
git tag v2.7.0
git push origin v2.7.0
```

Either way, the release workflow:

1. checks that the tag, both `VERSION` values and `release-notes/<tag>.md` agree;
2. runs the Linux and Windows test suites;
3. builds `MCManager.zip` and `MCManager-Linux.zip`;
4. writes `SHA256SUMS` and signs it (`SHA256SUMS.sig`) with `RELEASE_SIGNING_KEY`,
   after checking the key matches the public key in the code;
5. records a build provenance attestation;
6. publishes the release with the notes, marked *latest* (when run by hand,
   this step creates the tag).

A failure at any step publishes nothing.

---

## The rules that matter

**The tag and both `VERSION` values must describe the same version.** The
workflow refuses to publish otherwise. `mc update` compares the release tag
with the installed `VERSION`: a mismatch would announce an update forever.

**Never publish unsigned packages.** `mc update` refuses a release without
`SHA256SUMS` and `SHA256SUMS.sig`, or whose signature or hashes do not match.

**Changes to the systemd unit or to `install.sh`** are not applied by
`mc update`, which only replaces program files. Say in the release notes that
Linux users must re-run `sudo ./install.sh`. `mc update` and `mc doctor` also
detect an outdated unit.

---

## Pushing without releasing

Commits without a tag are tested by CI but notify nobody and touch no release.

---

## Troubleshooting

| Symptom | Cause |
|---|---|
| Workflow: `VERSION is X, the release is vY` | Bump both `mc_lang.py` files (and, for a pushed tag, move it: `git tag -f`, `git push -f origin vY`). |
| Workflow: `vY already exists` | That version is published: bump `VERSION` first. |
| Workflow: `Run this workflow on main` | Pick `main` in the *Run workflow* branch menu. |
| Workflow: `release-notes/vY.md is missing` | Add the notes file to `main`. |
| Workflow: `RELEASE_SIGNING_KEY is missing` | The repository secret is not set. |
| Workflow: `does not match the public key embedded in the code` | The secret and `RELEASE_PUBLIC_KEY` come from different key pairs. |
| Users: "Invalid signature" / "does not match its hash" | The release assets were replaced by hand. Delete the release and its tag, then run the workflow again. |
| Users are told about an update they already have | `VERSION` was not bumped with the tag. |
