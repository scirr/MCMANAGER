#!/usr/bin/env python3
"""
build_release.py — Generates MCManager-FR.zip and MCManager.zip

Run from the Windows/ directory:
    python build_release.py

Both ZIPs are written to the repo root (one level up).
"""
import os
import re
import shutil
import zipfile
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
DIST_DIR = os.path.join(HERE, "..", "dist")

# Files included in both releases (language-neutral or handled via mc_lang.py)
PYTHON_FILES = [
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
]

def set_lang(lang_file, lang):
    """Patch _LANG = "xx" in mc_lang.py inside a temp dir."""
    with open(lang_file, "r", encoding="utf-8") as f:
        content = f.read()
    patched = re.sub(r'^_LANG\s*=\s*["\'].*?["\']', f'_LANG = "{lang}"', content, flags=re.MULTILINE)
    with open(lang_file, "w", encoding="utf-8") as f:
        f.write(patched)

def build_zip(lang, zip_name, install_bat_src, uninstall_bat_src, webhook_src):
    print(f"Building {zip_name} (lang={lang})...")
    os.makedirs(DIST_DIR, exist_ok=True)
    zip_path = os.path.join(DIST_DIR, zip_name)

    with tempfile.TemporaryDirectory() as tmp:
        pkg = os.path.join(tmp, "MCManager")
        os.makedirs(pkg)

        # Python files
        for fname in PYTHON_FILES:
            shutil.copy2(os.path.join(HERE, fname), os.path.join(pkg, fname))

        # Patch language in the copy
        set_lang(os.path.join(pkg, "mc_lang.py"), lang)

        # Language-specific files — always named install.bat / uninstall.bat / webhook_templates.json
        shutil.copy2(install_bat_src,   os.path.join(pkg, "install.bat"))
        shutil.copy2(uninstall_bat_src, os.path.join(pkg, "uninstall.bat"))
        shutil.copy2(webhook_src,       os.path.join(pkg, "webhook_templates.json"))

        # Pack into ZIP (MCManager/ subfolder inside the archive)
        if os.path.exists(zip_path):
            os.remove(zip_path)
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(pkg):
                for file in files:
                    filepath = os.path.join(root, file)
                    arcname = os.path.join("MCManager", os.path.relpath(filepath, pkg))
                    zf.write(filepath, arcname)

    size_kb = os.path.getsize(zip_path) // 1024
    print(f"  -> {zip_path} ({size_kb} KB)")

def main():
    # FR release
    build_zip(
        lang="fr",
        zip_name="MCManager-FR.zip",
        install_bat_src=os.path.join(HERE, "install.bat"),
        uninstall_bat_src=os.path.join(HERE, "uninstall.bat"),
        webhook_src=os.path.join(HERE, "webhook_templates.json"),
    )

    # EN release
    build_zip(
        lang="en",
        zip_name="MCManager.zip",
        install_bat_src=os.path.join(HERE, "install_en.bat"),
        uninstall_bat_src=os.path.join(HERE, "uninstall_en.bat"),
        webhook_src=os.path.join(HERE, "webhook_templates_en.json"),
    )

    print("\nDone. ZIPs are in dist/")

if __name__ == "__main__":
    main()
