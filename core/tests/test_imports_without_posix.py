"""Every core module must import on a Python that lacks the POSIX-only pieces
(as on Windows): a module-level use of one of them stops the daemon there."""
import os
import subprocess
import sys
import unittest

CORE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

PROBE = r'''
import os, signal, socket, socketserver, sys
for mod, names in ((socketserver, ("UnixStreamServer", "UnixDatagramServer", "ThreadingUnixStreamServer",
                                    "ForkingMixIn", "ForkingTCPServer", "ForkingUDPServer")),
                   (socket, ("AF_UNIX",)),
                   (os, ("getuid", "geteuid", "getgid", "getegid", "killpg", "getpgid", "setsid",
                         "mkfifo", "sched_setaffinity", "chown")),
                   (signal, ("SIGKILL", "SIGSTOP", "SIGCONT", "SIGHUP", "SIGCHLD"))):
    for name in names:
        if hasattr(mod, name):
            delattr(mod, name)
for name in ("termios", "tty", "grp", "resource"):
    sys.modules[name] = None
sys.path.insert(0, sys.argv[1])
failed = []
for entry in sorted(os.listdir(sys.argv[1])):
    if entry.endswith(".py") and (entry.startswith("mc_") or entry.startswith("plat")):
        if entry == "platform_linux.py":
            continue
        try:
            __import__(entry[:-3])
        except Exception as exc:
            failed.append(f"{entry}: {type(exc).__name__}: {exc}")
print("\n".join(failed))
sys.exit(1 if failed else 0)
'''


class TestImportsWithoutPosix(unittest.TestCase):
    def test_every_core_module_imports(self):
        env = dict(os.environ, MCMANAGER_DATA_DIR=os.environ.get("MCMANAGER_DATA_DIR", ""))
        res = subprocess.run([sys.executable, "-c", PROBE, CORE], capture_output=True, text=True,
                             timeout=120, env=env, stdin=subprocess.DEVNULL)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)


if __name__ == "__main__":
    unittest.main()
