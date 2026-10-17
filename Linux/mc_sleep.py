"""
mc_sleep.py — Sleep mode: the listener that stands in for a sleeping server.

While a server sleeps, this listener holds its game port so the server stays
visible in the multiplayer list (with a "sleeping" MOTD), and wakes it when a
known player tries to join. Lessons from production, all enforced here:

- only a player name the server already knows (usercache, ops, whitelist of
  any registered server, plus a manual list) may wake it: most connection
  attempts on a public port come from scanners, and each false wake costs
  hours of JVM;
- the status reply copies the client's protocol number, otherwise the client
  shows "incompatible version";
- the client closes the socket first (the side that closes first keeps the
  port in TIME_WAIT); a client that lingers is cut with a reset, and
  shutdown(SHUT_WR) is never used;
- the decision to wake belongs to the daemon (on_login callback): it refuses
  during a world freeze, outside opening hours, and never wakes a manual stop.

In "hold" mode the listener is the permanent entry point of the server, which
runs on an internal port: awake, it forwards every connection; asleep, it
keeps the waking player connected and forwards the login once the server is
ready. Addresses in banned-ips.json are refused in both modes.
"""
import base64
import json
import os
import socket
import struct
import threading

import mc_proxy

import mc_protocol
from mc_protocol import (
    ProtocolError, recv_exact, read_varint_sock, read_varint, write_varint,
    read_string, write_string, packet, read_packet, parse_handshake,
    status_json, disconnect_json,
)  # noqa: F401 - re-exported for callers and tests

_recv_exact = recv_exact

CLIENT_CLOSE_WAIT = 3      # seconds we let the client close first
IO_TIMEOUT = 5
MAX_CONNECTIONS = 32
MAX_PER_IP = 4             # a single address cannot hold every slot


# ── known players ────────────────────────────────────────────────────────────

def _names_from(path):
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except Exception:
        return set()
    names = set()
    if isinstance(data, list):
        for entry in data:
            if isinstance(entry, dict) and entry.get("name"):
                names.add(str(entry["name"]).lower())
    return names


def known_players(server_dirs, extra=()):
    """Lower-cased names of every player any registered server has seen,
    opped or whitelisted, plus `extra`."""
    names = {str(n).lower() for n in extra if str(n).strip()}
    for dossier in server_dirs:
        for fname in ("usercache.json", "ops.json", "whitelist.json"):
            names |= _names_from(os.path.join(dossier, fname))
    return names


def server_favicon(dossier):
    path = os.path.join(dossier, "server-icon.png")
    try:
        with open(path, "rb") as f:
            raw = f.read(64 * 1024)
        if raw.startswith(b"\x89PNG"):
            return "data:image/png;base64," + base64.b64encode(raw).decode()
    except Exception:
        pass
    return None


# ── listener ─────────────────────────────────────────────────────────────────

BACKEND_UP, BACKEND_SUSPENDED, BACKEND_DOWN = "up", "suspended", "down"
MAX_RELAYS = 1024
MAX_RELAYS_PER_IP = 16


class HoldPolicy:
    """What hold mode needs to know about the real server.

    probe() -> BACKEND_UP / BACKEND_SUSPENDED / BACKEND_DOWN
    ready() -> True once the server can take a login (RCON answers)
    on_hold(player) -> (accepted, text): wake it (or note it is starting)
    """

    def __init__(self, backend_port, timeout=120, proxy_protocol=False, probe=None,
                 ready=None, on_hold=None, backend_host="127.0.0.1"):
        self.backend_host = backend_host
        self.backend_port = int(backend_port)
        self.timeout = timeout
        self.proxy_protocol = proxy_protocol
        self.on_hold = on_hold or (lambda player: (False, ""))
        self.ready = ready or (lambda: True)
        self.probe = probe or self._connect_probe

    def _connect_probe(self):
        sock = mc_proxy.connect(self.backend_host, self.backend_port, timeout=1)
        if sock is None:
            return BACKEND_DOWN
        mc_proxy.close(sock)
        return BACKEND_UP


class SleepListener(threading.Thread):
    """Holds a sleeping server's game port.

    status_provider() -> (motd, max_players, version_name, favicon)
    on_login(player_name) -> text shown to the player (the daemon decides,
    and triggers the wake itself when appropriate).
    on_error(message) is called when the port cannot be bound.
    banned: object with contains(ip) -> True to refuse the address.
    hold: HoldPolicy to run in hold mode; None for the plain listener.
    """

    def __init__(self, name, port, status_provider, on_login, on_error=None,
                 bind_host="0.0.0.0", hold=None, banned=None):  # nosec B104 - stands in for the public game port
        super().__init__(name=f"sleep-{name}", daemon=True)
        self.server_name = name
        self.port = int(port)
        self.bind_host = bind_host
        self.status_provider = status_provider
        self.on_login = on_login
        self.on_error = on_error or (lambda msg: None)
        self.hold = hold
        self.banned = banned
        self._halt = threading.Event()
        self._sock = None
        self._pending = mc_proxy.ConnectionTracker(MAX_CONNECTIONS, MAX_PER_IP)
        self._relays = mc_proxy.ConnectionTracker(MAX_RELAYS, MAX_RELAYS_PER_IP)
        self.bound = threading.Event()
        self.signature = None

    def stop(self):
        self._halt.set()
        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:
                pass
        self.join(timeout=5)

    def run(self):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((self.bind_host, self.port))
            sock.listen(64)
            sock.settimeout(1)
            self.port = sock.getsockname()[1]
        except OSError as e:
            self.on_error(str(e))
            return
        self._sock = sock
        self.bound.set()
        try:
            while not self._halt.is_set():
                try:
                    conn, addr = sock.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                ip = addr[0]
                if self.banned is not None and self.banned.contains(ip):
                    mc_proxy.reset(conn)
                    continue
                if not self._pending.take(ip):
                    mc_proxy.reset(conn)
                    continue
                threading.Thread(target=self._serve, args=(conn, addr), daemon=True).start()
        finally:
            try:
                sock.close()
            except Exception:
                pass

    def _serve(self, conn, addr):
        ip = addr[0]
        polite = False
        backend = None
        try:
            conn.settimeout(IO_TIMEOUT)
            hello = mc_protocol.read_hello(conn)
            if hello is None:
                return
            if self.hold is not None and self.hold.probe() == BACKEND_UP and self.hold.ready():
                backend = self._open(conn, addr, hello)
            if backend is None and hello.is_status:
                self._status(conn, hello.protocol)
                polite = True
            elif backend is None and hello.is_login:
                if self.hold is not None:
                    backend, polite = self._login_hold(conn, hello, addr)
                else:
                    self._login(conn, hello)
                    polite = True
        except (ProtocolError, OSError, ValueError):
            pass
        finally:
            if backend is not None:
                self._pending.release(ip)
                self._forward(conn, backend, ip)
            else:
                try:
                    if polite:
                        _close_after_client(conn)
                    else:
                        mc_proxy.reset(conn)
                finally:
                    self._pending.release(ip)

    def _open(self, conn, addr, hello):
        policy = self.hold
        return mc_proxy.open_backend(policy.backend_host, policy.backend_port, hello,
                                     addr[:2], conn.getsockname()[:2], policy.proxy_protocol)

    def _forward(self, conn, backend, ip):
        if not self._relays.take(ip):
            mc_proxy.close(backend)
            mc_proxy.reset(conn)
            return
        try:
            mc_proxy.relay(conn, backend, stop=self._halt)
        finally:
            self._relays.release(ip)

    def _status(self, conn, protocol):
        packet_id, _data, _pos = read_packet(conn)       # Status Request
        if packet_id != 0x00:
            return
        motd, max_players, version_name, favicon = self.status_provider()
        conn.sendall(packet(0x00, write_string(status_json(protocol, motd, max_players, version_name, favicon))))
        try:
            packet_id, data, pos = read_packet(conn)     # Ping
        except (ProtocolError, OSError):
            return
        if packet_id == 0x01 and len(data) - pos >= 8:
            conn.sendall(packet(0x01, data[pos:pos + 8]))

    def _login(self, conn, hello):
        text = self.on_login(hello.player)
        conn.sendall(packet(0x00, write_string(disconnect_json(text))))

    def _login_hold(self, conn, hello, addr):
        """Wait for the server and hand the login over. Returns (backend,
        polite): the backend socket when the server is ready; otherwise None,
        polite being True when a disconnect message went out (the client
        closes first)."""
        policy = self.hold
        accepted, text = policy.on_hold(hello.player)
        if not accepted:
            conn.sendall(packet(0x00, write_string(disconnect_json(text))))
            return None, True
        local = conn.getsockname()[:2]

        def attempt():
            if policy.probe() != BACKEND_UP or not policy.ready():
                return None
            return mc_proxy.open_backend(policy.backend_host, policy.backend_port, hello,
                                         addr[:2], local, policy.proxy_protocol)

        backend = mc_proxy.hold(conn, hello, attempt, policy.timeout, stop=self._halt)
        if backend is not None:
            return backend, False
        try:
            from mc_lang import T
            conn.sendall(packet(0x00, write_string(disconnect_json(T["sleep_hold_timeout_text"]))))
        except OSError:
            return None, False
        return None, True


def _reset(conn):
    mc_proxy.reset(conn)


def _close_after_client(conn):
    """Let the client close first; reset if it lingers."""
    try:
        conn.settimeout(CLIENT_CLOSE_WAIT)
        while conn.recv(4096):
            pass
        conn.close()
    except Exception:
        _reset(conn)
