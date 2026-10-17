"""
mc_proxy.py — Transparent TCP forwarding for the sleep listener and the router.

Everything here serves one connection at a time and is meant to run in that
connection's own thread: a slow or silent client only ever holds its own
thread, never the accept loop or another player.
"""
import ipaddress
import json
import os
import select
import struct
import socket
import threading
import time
from datetime import datetime

import mc_protocol
from mc_protocol import ProtocolError

CONNECT_TIMEOUT = 3
SEND_TIMEOUT = 30
RELAY_IDLE = 300            # Minecraft keeps a live connection busy every 15 s
HOLD_KEEPALIVE = 10
HOLD_POLL = 1
OUTSTANDING_WAIT = 5


# ── limits and filters ───────────────────────────────────────────────────────

class ConnectionTracker:
    """Concurrent connections, in total and per address."""

    def __init__(self, total, per_ip):
        self.total, self.per_ip = total, per_ip
        self._count = 0
        self._by_ip = {}
        self._lock = threading.Lock()

    def take(self, ip):
        with self._lock:
            if self._count >= self.total or self._by_ip.get(ip, 0) >= self.per_ip:
                return False
            self._count += 1
            self._by_ip[ip] = self._by_ip.get(ip, 0) + 1
            return True

    def release(self, ip):
        with self._lock:
            self._count = max(0, self._count - 1)
            left = self._by_ip.get(ip, 1) - 1
            if left > 0:
                self._by_ip[ip] = left
            else:
                self._by_ip.pop(ip, None)

    def counts(self):
        with self._lock:
            return self._count, dict(self._by_ip)


class RateLimiter:
    """At most `limit` new connections per address in any `window` seconds."""

    def __init__(self, limit, window=1.0, clock=time.monotonic):
        self.limit, self.window, self.clock = limit, window, clock
        self._hits = {}
        self._lock = threading.Lock()
        self._sweep_at = 0.0

    def allow(self, ip):
        if not self.limit or self.limit <= 0:
            return True
        now = self.clock()
        with self._lock:
            if now - self._sweep_at > 60:
                self._sweep_at = now
                for key in [k for k, v in self._hits.items() if not v or now - v[-1] > self.window]:
                    del self._hits[key]
            hits = [t for t in self._hits.get(ip, ()) if now - t < self.window]
            if len(hits) >= self.limit:
                self._hits[ip] = hits
                return False
            hits.append(now)
            self._hits[ip] = hits
            return True


def parse_networks(values):
    nets = []
    for value in values or ():
        nets.append(ipaddress.ip_network(str(value).strip(), strict=False))
    return nets


def valid_cidr(value):
    try:
        ipaddress.ip_network(str(value).strip(), strict=False)
        return True
    except ValueError:
        return False


def _address(ip):
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return None
    if addr.version == 6 and addr.ipv4_mapped:
        return addr.ipv4_mapped
    return addr


def in_networks(ip, nets):
    addr = _address(ip)
    return addr is not None and any(addr.version == n.version and addr in n for n in nets)


class AccessList:
    """CIDR allow/deny: a deny match always refuses; when an allow list exists
    the address must be in it."""

    def __init__(self, allow=(), deny=()):
        self.allow = parse_networks(allow)
        self.deny = parse_networks(deny)

    def permits(self, ip):
        if in_networks(ip, self.deny):
            return False
        return not self.allow or in_networks(ip, self.allow)


class BannedIPs:
    """banned-ips.json of a server, re-read only when the file changes.
    Expired temporary bans are ignored."""

    def __init__(self, path):
        self.path = path
        self._stamp = None
        self._checked = 0
        self._ips = set()
        self._lock = threading.Lock()

    @staticmethod
    def _active(entry, now):
        expires = str(entry.get("expires") or "forever").strip()
        if expires.lower() == "forever":
            return True
        for fmt in ("%Y-%m-%d %H:%M:%S %z", "%Y-%m-%d %H:%M:%S"):
            try:
                when = datetime.strptime(expires, fmt)
            except ValueError:
                continue
            if when.tzinfo is None:
                when = when.astimezone()
            return when.timestamp() > now
        return True

    def _load(self):
        try:
            with open(self.path, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
        except Exception:
            return set()
        if not isinstance(data, list):
            return set()
        now = time.time()
        return {str(e["ip"]).strip() for e in data
                if isinstance(e, dict) and e.get("ip") and self._active(e, now)}

    def contains(self, ip):
        try:
            stamp = os.stat(self.path).st_mtime_ns
        except OSError:
            stamp = None
        with self._lock:
            if stamp != self._stamp or time.monotonic() - self._checked >= 1:
                self._stamp = stamp
                self._checked = time.monotonic()
                self._ips = self._load() if stamp is not None else set()
            ips = self._ips
        addr = _address(ip)
        return ip in ips or (addr is not None and str(addr) in ips)


# ── forwarding ───────────────────────────────────────────────────────────────

def reset(conn):
    """Close with RST: no TIME_WAIT left behind."""
    try:
        conn.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
    except Exception:
        pass
    close(conn)


def close(conn):
    try:
        conn.close()
    except Exception:
        pass


def connect(host, port, timeout=CONNECT_TIMEOUT):
    """A connected socket, or None."""
    try:
        sock = socket.create_connection((host, int(port)), timeout=timeout)
    except OSError:
        return None
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    return sock


def open_backend(host, port, hello, client_addr, local_addr, proxy_protocol):
    """Connect to the real server and replay what the client already sent,
    behind a PROXY v2 header when the server expects one."""
    sock = connect(host, port)
    if sock is None:
        return None
    try:
        sock.settimeout(SEND_TIMEOUT)
        header = mc_protocol.proxy_v2_header(client_addr, local_addr) if proxy_protocol else b""
        sock.sendall(header + hello.raw)
    except OSError:
        close(sock)
        return None
    return sock


def relay(a, b, idle=RELAY_IDLE, stop=None):
    """Copy bytes both ways until either side closes or stays silent."""
    peers = {a: b, b: a}
    for sock in peers:
        sock.settimeout(SEND_TIMEOUT)
    last_data = time.monotonic()
    try:
        while stop is None or not stop.is_set():
            remaining = idle - (time.monotonic() - last_data)
            if remaining <= 0:
                return
            readable, _, _ = select.select(list(peers), [], [], min(remaining, 0.5))
            if not readable:
                continue
            last_data = time.monotonic()
            for sock in readable:
                data = sock.recv(65536)
                if not data:
                    return
                peers[sock].sendall(data)
    except (OSError, ValueError):
        return
    finally:
        close(a)
        close(b)


def hold(conn, hello, attempt, timeout, clock=time.monotonic, keepalive=HOLD_KEEPALIVE, poll=HOLD_POLL, stop=None):
    """Keep a logging-in client waiting until attempt() yields a backend socket.

    The client sits in the login phase, which times out after 30 s without a
    packet: a login-phase plugin request (answered with "not understood")
    goes out every `keepalive` seconds, and its answers are swallowed here so
    that the real server never sees them. Returns the backend socket, or None
    on timeout or when the client leaves."""
    deadline = clock() + timeout
    next_ping = clock() + keepalive
    can_ping = hello.protocol >= mc_protocol.LOGIN_PLUGIN_MIN_PROTOCOL
    outstanding = set()
    next_id = 1 << 20
    backend = None
    settle_until = None
    while True:
        now = clock()
        if now >= deadline or (stop is not None and stop.is_set()):
            close(backend)
            return None
        if backend is None and not outstanding:
            backend = attempt()
        if backend is not None:
            return backend
        if outstanding and now >= settle_until:
            return None
        if can_ping and backend is None and now >= next_ping:
            next_ping = now + keepalive
            outstanding.add(next_id)
            settle_until = now + OUTSTANDING_WAIT
            try:
                conn.sendall(mc_protocol.login_plugin_request(next_id))
            except OSError:
                return None
            next_id += 1
        try:
            readable, _, _ = select.select([conn], [], [], min(poll, max(0, deadline - clock())))
            if readable:
                conn.settimeout(poll + 2)
                packet_id, data, pos, _raw = mc_protocol.read_packet_raw(conn)
                if packet_id != mc_protocol.LOGIN_PLUGIN_RESPONSE:
                    raise ProtocolError("unexpected packet while holding")
                outstanding.discard(mc_protocol.read_login_plugin_response(data, pos))
        except (ProtocolError, OSError, ValueError):
            if backend is not None:
                close(backend)
            return None
