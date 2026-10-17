import codecs
import subprocess
import sys


from mc_platform import Unsupported

__all__ = ["Unsupported", "is_windows", "run", "run_powershell"]


def is_windows():
    return sys.platform == "win32"


def _codec(encoding):
    try:
        codecs.lookup(encoding)
        return encoding
    except LookupError:
        return "cp850" if encoding == "oem" else "utf-8"


def _exec(cmd, timeout, encoding):
    kwargs = {}
    if is_windows():
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=timeout, **kwargs)
    except FileNotFoundError as e:
        return 127, "", str(e)
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except OSError as e:
        return 126, "", str(e)
    codec = _codec(encoding)
    out = (result.stdout or b"").decode(codec, errors="replace")
    err = (result.stderr or b"").decode(codec, errors="replace")
    return result.returncode, out.lstrip("﻿"), err


def run(cmd, timeout=20, encoding="oem"):
    return _exec(cmd, timeout, encoding)


def run_powershell(script, timeout=20):
    prefix = "[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
    cmd = ["powershell", "-NoProfile", "-NonInteractive", "-Command", prefix + script]
    return _exec(cmd, timeout, "utf-8")
