"""Runs first: redirects the core's writable paths to a temp dir and snapshots core/."""
import atexit
import os
import shutil
import tempfile

CORE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_TMP = tempfile.mkdtemp(prefix="mcm-tests-")
atexit.register(shutil.rmtree, _TMP, ignore_errors=True)
os.environ.setdefault("MCMANAGER_LOG_DIR", os.path.join(_TMP, "logs"))
os.environ.setdefault("MCMANAGER_UPDATE_CACHE", os.path.join(_TMP, "update_check.json"))


def snapshot():
    found = set()
    for root, dirs, files in os.walk(CORE):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        rel = os.path.relpath(root, CORE)
        found.add(rel + "/")
        found.update(os.path.join(rel, f) for f in files)
    return found


BEFORE = snapshot()
