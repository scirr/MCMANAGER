import contextlib
import http.client
import json
import os
import socket
import sys
import tempfile
import time
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import mc_httpapi
import mc_servers


class UnixConnection(http.client.HTTPConnection):
    def __init__(self, path):
        super().__init__("localhost")
        self.path = path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(10)
        self.sock.connect(self.path)


class Client:
    """Minimal client for the local API; address comes from mc_httpapi.address()."""

    def __init__(self, folder, mode="unix"):
        self.found = mc_httpapi.address(folder, mode)
        self.token = self.found.get("token")

    def connection(self):
        if self.found["mode"] == "unix":
            return UnixConnection(self.found["path"])
        conn = http.client.HTTPConnection(self.found["host"], self.found["port"], timeout=10)
        return conn

    def headers(self, token=True):
        return {"Authorization": "Bearer " + self.token} if self.token and token is True else (
            {"Authorization": "Bearer " + token} if isinstance(token, str) else {})

    def request(self, method, path, body=None, token=True, raw=None, headers=None):
        conn = self.connection()
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        sent = dict(self.headers(token), **(headers or {}))
        if data is not None:
            sent["Content-Type"] = "application/json"
        conn.request(method, path, data, sent)
        response = conn.getresponse()
        payload = response.read()
        conn.close()
        try:
            parsed = json.loads(payload)
        except ValueError:
            parsed = payload.decode()
        return response.status, parsed, response

    def stream(self, path, token=True):
        conn = self.connection()
        conn.request("GET", path, headers=self.headers(token))
        return conn, conn.getresponse()


def read_event(response, timeout=10):
    """Next SSE message as (name, data) skipping comments."""
    end = time.time() + timeout
    name, data = None, []
    while time.time() < end:
        line = response.fp.readline().decode("utf-8")
        if line == "":
            return None
        line = line.rstrip("\n")
        if line == "":
            if name or data:
                return name, "\n".join(data)
            continue
        if line.startswith(":"):
            continue
        key, _, value = line.partition(": ")
        if key == "event":
            name = value
        elif key == "data":
            data.append(value)
    return None


@contextlib.contextmanager
def api_environment(config=None, extra_files=None):
    """A throw-away registry with one server 'a' and a running local API."""
    data = tempfile.mkdtemp()
    folder = tempfile.mkdtemp()
    run = tempfile.mkdtemp()
    cfg = {"port": 1, "rcon_port": 2, "mcrcon_pass": "x", "always_on": 1, "nom_serveur": "a",
           "dossier_backup": os.path.join(data, "bk")}
    cfg.update(config or {})
    with open(os.path.join(folder, "config.json"), "w") as f:
        json.dump(cfg, f)
    with open(os.path.join(folder, "server.properties"), "w") as f:
        f.write("online-mode=false\nlevel-name=world\n")
    os.makedirs(os.path.join(folder, "logs"))
    with open(os.path.join(data, "servers.json"), "w") as f:
        json.dump({"active": "a", "servers": {"a": {"id": 1, "dossier_serveur": folder}}}, f)
    registry = os.path.join(data, "servers.json")
    with mock.patch.object(mc_servers, "REGISTRY_FILE", registry), \
            mock.patch.object(mc_servers, "REGISTRY_DIR", data):
        yield {"data": data, "folder": folder, "run": run}
