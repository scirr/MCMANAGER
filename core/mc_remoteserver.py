"""
mc_remoteserver.py — The remote listener of the daemon: a second server for the same
application as the local API, TLS 1.3 only, with device authentication and roles.
A failed handshake or a client that disappears only closes its own connection.
"""
import http.server
import logging
import socket
import socketserver
import ssl
import threading

import mc_httpapi
import mc_remote

HANDSHAKE_S = 10
IDLE_S = 30
MAX_CONNECTIONS = 64


def server_context(info):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_3
    context.load_cert_chain(info["cert"], info["key"])
    return context


class TlsHandler(mc_httpapi.Handler):
    timeout = IDLE_S

    def setup(self):
        super().setup()
        self.connection.settimeout(HANDSHAKE_S)
        self.connection.do_handshake()
        self.connection.settimeout(IDLE_S)


class TlsServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, app, context):
        self.app = app
        self.context = context
        self.address_family = socket.AF_INET6 if ":" in address[0] else socket.AF_INET
        self.connections = 0
        self.connections_lock = threading.Lock()
        super().__init__(address, TlsHandler)

    def server_bind(self):
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = "localhost", self.server_address[1]

    def get_request(self):
        raw, address = self.socket.accept()
        raw.settimeout(HANDSHAKE_S)
        return self.context.wrap_socket(raw, server_side=True, do_handshake_on_connect=False), address

    def process_request(self, request, client_address):
        with self.connections_lock:
            if self.connections >= MAX_CONNECTIONS:
                self.shutdown_request(request)
                return
            self.connections += 1
        super().process_request(request, client_address)

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            with self.connections_lock:
                self.connections = max(0, self.connections - 1)

    def handle_error(self, request, client_address):
        logging.debug("Remote API connection from %s ended abnormally.", client_address[0])


class RemoteApi(mc_httpapi.LocalApi):
    """Owns the TLS listener; sync() follows remote.json and never raises."""
    label = "Remote API"

    def __init__(self, release=None, settle=mc_httpapi.SETTLE_S, enabled=None, bind=None):
        super().__init__(release=release, settle=settle, enabled=enabled)
        self.forced_bind = bind
        self.running = None

    def folder_path(self):
        return mc_remote.cert_dir()

    def wanted(self):
        return mc_remote.load_settings()["enabled"] if self.enabled is None else self.enabled()

    def bind_text(self):
        return self.forced_bind or mc_remote.load_settings()["bind"]

    def sync(self):
        try:
            if self.server and (self.bind_text() != self.running):
                self.stop()
        except Exception:
            logging.exception("Remote API")
        super().sync()

    def bind(self, folder):
        host, port = mc_remote.parse_bind(self.bind_text())
        info = mc_remote.ensure_certificate(host)
        if info is None:
            raise RuntimeError("no TLS certificate available: remote access stays off")
        context = server_context(info)
        self.app = mc_httpapi.ApiApp(release=self.release, settle=self.settle, remote=mc_remote.Gate())
        self.server = TlsServer((host, port), self.app, context)
        self.running = self.bind_text()

    def cleanup(self):
        self.running = None
