#!/usr/bin/env python3
"""
build_release.py — Generates MCManager-Linux.zip

Run from the Linux/ directory:
    python3 build_release.py

Shared modules come from ../core, the installer scripts from this folder.

The package is bilingual (FR/EN): the language is chosen at first launch and can
be changed anytime with `mc language fr|en`. A single ZIP is produced.
The ZIP is written to the repo root dist/ folder (one level up).
"""
import os
import shutil
import zipfile
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
DIST_DIR = os.path.join(HERE, "..", "dist")
CORE_DIR = os.path.join(HERE, "..", "core")
API_DIR = os.path.join(HERE, "..", "api")

# Files shipped in the package. language.txt is intentionally NOT shipped so the
# first launch prompts for the language.
PACKAGE_FILES = [
    "mc_cli.py",
    "mc_core.py",
    "mc_config.py",
    "mc_servers.py",
    "mc_deploy.py",
    "mc_daemon.py",
    "mc_setup.py",
    "mc_firewall.py",
    "mc_doctor.py",
    "mc_image.py",
    "mc_lang.py",
    "mc_validate.py",
    "mc_update.py",
    "mc_sig.py",
    "mc_api.py",
    "mc_ipc.py",
    "mc_protocol.py",
    "mc_proxy.py",
    "mc_router.py",
    "mc_sleep.py",
    "mc_content.py",
    "mc_http.py",
    "mc_java.py",
    "mc_software.py",
    "mc_modsources.py",
    "mc_modpack.py",
    "mc_crash.py",
    "mc_players.py",
    "mc_world.py",
    "mc_task.py",
    "mc_s3.py",
    "mc_backup.py",
    "mc_alert.py",
    "mc_metrics.py",
    "mc_statuspage.py",
    "mc_httpapi.py",
    "mc_apiops.py",
    "mc_jobs.py",
    "mc_remote.py",
    "mc_remoteserver.py",
    "mc_remoteclient.py",
    "openapi.json",
    "mc_platform.py",
    "platform_linux.py",
    "install.sh",
    "uninstall.sh",
    "webhook_templates.json",
    "requirements.txt",
]

def source_path(fname):
    for folder in (HERE, CORE_DIR, API_DIR):
        path = os.path.join(folder, fname)
        if os.path.exists(path):
            return path
    return os.path.join(CORE_DIR, fname)


def build_zip(zip_name="MCManager-Linux.zip", dist_dir=DIST_DIR):
    print(f"Building {zip_name} (bilingual FR/EN)...")
    os.makedirs(dist_dir, exist_ok=True)
    zip_path = os.path.join(dist_dir, zip_name)

    with tempfile.TemporaryDirectory() as tmp:
        pkg = os.path.join(tmp, "MCManager")
        os.makedirs(pkg)

        for fname in PACKAGE_FILES:
            shutil.copy2(source_path(fname), os.path.join(pkg, fname))

        if os.path.exists(zip_path):
            os.remove(zip_path)
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(pkg):
                for file in files:
                    filepath = os.path.join(root, file)
                    arcname = os.path.join("MCManager", os.path.relpath(filepath, pkg))
                    info = zipfile.ZipInfo.from_file(filepath, arcname)
                    # Keep shell scripts executable when extracted
                    if file.endswith(".sh"):
                        info.external_attr = 0o755 << 16
                    with open(filepath, "rb") as src:
                        zf.writestr(info, src.read(), zipfile.ZIP_DEFLATED)

    size_kb = os.path.getsize(zip_path) // 1024
    print(f"  -> {zip_path} ({size_kb} KB)")

def main():
    build_zip()
    print("\nDone. ZIP is in dist/")

if __name__ == "__main__":
    main()
