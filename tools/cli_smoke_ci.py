#!/usr/bin/env python3
"""Run a few CLI commands in a throw-away data folder and report any that
crash, with their stderr, as GitHub Actions annotations."""
import os
import subprocess
import sys
import tempfile

COMMANDS = (["version"], ["status", "--json"], ["java", "list", "--json"], ["api", "status"],
            ["alert", "list", "--json"], ["backup", "list", "--json"], ["task", "list", "--json"])


def _escape(text):
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def main():
    core = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "core")
    data = tempfile.mkdtemp()
    env = dict(os.environ, MCMANAGER_DATA_DIR=data, NO_COLOR="1",
               MCMANAGER_LOG_DIR=os.path.join(data, "logs"), MCMANAGER_RUN_DIR=os.path.join(data, "run"))
    with open(os.path.join(data, "language.txt"), "w") as f:
        f.write("en")
    bad = 0
    for argv in COMMANDS:
        res = subprocess.run([sys.executable, os.path.join(core, "mc_cli.py"), *argv], capture_output=True,
                             text=True, encoding="utf-8", errors="replace", env=env,
                             stdin=subprocess.DEVNULL, timeout=120)
        crashed = "Traceback" in res.stderr or (argv[-1] == "--json" and not res.stdout.strip())
        print(f"mc {' '.join(argv)} -> {res.returncode}, {len(res.stdout)} bytes out")
        if crashed:
            bad += 1
            tail = "\n".join((res.stderr or res.stdout).strip().splitlines()[-12:])
            print(f"::error title=mc {' '.join(argv)}::{_escape(tail)}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
