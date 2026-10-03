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
