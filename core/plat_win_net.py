import json
import socket

from plat_win_common import run, run_powershell, is_windows
import plat_win_process

_PS_TCP = ("ConvertTo-Json -Compress -InputObject @(Get-NetTCPConnection -State Listen "
           "-LocalPort %d -ErrorAction SilentlyContinue | "
           "Select-Object LocalAddress,LocalPort,OwningProcess)")
_PS_UDP = ("ConvertTo-Json -Compress -InputObject @(Get-NetUDPEndpoint "
           "-LocalPort %d -ErrorAction SilentlyContinue | "
           "Select-Object LocalAddress,LocalPort,OwningProcess)")
_ALL = ("0.0.0.0", "::", "[::]", "*")  # nosec B104 - addresses compared, not bound


def _split_endpoint(text):
    host, sep, port = text.rpartition(":")
    if not sep or not port.isdigit():
        return None
    return host.strip("[]") or "*", int(port)


def parse_netstat(text):
    rows = []
    for line in (text or "").splitlines():
        tok = line.split()
        if len(tok) < 4 or not tok[-1].isdigit():
            continue
        proto = tok[0].upper()
        if proto not in ("TCP", "UDP"):
            continue
        local = _split_endpoint(tok[1])
        if local is None:
            continue
        if proto == "TCP":
            remote = _split_endpoint(tok[2])
            if len(tok) < 5 or remote is None:
                continue
            listening = remote[1] == 0
        else:
            listening = True
        rows.append({"proto": proto.lower(), "address": local[0],
                     "port": local[1], "pid": int(tok[-1]),
                     "listening": listening})
    return rows


def parse_net_json(text):
    text = (text or "").strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except ValueError:
        return None
    if data is None:
        return []
    if isinstance(data, dict):
        data = [data]
    rows = []
    for item in data:
        if not isinstance(item, dict):
            continue
        pid, port = item.get("OwningProcess"), item.get("LocalPort")
        if isinstance(pid, int) and isinstance(port, int):
            rows.append({"address": str(item.get("LocalAddress") or "*"),
                         "port": port, "pid": pid})
    return rows


def _powershell_rows(port, proto):
    rc, out, _ = run_powershell((_PS_TCP if proto == "tcp" else _PS_UDP) % port)
    if rc != 0:
        return None
    return parse_net_json(out)


def _netstat_rows(port, proto):
    rc, out, _ = run(["netstat", "-ano"], encoding="oem")
    if rc != 0:
        return None
    return [r for r in parse_netstat(out)
            if r["proto"] == proto and r["port"] == port and r["listening"]]


def listeners(port, proto="tcp"):
    rows = _powershell_rows(port, proto)
    if rows is None:
        rows = _netstat_rows(port, proto)
    return rows


def _name_of(pid):
    try:
        return plat_win_process.process_name(pid)
    except Exception:
        return None


def port_listener(port, proto="tcp"):
    rows = listeners(int(port), proto)
    if not rows:
        return None
    pid = rows[0]["pid"]
    if not pid:
        return None, None
    return pid, _name_of(pid)


def listens_on_all_interfaces(port, proto="tcp"):
    rows = listeners(int(port), proto)
    if not rows:
        return None
    return any(r["address"] in _ALL for r in rows)


def _new_socket(proto):
    kind = socket.SOCK_STREAM if proto == "tcp" else socket.SOCK_DGRAM
    return socket.socket(socket.AF_INET, kind)


def port_in_use(port, proto="tcp", host="0.0.0.0"):  # nosec B104 - bind test of the public port
    sock = _new_socket(proto)
    try:
        if is_windows() and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        elif not is_windows():
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, int(port)))
        return False
    except OSError:
        return True
    finally:
        sock.close()
