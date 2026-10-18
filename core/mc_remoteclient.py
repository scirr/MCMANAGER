"""
mc_remoteclient.py — Client of the remote API: profiles (remotes.json, 0600), TLS with
the server certificate pinned by its SHA-256 fingerprint, and the calls `mc --remote`
makes. No CA is consulted: only a certificate matching the pinned fingerprint is trusted.
"""
import hmac
import http.client
import json
import os
import socket
import ssl
import time

import mc_api
import mc_remote
import mc_servers
from mc_platform import plat

PROFILES_FILE = "remotes.json"
TIMEOUT_S = 20


class FingerprintMismatch(Exception):
    def __init__(self, expected, presented):
        super().__init__("fingerprint_mismatch")
        self.expected = expected
        self.presented = presented


def profiles_path():
    return os.path.join(os.path.dirname(mc_servers.REGISTRY_FILE), PROFILES_FILE)


def load_profiles():
    try:
        return mc_servers.read_json(profiles_path(), {})
    except mc_servers.DataFileError:
        return {}


def save_profiles(profiles):
    plat.write_private_file(profiles_path(), json.dumps(profiles, indent=2, ensure_ascii=False))


def client_context(minimum=ssl.TLSVersion.TLSv1_3, maximum=None):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    context.minimum_version = minimum
    if maximum is not None:
        context.maximum_version = maximum
    return context


def same_fingerprint(left, right):
    return hmac.compare_digest(str(left).upper().encode(), str(right).upper().encode())


class PinnedConnection(http.client.HTTPSConnection):
    """HTTPS connection that accepts one certificate only. Without a pin, it records the one presented."""

    def __init__(self, host, port, pin=None, timeout=TIMEOUT_S, context=None):
        super().__init__(host, port, timeout=timeout, context=context or client_context())
        self.pin = pin
        self.presented = None

    def connect(self):
        raw = socket.create_connection((self.host, self.port), self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except Exception:
            raw.close()
            raise
        self.presented = mc_remote.format_fingerprint(self.sock.getpeercert(binary_form=True))
        if self.pin is not None and not same_fingerprint(self.pin, self.presented):
            self.sock.close()
            self.sock = None
            raise FingerprintMismatch(self.pin, self.presented)


def split_address(text):
    host, sep, port = text.strip().rpartition(":")
    if not sep or not port.isdigit() or not 0 < int(port) < 65536 or not host:
        raise ValueError(text)
    return host.strip("[]"), int(port)


def fetch_fingerprint(host, port):
    """The fingerprint of the certificate a server presents (to confirm before pinning)."""
    conn = PinnedConnection(host, port)
    try:
        conn.connect()
        return conn.presented
    finally:
        conn.close()


class Remote:
    """One paired server: JSON calls with the pinned fingerprint and the device token."""

    def __init__(self, host, port, fingerprint, token=None, context=None):
        self.host, self.port, self.fingerprint, self.token, self.context = host, port, fingerprint, token, context

    @classmethod
    def from_profile(cls, name):
        profile = load_profiles().get(name)
        if not profile:
            return None
        return cls(profile["host"], profile["port"], profile["fingerprint"], profile.get("token"))

    def connection(self, timeout=TIMEOUT_S):
        return PinnedConnection(self.host, self.port, self.fingerprint, timeout, self.context)

    def headers(self):
        return {"Authorization": "Bearer " + self.token} if self.token else {}

    def request(self, method, path, body=None):
        """(status, document); a transport failure is a document with ok false."""
        conn = self.connection()
        try:
            headers = self.headers()
            data = None
            if body is not None:
                data = json.dumps(body).encode()
                headers["Content-Type"] = "application/json"
            conn.request(method, path, data, headers)
            response = conn.getresponse()
            payload = response.read()
        except FingerprintMismatch as exc:
            return 0, mc_api.result(False, "fingerprint_mismatch", expected=exc.expected, presented=exc.presented)
        except (OSError, http.client.HTTPException) as exc:
            return 0, mc_api.result(False, "remote_unreachable", detail=type(exc).__name__)
        finally:
            conn.close()
        try:
            document = json.loads(payload)
        except ValueError:
            document = mc_api.result(False, "bad_remote_answer")
        if not isinstance(document, dict):
            document = mc_api.result(False, "bad_remote_answer")
        document.pop("schema", None)
        return response.status, document

    def stream(self, path):
        """(connection, response) of a Server-Sent Events route; the caller closes the connection."""
        conn = self.connection(timeout=60)
        conn.request("GET", path, headers=self.headers())
        return conn, conn.getresponse()

    def job(self, document, wait_s=3600, step=1.0):
        """Follow a 202 job document to its end; returns the job's own result."""
        job_id = document.get("id")
        end = time.time() + wait_s
        while time.time() < end:
            status, current = self.request("GET", f"/v1/jobs/{job_id}")
            if status != 200:
                return current
            if current.get("state") in ("succeeded", "failed", "cancelled"):
                result = current.get("result")
                if isinstance(result, dict):
                    result.pop("schema", None)
                    return result
                return mc_api.result(False, "job_" + current["state"], id=job_id)
            time.sleep(step)
        return mc_api.result(False, "daemon_timeout", id=job_id)


def pair(host, port, fingerprint, code, name):
    """Exchange a pairing code; returns (document, Remote or None)."""
    remote = Remote(host, port, fingerprint)
    status, document = remote.request("POST", "/v1/pair", {"code": code, "name": name})
    if status == 201 and document.get("ok") and document.get("token"):
        if not same_fingerprint(document.get("fingerprint", fingerprint), fingerprint):
            return mc_api.result(False, "fingerprint_mismatch"), None
        remote.token = document["token"]
        return document, remote
    document["ok"] = False
    return document, None
