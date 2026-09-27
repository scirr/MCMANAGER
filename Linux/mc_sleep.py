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
"""
import base64
import json
import os
import socket
import struct
import threading

CLIENT_CLOSE_WAIT = 3      # seconds we let the client close first
IO_TIMEOUT = 5
MAX_CONNECTIONS = 32
MAX_PER_IP = 4             # a single address cannot hold every slot


# ── protocol primitives ──────────────────────────────────────────────────────

class ProtocolError(Exception):
    pass


def _recv_exact(sock, n):
    data = b""
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            raise ProtocolError("closed")
        data += chunk
    return data


def read_varint_sock(sock):
    value = 0
    for i in range(5):
        byte = _recv_exact(sock, 1)[0]
        value |= (byte & 0x7F) << (7 * i)
        if not byte & 0x80:
            return value
    raise ProtocolError("varint too long")


def read_varint(buf, pos):
    value = 0
    for i in range(5):
        if pos >= len(buf):
            raise ProtocolError("truncated varint")
        byte = buf[pos]
        pos += 1
        value |= (byte & 0x7F) << (7 * i)
        if not byte & 0x80:
            if value & (1 << 31):
                value -= 1 << 32
            return value, pos
    raise ProtocolError("varint too long")


def write_varint(value):
    value &= 0xFFFFFFFF
    out = b""
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out += bytes([byte | 0x80])
        else:
            return out + bytes([byte])


def read_string(buf, pos, max_len=32767):
    length, pos = read_varint(buf, pos)
    if length < 0 or length > max_len * 4 or pos + length > len(buf):
        raise ProtocolError("bad string")
    return buf[pos:pos + length].decode("utf-8", "replace"), pos + length


def write_string(text):
    raw = text.encode("utf-8")
    return write_varint(len(raw)) + raw


def packet(packet_id, payload=b""):
    body = write_varint(packet_id) + payload
    return write_varint(len(body)) + body


def read_packet(sock):
    length = read_varint_sock(sock)
    if length <= 0 or length > 1 << 16:
        raise ProtocolError("bad packet length")
    data = _recv_exact(sock, length)
    packet_id, pos = read_varint(data, 0)
    return packet_id, data, pos


def parse_handshake(data, pos):
    """(protocol, address, port, next_state) from a handshake body."""
    protocol, pos = read_varint(data, pos)
    address, pos = read_string(data, pos, 255)
    if pos + 2 > len(data):
        raise ProtocolError("truncated handshake")
    port = struct.unpack(">H", data[pos:pos + 2])[0]
    next_state, pos = read_varint(data, pos + 2)
    return protocol, address, port, next_state


def status_json(protocol, motd, max_players, version_name="Minecraft", favicon=None):
    doc = {
        "version": {"name": version_name, "protocol": protocol},
        "players": {"max": max_players, "online": 0, "sample": []},
        "description": {"text": motd},
    }
    if favicon:
        doc["favicon"] = favicon
    return json.dumps(doc, ensure_ascii=False)


def disconnect_json(text):
    return json.dumps({"text": text}, ensure_ascii=False)


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

class SleepListener(threading.Thread):
    """Holds a sleeping server's game port.

    status_provider() -> (motd, max_players, version_name, favicon)
    on_login(player_name) -> text shown to the player (the daemon decides,
    and triggers the wake itself when appropriate).
    on_error(message) is called when the port cannot be bound.
    """

    def __init__(self, name, port, status_provider, on_login, on_error=None):
        super().__init__(name=f"sleep-{name}", daemon=True)
        self.server_name = name
        self.port = int(port)
        self.status_provider = status_provider
        self.on_login = on_login
        self.on_error = on_error or (lambda msg: None)
        self._halt = threading.Event()
        self._sock = None
        self._slots = threading.BoundedSemaphore(MAX_CONNECTIONS)
        self._per_ip = {}
        self._per_ip_lock = threading.Lock()
        self.bound = threading.Event()

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
            sock.bind(("0.0.0.0", self.port))  # nosec B104 - stands in for the public game port
            sock.listen(16)
            sock.settimeout(1)
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
                if not self._take_ip(ip):
                    _reset(conn)
                    continue
                if not self._slots.acquire(blocking=False):
                    self._release_ip(ip)
                    _reset(conn)
                    continue
                threading.Thread(target=self._serve, args=(conn, ip), daemon=True).start()
        finally:
            try:
                sock.close()
            except Exception:
                pass

    def _take_ip(self, ip):
        with self._per_ip_lock:
            if self._per_ip.get(ip, 0) >= MAX_PER_IP:
                return False
            self._per_ip[ip] = self._per_ip.get(ip, 0) + 1
            return True

    def _release_ip(self, ip):
        with self._per_ip_lock:
            left = self._per_ip.get(ip, 1) - 1
            if left > 0:
                self._per_ip[ip] = left
            else:
                self._per_ip.pop(ip, None)

    def _serve(self, conn, ip=None):
        polite = False
        try:
            conn.settimeout(IO_TIMEOUT)
            first = conn.recv(1, socket.MSG_PEEK)
            if not first or first[0] == 0xFE:      # empty or legacy (pre-1.7) ping
                return
            packet_id, data, pos = read_packet(conn)
            if packet_id != 0x00:
                return
            protocol, _addr, _port, next_state = parse_handshake(data, pos)
            if next_state == 1:
                self._status(conn, protocol)
                polite = True
            elif next_state in (2, 3):
                self._login(conn)
                polite = True
        except (ProtocolError, OSError, ValueError):
            pass
        finally:
            # A real client gets to close first (no TIME_WAIT on our side);
            # garbage and scanners are cut at once.
            if polite:
                _close_after_client(conn)
            else:
                _reset(conn)
            self._slots.release()
            if ip is not None:
                self._release_ip(ip)

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

    def _login(self, conn):
        packet_id, data, pos = read_packet(conn)         # Login Start
        if packet_id != 0x00:
            return
        player, _pos = read_string(data, pos, 16)
        text = self.on_login(player.strip())
        conn.sendall(packet(0x00, write_string(disconnect_json(text))))


def _reset(conn):
    """Close with RST: no TIME_WAIT left on the port."""
    try:
        conn.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
    except Exception:
        pass
    try:
        conn.close()
    except Exception:
        pass


def _close_after_client(conn):
    """Let the client close first; reset if it lingers."""
    try:
        conn.settimeout(CLIENT_CLOSE_WAIT)
        while conn.recv(4096):
            pass
        conn.close()
    except Exception:
        _reset(conn)
