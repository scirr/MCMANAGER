"""
mc_metrics.py — Prometheus text exposition (format 0.0.4) of every
registered server, served over HTTP, plus the sampling shared with the
status page.

Sampling is cached for CACHE_TTL seconds so that scrapers never hammer RCON.
"""
import ipaddress
import logging
import os
import re
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(BASE_DIR)

import mc_api
import mc_config
import mc_core
import mc_servers
from mc_platform import plat

DEFAULT_BIND = "127.0.0.1:9225"
CACHE_TTL = 10
CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"

TPS_COMMANDS = {
    "paper": "tps", "purpur": "tps", "spigot": "tps", "folia": "tps", "pufferfish": "tps",
    "neoforge": "neoforge tps", "forge": "forge tps",
}

_FORMATTING = re.compile(r"§.")
_PAPER_TPS = re.compile(r"TPS from last[^:]*:\s*([^\r\n]+)", re.IGNORECASE)
_FORGE_TPS = re.compile(r"^\s*(?P<label>[^\r\n]+?):\s*Mean tick time:\s*[\d.,]+\s*ms\.\s*Mean TPS:\s*(?P<tps>[\d.,]+)",
                        re.IGNORECASE | re.MULTILINE)


# ── bind address ─────────────────────────────────────────────────────────────

def parse_bind(text):
    """'host:port' -> (host, port). ValueError if malformed."""
    value = str(text or "").strip()
    match = re.fullmatch(r"\[([^\]]+)\]:(\d{1,5})|([^:\[\]]*):(\d{1,5})", value)
    if not match:
        raise ValueError(text)
    host = match.group(1) if match.group(1) is not None else match.group(3)
    port = int(match.group(2) or match.group(4))
    if not 0 <= port <= 65535:
        raise ValueError(text)
    return host, port


def is_local_host(host):
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


# ── TPS ──────────────────────────────────────────────────────────────────────

def tps_command(loader):
    return TPS_COMMANDS.get(str(loader or "").strip().lower())


def _number(text):
    try:
        return float(str(text).strip().lstrip("*").replace(",", "."))
    except ValueError:
        return None


def parse_tps(text):
    """TPS from the reply of 'tps' (Paper, Purpur), 'forge tps' or
    'neoforge tps'; None if the reply holds none."""
    clean = _FORMATTING.sub("", text or "")
    match = _PAPER_TPS.search(clean)
    if match:
        first = match.group(1).split(",")[0]
        return _number(first)
    lines = [(m.group("label").strip().lower(), _number(m.group("tps"))) for m in _FORGE_TPS.finditer(clean)]
    lines = [(label, value) for label, value in lines if value is not None]
    if not lines:
        return None
    for label, value in lines:
        if label == "overall":
            return value
    for label, value in lines:
        if "overworld" in label:
            return value
    return min(value for _, value in lines)


# ── sampling ─────────────────────────────────────────────────────────────────

def proc_cpu_seconds(pid):
    """User + system CPU time of a process in seconds, or None."""
    return plat.process_cpu_seconds(pid)


def last_backup_timestamp(config):
    """Modification time of the newest backup archive, or None."""
    root = config.get("dossier_backup") or ""
    newest = None
    try:
        for day in os.scandir(root):
            if not day.is_dir():
                continue
            for entry in os.scandir(day.path):
                if entry.name.endswith(".zip") and entry.is_file():
                    mtime = entry.stat().st_mtime
                    if newest is None or mtime > newest:
                        newest = mtime
    except OSError:
        pass
    return newest


def sample_server(name, config):
    """Everything the exporter and the status page report about one server."""
    state = mc_api.server_state(config)
    loader, version = mc_core.guess_loader_and_version(config)
    sample = {
        "name": name, "state": state, "loader": loader, "version": version,
        "players_online": None, "players_max": None, "players": [],
        "rss_bytes": None, "cpu_seconds": None, "uptime_s": None, "tps": None,
        "backup_ts": last_backup_timestamp(config),
    }
    if state in ("running", "starting"):
        pid = mc_api._main_pid(config)
        if pid:
            rss_kb, _ = mc_core.proc_memory(pid)
            sample["rss_bytes"] = rss_kb * 1024 if rss_kb is not None else None
            sample["cpu_seconds"] = proc_cpu_seconds(pid)
            sample["uptime_s"] = mc_api._uptime_seconds(pid)
    if state == "running":
        ok, data = mc_api.query_players(config)
        if ok:
            sample["players_online"], sample["players_max"] = data["online"], data["max"]
            sample["players"] = data["players"]
        command = tps_command(loader)
        if command:
            ok, reply = mc_api.rcon_exec(config, command)
            if ok:
                sample["tps"] = parse_tps(reply)
    return sample


class Collector:
    """Per-server samples cached for `ttl` seconds."""

    def __init__(self, sampler=sample_server, clock=time.time, ttl=CACHE_TTL):
        self.sampler, self.clock, self.ttl = sampler, clock, ttl
        self.cache = {}
        self.lock = threading.Lock()

    def sample(self, name, config):
        with self.lock:
            now = self.clock()
            hit = self.cache.get(name)
            if hit and now - hit[0] < self.ttl:
                return hit[1]
            sample = self.sampler(name, config)
            self.cache[name] = (now, sample)
            return sample

    def samples(self, servers):
        """Samples for {name: info}; a server that cannot be read is skipped."""
        out = []
        for name, info in servers.items():
            dossier = info.get("dossier_serveur", "")
            try:
                if not os.path.isdir(dossier):
                    continue
                config = mc_config.load_config(dossier)
                config["dossier_serveur"] = dossier
                out.append(self.sample(name, config))
            except Exception as e:
                logging.warning(f"[{name}] Metrics sampling failed: {e}")
        return out


COLLECTOR = Collector()


# ── exposition ───────────────────────────────────────────────────────────────

def _escape_label(value):
    return str(value).replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _escape_help(text):
    return text.replace("\\", "\\\\").replace("\n", "\\n")


def _format_value(value):
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    return repr(float(value))


class Exposition:
    def __init__(self):
        self.families = {}

    def add(self, name, mtype, help_text, labels, value):
        if value is None:
            return
        family = self.families.setdefault(name, (mtype, help_text, []))
        family[2].append((labels, value))

    def render(self):
        lines = []
        for name, (mtype, help_text, series) in self.families.items():
            lines.append(f"# HELP {name} {_escape_help(help_text)}")
            lines.append(f"# TYPE {name} {mtype}")
            for labels, value in series:
                label_text = ",".join(f'{k}="{_escape_label(v)}"' for k, v in labels.items())
                lines.append(f"{name}{{{label_text}}} {_format_value(value)}")
        return "\n".join(lines) + "\n"


def exposition(samples):
    out = Exposition()
    for s in samples:
        base = {"server": s["name"]}
        out.add("mcm_server_up", "gauge", "1 when the server is running and accepting RCON, 0 otherwise.",
                base, 1 if s["state"] == "running" else 0)
        for state in mc_api.STATES:
            out.add("mcm_server_state", "gauge", "Server state, one series per state (1 for the current one).",
                    {**base, "state": state}, 1 if s["state"] == state else 0)
        out.add("mcm_players_online", "gauge", "Players currently connected.", base, s["players_online"])
        out.add("mcm_players_max", "gauge", "Maximum number of players.", base, s["players_max"])
        out.add("mcm_jvm_rss_bytes", "gauge", "Resident memory of the server JVM.", base, s["rss_bytes"])
        out.add("mcm_jvm_cpu_seconds_total", "counter", "CPU time used by the server JVM.", base, s["cpu_seconds"])
        out.add("mcm_tps", "gauge", "Server ticks per second (1 minute average where the server reports it).",
                base, s["tps"])
        out.add("mcm_backup_last_success_timestamp", "gauge",
                "Unix time of the newest backup archive.", base, s["backup_ts"])
        out.add("mcm_uptime_seconds", "gauge", "Seconds since the server JVM started.", base, s["uptime_s"])
    return out.render()


def render(servers=None, collector=None):
    if servers is None:
        servers = mc_servers.list_servers()
    return exposition((collector or COLLECTOR).samples(servers))


# ── HTTP ─────────────────────────────────────────────────────────────────────

def make_server(bind, allow_remote=False, body=render):
    """A ThreadingHTTPServer bound to `bind`, not yet serving. ValueError for a
    malformed address, PermissionError for a non-local one without
    allow_remote, OSError if the port cannot be bound."""
    host, port = parse_bind(bind)
    if not allow_remote and not is_local_host(host):
        raise PermissionError(bind)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.split("?", 1)[0] != "/metrics":
                self.send_error(404)
                return
            try:
                payload = body().encode("utf-8")
            except Exception as e:
                logging.error(f"Metrics rendering failed: {e}")
                self.send_error(500)
                return
            self.send_response(200)
            self.send_header("Content-Type", CONTENT_TYPE)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    class Server(ThreadingHTTPServer):
        daemon_threads = True
        address_family = socket.AF_INET6 if ":" in host else socket.AF_INET

    return Server((host, port), Handler)


class DaemonEndpoint:
    """Serves /metrics from a thread while a registered server's config.json
    defines `metrics_bind`; follows changes of that key."""

    def __init__(self, maker=make_server):
        self.maker = maker
        self.current = None
        self.server = None
        self.failed = None

    @staticmethod
    def wanted(servers):
        for info in servers.values():
            try:
                config = mc_config.load_config(info.get("dossier_serveur", ""))
            except Exception:
                continue
            bind = str(config.get("metrics_bind") or "").strip()
            if bind:
                return bind, config.get("metrics_allow_remote", 0) == 1
        return None

    def sync(self, servers):
        wanted = self.wanted(servers)
        if wanted == self.current or (wanted and wanted == self.failed):
            return
        self.stop()
        self.failed = None
        if not wanted:
            return
        try:
            self.server = self.maker(*wanted)
        except (ValueError, PermissionError, OSError) as e:
            self.failed = wanted
            logging.error(f"Metrics endpoint {wanted[0]} not started: {e}")
            return
        threading.Thread(target=self.server.serve_forever, daemon=True, name="metrics").start()
        self.current = wanted
        logging.info(f"Metrics served on {wanted[0]}.")

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
        self.server = None
        self.current = None
