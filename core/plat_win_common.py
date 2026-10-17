import codecs
import subprocess
import sys


class Unsupported(Exception):
    code = "unsupported_on_windows"


def is_windows():
    return sys.platform == "win32"


def _decode(data, encoding):
    try:
        codecs.lookup(encoding)
    except LookupError:
        encoding = "cp437" if encoding == "oem" else "utf-8"
    return (data or b"").decode(encoding, errors="replace")


def run(cmd, timeout=20, encoding="oem"):
    try:
        done = subprocess.run(cmd, capture_output=True, timeout=timeout)
    except FileNotFoundError as exc:
        return 127, "", "command not found: %s (%s)" % (cmd[0], exc)
    except subprocess.TimeoutExpired:
        return 124, "", "timeout after %ss: %s" % (timeout, cmd[0])
    except OSError as exc:
        return 126, "", "cannot run %s: %s" % (cmd[0], exc)
    return (done.returncode, _decode(done.stdout, encoding),
            _decode(done.stderr, encoding))


def run_powershell(script, timeout=20):
    full = "[Console]::OutputEncoding=[Text.Encoding]::UTF8; " + script
    rc, out, err = run(["powershell", "-NoProfile", "-NonInteractive",
                        "-Command", full], timeout=timeout, encoding="utf-8")
    return rc, out.lstrip("﻿"), err.lstrip("﻿")
