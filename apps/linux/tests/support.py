import os
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "core"))
sys.path.insert(0, os.path.join(ROOT, "core", "tests"))
sys.path.insert(0, os.path.join(ROOT, "apps", "linux"))

import mc_httpapi  # noqa: E402
from apiclient import api_environment  # noqa: E402, F401 - re-exported for the tests

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
        self.lists = {}
        self.calls = []
        self.fail = {}
        self.action_status = 200
        self.streams = []
        self.backups = []
        self.mods = []
        self.packs = []
        self.running = True
        self.dimensions = []
        self.pregen = {"progress": "idle"}
        self.tasks = []
        self.config_doc = {"config": {"port": 25565}, "secrets_set": ["mcrcon_pass"]}
        self.java_doc = {"runtimes": {}, "servers": []}
        self.sleep_doc = {"enabled": False, "after_s": 7200, "allow": [], "join_mode": "kick", "hold_timeout_s": 120,
                          "freeze": False}
        self.result = {}

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

    def player_list(self, name, kind):
        self._check("list_" + kind)
        return {"entries": [{"name": n} for n in self.lists.get(kind, [])]}

    def add_to_list(self, name, kind, subject, reason=None):
        self._check("add")
        self.calls.append(("add", kind, subject))
        self.lists.setdefault(kind, []).append(subject)
        return {"ok": True}

    def remove_from_list(self, name, kind, subject):
        self._check("remove")
        self.calls.append(("remove", kind, subject))
        self.lists[kind].remove(subject)
        return {"ok": True}

    def kick(self, name, player, reason=None):
        self._check("kick")
        self.calls.append(("kick", player))
        return {"ok": True}

    def action(self, name, action):
        self.calls.append((name, action))
        self._check(action)
        return self.action_status, {"id": "j1"}

    def wait_job(self, job_id, on_progress=None):
        self.calls.append(("wait", job_id))
        if on_progress:
            on_progress(40)
        self._check("wait")
        return dict(self.result)

    def list_backups(self, name):
        self._check("backups")
        return {"backups": self.backups}

    def create_backup(self, name):
        self._check("create_backup")
        self.calls.append(("backup", name))
        return {"id": "jb"}

    def restore_backup(self, name, backup):
        self._check("restore_backup")
        self.calls.append(("restore", backup))
        return {"id": "jr"}

    def config(self, name):
        self._check("config")
        return self.config_doc

    def _record(self, key, *call):
        self._check(key)
        self.calls.append((key,) + call)
        return {"id": "j_" + key, **self.result}

    def list_mods(self, name):
        self._check("list_mods")
        return {"mods": self.mods}

    def add_mod(self, name, ref, source=None, server_only=False):
        return self._record("add_mod", ref, source, server_only)

    def remove_mod(self, name, mod, confirm_blocks=False):
        return self._record("remove_mod", mod, confirm_blocks)

    def update_mods(self, name, target=None):
        return self._record("update_mods", target)

    def list_datapacks(self, name):
        self._check("list_datapacks")
        return {"running": self.running, "packs": self.packs}

    def set_datapack(self, name, pack, enabled, placement=None):
        return self._record("set_datapack", pack, enabled, placement)

    def list_worlds(self, name):
        self._check("list_worlds")
        return {"dimensions": self.dimensions, "size_bytes": sum(d.get("size_bytes", 0) for d in self.dimensions)}

    def pregen_status(self, name):
        self._check("pregen_status")
        return self.pregen

    def start_pregen(self, name, radius, center=None):
        return self._record("start_pregen", radius, center)

    def reset_dimension(self, name, dimension, include_overworld=False):
        return self._record("reset_dimension", dimension, include_overworld)

    def list_tasks(self, name):
        self._check("list_tasks")
        return {"tasks": self.tasks}

    def create_task(self, name, action, cron, task_name=None, command=None, warn=None):
        return self._record("create_task", action, cron, task_name, command, warn)

    def update_task(self, name, task, enabled):
        return self._record("update_task", task, enabled)

    def delete_task(self, name, task):
        return self._record("delete_task", task)

    def run_task(self, name, task, skip_warn=False):
        return self._record("run_task", task, skip_warn)

    def set_config_value(self, name, key, value):
        return self._record("set_config", key, value)

    def set_mode(self, name, mode):
        return self._record("set_mode", mode)

    def set_schedule(self, name, *times):
        return self._record("set_schedule", *times)

    def sleep_settings(self, name):
        self._check("sleep_settings")
        return self.sleep_doc

    def set_sleep(self, name, **fields):
        return self._record("set_sleep", fields)

    def server_java(self, name):
        self._check("server_java")
        return self.java_doc

    def set_server_java(self, name, choice):
        return self._record("set_java", choice)

    def create_server(self, name, loader, accept_eula, version=None, ram=None, port=None, rcon_port=None):
        return self._record("create_server", name, loader, version, ram, port, rcon_port)

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
