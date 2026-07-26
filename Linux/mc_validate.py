"""
mc_validate.py — Pure validation functions (no dependencies).
Imported by mc_config, mc_deploy, and the test suite.
"""
import re


def valid_port(val):
    try:
        return 1 <= int(val) <= 65535
    except (ValueError, TypeError):
        return False


def valid_ram(val):
    s = str(val).strip()
    m = re.match(r'^(\d+)[GgMm]$', s)
    return bool(m) and int(m.group(1)) > 0


def valid_cpu(val):
    return bool(re.match(r'^\d+(-\d+)?(,\d+(-\d+)?)*$', str(val).strip()))


def valid_bool(val):
    try:
        return int(val) in (0, 1)
    except (ValueError, TypeError):
        return False
