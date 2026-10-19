"""
test_remote.py - the remote API: certificate, pairing, authentication, roles, limits,
audit, separation from the local API, and the `mc --remote` client. Everything runs on
127.0.0.1 with a simulated firewall.
"""
import contextlib
import hashlib
import io
import json
import os
import socket
import ssl
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

import mc_api
import mc_cli
import mc_httpapi
import mc_remote
import mc_remoteclient
import mc_platform
import mc_remoteserver
import mc_servers
from apiclient import Client, api_environment
from mc_remoteclient import Remote
from test_openapi import SPEC
import test_secrets_leak as leaks

FIREWALL = {"firewall_name": "ufw", "firewall_port_open": False, "firewall_allow": (True, ""),
            "firewall_remove": True, "firewall_manual_command": "fw-open"}


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def slurp(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class RemoteCase(unittest.TestCase):
    start_remote = True

    def setUp(self):
        manager = api_environment()
        self.env = manager.__enter__()
        self.addCleanup(manager.__exit__, None, None, None)
        self.certs = tempfile.mkdtemp()
        self.logs = tempfile.mkdtemp()
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(mock.patch.object(mc_remote, "CERT_DIR", self.certs))
        stack.enter_context(mock.patch.object(mc_remote, "LOGS_DIR", self.logs))
        stack.enter_context(mock.patch.object(mc_remote, "PAIR_DELAY_S", 0))
        self.firewall = {}
        for name, value in FIREWALL.items():
            self.firewall[name] = stack.enter_context(mock.patch.object(mc_platform._load(), name, mock.Mock(return_value=value)))
        mc_remote._PAIRING["locks"].clear()
        mc_remote._SEEN.clear()
        mc_remote._CACHE.clear()
        self.api = None
        self.local = None
        if self.start_remote:
            self.start_api()

    def start_api(self):
        self.api = mc_remoteserver.RemoteApi(enabled=lambda: True, bind="127.0.0.1:0", settle=0.3)
        self.api.sync()
        self.addCleanup(self.api.stop)
        self.port = self.api.server.server_address[1]
        self.fingerprint = mc_remote.certificate_info()["fingerprint"]

    def remote(self, token=None, fingerprint=None):
        return Remote("127.0.0.1", self.port, fingerprint or self.fingerprint, token)

    def pair(self, role="operator", servers=None, name="phone"):
        code = mc_remote.create_code(role, servers)["pairing_code"]
        remote = self.remote()
        status, document = remote.request("POST", "/v1/pair", {"code": code, "name": name})
        self.assertEqual(status, 201, document)
        remote.token = document["token"]
        remote.device_id = document["device_id"]
        return remote

    def add_server(self, name):
        folder = tempfile.mkdtemp()
        with open(os.path.join(folder, "config.json"), "w") as f:
            json.dump({"port": 1, "rcon_port": 2, "mcrcon_pass": "x", "always_on": 1, "nom_serveur": name}, f)
        with open(os.path.join(folder, "server.properties"), "w") as f:
            f.write("online-mode=false\nlevel-name=world\n")
        os.makedirs(os.path.join(folder, "logs"))
        registry = mc_servers.load_registry()
        registry["servers"][name] = {"id": len(registry["servers"]) + 1, "dossier_serveur": folder}
        mc_servers.save_registry(registry)
        return folder

    def read_everything(self):
        text = ""
        for folder in (self.env["data"], self.certs, self.logs):
            for root, _dirs, files in os.walk(folder):
                for name in files:
                    path = os.path.join(root, name)
                    if os.path.getsize(path) < 5 << 20:
                        with open(path, "rb") as f:
                            text += f.read().decode("utf-8", "replace") + "\n"
        return text

    def tls_socket(self, maximum=None):
        context = mc_remoteclient.client_context(ssl.TLSVersion.MINIMUM_SUPPORTED, maximum)
        raw = socket.create_connection(("127.0.0.1", self.port), timeout=5)
        return context.wrap_socket(raw, server_hostname="127.0.0.1")


class TestDisabledByDefault(RemoteCase):
    start_remote = False

    def test_nothing_listens_until_enabled(self):
        self.assertFalse(mc_remote.load_settings()["enabled"])
        api = mc_remoteserver.RemoteApi()
        api.sync()
        self.assertIsNone(api.server)
        self.assertFalse(os.path.exists(os.path.join(self.env["data"], "remote.json")))

    @unittest.skipIf(sys.platform == "win32", "POSIX-only behavior")
    def test_enable_writes_private_settings_and_opens_the_port_with_the_label(self):
        res = mc_remote.set_access(True, "0.0.0.0:8765")
        self.assertEqual((res["ok"], res["code"], res["firewall"]), (True, "remote_enabled", "opened"))
        path = os.path.join(self.env["data"], "remote.json")
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        self.assertEqual(load(path), {"enabled": True, "bind": "0.0.0.0:8765"})
        self.firewall["firewall_allow"].assert_called_once_with(8765, "tcp", "API")
        res = mc_remote.set_access(False)
        self.assertEqual((res["code"], res["firewall"]), ("remote_disabled", "closed"))
        self.firewall["firewall_remove"].assert_called_once_with(8765, "tcp", "API")
        self.assertFalse(mc_remote.load_settings()["enabled"])

    def test_default_bind_and_loopback_never_touch_the_firewall(self):
        self.assertEqual(mc_remote.set_access(True)["bind"], "0.0.0.0:8765")
        self.firewall["firewall_allow"].reset_mock()
        res = mc_remote.set_access(True, "127.0.0.1:9000")
        self.assertEqual(res["firewall"], "skipped")
        self.firewall["firewall_allow"].assert_not_called()

    def test_manual_command_when_the_firewall_refuses(self):
        self.firewall["firewall_allow"].return_value = (False, "denied")
        res = mc_remote.set_access(True, "0.0.0.0:8765")
        self.assertEqual((res["ok"], res["firewall"], res["firewall_command"]), (True, "manual", "fw-open"))

    def test_bad_bind_is_refused_and_leaves_remote_off(self):
        for bind in ("nonsense", "0.0.0.0", "host:80", "1.2.3.4:99999"):
            res = mc_remote.set_access(True, bind)
            self.assertEqual((res["ok"], res["code"]), (False, "bad_bind"), bind)
        self.assertFalse(mc_remote.load_settings()["enabled"])

    def test_daemon_follows_the_setting(self):
        api = mc_remoteserver.RemoteApi(bind="127.0.0.1:0")
        self.addCleanup(api.stop)
        mc_remote.set_access(True, "127.0.0.1:0")
        api.sync()
        self.assertTrue(api.alive())
        mc_remote.set_access(False)
        api.sync()
        self.assertIsNone(api.server)

    def test_cli_enable_status_disable(self):
        def run(*argv):
            out = io.StringIO()
            with mock.patch.object(sys, "argv", ["mc", *argv]), contextlib.redirect_stdout(out):
                code = mc_cli.main()
            return code or 0, out.getvalue()
        code, text = run("remote", "status", "--json")
        self.assertEqual((code, json.loads(text)["enabled"]), (0, False))
        code, text = run("remote", "enable", "--bind", "127.0.0.1:0", "--json")
        document = json.loads(text)
        self.assertEqual((code, document["code"], document["tls"] in ("cryptography", "openssl")), (0, "remote_enabled", True))
        self.assertRegex(document["fingerprint"], r"^([0-9A-F]{2}:){31}[0-9A-F]{2}$")
        code, text = run("remote", "status")
        self.assertIn("127.0.0.1:0", text)
        self.assertEqual(run("remote", "disable", "--json")[0], 0)


class TestCertificate(RemoteCase):
    start_remote = False

    @unittest.skipIf(sys.platform == "win32", "POSIX-only behavior")
    def test_each_available_generator_makes_a_p256_ten_year_private_certificate(self):
        available = [name for name, _ in mc_remote.generators()]
        self.assertTrue(available)
        for name in available:
            with self.subTest(generator=name):
                folder = tempfile.mkdtemp()
                with mock.patch.object(mc_remote, "CERT_DIR", folder):
                    info = mc_remote.ensure_certificate("127.0.0.1", prefer=name)
                    self.assertEqual(info["generator"], name)
                    self.assertEqual(stat.S_IMODE(os.stat(info["key"]).st_mode), 0o600)
                    self.assertRegex(info["fingerprint"], r"^([0-9A-F]{2}:){31}[0-9A-F]{2}$")
                    shown = subprocess.run(["openssl", "x509", "-in", info["cert"], "-noout", "-text", "-enddate"],
                                           capture_output=True, text=True).stdout if mc_remote.openssl_path() else ""
                    if shown:
                        self.assertIn("prime256v1", shown)
                        self.assertIn("IP Address:127.0.0.1", shown)
                    again = mc_remote.ensure_certificate("127.0.0.1")
                    self.assertEqual(again["fingerprint"], info["fingerprint"])

    @unittest.skipUnless(mc_remote.have_cryptography(), "cryptography missing")
    def test_cryptography_certificate_content(self):
        from cryptography import x509
        from cryptography.hazmat.primitives.asymmetric import ec
        info = mc_remote.ensure_certificate("127.0.0.1", prefer="cryptography")
        with open(info["cert"], "rb") as f:
            cert = x509.load_pem_x509_certificate(f.read())
        self.assertIsInstance(cert.public_key().curve, ec.SECP256R1)
        days = (cert.not_valid_after - cert.not_valid_before).days
        self.assertTrue(3649 <= days <= 3652, days)
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        self.assertEqual([str(ip) for ip in san.get_values_for_type(x509.IPAddress)], ["127.0.0.1"])
        self.assertTrue(san.get_values_for_type(x509.DNSName))

    @unittest.skipUnless(mc_remote.openssl_path(), "openssl missing")
    def test_openssl_route_uses_an_argument_list_never_a_shell(self):
        with mock.patch.object(mc_remote, "have_cryptography", return_value=False), \
                mock.patch.object(mc_remote.subprocess, "run", wraps=subprocess.run) as run:
            info = mc_remote.ensure_certificate("0.0.0.0")
        self.assertEqual(info["generator"], "openssl")
        command = run.call_args[0][0]
        self.assertIsInstance(command, list)
        self.assertIn("ec_paramgen_curve:P-256", command)
        self.assertNotIn("shell", run.call_args[1])

    def test_no_generator_means_a_clear_refusal_and_no_listener(self):
        with mock.patch.object(mc_remote, "have_cryptography", return_value=False), \
                mock.patch.object(mc_remote, "openssl_path", return_value=None):
            res = mc_remote.set_access(True, "127.0.0.1:0")
            api = mc_remoteserver.RemoteApi(enabled=lambda: True, bind="127.0.0.1:0")
            with self.assertLogs(level="ERROR"):
                api.sync()
        self.assertEqual((res["ok"], res["code"]), (False, "tls_unavailable"))
        self.assertEqual(mc_httpapi.status_for("tls_unavailable"), 422)
        self.assertFalse(mc_remote.load_settings()["enabled"])
        self.assertIsNone(api.server)
        self.assertFalse(mc_remote.certificate_info())

    def test_failing_generator_leaves_no_half_certificate(self):
        with mock.patch.object(mc_remote, "have_cryptography", return_value=False), \
                mock.patch.object(mc_remote, "openssl_path", return_value="/nonexistent/openssl"):
            self.assertIsNone(mc_remote.ensure_certificate("127.0.0.1"))
        self.assertFalse(os.path.exists(os.path.join(self.certs, "cert.pem")))

    def test_server_context_is_tls13_only(self):
        info = mc_remote.ensure_certificate("127.0.0.1")
        context = mc_remoteserver.server_context(info)
        self.assertEqual(context.minimum_version, ssl.TLSVersion.TLSv1_3)


class TestPairing(RemoteCase):

    @unittest.skipIf(sys.platform == "win32", "POSIX-only behavior")
    def test_full_pairing_returns_a_token_once_and_stores_only_hashes(self):
        created = mc_remote.create_code("operator", None)
        self.assertRegex(created["pairing_code"], r"^[0-9]{8}$")
        self.assertEqual(created["expires_in_s"], 300)
        code = created["pairing_code"]
        remote = self.remote()
        status, document = remote.request("POST", "/v1/pair", {"code": code, "name": "Phone"})
        self.assertEqual((status, document["code"]), (201, "paired"))
        token = document["token"]
        self.assertTrue(len(token) >= 43)
        self.assertEqual(document["fingerprint"], self.fingerprint)
        self.assertEqual(document["roles"], {"default": "operator"})
        remote.token = token
        status, listing = remote.request("GET", "/v1/servers")
        self.assertEqual(status, 200)
        everything = self.read_everything()
        self.assertNotIn(token, everything)
        self.assertNotIn(code, everything)
        devices = load(os.path.join(self.env["data"], "remote_devices.json"))["devices"]
        self.assertEqual(devices[document["device_id"]]["token_hash"], hashlib.sha256(token.encode()).hexdigest())
        mode = stat.S_IMODE(os.stat(os.path.join(self.env["data"], "remote_devices.json")).st_mode)
        self.assertEqual(mode, 0o600)
        pairing = os.path.join(self.env["data"], "remote_pairing.json")
        self.assertFalse(os.path.exists(pairing))

    @unittest.skipIf(sys.platform == "win32", "POSIX-only behavior")
    def test_code_is_stored_hashed_with_its_role_while_waiting(self):
        created = mc_remote.create_code("viewer", None)
        path = os.path.join(self.env["data"], "remote_pairing.json")
        stored = load(path)
        self.assertNotIn(created["pairing_code"], json.dumps(stored))
        self.assertEqual((stored["role"], len(stored["hash"])), ("viewer", 64))
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)

    def test_the_token_is_never_listed(self):
        admin = self.pair("admin")
        status, body = admin.request("GET", "/v1/devices")
        self.assertEqual(status, 200)
        self.assertNotIn(admin.token, json.dumps(body))
        self.assertNotIn("token", json.dumps(body))

    def test_expired_code(self):
        code = mc_remote.create_code()["pairing_code"]
        path = os.path.join(self.env["data"], "remote_pairing.json")
        stored = load(path)
        stored["expires"] = time.time() - 1
        with open(path, "w") as f:
            json.dump(stored, f)
        status, document = self.remote().request("POST", "/v1/pair", {"code": code, "name": "x"})
        self.assertEqual((status, document["code"]), (422, "bad_pair_code"))

    def test_code_is_single_use(self):
        code = mc_remote.create_code()["pairing_code"]
        self.assertEqual(self.remote().request("POST", "/v1/pair", {"code": code, "name": "a"})[0], 201)
        status, document = self.remote().request("POST", "/v1/pair", {"code": code, "name": "b"})
        self.assertEqual((status, document["code"]), (422, "bad_pair_code"))

    def test_a_new_code_replaces_the_previous_one(self):
        first = mc_remote.create_code()["pairing_code"]
        second = mc_remote.create_code()["pairing_code"]
        if first != second:
            self.assertEqual(self.remote().request("POST", "/v1/pair", {"code": first, "name": "a"})[0], 422)
        self.assertEqual(self.remote().request("POST", "/v1/pair", {"code": second, "name": "a"})[0], 201)

    def test_five_wrong_codes_cancel_the_current_code(self):
        code = mc_remote.create_code()["pairing_code"]
        wrong = "00000000" if code != "00000000" else "11111111"
        for _ in range(mc_remote.CODE_MAX_FAILS):
            self.assertEqual(self.remote().request("POST", "/v1/pair", {"code": wrong, "name": "a"})[0], 422)
        status, document = self.remote().request("POST", "/v1/pair", {"code": code, "name": "a"})
        self.assertEqual((status, document["code"]), (422, "bad_pair_code"))
        self.assertFalse(os.path.exists(os.path.join(self.env["data"], "remote_pairing.json")))

    def test_four_wrong_codes_do_not_cancel_it(self):
        code = mc_remote.create_code()["pairing_code"]
        wrong = "00000000" if code != "00000000" else "11111111"
        for _ in range(mc_remote.CODE_MAX_FAILS - 1):
            self.remote().request("POST", "/v1/pair", {"code": wrong, "name": "a"})
        self.assertEqual(self.remote().request("POST", "/v1/pair", {"code": code, "name": "a"})[0], 201)

    def test_ten_failures_from_one_ip_lock_pairing_for_fifteen_minutes(self):
        for _ in range(mc_remote.PAIR_LOCK_AFTER):
            self.assertEqual(self.remote().request("POST", "/v1/pair", {"code": "00000000", "name": "a"})[0], 422)
        code = mc_remote.create_code()["pairing_code"]
        conn = self.remote().connection()
        conn.request("POST", "/v1/pair", json.dumps({"code": code, "name": "a"}), {"Content-Type": "application/json"})
        response = conn.getresponse()
        body = json.loads(response.read())
        conn.close()
        self.assertEqual((response.status, body["code"]), (429, "pair_locked"))
        self.assertTrue(0 < int(response.getheader("Retry-After")) <= 900)
        lock = mc_remote._PAIRING["locks"]["127.0.0.1"]
        lock["until"] = time.time() - 1
        self.assertEqual(self.remote().request("POST", "/v1/pair", {"code": code, "name": "a"})[0], 201)

    def test_malformed_codes_count_as_failures_and_validate(self):
        status, body = self.remote().request("POST", "/v1/pair", {"code": "abc", "name": "a"})
        self.assertEqual((status, body["code"]), (422, "bad_pair_code"))
        self.assertEqual(self.remote().request("POST", "/v1/pair", {"name": "a"})[0], 422)

    def test_failed_attempts_take_a_constant_minimum_time(self):
        mc_remote.create_code()
        with mock.patch.object(mc_remote, "PAIR_DELAY_S", 0.3):
            for code in ("00000000", "not-a-code"):
                started = time.monotonic()
                self.remote().request("POST", "/v1/pair", {"code": code, "name": "a"})
                self.assertGreaterEqual(time.monotonic() - started, 0.3)
        os.remove(os.path.join(self.env["data"], "remote_pairing.json"))
        with mock.patch.object(mc_remote, "PAIR_DELAY_S", 0.3):
            started = time.monotonic()
            self.remote().request("POST", "/v1/pair", {"code": "00000000", "name": "a"})
            self.assertGreaterEqual(time.monotonic() - started, 0.3)

    def test_pairing_is_the_only_route_without_a_token(self):
        remote = self.remote()
        public = {"getApiInfo", "pairDevice"}
        for route in mc_httpapi.build_routes(SPEC):
            if route.operation_id in public or route.operation_id.startswith("stream"):
                continue
            path = route.template
            for name in ("server", "device", "job", "kind", "key", "backup", "remote", "channel", "task", "major"):
                path = path.replace("{" + name + "}", "a")
            status, body = remote.request(route.method, path, {} if route.method in ("POST", "PUT") else None)
            self.assertEqual((status, body["code"]), (401, "unauthorized"), route.operation_id)
        self.assertEqual(remote.request("GET", "/v1")[0], 200)

    def test_code_carries_role_servers_and_default_name(self):
        self.add_server("b")
        created = mc_remote.create_code("viewer", ["b"], "Tablet")
        self.assertTrue(created["ok"])
        status, doc = self.remote().request("POST", "/v1/pair", {"code": created["pairing_code"], "name": ""})
        self.assertEqual(status, 201)
        device = mc_remote.list_devices()["devices"][0]
        self.assertEqual((device["name"], device["roles"]["default"], device["servers"]), ("Tablet", "viewer", ["b"]))
        self.assertEqual(mc_remote.create_code("viewer", ["zz"])["code"], "bad_servers")
        self.assertEqual(mc_remote.create_code("root")["code"], "bad_role")


class TestAuthentication(RemoteCase):

    def test_unknown_and_missing_tokens_get_a_bare_401(self):
        for token in (None, "nope", "x" * 43):
            status, body = self.remote(token).request("GET", "/v1/servers")
            self.assertEqual((status, body["code"]), (401, "unauthorized"))
            self.assertNotIn("detail", body)
        conn = self.remote("nope").connection()
        conn.request("GET", "/v1/servers", headers={"Authorization": "Basic abc"})
        response = conn.getresponse()
        response.read()
        self.assertEqual((response.status, response.getheader("WWW-Authenticate")), (401, "Bearer"))

    def test_token_comparison_is_constant_time(self):
        remote = self.pair()
        with mock.patch.object(mc_remote.hmac, "compare_digest", wraps=mc_remote.hmac.compare_digest) as compare:
            self.assertEqual(remote.request("GET", "/v1/servers")[0], 200)
        self.assertTrue(compare.called)

    def test_revoked_device_gets_401_at_once(self):
        admin = self.pair("admin")
        phone = self.pair("operator", name="phone")
        self.assertEqual(phone.request("GET", "/v1/servers")[0], 200)
        status, body = admin.request("DELETE", f"/v1/devices/{phone.device_id}")
        self.assertEqual((status, body["code"]), (200, "device_revoked"))
        self.assertEqual(phone.request("GET", "/v1/servers")[0], 401)
        self.assertNotIn(phone.token, self.read_everything())
        self.assertEqual(admin.request("DELETE", "/v1/devices/d_none")[0], 404)
        listed = admin.request("GET", "/v1/devices")[1]["devices"]
        self.assertTrue(next(d for d in listed if d["id"] == phone.device_id)["revoked"])

    def test_revoking_closes_open_streams(self):
        admin = self.pair("admin")
        phone = self.pair("viewer", name="phone")
        conn, response = phone.stream("/v1/events")
        self.assertEqual(response.status, 200)
        self.assertEqual(admin.request("DELETE", f"/v1/devices/{phone.device_id}")[0], 200)
        response.fp.raw._sock.settimeout(5) if hasattr(response.fp, "raw") and hasattr(response.fp.raw, "_sock") else None
        deadline = time.time() + 5
        data = b""
        while time.time() < deadline:
            line = response.fp.readline()
            if not line:
                break
            data += line
        self.assertEqual(response.fp.readline(), b"")
        conn.close()

    def test_cli_can_list_and_revoke_devices(self):
        phone = self.pair("operator", name="phone")

        def run(*argv):
            out = io.StringIO()
            with mock.patch.object(sys, "argv", ["mc", *argv]), contextlib.redirect_stdout(out):
                code = mc_cli.main()
            return code or 0, out.getvalue()
        code, text = run("remote", "devices", "list", "--json")
        listing = json.loads(text)["devices"]
        self.assertEqual([d["name"] for d in listing], ["phone"])
        self.assertNotIn(phone.token, text)
        self.assertEqual(run("remote", "devices", "revoke", phone.device_id)[0], 0)
        self.assertEqual(phone.request("GET", "/v1/servers")[0], 401)
        self.assertEqual(run("remote", "devices", "revoke", "d_none", "--json")[0], 1)

    def test_last_seen_is_recorded_outside_the_device_file(self):
        phone = self.pair()
        phone.request("GET", "/v1/servers")
        device = mc_remote.list_devices()["devices"][0]
        self.assertEqual(device["last_ip"], "127.0.0.1")
        self.assertTrue(device["last_seen"])


class TestRoles(RemoteCase):

    def test_viewer_reads_but_cannot_start(self):
        viewer = self.pair("viewer")
        self.assertEqual(viewer.request("GET", "/v1/servers/a")[0], 200)
        with mock.patch.object(mc_api, "start") as start:
            status, body = viewer.request("POST", "/v1/servers/a/start")
        self.assertEqual((status, body["code"]), (403, "forbidden"))
        start.assert_not_called()

    def test_operator_starts_but_cannot_set_config_or_manage_devices(self):
        operator = self.pair("operator")
        with mock.patch.object(mc_api, "start", return_value=mc_api.result(True, "started", server="a")) as start:
            self.assertEqual(operator.request("POST", "/v1/servers/a/start")[0], 200)
        start.assert_called_once()
        for method, path, body in (("PUT", "/v1/servers/a/config/port", {"value": "25570"}),
                                   ("GET", "/v1/devices", None), ("GET", "/v1/audit", None),
                                   ("GET", "/v1/remote", None),
                                   ("PUT", "/v1/devices/d_x/roles", {"roles": {"default": "admin"}}),
                                   ("DELETE", "/v1/devices/d_x", None)):
            status, answer = operator.request(method, path, body)
            self.assertEqual((status, answer["code"]), (403, "forbidden"), path)

    def test_admin_manages_devices_and_reads_the_audit(self):
        admin = self.pair("admin")
        self.assertEqual(admin.request("GET", "/v1/devices")[0], 200)
        self.assertEqual(admin.request("GET", "/v1/audit")[0], 200)
        status, body = admin.request("GET", "/v1/remote")
        self.assertEqual((status, body["enabled"], body["devices"]), (200, False, 1))
        self.assertEqual(body["fingerprint"], self.fingerprint)

    def test_enabling_and_pairing_codes_are_local_only(self):
        admin = self.pair("admin")
        for method, path, body in (("PUT", "/v1/remote", {"enabled": False}), ("POST", "/v1/pair/codes", {})):
            status, answer = admin.request(method, path, body)
            self.assertEqual((status, answer["code"]), (403, "forbidden"), path)
        self.assertFalse(mc_remote.load_settings()["enabled"])

    def test_role_matrix_over_the_whole_contract(self):
        devices = {role: self.pair(role, name=role) for role in mc_remote.ROLES}
        for route in mc_httpapi.build_routes(SPEC):
            if route.public or route.operation_id.startswith("stream"):
                continue
            needed = route.operation.get("x-mcm-role", "admin")
            path = route.template
            for name in ("server", "device", "job", "kind", "key", "backup", "remote", "channel", "task", "major"):
                path = path.replace("{" + name + "}", "a")
            for role, remote in devices.items():
                denied = route.operation_id in mc_httpapi.LOCAL_ONLY or mc_remote.rank(role) < mc_remote.rank(needed)
                if not denied:
                    continue
                status, body = remote.request(route.method, path, {} if route.method in ("POST", "PUT") else None)
                self.assertEqual((status, body["code"]), (403, "forbidden"), f"{role} {route.operation_id}")

    def test_per_server_role_overrides(self):
        self.add_server("b")
        admin = self.pair("admin")
        viewer = self.pair("viewer", name="v")
        status, body = admin.request("PUT", f"/v1/devices/{viewer.device_id}/roles",
                                     {"roles": {"default": "viewer", "servers": {"a": "operator"}}})
        self.assertEqual((status, body["roles"]["servers"]), (200, {"a": "operator"}))
        with mock.patch.object(mc_api, "start", return_value=mc_api.result(True, "started", server="a")):
            self.assertEqual(viewer.request("POST", "/v1/servers/a/start")[0], 200)
            self.assertEqual(viewer.request("POST", "/v1/servers/b/start")[0], 403)
        self.assertEqual(admin.request("PUT", f"/v1/devices/{viewer.device_id}/roles",
                                       {"roles": {"default": "root"}})[0], 422)
        self.assertEqual(admin.request("PUT", "/v1/devices/d_none/roles", {"roles": {"default": "viewer"}})[0], 404)

    def test_server_restriction_covers_name_id_and_active(self):
        self.add_server("b")
        only_b = self.pair("admin", ["b"], name="b-only")
        for ref in ("a", "1", "active", "nothing"):
            status, body = only_b.request("GET", f"/v1/servers/{ref}")
            self.assertEqual((status, body["code"]), (403, "forbidden"), ref)
        self.assertEqual(only_b.request("GET", "/v1/servers/b")[0], 200)
        self.assertEqual(only_b.request("GET", "/v1/servers/2")[0], 200)
        registry = mc_servers.load_registry()
        registry["active"] = "b"
        mc_servers.save_registry(registry)
        self.assertEqual(only_b.request("GET", "/v1/servers/active")[1]["name"], "b")

    def test_lists_only_show_allowed_servers(self):
        self.add_server("b")
        unrestricted = self.pair("viewer", name="all")
        only_b = self.pair("viewer", ["b"], name="b-only")
        def names(r):
            return [s["name"] for s in r.request("GET", "/v1/servers")[1]["servers"]]
        self.assertEqual(names(unrestricted), ["a", "b"])
        self.assertEqual(names(only_b), ["b"])
        self.assertIsNone(only_b.request("GET", "/v1/servers")[1]["active"])

    def test_restricted_device_is_refused_the_global_routes_that_are_not_filtered(self):
        self.add_server("b")
        only_b = self.pair("admin", ["b"])
        for method, path in (("GET", "/v1/router"), ("GET", "/v1/metrics"), ("GET", "/v1/devices"),
                             ("GET", "/v1/audit"), ("GET", "/v1/remote"), ("POST", "/v1/servers"),
                             ("GET", "/v1/doctor")):
            status, body = only_b.request(method, path, {} if method == "POST" else None)
            self.assertEqual((status, body["code"]), (403, "forbidden"), path)

    def test_jobs_are_filtered_for_restricted_devices(self):
        self.add_server("b")
        only_b = self.pair("operator", ["b"])
        everyone = self.pair("operator", name="all")
        with mock.patch.object(mc_api, "backup_now", return_value=mc_api.result(True, "backup_done")):
            status, job = everyone.request("POST", "/v1/servers/a/backups")
        self.assertIn(status, (200, 202))
        job_id = job.get("id")
        if job_id:
            self.assertEqual(only_b.request("GET", f"/v1/jobs/{job_id}")[0], 404)
            self.assertEqual(only_b.request("DELETE", f"/v1/jobs/{job_id}")[0], 404)
        self.assertEqual(only_b.request("GET", "/v1/jobs")[1]["jobs"], [])

    def test_events_are_filtered_for_restricted_devices(self):
        self.add_server("b")
        only_b = self.pair("viewer", ["b"])
        conn, response = only_b.stream("/v1/events")
        self.assertEqual(response.status, 200)
        app = self.api.app
        deadline = time.time() + 5
        while not app.hub.listening() and time.time() < deadline:
            time.sleep(0.05)
        app.hub.publish({"type": "state", "server": "a", "state": "running"})
        app.hub.publish({"type": "state", "server": "b", "state": "stopped"})
        app.hub.publish({"type": "alert", "event": "update"})
        seen = []
        end = time.time() + 5
        while time.time() < end and not seen:
            line = response.fp.readline().decode()
            if line.startswith("data: "):
                seen.append(json.loads(line[6:]))
        conn.close()
        self.assertEqual([e["server"] for e in seen], ["b"])


class TestLimits(RemoteCase):

    def test_rate_limit_per_device_with_retry_after(self):
        busy = self.pair("viewer", name="busy")
        calm = self.pair("viewer", name="calm")
        self.api.app.remote.limit = 5
        statuses = []
        conn = busy.connection()
        for _ in range(8):
            conn.request("GET", "/v1/servers", headers=busy.headers())
            response = conn.getresponse()
            response.read()
            statuses.append((response.status, response.getheader("Retry-After")))
        conn.close()
        self.assertEqual([s for s, _ in statuses[:5]], [200] * 5)
        self.assertEqual({s for s, _ in statuses[5:]}, {429})
        self.assertGreaterEqual(int(statuses[-1][1]), 1)
        self.assertEqual(calm.request("GET", "/v1/servers")[0], 200)

    def test_sliding_window_releases_after_the_window(self):
        clock = [0.0]
        gate = mc_remote.Gate(clock=lambda: clock[0], limit=20, window=1.0)
        self.assertTrue(all(gate.allow("d")[0] for _ in range(20)))
        allowed, wait = gate.allow("d")
        self.assertFalse(allowed)
        self.assertGreater(wait, 0)
        clock[0] = 1.01
        self.assertTrue(gate.allow("d")[0])
        self.assertEqual(mc_remote.RATE_LIMIT, 20)

    def test_three_console_streams_per_device(self):
        viewer = self.pair("operator", name="one")
        other = self.pair("operator", name="two")
        opened = []
        for _ in range(3):
            conn, response = viewer.stream("/v1/servers/a/console")
            self.assertEqual(response.status, 200)
            opened.append(conn)
        conn, response = viewer.stream("/v1/servers/a/console")
        body = json.loads(response.read())
        conn.close()
        self.assertEqual((response.status, body["code"]), (429, "too_many_streams"))
        other_conn, other_response = other.stream("/v1/servers/a/console")
        self.assertEqual(other_response.status, 200)
        other_conn.close()
        for conn in opened:
            conn.close()

    def test_body_limit_over_tls(self):
        operator = self.pair("operator")
        conn = operator.connection()
        conn.request("POST", "/v1/servers/a/console", b" " * (mc_httpapi.MAX_BODY + 1),
                     dict(operator.headers(), **{"Content-Type": "application/json"}))
        response = conn.getresponse()
        self.assertEqual((response.status, json.loads(response.read())["code"]), (413, "payload_too_large"))
        conn.close()

    def test_tls_below_1_3_is_refused(self):
        with self.assertRaises((ssl.SSLError, OSError)):
            self.tls_socket(maximum=ssl.TLSVersion.TLSv1_2)
        sock = self.tls_socket()
        self.assertEqual(sock.version(), "TLSv1.3")
        sock.close()

    def test_plain_http_gets_nothing(self):
        raw = socket.create_connection(("127.0.0.1", self.port), timeout=5)
        raw.sendall(b"GET /v1 HTTP/1.1\r\nHost: x\r\n\r\n")
        raw.settimeout(5)
        try:
            data = raw.recv(1024)
        except OSError:
            data = b""
        raw.close()
        self.assertNotIn(b"HTTP/1.", data)
        self.assertNotIn(b"api_info", data)


class TestResilience(RemoteCase):

    def test_the_daemon_survives_broken_handshakes(self):
        raw = socket.create_connection(("127.0.0.1", self.port), timeout=5)
        raw.close()
        raw = socket.create_connection(("127.0.0.1", self.port), timeout=5)
        raw.sendall(b"\x16\x03\x01\x00\x10garbage-not-tls!")
        raw.close()
        raw = socket.create_connection(("127.0.0.1", self.port), timeout=5)
        raw.sendall(b"\x16\x03\x03\x00\xff")
        raw.close()
        with self.assertRaises((ssl.SSLError, OSError)):
            self.tls_socket(maximum=ssl.TLSVersion.TLSv1_2)
        client = self.tls_socket()
        client.close()
        self.assertTrue(self.api.alive())
        self.assertEqual(self.remote().request("GET", "/v1")[0], 200)

    def test_a_client_that_leaves_mid_request_does_not_stop_the_listener(self):
        operator = self.pair("operator")
        sock = self.tls_socket()
        sock.sendall(b"POST /v1/servers/a/console HTTP/1.1\r\nHost: x\r\nContent-Length: 500\r\n\r\n{")
        sock.close()
        self.assertEqual(operator.request("GET", "/v1/servers")[0], 200)

    def test_connection_cap(self):
        with mock.patch.object(mc_remoteserver, "MAX_CONNECTIONS", 0):
            with self.assertRaises((ssl.SSLError, OSError)):
                sock = self.tls_socket()
                sock.sendall(b"GET /v1 HTTP/1.1\r\nHost: x\r\n\r\n")
                if not sock.recv(100):
                    raise OSError("closed")
        self.assertEqual(self.remote().request("GET", "/v1")[0], 200)

    def test_stop_closes_the_listener(self):
        port = self.port
        self.api.stop()
        with self.assertRaises(OSError):
            socket.create_connection(("127.0.0.1", port), timeout=2)


class TestAudit(RemoteCase):

    def lines(self):
        path = os.path.join(self.logs, "audit.log")
        return [json.loads(line) for line in slurp(path).splitlines()]

    @unittest.skipIf(sys.platform == "win32", "POSIX-only behavior")
    def test_every_request_is_logged_without_secrets(self):
        operator = self.pair("operator", name="phone")
        marker = "LEAK-body-secret-777"
        with mock.patch.object(mc_api, "rcon_exec", return_value=(True, "ok")), \
                mock.patch.object(mc_core_module(), "is_server_running", return_value=True):
            operator.request("POST", "/v1/servers/a/console", {"command": marker})
        operator.request("GET", "/v1/servers/a?token=" + marker)
        operator.request("GET", "/v1/servers/a/start")
        self.remote("wrong-token-123").request("GET", "/v1/servers")
        self.remote().request("POST", "/v1/pair", {"code": "00000000", "name": "x"})
        rows = self.lines()
        path = os.path.join(self.logs, "audit.log")
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        for row in rows:
            self.assertEqual(set(row), {"at", "device", "ip", "method", "op", "server", "status", "code"})
        console = next(r for r in rows if r["op"] == "sendConsoleCommand")
        self.assertEqual((console["device"], console["ip"], console["method"], console["server"], console["status"]),
                         (operator.device_id, "127.0.0.1", "POST", "a", 200))
        ops = [r["op"] for r in rows]
        self.assertIn("pairDevice", ops)
        denied = [r for r in rows if r["status"] == 401]
        self.assertTrue(denied and all(r["device"] is None for r in denied))
        text = slurp(path)
        for secret in (operator.token, marker, "wrong-token-123", "00000000"):
            self.assertNotIn(secret, text)

    def test_the_paired_device_is_named_in_the_pairing_line(self):
        operator = self.pair("viewer")
        first = self.lines()[0]
        self.assertEqual((first["op"], first["device"], first["status"]), ("pairDevice", operator.device_id, 201))

    def test_audit_endpoint_filters_and_is_newest_first(self):
        admin = self.pair("admin", name="boss")
        viewer = self.pair("viewer", name="eye")
        viewer.request("GET", "/v1/servers/a")
        viewer.request("GET", "/v1/servers")
        status, body = admin.request("GET", f"/v1/audit?device={viewer.device_id}&limit=2")
        self.assertEqual(status, 200)
        self.assertEqual([e["action"] for e in body["entries"]], ["listServers", "getServer"])
        self.assertTrue(all(e["device"] == viewer.device_id for e in body["entries"]))
        by_server = admin.request("GET", "/v1/audit?server=a")[1]["entries"]
        self.assertEqual({e["server"] for e in by_server}, {"a"})
        self.assertEqual(admin.request("GET", "/v1/audit?limit=0")[0], 422)

    def test_rotation_at_the_size_limit(self):
        with mock.patch.object(mc_remote, "AUDIT_MAX", 2000):
            for _ in range(60):
                mc_remote.audit("d_1", "127.0.0.1", "GET", "listServers", None, 200, "status")
        path = os.path.join(self.logs, "audit.log")
        self.assertTrue(os.path.exists(path + ".1"))
        self.assertLessEqual(os.path.getsize(path), 2200)
        self.assertFalse(os.path.exists(path + ".2"))

    def test_no_secret_of_a_server_reaches_a_remote_answer_or_a_file(self):
        cases = leaks.TestLeaks
        cases.setUpClass()
        registry = os.path.join(cases.data, "servers.json")
        with mock.patch.object(mc_servers, "REGISTRY_FILE", registry), \
                mock.patch.object(mc_servers, "REGISTRY_DIR", cases.data):
            admin = self.pair("admin")
            checked = 0
            for route in mc_httpapi.build_routes(SPEC):
                if route.method != "GET" or route.operation_id in ("streamEvents", "streamConsole", "getModpackInfo",
                                                                  "checkUpdate"):
                    continue
                path = route.template
                for name, value in (("server", "a"), ("kind", "whitelist"), ("job", "j_x"), ("key", "mcrcon_pass"),
                                    ("device", "d_x")):
                    path = path.replace("{" + name + "}", value)
                status, body = admin.request("GET", path)
                text = json.dumps(body)
                for label, value in leaks.SECRETS.items():
                    self.assertNotIn(value, text, f"{label} leaked by GET {path}")
                checked += 1
            self.assertGreater(checked, 25)
            self.assertEqual(admin.request("PUT", "/v1/servers/a/config/webhook_url",
                                           {"value": "https://x.example/" + leaks.SECRETS["hook"]})[0] in (200, 422), True)
            for secret in leaks.SECRETS.values():
                self.assertNotIn(secret, slurp(os.path.join(self.logs, "audit.log")))
                self.assertNotIn(secret, slurp(os.path.join(mc_remote.state_dir(), "remote_devices.json")))


def mc_core_module():
    import mc_core
    return mc_core


class TestSeparationFromTheLocalApi(RemoteCase):

    def setUp(self):
        super().setUp()
        self.local = mc_httpapi.LocalApi(folder=self.env["run"], mode="tcp", enabled=lambda: True, settle=0.3)
        self.local.sync()
        self.addCleanup(self.local.stop)
        self.client = Client(self.env["run"], "tcp")

    def test_two_applications_one_without_remote_rules(self):
        self.assertIsNot(self.local.app, self.api.app)
        self.assertIsNone(self.local.app.remote)
        self.assertIsNotNone(self.api.app.remote)

    def test_local_requests_skip_roles_audit_and_limits(self):
        for method, path, body in (("GET", "/v1/devices", None), ("GET", "/v1/audit", None),
                                   ("POST", "/v1/pair/codes", {"role": "viewer"}), ("GET", "/v1/remote", None)):
            status, answer, _ = self.client.request(method, path, body)
            self.assertIn(status, (200, 201), (path, answer))
        for _ in range(30):
            self.assertEqual(self.client.request("GET", "/v1/servers")[0], 200)
        self.assertFalse(os.path.exists(os.path.join(self.logs, "audit.log")))

    def test_local_api_can_switch_remote_access(self):
        status, body, _ = self.client.request("PUT", "/v1/remote", {"enabled": True, "bind": "127.0.0.1:0"})
        self.assertEqual((status, body["code"]), (200, "remote_enabled"))
        self.assertTrue(mc_remote.load_settings()["enabled"])
        status, body, _ = self.client.request("PUT", "/v1/remote", {"enabled": True, "bind": "garbage"})
        self.assertEqual((status, body["code"]), (422, "bad_bind"))
        status, body, _ = self.client.request("PUT", "/v1/remote", {"enabled": False})
        self.assertEqual((status, body["code"]), (200, "remote_disabled"))

    def test_the_pairing_route_does_not_exist_locally(self):
        status, body, _ = self.client.request("POST", "/v1/pair", {"code": "12345678", "name": "x"}, token=False)
        self.assertEqual((status, body["code"]), (404, "not_found"))
        status, body, _ = self.client.request("POST", "/v1/pair", {"code": "12345678", "name": "x"})
        self.assertEqual((status, body["code"]), (404, "not_found"))

    def test_tokens_do_not_cross_over(self):
        remote_token = self.pair("admin").token
        status, _, _ = self.client.request("GET", "/v1/servers", token=remote_token)
        self.assertEqual(status, 401)
        status, body = self.remote(self.client.token).request("GET", "/v1/servers")
        self.assertEqual((status, body["code"]), (401, "unauthorized"))

    def test_local_pairing_code_lets_a_remote_device_in(self):
        status, body, _ = self.client.request("POST", "/v1/pair/codes", {"role": "viewer", "servers": ["a"]})
        self.assertEqual(status, 201)
        status, paired = self.remote().request("POST", "/v1/pair", {"code": body["pairing_code"], "name": "tab"})
        self.assertEqual((status, paired["roles"]["default"]), (201, "viewer"))
        status, devices, _ = self.client.request("GET", "/v1/devices")
        self.assertEqual([d["name"] for d in devices["devices"]], ["tab"])
        self.assertEqual(devices["devices"][0]["servers"], ["a"])

    def test_api_info_tells_which_listener_answers(self):
        self.assertFalse(self.client.request("GET", "/v1")[1]["remote"])
        self.assertTrue(self.remote().request("GET", "/v1")[1]["remote"])


class TestClient(RemoteCase):

    def run_cli(self, *argv, stdin_tty=False):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(sys, "argv", ["mc", *argv]), contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(err), mock.patch.object(sys.stdin, "isatty", return_value=stdin_tty):
            try:
                code = mc_cli.main()
            except SystemExit as exc:
                code = exc.code
        return code or 0, out.getvalue(), err.getvalue()

    def add_profile(self, name="r", role="admin", servers=None):
        code = mc_remote.create_code(role, servers)["pairing_code"]
        argv = ["remote", "add", name, f"127.0.0.1:{self.port}", "--code", code, "--yes", "--name", "cli", "--json"]
        status, text, _ = self.run_cli(*argv)
        self.assertEqual(status, 0, text)
        return json.loads(text)

    @unittest.skipIf(sys.platform == "win32", "POSIX-only behavior")
    def test_add_pins_the_fingerprint_and_stores_a_private_profile(self):
        document = self.add_profile()
        self.assertEqual(document["fingerprint"], self.fingerprint)
        path = os.path.join(self.env["data"], "remotes.json")
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        profile = load(path)["r"]
        self.assertEqual((profile["fingerprint"], profile["port"]), (self.fingerprint, self.port))
        self.assertTrue(profile["token"])
        self.assertNotIn(profile["token"], self.run_cli("remote", "profiles", "--json")[1])

    def test_add_needs_confirmation_without_yes(self):
        code = mc_remote.create_code()["pairing_code"]
        status, text, _ = self.run_cli("remote", "add", "r", f"127.0.0.1:{self.port}", "--code", code, "--json")
        document = json.loads(text)
        self.assertEqual((status, document["code"], document["fingerprint"]), (2, "confirm_required", self.fingerprint))
        self.assertFalse(os.path.exists(os.path.join(self.env["data"], "remotes.json")))
        self.assertEqual(self.remote().request("POST", "/v1/pair", {"code": code, "name": "x"})[0], 201)

    def test_add_with_a_wrong_code_and_with_an_existing_profile(self):
        mc_remote.create_code()
        status, text, _ = self.run_cli("remote", "add", "r", f"127.0.0.1:{self.port}", "--code", "00000000", "--yes",
                                       "--json")
        self.assertEqual((status, json.loads(text)["code"]), (1, "bad_pair_code"))
        self.add_profile()
        status, text, _ = self.run_cli("remote", "add", "r", f"127.0.0.1:{self.port}", "--code", "1", "--yes", "--json")
        self.assertEqual(json.loads(text)["code"], "profile_exists")
        self.assertEqual(self.run_cli("remote", "forget", "r", "--json")[0], 0)
        self.assertEqual(self.run_cli("remote", "forget", "r", "--json")[0], 1)

    def test_pinned_fingerprint_is_accepted(self):
        self.add_profile()
        status, text, _ = self.run_cli("--remote", "r", "status", "--json")
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(text)["code"], "status")

    def test_changed_certificate_is_refused(self):
        self.add_profile()
        self.api.stop()
        mc_remote.ensure_certificate("127.0.0.1", regenerate=True)
        self.api = mc_remoteserver.RemoteApi(enabled=lambda: True, bind=f"127.0.0.1:{self.port}")
        self.api.sync()
        self.addCleanup(self.api.stop)
        self.assertTrue(self.api.alive())
        self.assertNotEqual(mc_remote.certificate_info()["fingerprint"], self.fingerprint)
        status, text, _ = self.run_cli("--remote", "r", "status", "--json")
        document = json.loads(text)
        self.assertEqual((status, document["code"]), (1, "fingerprint_mismatch"))
        self.assertNotIn("token", text)
        stolen = Remote("127.0.0.1", self.port, self.fingerprint)
        status, document = stolen.request("GET", "/v1/servers")
        self.assertEqual((status, document["code"]), (0, "fingerprint_mismatch"))

    def test_a_profile_without_fingerprint_never_connects_unpinned(self):
        for pin in (None, ""):
            status, document = Remote("127.0.0.1", self.port, pin, token="x").request("GET", "/v1/servers")
            self.assertEqual((status, document["code"]), (0, "fingerprint_mismatch"))

    def test_remote_status_json_equals_local_status_json(self):
        self.add_profile()
        self.add_server("b")
        local_code, local_text, _ = self.run_cli("status", "--json")
        remote_code, remote_text, _ = self.run_cli("--remote", "r", "status", "--json")
        self.assertEqual((local_code, remote_code), (0, 0))
        self.assertEqual(json.loads(remote_text), json.loads(local_text))
        self.assertEqual(self.run_cli("--remote", "r", "status", "b", "--json")[1],
                         self.run_cli("status", "b", "--json")[1])
        self.assertEqual(self.run_cli("--remote", "r", "status", "zz", "--json")[0],
                         self.run_cli("status", "zz", "--json")[0])

    def test_remote_status_text(self):
        self.add_profile()
        status, text, _ = self.run_cli("--remote", "r", "status")
        self.assertEqual(status, 0)
        self.assertIn("a", text)

    def test_remote_players_json_equals_local(self):
        self.add_profile()
        document = mc_api.result(True, "players", server="a", online=1, max=20, players=["Steve"])
        with mock.patch.object(mc_api, "players_document", return_value=document):
            local = self.run_cli("players", "--json")
            remote = self.run_cli("--remote", "r", "players", "--json")
            text = self.run_cli("--remote", "r", "players")
        self.assertEqual(local[0], remote[0])
        self.assertEqual(json.loads(remote[1]), json.loads(local[1]))
        self.assertIn("Steve", text[1])

    def test_remote_start_stop_logs_backup(self):
        self.add_profile()
        with mock.patch.object(mc_api, "start", return_value=mc_api.result(True, "started", server="a",
                                                                          message="started-ok")):
            status, text, _ = self.run_cli("--remote", "r", "start")
        self.assertEqual((status, "started-ok" in text), (0, True))
        with mock.patch.object(mc_api, "stop", return_value=mc_api.result(True, "stopped", server="a")) as stop:
            status, text, _ = self.run_cli("--remote", "r", "stop", "--reason", "user", "--quiet")
        self.assertEqual(status, 0)
        self.assertEqual(stop.call_args[1], {"reason": "user", "quiet": True, "force": False})
        log = os.path.join(mc_api.BASE_DIR, "logs", "daemon.log")
        with mock.patch.object(mc_api, "log_lines", return_value=mc_api.result(True, "logs", server="a",
                                                                              lines=["l1", "l2"])):
            status, text, _ = self.run_cli("--remote", "r", "logs")
            self.assertEqual((status, text.splitlines()[:2]), (0, ["l1", "l2"]))
            local = self.run_cli("logs", "--json")
            remote = self.run_cli("--remote", "r", "logs", "--json")
        self.assertEqual(json.loads(remote[1]), json.loads(local[1]))
        with mock.patch.object(mc_api, "backup_now", return_value=mc_api.result(True, "backup_done", server="a")):
            with mock.patch.object(mc_remoteclient.time, "sleep"):
                status, text, _ = self.run_cli("--remote", "r", "backup", "--json")
        self.assertEqual((status, json.loads(text)["code"]), (0, "backup_done"))
        del log

    def test_viewer_profile_cannot_start_remotely(self):
        self.add_profile("v", role="viewer")
        with mock.patch.object(mc_api, "start") as start:
            status, text, _ = self.run_cli("--remote", "v", "start")
        self.assertEqual(status, 1)
        start.assert_not_called()

    def test_unsupported_command_and_unknown_profile(self):
        self.add_profile()
        status, text, _ = self.run_cli("--remote", "r", "mod", "list", "--json")
        self.assertEqual((status, json.loads(text)["code"]), (2, "remote_unsupported"))
        status, text, _ = self.run_cli("--remote", "zz", "status", "--json")
        self.assertEqual((status, json.loads(text)["code"]), (1, "profile_not_found"))
        self.assertEqual(self.run_cli("--remote")[0], 2)

    def test_remote_console_streams_lines_and_sends_commands(self):
        self.add_profile()
        folder = mc_servers.load_registry()["servers"]["a"]["dossier_serveur"]
        with open(os.path.join(folder, "logs", "latest.log"), "w") as f:
            f.write("first line\nsecond line\n")
        remote = Remote.from_profile("r")
        out = io.StringIO()
        sent = threading.Event()

        def fake_rcon(config, command, wait=0):
            sent.set()
            return True, "echo:" + command
        args = mock.Mock(target=None)
        with mock.patch.object(mc_api, "rcon_exec", fake_rcon), \
                mock.patch.object(mc_cli.mc_core if hasattr(mc_cli, "mc_core") else mc_core_module(),
                                  "is_server_running", return_value=True):
            runner = threading.Thread(target=mc_cli.remote_console, args=(remote, args, io.StringIO("list\n"), out),
                                      daemon=True)
            runner.start()
            self.assertTrue(sent.wait(10))
            deadline = time.time() + 10
            while "echo:list" not in out.getvalue() and time.time() < deadline:
                time.sleep(0.05)
            device_id = load(os.path.join(self.env["data"], "remotes.json"))["r"]["device_id"]
            mc_remote.revoke_device(device_id)
            runner.join(10)
        self.assertFalse(runner.is_alive())
        text = out.getvalue()
        self.assertIn("first line", text)
        self.assertIn("second line", text)
        self.assertIn("echo:list", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
