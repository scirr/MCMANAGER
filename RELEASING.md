# Releasing MC Manager

Maintainer procedure for publishing a new version. Users receive it through
`mc update`, which reads the **latest GitHub release**.

Only one release exists at a time: publishing a new one deletes the previous
releases and their tags, so `latest` is never ambiguous.

---

## Prerequisites

**`create_release.ps1`** — the publishing script. It is deliberately **not in
this repository** (maintainer-only tooling, and it once carried a token). It
lives in the working copy root, `D:\Code\MCMANAGER\create_release.ps1`.
**Keep a backup outside the repo** — losing it means rewriting it.

**A GitHub token** — Settings → Developer settings → Personal access tokens.
Scope `repo` (classic) or *Contents: Read and write* (fine-grained). Set it once
and forget it:

```powershell
[Environment]::SetEnvironmentVariable("GITHUB_TOKEN", "<your-token>", "User")
```

Reopen the terminal afterwards. Never hardcode the token in the script.

---

## Steps

### 1. Bump the version — in three places, same value

| File | Field | Example |
|---|---|---|
| `Windows/mc_lang.py` | `VERSION` | `"2.4.8"` |
| `Linux/mc_lang.py` | `VERSION` | `"2.4.8"` (identical) |
| `create_release.ps1` | `$tag` | `"v2.4.8"` (`v` prefix) |

Bug fix → bump the last digit. New feature → bump the middle one.

### 1b. Write the release notes

In `release-notes/vX.Y.Z.md`, following the previous files: what is fixed,
improved or deprecated, the behaviour changes, and **what updating requires**
(`mc update` alone, or `sudo ./install.sh` when the systemd unit changed).
Keep it ASCII-only: it becomes `$bodyText` in `create_release.ps1`.

### 2. Test

```powershell
cd Windows
python -m unittest discover tests/
```

Everything must pass. The Linux suite runs the same way from `Linux/`, though
its POSIX path tests only pass on Linux.

### 3. Build both packages

```powershell
cd Windows ; python build_release.py
cd ..\Linux ; python build_release.py
```

Produces `dist/MCManager.zip` and `dist/MCManager-Linux.zip`. Both are
bilingual — there is one package per platform, not per language.

### 4. Commit and push

```powershell
cd ..
git add -A
git commit -m "fix(scope): what changed and why"
git push origin main
```

### 5. Tag

```powershell
git tag v2.4.8
git push origin v2.4.8
```

### 6. Publish

```powershell
.\create_release.ps1
```

The script deletes every existing release and tag, creates the new release from
`$tag`, and uploads the two ZIPs. Expected output ends with `Done.`

---

## The one rule that matters

**`VERSION` and `$tag` must describe the same version.**

`mc update` compares the release tag against the `VERSION` compiled into the
package. If the tag is bumped but `mc_lang.py` is not, users download the update,
still report the old version, and are told *again* that an update is available —
**a notification loop with no way out**. Both `mc_lang.py` files must also stay
identical to each other.

---

## Pushing without releasing

For documentation or work in progress, step 4 alone is enough. No version bump,
no build, no tag: nobody is notified and no release is touched.

---

## Troubleshooting

| Symptom | Cause |
|---|---|
| `GITHUB_TOKEN environment variable is not set` | Token missing from the environment; reopen the terminal after setting it. |
| `401 Unauthorized` | Token expired or lacking the `repo` / Contents:write scope. |
| Users are told about an update they already have | `VERSION` was not bumped along with `$tag`. Fix `mc_lang.py`, rebuild, republish. |
| Garbled characters in the release notes | The script is read as ANSI, not UTF-8. Keep `$bodyText` ASCII-only. |
| `Skipping missing asset` | `build_release.py` was not run, or was run before the version bump. |

**Changes to the systemd unit** (`_service_unit_content` in `Linux/mc_config.py`)
are not applied by `mc update`, which only replaces program files. Such a release
must tell Linux users to re-run `sudo ./install.sh`.
