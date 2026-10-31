#!/usr/bin/env python3
"""
build_installer.py — Builds MCManager-Setup.exe (Inno Setup) for Windows.

    python packaging/windows/build_installer.py --zip dist/MCManager.zip --app build/app [--out dist]

Inputs:
  --zip  the Windows package (MCManager.zip): the core and the service installer;
  --app  the published desktop app (self-contained, x64).

The installer carries the Python embeddable package, whose version and SHA-256
are pinned here: it does not depend on any Python installed on the machine. The
installer scripts of the zip (install.bat, uninstall.bat) are replaced by the
installer itself. Servers and worlds live outside the installation folder
(%ProgramData%\\MCManager) and are never part of the installer or touched by
the uninstaller.

The installer is signed with Authenticode only when WINDOWS_CERT_PFX (base64)
and WINDOWS_CERT_PASSWORD are set.
"""
import argparse
import base64
import glob
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
SCRIPT = os.path.join(HERE, "MCManager.iss")

PYTHON_VERSION = "3.12.10"
PYTHON_URL = f"https://www.python.org/ftp/python/{PYTHON_VERSION}/python-{PYTHON_VERSION}-embed-amd64.zip"
PYTHON_SHA256 = "4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3"

NOT_INSTALLED = {"install.bat", "uninstall.bat"}
ISCC_DEFAULTS = (
    r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    r"C:\Program Files\Inno Setup 6\ISCC.exe",
)


def read_version():
    with open(os.path.join(ROOT, "core", "mc_lang.py"), encoding="utf-8") as f:
        match = re.search(r'^VERSION = "([^"]+)"$', f.read(), re.M)
    if not match:
        raise RuntimeError("VERSION not found in core/mc_lang.py")
    return match.group(1)


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def fetch_python(cache_dir, url=PYTHON_URL, expected=PYTHON_SHA256):
    os.makedirs(cache_dir, exist_ok=True)
    target = os.path.join(cache_dir, os.path.basename(url))
    if not (os.path.exists(target) and sha256_of(target) == expected):
        with urllib.request.urlopen(url, timeout=120) as response, open(target, "wb") as out:  # nosec B310 - pinned https URL
            shutil.copyfileobj(response, out)
    got = sha256_of(target)
    if got != expected:
        os.remove(target)
        raise ValueError(f"Python embeddable package: checksum mismatch (got {got}, expected {expected})")
    return target


def path_file_text(stdlib_zip):
    """The embeddable Python ignores PYTHONPATH and the script folder: its
    ._pth file lists every folder the core may be imported from."""
    return f"{stdlib_zip}\n.\n..\\core\n"


def stage_python(archive, dest):
    os.makedirs(dest, exist_ok=True)
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(dest)
    pth = glob.glob(os.path.join(dest, "python*._pth"))
    if len(pth) != 1:
        raise RuntimeError("python*._pth not found in the embeddable package")
    stdlib = os.path.basename(pth[0])[: -len("._pth")] + ".zip"
    with open(pth[0], "w", encoding="ascii", newline="\r\n") as f:
        f.write(path_file_text(stdlib))


def stage_core(zip_path, dest):
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.namelist():
            parts = member.split("/")
            if member.startswith("/") or ".." in parts or len(parts) != 2 or not parts[1]:
                continue
            if parts[1] in NOT_INSTALLED:
                continue
            os.makedirs(dest, exist_ok=True)
            with open(os.path.join(dest, parts[1]), "wb") as f:
                f.write(zf.read(member))


def stage(zip_path, app_dir, stage_dir, python_archive):
    if os.path.exists(stage_dir):
        shutil.rmtree(stage_dir)
    stage_python(python_archive, os.path.join(stage_dir, "python"))
    stage_core(zip_path, os.path.join(stage_dir, "core"))
    if not os.path.isfile(os.path.join(app_dir, "MCManager.exe")):
        raise FileNotFoundError(f"{app_dir}: MCManager.exe not found (publish the app first)")
    shutil.copytree(app_dir, os.path.join(stage_dir, "app"))
    return stage_dir


def find_iscc():
    found = shutil.which("ISCC") or shutil.which("iscc")
    if found:
        return found
    for candidate in ISCC_DEFAULTS:
        if os.path.exists(candidate):
            return candidate
    return None


def iscc_command(iscc, version, stage_dir, out_dir):
    return [iscc, "/Qp", f"/DAppVersion={version}", f"/DStageDir={stage_dir}", f"/DOutDir={out_dir}", SCRIPT]


def sign_installer(path, env=None):
    env = os.environ if env is None else env
    pfx = env.get("WINDOWS_CERT_PFX", "").strip()
    if not pfx:
        print("No certificate: the installer is not signed")
        return False
    password = env.get("WINDOWS_CERT_PASSWORD", "")
    signtool = shutil.which("signtool")
    if not signtool:
        kits = sorted(glob.glob(r"C:\Program Files (x86)\Windows Kits\10\bin\*\x64\signtool.exe"))
        signtool = kits[-1] if kits else None
    if not signtool:
        raise RuntimeError("signtool not found")
    with tempfile.TemporaryDirectory() as tmp:
        pfx_path = os.path.join(tmp, "cert.pfx")
        with open(pfx_path, "wb") as f:
            f.write(base64.b64decode(pfx))
        subprocess.run(
            [signtool, "sign", "/fd", "SHA256", "/f", pfx_path, "/p", password,
             "/tr", "http://timestamp.digicert.com", "/td", "SHA256", path],
            check=True,
        )
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build the MC Manager Windows installer")
    parser.add_argument("--zip", required=True, help="MCManager.zip")
    parser.add_argument("--app", required=True, help="published app folder (contains MCManager.exe)")
    parser.add_argument("--out", default=os.path.join(ROOT, "dist"))
    parser.add_argument("--work", help="working folder (default: a temporary one)")
    parser.add_argument("--stage-only", action="store_true", help="prepare the files, do not compile")
    args = parser.parse_args(argv)

    out_dir = os.path.abspath(args.out)
    os.makedirs(out_dir, exist_ok=True)
    version = read_version()
    work = os.path.abspath(args.work) if args.work else tempfile.mkdtemp(prefix="mcsetup-")
    archive = fetch_python(os.path.join(work, "cache"))
    stage_dir = stage(os.path.abspath(args.zip), os.path.abspath(args.app), os.path.join(work, "stage"), archive)
    if args.stage_only:
        print(stage_dir)
        return 0
    iscc = find_iscc()
    if not iscc:
        print("ISCC.exe (Inno Setup 6) not found", file=sys.stderr)
        return 1
    subprocess.run(iscc_command(iscc, version, stage_dir, out_dir), check=True)  # nosec B603
    installer = os.path.join(out_dir, "MCManager-Setup.exe")
    if not os.path.isfile(installer):
        print("MCManager-Setup.exe was not produced", file=sys.stderr)
        return 1
    sign_installer(installer)
    print(installer)
    return 0


if __name__ == "__main__":
    sys.exit(main())
