#!/usr/bin/env python3
"""Run a unittest suite and report each failure as a GitHub Actions annotation,
so failures are readable from the checks page without opening the raw log."""
import os
import sys
import unittest


def _escape(text):
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def main():
    start = sys.argv[1] if len(sys.argv) > 1 else "tests"
    sys.path.insert(0, os.getcwd())
    suite = unittest.defaultTestLoader.discover(start)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    problems = [("error", t, tb) for t, tb in result.errors] + [("failure", t, tb) for t, tb in result.failures]
    problems.sort(key=lambda item: "stdout=" not in item[2])
    seen = set()
    unique = []
    for item in problems:
        key = item[2].strip().splitlines()[-1][:160]
        if key not in seen:
            seen.add(key)
            unique.append(item)
    for kind, test, trace in unique[:10]:
        lines = [line for line in trace.strip().splitlines() if line.strip()]
        tail = "\n".join(lines[-12:])
        print(f"::error title={kind}: {test.id()}::{_escape(tail)}")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
