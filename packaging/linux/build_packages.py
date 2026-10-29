#!/usr/bin/env python3
"""
build_packages.py — Builds the .deb and .rpm packages of MC Manager.

    python3 packaging/linux/build_packages.py [--out dist] [--zip MCManager-Linux.zip] [--only deb|rpm]

The content comes from MCManager-Linux.zip (built by Linux/build_release.py when
--zip is not given). The application goes to /opt/mcmanager, the command to
/usr/bin/mc. No user data is ever part of a package: servers, worlds and the
registry are created later, next to the application or in the user's home.

The systemd unit is rendered by platform_linux, the same code that writes it for
a zip install. Its User= is a placeholder: `mcmanager-setup <user>` installs the
real unit (and the polkit rule) for the chosen user through that same code.
"""
import argparse
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
CORE_DIR = os.path.join(ROOT, "core")
LINUX_DIR = os.path.join(ROOT, "Linux")

NAME = "mcmanager"
APP_DIR = "/opt/mcmanager"
PYTHON = "/usr/bin/python3"
USER_PLACEHOLDER = "__MC_USER__"
UNIT_NAME = "mc_manager.service"
MAINTAINER = "Cris <crisfrtith@gmail.com>"
HOMEPAGE = "https://github.com/scirr/MCMANAGER"
SUMMARY = "Minecraft server manager with a background daemon"
DESCRIPTION = (
    "MC Manager deploys, supervises, backs up and updates Minecraft servers\n"
    "from the command line, with a systemd daemon that keeps them running.\n"
    "Java is not required by the package: MC Manager installs one per server.\n"
    "After installing, run: sudo mcmanager-setup"
)
NOT_SHIPPED = {"install.sh", "uninstall.sh"}
APP_ID = "io.github.scirr.MCManager"
APP_COMMAND = "mcmanager-app"
APP_DATA_DIRS = {
    f"{APP_ID}.desktop": "usr/share/applications",
    f"{APP_ID}.metainfo.xml": "usr/share/metainfo",
    f"{APP_ID}.svg": "usr/share/icons/hicolor/scalable/apps",
}
RECOMMENDS = {
    "deb": ["python3-pil", "python3-gi", "gir1.2-gtk-4.0", "gir1.2-adw-1"],
    "rpm": ["python3-pillow", "python3-gobject", "gtk4", "libadwaita"],
}
EXECUTABLE_APP_FILES = {"mc_cli.py", "mc_daemon.py"}

UNIT_DIRS = {"deb": "/lib/systemd/system", "rpm": "/usr/lib/systemd/system"}
MARKERS = {"deb": "apt", "rpm": "dnf"}

LOCAL_UNIT = f"/etc/systemd/system/{UNIT_NAME}"
POLKIT_RULE = "/etc/polkit-1/rules.d/50-mc-manager.rules"

COMMAND_SCRIPT = f"""#!/bin/sh
exec {PYTHON} {APP_DIR}/mc_cli.py "$@"
"""

APP_COMMAND_SCRIPT = f"""#!/bin/sh
PYTHONPATH={APP_DIR}/app${{PYTHONPATH:+:$PYTHONPATH}} exec {PYTHON} -m mcmanager_app "$@"
"""

SETUP_SCRIPT = f"""#!/bin/sh
# Installs the MC Manager service for the user who manages the servers.
set -e
APP={APP_DIR}
if [ "$(id -u)" -ne 0 ]; then
    echo "Run as root: sudo mcmanager-setup [user]" >&2
    exit 1
fi
USER_NAME="${{1:-${{SUDO_USER:-}}}}"
if [ -z "$USER_NAME" ]; then
    echo "Usage: sudo mcmanager-setup <user>" >&2
    exit 1
fi
if ! id "$USER_NAME" >/dev/null 2>&1; then
    echo "Unknown user: $USER_NAME" >&2
    exit 1
fi
chown -R "$USER_NAME:" "$APP"
cd "$APP"
{PYTHON} -c 'import sys, mc_config; mc_config.install_daemon_service(sys.argv[1])' "$USER_NAME"
chown -R "$USER_NAME:" "$APP"
echo "Done. Open a new terminal and type: mc deploy"
"""

_RELOAD = """if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
    systemctl daemon-reload || true
fi"""

_POST_BODY = f"""if [ -f {LOCAL_UNIT} ]; then
    SERVICE_USER=$(sed -n 's/^User=//p' {LOCAL_UNIT} | head -n 1)
    if [ -n "$SERVICE_USER" ] && [ "$SERVICE_USER" != root ] && id "$SERVICE_USER" >/dev/null 2>&1; then
        chown -R "$SERVICE_USER:" {APP_DIR}
    fi
fi
{_RELOAD}
if [ -f {LOCAL_UNIT} ]; then
    if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
        systemctl try-restart mc_manager || true
    fi
else
    echo "MC Manager is installed. Choose the user who manages the servers: sudo mcmanager-setup"
fi"""

_STOP_BODY = """if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
    systemctl stop mc_manager || true
    systemctl disable mc_manager || true
fi"""

_PURGE_BODY = f"""rm -f {LOCAL_UNIT} {POLKIT_RULE}
{_RELOAD}"""


def read_version():
    with open(os.path.join(CORE_DIR, "mc_lang.py"), encoding="utf-8") as f:
        match = re.search(r'^VERSION = "([^"]+)"$', f.read(), re.M)
    if not match:
        raise RuntimeError("VERSION not found in core/mc_lang.py")
    return match.group(1)


def deb_scripts():
    sh = "#!/bin/sh\nset -e\n"
    return {
        "postinst": f'{sh}if [ "$1" = configure ]; then\n{_POST_BODY}\nfi\nexit 0\n',
        "prerm": f'{sh}case "$1" in\n    remove|deconfigure)\n{_STOP_BODY}\n        ;;\nesac\nexit 0\n',
        "postrm": (
            f'{sh}case "$1" in\n    remove|purge)\n        rm -rf {APP_DIR}/__pycache__\n        ;;\nesac\n'
            f'if [ "$1" = purge ]; then\n{_PURGE_BODY}\nelse\n{_RELOAD}\nfi\nexit 0\n'
        ),
    }


def rpm_scripts():
    return {
        "post": _POST_BODY,
        "preun": f"if [ \"$1\" -eq 0 ]; then\n{_STOP_BODY}\nfi",
        "postun": f"if [ \"$1\" -eq 0 ]; then\nrm -rf {APP_DIR}/__pycache__\n{_PURGE_BODY}\nfi",
    }


def render_unit():
    sys.path.insert(0, CORE_DIR)
    import platform_linux
    saved = (platform_linux.BASE_DIR, sys.executable, os.environ.pop("MCMANAGER_DATA_DIR", None))
    platform_linux.BASE_DIR = APP_DIR
    sys.executable = PYTHON
    try:
        return platform_linux._service_unit_content(USER_PLACEHOLDER)
    finally:
        platform_linux.BASE_DIR, sys.executable = saved[0], saved[1]
        if saved[2] is not None:
            os.environ["MCMANAGER_DATA_DIR"] = saved[2]


def build_app_zip(out_dir):
    sys.path.insert(0, LINUX_DIR)
    import build_release
    build_release.build_zip(dist_dir=out_dir)
    return os.path.join(out_dir, "MCManager-Linux.zip")


def _write(path, data, mode):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if isinstance(data, str):
        data = data.encode("utf-8")
    with open(path, "wb") as f:
        f.write(data)
    os.chmod(path, mode)


def stage_tree(stage, zip_path, kind):
    """Lays out the files of the package under `stage` (as the target root)."""
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.namelist():
            parts = member.split("/")
            if member.startswith("/") or ".." in parts or not parts[-1]:
                continue
            if len(parts) == 2:
                if parts[1] in NOT_SHIPPED:
                    continue
                mode = 0o755 if parts[1] in EXECUTABLE_APP_FILES else 0o644
                _write(os.path.join(stage, APP_DIR.lstrip("/"), parts[1]), zf.read(member), mode)
            elif len(parts) >= 4 and parts[1] == "app" and parts[2] == "mcmanager_app":
                _write(os.path.join(stage, APP_DIR.lstrip("/"), *parts[1:]), zf.read(member), 0o644)
            elif len(parts) == 4 and parts[1:3] == ["app", "data"] and parts[3] in APP_DATA_DIRS:
                _write(os.path.join(stage, APP_DATA_DIRS[parts[3]], parts[3]), zf.read(member), 0o644)
    _write(os.path.join(stage, APP_DIR.lstrip("/"), "installed-by-package"), MARKERS[kind] + "\n", 0o644)
    _write(os.path.join(stage, "usr/bin/mc"), COMMAND_SCRIPT, 0o755)
    _write(os.path.join(stage, "usr/bin", APP_COMMAND), APP_COMMAND_SCRIPT, 0o755)
    _write(os.path.join(stage, "usr/sbin/mcmanager-setup"), SETUP_SCRIPT, 0o755)
    _write(os.path.join(stage, UNIT_DIRS[kind].lstrip("/"), UNIT_NAME), render_unit(), 0o644)
    os.chmod(stage, 0o755)  # nosec B103 - package directories are world-readable by design
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    for base, dirs, files in os.walk(stage):
        for entry in dirs:
            os.chmod(os.path.join(base, entry), 0o755)  # nosec B103 - package directories are world-readable by design
        if epoch:
            for entry in dirs + files:
                os.utime(os.path.join(base, entry), (int(epoch), int(epoch)))


def staged_files(stage):
    found = []
    for base, _dirs, files in os.walk(stage):
        for fname in files:
            full = os.path.join(base, fname)
            found.append(("/" + os.path.relpath(full, stage), stat.S_IMODE(os.stat(full).st_mode)))
    return sorted(found)


def installed_size_kib(stage):
    total = sum(os.path.getsize(os.path.join(b, f)) for b, _d, fs in os.walk(stage) for f in fs)
    return max(1, (total + 1023) // 1024)


def control_text(version, size_kib):
    description = "\n".join(
        (" " + line) if line else " ." for line in DESCRIPTION.splitlines()
    )
    return (
        f"Package: {NAME}\n"
        f"Version: {version}\n"
        "Architecture: all\n"
        f"Maintainer: {MAINTAINER}\n"
        f"Installed-Size: {size_kib}\n"
        "Depends: python3 (>= 3.10)\n"
        f"Recommends: {', '.join(RECOMMENDS['deb'])}\n"
        "Section: utils\n"
        "Priority: optional\n"
        f"Homepage: {HOMEPAGE}\n"
        f"Description: {SUMMARY}\n"
        f"{description}\n"
    )


def build_deb(zip_path, out_dir, version):
    out = os.path.join(out_dir, f"{NAME}_{version}_all.deb")
    with tempfile.TemporaryDirectory() as tmp:
        stage = os.path.join(tmp, "root")
        stage_tree(stage, zip_path, "deb")
        debian = os.path.join(stage, "DEBIAN")
        _write(os.path.join(debian, "control"), control_text(version, installed_size_kib(stage)), 0o644)
        for name, body in deb_scripts().items():
            _write(os.path.join(debian, name), body, 0o755)
        os.chmod(debian, 0o755)  # nosec B103 - package directories are world-readable by design
        if os.path.exists(out):
            os.remove(out)
        subprocess.run(["dpkg-deb", "--build", "--root-owner-group", stage, out], check=True)
    return out


def spec_text(version, stage_files, stagedir="%{_stagedir}"):
    scripts = rpm_scripts()
    files = "\n".join(f'%attr({mode:04o},root,root) "{path}"' for path, mode in stage_files)
    app_dirs = set()
    for path, _mode in stage_files:
        folder = os.path.dirname(path)
        while path.startswith(APP_DIR + "/") and folder != APP_DIR:
            app_dirs.add(folder)
            folder = os.path.dirname(folder)
    app_dirs = sorted(app_dirs)
    files = "\n".join([f"%dir %attr(0755,root,root) {d}" for d in app_dirs] + [files])
    changelog_date = time.strftime("%a %b %d %Y", time.gmtime())
    return f"""%global debug_package %{{nil}}
%global __os_install_post %{{nil}}
%define _build_id_links none

Name:           {NAME}
Version:        {version}
Release:        1
Summary:        {SUMMARY}
License:        MPL-2.0
URL:            {HOMEPAGE}
BuildArch:      noarch
AutoReqProv:    no
Requires:       python3 >= 3.10
Recommends:     {", ".join(RECOMMENDS["rpm"])}

%description
{DESCRIPTION}

%install
mkdir -p %{{buildroot}}
cp -a {stagedir}/. %{{buildroot}}/

%post
{scripts["post"]}

%preun
{scripts["preun"]}

%postun
{scripts["postun"]}

%files
%dir %attr(0755,root,root) {APP_DIR}
{files}

%changelog
* {changelog_date} {MAINTAINER} - {version}-1
- Package build
"""


def build_rpm(zip_path, out_dir, version):
    with tempfile.TemporaryDirectory() as tmp:
        stage = os.path.join(tmp, "stage")
        stage_tree(stage, zip_path, "rpm")
        top = os.path.join(tmp, "rpmbuild")
        os.makedirs(os.path.join(top, "SPECS"))
        spec = os.path.join(top, "SPECS", f"{NAME}.spec")
        _write(spec, spec_text(version, staged_files(stage)), 0o644)
        subprocess.run(
            ["rpmbuild", "-bb", "--define", f"_topdir {top}", "--define", f"_stagedir {stage}", spec],
            check=True,
        )
        built = os.path.join(top, "RPMS", "noarch", f"{NAME}-{version}-1.noarch.rpm")
        out = os.path.join(out_dir, os.path.basename(built))
        shutil.copy2(built, out)
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build the MC Manager .deb and .rpm packages")
    parser.add_argument("--out", default=os.path.join(ROOT, "dist"))
    parser.add_argument("--zip", help="use this MCManager-Linux.zip instead of building one")
    parser.add_argument("--only", choices=["deb", "rpm"])
    args = parser.parse_args(argv)

    out_dir = os.path.abspath(args.out)
    os.makedirs(out_dir, exist_ok=True)
    version = read_version()
    zip_path = args.zip or build_app_zip(out_dir)

    built = []
    if args.only in (None, "deb"):
        if not shutil.which("dpkg-deb"):
            print("dpkg-deb not found", file=sys.stderr)
            return 1
        built.append(build_deb(zip_path, out_dir, version))
    if args.only in (None, "rpm"):
        if shutil.which("rpmbuild"):
            built.append(build_rpm(zip_path, out_dir, version))
        elif args.only == "rpm":
            print("rpmbuild not found", file=sys.stderr)
            return 1
        else:
            print("rpmbuild not found: .rpm skipped")
    for path in built:
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
