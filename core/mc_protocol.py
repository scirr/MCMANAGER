"""
mc_protocol.py — Minecraft Java network protocol, the small part MC Manager
needs: VarInt, strings, packets, handshake, status and disconnect payloads.
Shared by the sleep listener and the multi-server router.
"""
import json
import socket
import struct


class ProtocolError(Exception):
    pass


def recv_exact(sock, n):
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
        byte = recv_exact(sock, 1)[0]
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
    data = recv_exact(sock, length)
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


# ── client hello ─────────────────────────────────────────────────────────────

HANDSHAKE_PACKET = 0x00
LOGIN_PLUGIN_REQUEST = 0x04
LOGIN_PLUGIN_RESPONSE = 0x02
LOGIN_PLUGIN_MIN_PROTOCOL = 393      # Minecraft 1.13: first version with login plugin messages


def read_varint_sock_raw(sock):
    value, raw = 0, b""
    for i in range(5):
        byte = recv_exact(sock, 1)
        raw += byte
        value |= (byte[0] & 0x7F) << (7 * i)
        if not byte[0] & 0x80:
            return value, raw
    raise ProtocolError("varint too long")


def read_packet_raw(sock, max_len=1 << 16):
    """(packet_id, body, offset_after_id, raw_bytes_as_received)."""
    length, raw = read_varint_sock_raw(sock)
    if length <= 0 or length > max_len:
        raise ProtocolError("bad packet length")
    data = recv_exact(sock, length)
    packet_id, pos = read_varint(data, 0)
    return packet_id, data, pos, raw + data


def normalize_host(address):
    """Hostname a client asked for, without what mods and resolvers append:
    Forge/FML markers after a NUL ("host\\0FML2\\0"), trailing DNS dots,
    case, stray whitespace and a port suffix."""
    host = (address or "").split("\x00", 1)[0].strip().lower()
    while host.endswith("."):
        host = host[:-1]
    if host.count(":") == 1:
        host = host.rsplit(":", 1)[0]
    return host


class Hello:
    """What a client sent before the game proper: handshake and, for a login,
    the Login Start packet. `raw` is exactly what has to be replayed to
    whoever serves the connection."""

    def __init__(self, protocol, address, port, next_state, player=None, raw=b""):
        self.protocol = protocol
        self.address = address
        self.host = normalize_host(address)
        self.port = port
        self.next_state = next_state
        self.player = player
        self.raw = raw

    @property
    def is_status(self):
        return self.next_state == 1

    @property
    def is_login(self):
        return self.next_state in (2, 3)


def read_hello(sock):
    """Read the handshake (and Login Start). None for a legacy (pre-1.7) ping
    or an empty connection; ProtocolError for anything that is not Minecraft."""
    first = sock.recv(1, socket.MSG_PEEK)
    if not first or first[0] == 0xFE:
        return None
    packet_id, data, pos, raw = read_packet_raw(sock)
    if packet_id != HANDSHAKE_PACKET:
        raise ProtocolError("not a handshake")
    protocol, address, port, next_state = parse_handshake(data, pos)
    hello = Hello(protocol, address, port, next_state, raw=raw)
    if next_state in (2, 3):
        packet_id, data, pos, raw2 = read_packet_raw(sock)
        if packet_id != 0x00:
            raise ProtocolError("login start expected")
        name, _ = read_string(data, pos, 16)
        hello.player = name.strip()
        hello.raw = raw + raw2
    elif next_state != 1:
        raise ProtocolError("bad next state")
    return hello


def login_plugin_request(message_id, channel="mcmanager:hold"):
    """A login-phase packet every client answers ("not understood") and that
    restarts its read timeout: how a held login stays alive."""
    return packet(LOGIN_PLUGIN_REQUEST, write_varint(message_id) + write_string(channel))


def read_login_plugin_response(data, pos):
    message_id, _ = read_varint(data, pos)
    return message_id


# ── PROXY protocol v2 ────────────────────────────────────────────────────────

PROXY_V2_SIGNATURE = b"\r\n\r\n\x00\r\nQUIT\n"
_FAMILY = {socket.AF_INET: 0x11, socket.AF_INET6: 0x21}


def _ip_family(ip):
    try:
        socket.inet_pton(socket.AF_INET, ip)
        return socket.AF_INET
    except OSError:
        pass
    try:
        socket.inet_pton(socket.AF_INET6, ip)
        return socket.AF_INET6
    except OSError:
        return None


def proxy_v2_header(src, dst):
    """PROXY protocol v2 header for a TCP connection src=(ip, port) ->
    dst=(ip, port). IPv4 when both ends are IPv4, IPv6 when both are IPv6
    (an IPv4 end is then written as ::ffff:a.b.c.d); anything else is sent as
    a LOCAL header, which receivers treat as "no address information"."""
    src_family, dst_family = _ip_family(src[0]), _ip_family(dst[0])
    if src_family is None or dst_family is None:
        return PROXY_V2_SIGNATURE + b"\x20\x00\x00\x00"
    if src_family != dst_family:
        family = socket.AF_INET6
    else:
        family = src_family
    packed = []
    for ip, ip_family in ((src[0], src_family), (dst[0], dst_family)):
        raw = socket.inet_pton(ip_family, ip)
        if family == socket.AF_INET6 and ip_family == socket.AF_INET:
            raw = b"\x00" * 10 + b"\xff\xff" + raw
        packed.append(raw)
    payload = packed[0] + packed[1] + struct.pack(">HH", int(src[1]), int(dst[1]))
    return PROXY_V2_SIGNATURE + bytes([0x21, _FAMILY[family]]) + struct.pack(">H", len(payload)) + payload


def read_proxy_v2(sock):
    """Read a PROXY v2 header from a socket. Returns ((src_ip, src_port),
    (dst_ip, dst_port)), or None for a LOCAL header. ProtocolError when the
    bytes are not a PROXY v2 header."""
    head = recv_exact(sock, 16)
    if head[:12] != PROXY_V2_SIGNATURE:
        raise ProtocolError("no PROXY v2 signature")
    version_command, family, length = head[12], head[13], struct.unpack(">H", head[14:16])[0]
    if version_command not in (0x20, 0x21) or length > 536:
        raise ProtocolError("bad PROXY v2 header")
    body = recv_exact(sock, length)
    if version_command & 0x0F == 0:
        return None
    if family == 0x11 and length >= 12:
        src, dst = socket.inet_ntop(socket.AF_INET, body[0:4]), socket.inet_ntop(socket.AF_INET, body[4:8])
        sport, dport = struct.unpack(">HH", body[8:12])
    elif family == 0x21 and length >= 36:
        src, dst = socket.inet_ntop(socket.AF_INET6, body[0:16]), socket.inet_ntop(socket.AF_INET6, body[16:32])
        sport, dport = struct.unpack(">HH", body[32:36])
    else:
        raise ProtocolError("unsupported PROXY v2 family")
    return (src, sport), (dst, dport)
