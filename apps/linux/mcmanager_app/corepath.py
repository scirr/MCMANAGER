import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CANDIDATES = (
    os.environ.get("MCMANAGER_CORE", ""),
    os.path.join(HERE, "..", "..", "..", "core"),
    os.path.join(HERE, "..", ".."),
    "/opt/mcmanager",
)


def ensure():
    """Put the MC Manager core on sys.path; returns the folder or None."""
    for folder in CANDIDATES:
        folder = os.path.abspath(folder) if folder else ""
        if folder and os.path.isfile(os.path.join(folder, "mc_remoteclient.py")):
            if folder not in sys.path:
                sys.path.insert(0, folder)
            return folder
    return None
