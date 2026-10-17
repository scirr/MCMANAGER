"""A tiny stand-in for a Minecraft server, on 127.0.0.1 with an ephemeral port:
reads (optionally behind a PROXY v2 header) the handshake and the next packet,
answers like a login or a status, then echoes every byte it receives."""
import json
import os
import socket
import sys
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import mc_protocol
from mc_protocol import packet, write_string


class FakeServer(threading.Thread):

    def __init__(self, expect_proxy=False, port=0, label="fake"):
        super().__init__(daemon=True)
        self.expect_proxy = expect_proxy
        self.label = label
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", port))
        self.sock.listen(16)
        self.sock.settimeout(0.2)
        self.port = self.sock.getsockname()[1]
        self.seen = []
        self._halt = threading.Event()

    def run(self):
        while not self._halt.is_set():
            try:
                conn, _ = self.sock.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _serve(self, conn):
        record = {"proxy_raw": b"", "hello_raw": b"", "label": self.label}
        try:
            conn.settimeout(5)
            if self.expect_proxy:
                head = mc_protocol.recv_exact(conn, 16)
                length = int.from_bytes(head[14:16], "big")
                record["proxy_raw"] = head + mc_protocol.recv_exact(conn, length)
            first = mc_protocol.read_packet_raw(conn)
            raw = first[3]
            hello_state = mc_protocol.parse_handshake(first[1], first[2])[3]
            if hello_state in (2, 3):
                raw += mc_protocol.read_packet_raw(conn)[3]
            record["hello_raw"] = raw
            self.seen.append(record)
            if hello_state == 1:
                mc_protocol.read_packet_raw(conn)
                conn.sendall(packet(0x00, write_string(json.dumps({"description": {"text": self.label}}))))
            else:
                conn.sendall(packet(0x02, b"welcome-" + self.label.encode()))
            while True:
                data = conn.recv(65536)
                if not data:
                    break
                conn.sendall(data)
        except (OSError, mc_protocol.ProtocolError):
            pass
        finally:
            conn.close()

    def stop(self):
        self._halt.set()
        self.sock.close()
