import json
import re
import shutil

import plat_win_common as common
import plat_win_files as files

RULE_PREFIX = "MC Manager "
_NAME = re.compile(r"^MC Manager (.+) (\d+)/(tcp|udp)$", re.IGNORECASE)
_LEGACY = re.compile(r"^MCManager - Port (\d+)$", re.IGNORECASE)
_ERR_DENIED = 5
_BLOCK_WORDS = {"block", "bloquer", "bloquear", "blockieren", "bloccare", "bloqueia"}
_OUT_WORDS = {"out", "outbound", "sortant", "sortante", "ausgehend", "saliente", "uscita", "saida", "saída"}
_NO_WORDS = {"no", "non", "nein", "nao", "não"}

_LIST_SCRIPT = (
    "try { "
    "$rules = @(Get-NetFirewallRule @@SEL@@ -ErrorAction SilentlyContinue); "
    "$out = @(foreach ($r in $rules) { $f = $r | Get-NetFirewallPortFilter; "
    "[pscustomobject]@{Name=[string]$r.Name; DisplayName=[string]$r.DisplayName; "
    "Enabled=[string]$r.Enabled; Direction=[string]$r.Direction; Action=[string]$r.Action; "
    "Protocol=[string]$f.Protocol; LocalPort=@($f.LocalPort | ForEach-Object { [string]$_ })} }); "
    "ConvertTo-Json -Compress -InputObject $out "
    "} catch { if ($_.CategoryInfo.Category -eq 'PermissionDenied' -or $_.Exception.HResult -eq -2147024891) "
    "{ exit 5 }; Write-Error $_; exit 1 }"
)
_SELECT_OURS = "-DisplayName 'MC Manager *','MCManager - Port *'"
_SELECT_ALLOWING = "-Direction Inbound -Action Allow -Enabled True"


def _build(selector):
    return _LIST_SCRIPT.replace("@@SEL@@", selector)


def sanitize_label(label):
    return re.sub(r'[\x00-\x1f"%]', "_", str(label)).strip() or "server"


def rule_name(label, port, proto="tcp"):
    return f"{RULE_PREFIX}{sanitize_label(label)} {int(port)}/{proto.lower()}"


def parse_rule_name(name):
    m = _NAME.match(name or "")
    if m:
        return m.group(1), int(m.group(2)), m.group(3).lower()
    m = _LEGACY.match(name or "")
    if m:
        return "MCManager", int(m.group(1)), "tcp"
    return None


def is_ours(name):
    return parse_rule_name(name) is not None


def firewall_name():
    return "netsh" if shutil.which("netsh") else None


def firewall_manual_command(port, proto, label):
    return (f'netsh advfirewall firewall add rule name="{rule_name(label, port, proto)}" '
            f"dir=in action=allow protocol={proto.upper()} localport={int(port)}")


def _bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value == 1
    return str(value).strip().lower() in ("true", "1", "yes", "oui", "ja", "si", "sim")


def _entry(raw):
    ports = raw.get("LocalPort")
    if ports is None:
        ports = []
    elif not isinstance(ports, list):
        ports = [ports]
    action = raw.get("Action")
    direction = raw.get("Direction")
    return {
        "id": str(raw.get("Name", "")),
        "name": str(raw.get("DisplayName", "")),
        "enabled": _bool(raw.get("Enabled")),
        "inbound": str(direction).strip().lower() in ("1", "inbound"),
        "allow": str(action).strip().lower() in ("2", "allow"),
        "proto": str(raw.get("Protocol", "")).lower(),
        "ports": [str(p) for p in ports],
    }


def parse_powershell_rules(text):
    text = (text or "").strip()
    if not text:
        return []
    data = json.loads(text)
    if data is None:
        return []
    if isinstance(data, dict):
        data = [data]
    return [_entry(r) for r in data if isinstance(r, dict)]


def parse_netsh_rules(text):
    """Structural parse: each rule is a name line followed by a dashed line, and the
    field order is fixed across languages while the labels are not."""
    rules = []
    current = None
    head = ""
    for line in (text or "").splitlines():
        if re.match(r"^-{10,}\s*$", line.strip()):
            if current is not None:
                name = current["values"].pop() if current["values"] else ""
                _close(current, rules)
            else:
                name = head
            current = {"name": name, "values": []}
            continue
        m = re.match(r"^\S[^:]*?\s*:\s?(.*)$", line)
        if not m:
            continue
        if current is None:
            head = m.group(1).strip()
        else:
            current["values"].append(m.group(1).strip())
    if current is not None:
        _close(current, rules)
    return rules


def _close(block, rules):
    v = block["values"]
    if len(v) < 8:
        return
    rules.append({
        "id": block["name"], "name": block["name"],
        "enabled": v[0].lower() not in _NO_WORDS,
        "inbound": v[1].lower() not in _OUT_WORDS,
        "allow": v[-1].lower() not in _BLOCK_WORDS,
        "proto": v[6].lower(),
        "ports": [p.strip() for p in v[7].split(",") if p.strip()],
    })


def _list(selector):
    rc, out, _err = common.run_powershell(_build(selector))
    if rc == _ERR_DENIED:
        return None, "no_permission"
    if rc == 0:
        try:
            return parse_powershell_rules(out), "ok"
        except ValueError:
            pass
    return None, "error"


def _list_netsh():
    rc, out, _err = common.run(["netsh", "advfirewall", "firewall", "show", "rule", "name=all", "dir=in"])
    if rc not in (0, 1):
        return None
    return parse_netsh_rules(out)


def list_rules(only_ours=True):
    rules, status = _list(_SELECT_OURS if only_ours else _SELECT_ALLOWING)
    if rules is None:
        rules = _list_netsh()
        if rules is None:
            return None
        if only_ours:
            rules = [r for r in rules if is_ours(r["name"])]
        else:
            rules = [r for r in rules if r["enabled"] and r["allow"]]
    if only_ours:
        rules = [r for r in rules if r["inbound"]]
    return rules


def _proto_matches(rule_proto, proto):
    rule_proto = rule_proto.lower()
    if rule_proto == proto:
        return True
    if rule_proto in ("tcp", "udp") or rule_proto.startswith(("icmp", "igmp", "gre", "ipv", "esp", "ah")):
        return False
    return not rule_proto.isdigit()


def _covers(rule, port, proto):
    if not _proto_matches(rule["proto"], proto.lower()):
        return False
    if not rule["ports"]:
        return True
    for spec in rule["ports"]:
        if "-" in spec:
            lo, _, hi = spec.partition("-")
            if lo.isdigit() and hi.isdigit() and int(lo) <= port <= int(hi):
                return True
        elif spec.isdigit():
            if int(spec) == port:
                return True
        else:
            return True
    return False


def firewall_port_open(port, proto="tcp"):
    rules = list_rules(only_ours=False)
    if rules is None:
        return None
    port = int(port)
    return any(r["enabled"] and r["inbound"] and r["allow"] and _covers(r, port, proto) for r in rules)


def _quote(value):
    return "'" + value.replace("'", "''") + "'"


def firewall_add(port, proto, label):
    port, proto = int(port), proto.lower()
    name = rule_name(label, port, proto)
    existing = list_rules(only_ours=True)
    if existing and any(r["name"] == name and r["enabled"] and r["allow"] for r in existing):
        return "ok", ""
    script = (f"try {{ New-NetFirewallRule -DisplayName {_quote(name)} -Direction Inbound "
              f"-Action Allow -Protocol {proto.upper()} -LocalPort {port} -Profile Any "
              f"-ErrorAction Stop | Out-Null }} catch {{ "
              f"if ($_.CategoryInfo.Category -eq 'PermissionDenied' -or $_.Exception.HResult -eq -2147024891) "
              f"{{ exit 5 }}; Write-Error $_; exit 1 }}")
    rc, out, err = common.run_powershell(script)
    if rc == 0:
        return "ok", ""
    if rc != _ERR_DENIED:
        rc, out, err = common.run(["netsh", "advfirewall", "firewall", "add", "rule", f"name={name}",
                                   "dir=in", "action=allow", f"protocol={proto.upper()}",
                                   f"localport={port}"])
        if rc == 0:
            return "ok", ""
    if rc == _ERR_DENIED or not files.is_elevated():
        return "no_permission", firewall_manual_command(port, proto, label)
    return "error", (err or out).strip()


def firewall_allow(port, proto, label):
    code, detail = firewall_add(port, proto, label)
    return code == "ok", detail


def _used_by_other(port, label):
    try:
        import mc_servers
        return mc_servers.find_port_conflict(port=port, exclude_name=label) is not None
    except Exception:
        return False


def firewall_remove(port, proto, label=None, in_use_by_other=None):
    port, proto = int(port), proto.lower()
    check = in_use_by_other or _used_by_other
    if check(port, label):
        return False
    rules = list_rules(only_ours=True)
    if not rules:
        return False
    removed = False
    for r in rules:
        parsed = parse_rule_name(r["name"])
        if not parsed or parsed[1] != port or parsed[2] != proto:
            continue
        script = (f"try {{ Remove-NetFirewallRule -DisplayName {_quote(r['name'])} "
                  f"-ErrorAction Stop }} catch {{ exit 1 }}")
        rc, _out, _err = common.run_powershell(script)
        if rc != 0:
            rc, _out, _err = common.run(["netsh", "advfirewall", "firewall", "delete", "rule",
                                         f"name={r['name']}"])
        removed = removed or rc == 0
    return removed
