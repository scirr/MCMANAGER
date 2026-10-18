import codecs
import subprocess
import sys


from mc_platform import Unsupported

__all__ = ["Unsupported", "decode_output", "is_windows", "run", "run_powershell"]


def is_windows():
    return sys.platform == "win32"


def _codec(encoding):
    try:
        codecs.lookup(encoding)
        return encoding
    except LookupError:
        return "cp850" if encoding == "oem" else "utf-8"


def decode_output(data, encoding="oem"):
    if isinstance(data, str):
        return data
    data = data or b""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass
    wanted = str(encoding or "oem").lower().replace("_", "-")
    codec = _codec("oem" if wanted in ("utf-8", "utf8", "oem") else encoding)
    try:
        return data.decode(codec)
    except (UnicodeDecodeError, LookupError):
        return data.decode("cp850", errors="replace")


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
    return result.returncode, decode_output(result.stdout, encoding).lstrip("﻿"), decode_output(result.stderr, encoding)


def run(cmd, timeout=20, encoding="oem"):
    return _exec(cmd, timeout, encoding)


def run_powershell(script, timeout=20):
    prefix = "[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
    cmd = ["powershell", "-NoProfile", "-NonInteractive", "-Command", prefix + script]
    return _exec(cmd, timeout, "utf-8")
