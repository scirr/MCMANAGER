import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CORE = os.path.dirname(HERE)
if CORE not in sys.path:
    sys.path.insert(0, CORE)


def load(name):
    path = os.path.join(HERE, "fixtures", "windows", name)
    with open(path, encoding="utf-8") as fh:
        lines = [ln for ln in fh.read().splitlines() if not ln.startswith("###")]
    return "\n".join(lines) + "\n"
