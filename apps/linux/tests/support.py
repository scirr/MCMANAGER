import os
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "core"))
sys.path.insert(0, os.path.join(ROOT, "core", "tests"))
sys.path.insert(0, os.path.join(ROOT, "apps", "linux"))

import mc_httpapi  # noqa: E402

from mcmanager_app.client import ApiClient, LocalTransport  # noqa: E402
from mcmanager_app.models import Runner  # noqa: E402


def sync_runner():
    return Runner(spawn=lambda function: function(), dispatch=lambda function, *args: function(*args))


def wait_for(condition, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if condition():
            return True
        time.sleep(0.02)
    return condition()


class FakeClient:
    """Stands in for ApiClient in model tests."""

    def __init__(self):
        self.servers = []
        self.player_docs = {}
        self.calls = []
        self.fail = {}
        self.action_status = 200
        self.streams = []

    def _check(self, name):
        if name in self.fail:
            from mcmanager_app.client import ApiError
            raise ApiError(self.fail[name])

    def list_servers(self):
        self._check("list")
        return self.servers

    def players(self, name):
        self._check("players")
        return self.player_docs.get(name, {"online": 0, "max": 20, "players": []})

    def action(self, name, action):
        self.calls.append((name, action))
        self._check(action)
        return self.action_status, {"id": "j1"}

    def wait_job(self, job_id):
        self.calls.append(("wait", job_id))
        self._check("wait")
        return {}

    def config(self, name):
        self._check("config")
        return {"config": {"port": 25565}, "secrets_set": ["mcrcon_pass"]}

    def send_command(self, name, command):
        self.calls.append((name, "cmd", command))
        self._check("cmd")
        return {}

    def events(self, on_message, on_state=None, **kwargs):
        stream = FakeStream(on_message, on_state)
        self.streams.append(stream)
        return stream

    def console(self, name, on_message, on_state=None, **kwargs):
        stream = FakeStream(on_message, on_state)
        self.streams.append(stream)
        return stream


class FakeStream:
    def __init__(self, on_message, on_state):
        self.on_message, self.on_state = on_message, on_state
        self.started = self.stopped = False

    def start(self):
        self.started = True
        return self

    def stop(self):
        self.stopped = True


def local_client(env):
    transport = LocalTransport.discover(env["run"])
    return ApiClient(transport)


def start_api(env, **kwargs):
    api = mc_httpapi.LocalApi(folder=env["run"], mode="unix", enabled=lambda: True, settle=0.3, **kwargs)
    api.sync()
    return api
