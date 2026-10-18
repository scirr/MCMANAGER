"""Hostname routing on one TCP listener."""
import copy
import ipaddress
import os
import re
import socket
import threading

import mc_protocol
import mc_proxy
import mc_servers
import mc_sleep
from mc_lang import T

DEFAULTS = {
    "enabled": False, "port": 25565, "bind_host": "0.0.0.0",  # nosec B104 - public game port
    "routes": {}, "default": None, "allow": [], "deny": [],
    "max_connections": 128, "per_ip": 16, "per_second": 8,
    "proxy_in": False, "trusted_proxies": [], "proxy_out": False,
}


def path():
    return os.path.join(os.path.dirname(mc_servers.REGISTRY_FILE), "router.json")


def hostname(value):
    host = mc_protocol.normalize_host(value)
    if not host or len(host) > 253 or any(
            not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
            for label in host.split(".")):
        raise ValueError("hostname")
    return host


def validate(config, ephemeral=False):
    if not isinstance(config, dict):
        raise ValueError("router")
    merged = copy.deepcopy(DEFAULTS)
    merged.update(config)
    for key, low, high in (("port", 0 if ephemeral else 1, 65535),
                           ("max_connections", 1, 1024), ("per_ip", 1, 128),
                           ("per_second", 1, 1000)):
        value = merged[key]
        if type(value) is not int or not low <= value <= high:
            raise ValueError(key)
    ipaddress.ip_address(merged["bind_host"])
    for key in ("enabled", "proxy_in", "proxy_out"):
        if type(merged[key]) is not bool:
            raise ValueError(key)
    for key in ("allow", "deny", "trusted_proxies"):
        if not isinstance(merged[key], list):
            raise ValueError(key)
        mc_proxy.parse_networks(merged[key])
    if merged["proxy_in"] and not merged["trusted_proxies"]:
        raise ValueError("trusted_proxies")
    if not isinstance(merged["routes"], dict):
        raise ValueError("routes")
    routes = {}
    for host, server in merged["routes"].items():
        if not isinstance(server, str) or not server:
            raise ValueError("server")
        routes[hostname(host)] = server
    merged["routes"] = routes
    if merged["default"] is not None and (not isinstance(merged["default"], str) or not merged["default"]):
        raise ValueError("default")
    return merged


def load():
    try:
        return validate(mc_servers.read_json(path(), DEFAULTS))
    except (ValueError, TypeError, AttributeError) as exc:
        raise mc_servers.DataFileError(path(), str(exc)) from exc


def save(config):
    mc_servers._atomic_write_json(path(), validate(config))


class Target:
    def __init__(self, policy, status, banned=None):
        self.policy, self.status, self.banned = policy, status, banned


class RouterListener(threading.Thread):
    def __init__(self, config, resolve, on_error=None):
        super().__init__(name="router", daemon=True)
        self.config = validate(config, ephemeral=True)
        self.resolve = resolve
        self.on_error = on_error or (lambda message: None)
        self.port = self.config["port"]
        self.bound = threading.Event()
        self._halt = threading.Event()
        self._sock = None
        self._sockets = set()
        self._lock = threading.Lock()
        self._slots = mc_proxy.ConnectionTracker(self.config["max_connections"], self.config["max_connections"])
        self._clients = mc_proxy.ConnectionTracker(self.config["max_connections"], self.config["per_ip"])
        self._rate = mc_proxy.RateLimiter(self.config["per_second"])
        self._access = mc_proxy.AccessList(self.config["allow"], self.config["deny"])
        self._trusted = mc_proxy.parse_networks(self.config["trusted_proxies"])

    def stop(self):
        self._halt.set()
        with self._lock:
            sockets = list(self._sockets)
        for sock in sockets:
            mc_proxy.reset(sock)
        mc_proxy.close(self._sock)

    def run(self):
        host = self.config["bind_host"]
        sock = socket.socket(socket.AF_INET6 if ":" in host else socket.AF_INET, socket.SOCK_STREAM)
        self._sock = sock
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((host, self.port))
            sock.listen(64)
            sock.settimeout(0.2)
            self.port = sock.getsockname()[1]
            self.bound.set()
            while not self._halt.is_set():
                try:
                    conn, addr = sock.accept()
                except socket.timeout:
                    continue
                if not self._slots.take(addr[0]):
                    mc_proxy.reset(conn)
                    continue
                with self._lock:
                    self._sockets.add(conn)
                try:
                    threading.Thread(target=self._serve, args=(conn, addr), daemon=True).start()
                except RuntimeError:
                    with self._lock:
                        self._sockets.discard(conn)
                    self._slots.release(addr[0])
                    mc_proxy.reset(conn)
        except OSError as exc:
            if not self._halt.is_set():
                self.on_error(str(exc))
        finally:
            mc_proxy.close(sock)

    def _serve(self, conn, peer):
        backend, client_ip, admitted, polite = None, peer[0], False, False
        try:
            conn.settimeout(mc_sleep.IO_TIMEOUT)
            source, destination = peer[:2], conn.getsockname()[:2]
            if self.config["proxy_in"]:
                if not mc_proxy.in_networks(peer[0], self._trusted):
                    return
                forwarded = mc_protocol.read_proxy_v2(conn)
                if forwarded:
                    source, destination = forwarded
            client_ip = str(mc_proxy._address(source[0]))
            if not self._access.permits(client_ip) or not self._rate.allow(client_ip):
                return
            admitted = self._clients.take(client_ip)
            if not admitted:
                return
            hello = mc_protocol.read_hello(conn)
            if hello is None:
                return
            name = self.config["routes"].get(hello.host, self.config["default"])
            target = self.resolve(name) if name else None
            if target is None:
                if hello.is_login:
                    self._disconnect(conn, T["router_unavailable"])
                    polite = True
                return
            if target.banned and target.banned.contains(client_ip):
                return
            policy = target.policy

            def attempt():
                if self._halt.is_set() or policy.probe() != mc_sleep.BACKEND_UP or not policy.ready():
                    return None
                return mc_proxy.open_backend(policy.backend_host, policy.backend_port, hello,
                                             source, destination,
                                             self.config["proxy_out"] or policy.proxy_protocol)

            backend = attempt()
            if backend is None and hello.is_status:
                responder = mc_sleep.SleepListener(name, 0, target.status, lambda player: "")
                responder._status(conn, hello.protocol)
                polite = True
                return
            if backend is None:
                accepted, message = policy.on_hold(hello.player)
                if accepted:
                    backend = mc_proxy.hold(conn, hello, attempt, policy.timeout, stop=self._halt)
                    message = T["sleep_hold_timeout_text"]
                if backend is None:
                    self._disconnect(conn, message)
                    polite = True
                    return
            with self._lock:
                self._sockets.add(backend)
            mc_proxy.relay(conn, backend, stop=self._halt)
        except (mc_protocol.ProtocolError, OSError, ValueError, mc_servers.DataFileError):
            pass
        finally:
            if polite:
                mc_sleep._close_after_client(conn)
            else:
                mc_proxy.reset(conn)
            mc_proxy.close(backend)
            with self._lock:
                self._sockets.discard(conn)
                self._sockets.discard(backend)
            if admitted:
                self._clients.release(client_ip)
            self._slots.release(peer[0])

    @staticmethod
    def _disconnect(conn, message):
        conn.sendall(mc_protocol.packet(0, mc_protocol.write_string(mc_protocol.disconnect_json(message))))
