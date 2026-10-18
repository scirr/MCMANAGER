"""
test_openapi.py - the OpenAPI 3.1 contract of the daemon API (api/openapi.json):
structure, references, operations, secrets, examples, and no drift with the
sources in api/src merged by api/build_openapi.py.
"""
import ast
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
API_DIR = os.path.join(ROOT, "api")
SPEC_PATH = os.path.join(API_DIR, "openapi.json")
README_PATH = os.path.join(API_DIR, "README.md")
MC_API_PATH = os.path.join(ROOT, "core", "mc_api.py")

sys.path.insert(0, API_DIR)
import build_openapi

METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")
ROLES = ("viewer", "operator", "admin")
REQUIRED_ERRORS = (400, 401, 403, 404, 409, 413, 422, 429, 500, 503)
PUBLIC_OPERATIONS = {"getApiInfo", "pairDevice"}


def load_text():
    with open(SPEC_PATH, "r", encoding="utf-8") as f:
        return f.read()


SPEC = json.loads(load_text())
OPERATIONS = {}


def operations():
    for path, item in SPEC["paths"].items():
        for method, op in item.items():
            if method in METHODS:
                yield path, method, op


OPERATIONS.update({op["operationId"]: op for _p, _m, op in operations()})


def resolve(ref):
    assert ref.startswith("#/"), ref
    node = SPEC
    for part in ref[2:].split("/"):
        node = node[part.replace("~1", "/").replace("~0", "~")]
    return node


def walk(node):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from walk(value)


def secret_like(name):
    lowered = name.lower()
    if lowered.endswith("_file"):
        return False
    if lowered == "public_key":
        return False
    parts = lowered.split("_")
    return (any(p in ("pass", "password", "secret", "token") for p in parts)
            or lowered == "webhook_url" or lowered.endswith("_key"))


def reachable_properties(schema, seen=None):
    """(property name, property schema) for every property reachable from a schema."""
    seen = set() if seen is None else seen
    found = []
    if isinstance(schema, dict):
        if "$ref" in schema:
            if schema["$ref"] in seen:
                return found
            seen.add(schema["$ref"])
            return reachable_properties(resolve(schema["$ref"]), seen)
        for name, sub in (schema.get("properties") or {}).items():
            found.append((name, sub))
            found += reachable_properties(sub, seen)
        for key in ("items", "additionalProperties", "contentSchema"):
            if isinstance(schema.get(key), dict):
                found += reachable_properties(schema[key], seen)
        for key in ("allOf", "oneOf", "anyOf"):
            for sub in schema.get(key, []):
                found += reachable_properties(sub, seen)
    return found


def response_schemas(op):
    for code, response in op["responses"].items():
        if "$ref" in response:
            response = resolve(response["$ref"])
        for media in response.get("content", {}).values():
            if "schema" in media:
                yield code, media["schema"]


def request_schemas(op):
    body = op.get("requestBody")
    if body:
        for media in body["content"].values():
            if "schema" in media:
                yield media["schema"]


TYPE_CHECKS = {
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "array": lambda v: isinstance(v, list),
    "object": lambda v: isinstance(v, dict),
    "null": lambda v: v is None,
}


def validate(value, schema, where="$"):
    """Small JSON Schema subset check; returns a list of problems."""
    if "$ref" in schema:
        return validate(value, resolve(schema["$ref"]), where)
    problems = []
    for sub in schema.get("allOf", []):
        problems += validate(value, sub, where)
    for key in ("oneOf", "anyOf"):
        if key in schema:
            if not any(not validate(value, sub, where) for sub in schema[key]):
                problems.append(f"{where}: matches none of {key}")
    if "enum" in schema and value not in schema["enum"]:
        problems.append(f"{where}: {value!r} not in enum")
    kinds = schema.get("type")
    if kinds is not None:
        kinds = [kinds] if isinstance(kinds, str) else kinds
        if not any(TYPE_CHECKS[k](value) for k in kinds):
            return problems + [f"{where}: {value!r} is not {kinds}"]
    if isinstance(value, dict):
        for name in schema.get("required", []):
            if name not in value:
                problems.append(f"{where}: missing {name}")
        for name, sub in (schema.get("properties") or {}).items():
            if name in value:
                problems += validate(value[name], sub, f"{where}.{name}")
        extra = schema.get("additionalProperties")
        if isinstance(extra, dict):
            declared = schema.get("properties") or {}
            for name, item in value.items():
                if name not in declared:
                    problems += validate(item, extra, f"{where}.{name}")
    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        for index, item in enumerate(value):
            problems += validate(item, schema["items"], f"{where}[{index}]")
    return problems


def declared_names(schema):
    if "$ref" in schema:
        return declared_names(resolve(schema["$ref"]))
    names = set(schema.get("properties") or {})
    for key in ("allOf", "oneOf", "anyOf"):
        for sub in schema.get(key, []):
            names |= declared_names(sub)
    return names


def open_ended(schema):
    if "$ref" in schema:
        return open_ended(resolve(schema["$ref"]))
    if schema.get("additionalProperties") not in (None, False):
        return True
    return any(open_ended(sub) for key in ("allOf", "oneOf", "anyOf") for sub in schema.get(key, []))


def validate_strict(value, schema, where="$", check=True):
    """validate() plus: an object may not carry a property the schema does not declare
    (secret-looking names are exempt: the CLI shows masked placeholders for them)."""
    if "$ref" in schema:
        return validate_strict(value, resolve(schema["$ref"]), where, check)
    problems = []
    for sub in schema.get("allOf", []):
        problems += validate_strict(value, sub, where, False)
    for key in ("oneOf", "anyOf"):
        if key in schema:
            attempts = [validate_strict(value, sub, where, False) for sub in schema[key]]
            problems += min(attempts, key=len) if attempts else []
    if "enum" in schema and value not in schema["enum"]:
        problems.append(f"{where}: {value!r} not in enum")
    kinds = schema.get("type")
    if kinds is not None:
        kinds = [kinds] if isinstance(kinds, str) else kinds
        if not any(TYPE_CHECKS[k](value) for k in kinds):
            return problems + [f"{where}: {value!r:.60} is not {kinds}"]
    if isinstance(value, dict):
        props = schema.get("properties") or {}
        problems += [f"{where}: missing {name}" for name in schema.get("required", []) if name not in value]
        for name, sub in props.items():
            if name in value:
                problems += validate_strict(value[name], sub, f"{where}.{name}")
        extra = schema.get("additionalProperties")
        for name, item in value.items():
            if name not in props and isinstance(extra, dict):
                problems += validate_strict(item, extra, f"{where}.{name}")
        if check and (props or schema.get("allOf")) and not open_ended(schema):
            known = declared_names(schema)
            problems += [f"{where}: undeclared {name}" for name in value
                         if name not in known and not secret_like(name)]
    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        for index, item in enumerate(value):
            problems += validate_strict(item, schema["items"], f"{where}[{index}]")
    return problems


class TestStructure(unittest.TestCase):

    def test_version_and_metadata(self):
        self.assertTrue(SPEC["openapi"].startswith("3.1."))
        self.assertEqual(SPEC["info"]["version"].split(".")[0], "1")
        text = SPEC["info"]["description"]
        for needle in ("1 MB", "20 requests per second", "3 simultaneous console streams"):
            self.assertIn(needle, text)
        self.assertIn("bearerAuth", SPEC["components"]["securitySchemes"])
        self.assertEqual(SPEC["security"], [{"bearerAuth": []}])

    def test_every_reference_resolves(self):
        count = 0
        for node in walk(SPEC):
            if "$ref" in node and isinstance(node["$ref"], str):
                count += 1
                resolve(node["$ref"])
        self.assertGreater(count, 200)

    def test_paths_live_under_v1(self):
        for path in SPEC["paths"]:
            self.assertTrue(path == "/v1" or path.startswith("/v1/"), path)

    def test_path_parameters_declared(self):
        for path, method, op in operations():
            names = set(re.findall(r"\{([^}]+)\}", path))
            declared = set()
            for p in SPEC["paths"][path].get("parameters", []) + op.get("parameters", []):
                p = resolve(p["$ref"]) if "$ref" in p else p
                if p["in"] == "path":
                    declared.add(p["name"])
                    self.assertTrue(p["required"])
            self.assertEqual(names, declared, f"{method} {path}")

    def test_operation_count(self):
        self.assertGreaterEqual(len(list(operations())), 60)

    def test_operation_ids_unique_camel_case(self):
        seen = {}
        for path, method, op in operations():
            oid = op.get("operationId")
            self.assertTrue(oid and re.fullmatch(r"[a-z][A-Za-z0-9]*", oid), f"{method} {path}: {oid}")
            self.assertNotIn(oid, seen, f"{oid} used twice")
            seen[oid] = (method, path)

    def test_roles(self):
        for path, method, op in operations():
            self.assertIn(op.get("x-mcm-role"), ROLES, f"{method} {path}")
            self.assertIsInstance(op.get("x-mcm-source"), list, f"{method} {path}")
            self.assertTrue(op.get("summary"), f"{method} {path}")
            self.assertTrue(op.get("tags"), f"{method} {path}")

    def test_tags_declared(self):
        declared = {t["name"] for t in SPEC["tags"]}
        for path, method, op in operations():
            for tag in op["tags"]:
                self.assertIn(tag, declared)

    def test_each_operation_has_an_error_response(self):
        for path, method, op in operations():
            errors = [c for c in op["responses"] if c[0] in "45"]
            self.assertTrue(errors, f"{method} {path}")
            self.assertTrue(any(c[0] == "2" for c in op["responses"]), f"{method} {path}")

    def test_server_operations_answer_404(self):
        for path, method, op in operations():
            if "{server}" in path:
                self.assertIn("404", op["responses"], f"{method} {path}")

    def test_standard_error_responses(self):
        responses = SPEC["components"]["responses"]
        self.assertEqual(len(responses), len(REQUIRED_ERRORS))
        used = {c for _p, _m, op in operations() for c in op["responses"]}
        for code in REQUIRED_ERRORS:
            self.assertIn(code, [int(c) for c in used], code)
        for body in responses.values():
            self.assertEqual(body["content"]["application/json"]["schema"], {"$ref": "#/components/schemas/Error"})
        error = SPEC["components"]["schemas"]["Error"]
        self.assertEqual(error["required"], ["ok", "code", "message"])
        self.assertIn("detail", error["properties"])

    def test_long_operations_answer_202_with_a_job(self):
        jobs = [(p, m, op) for p, m, op in operations() if "202" in op["responses"]]
        self.assertGreaterEqual(len(jobs), 10)
        for path, method, op in jobs:
            schema = op["responses"]["202"]["content"]["application/json"]["schema"]
            self.assertEqual(schema, {"$ref": "#/components/schemas/Job"}, f"{method} {path}")
            self.assertIn("Location", op["responses"]["202"]["headers"])

    def test_required_routes_exist(self):
        for path in ("/v1/events", "/v1/servers/{server}/console", "/v1/jobs/{job}", "/v1/pair", "/v1/devices",
                     "/v1/doctor", "/v1/update", "/v1/update/rollback", "/v1/metrics", "/v1/java",
                     "/v1/servers/{server}/config/{key}", "/v1/servers/{server}/backups/{backup}/restore"):
            self.assertIn(path, SPEC["paths"])
        self.assertIn("text/event-stream", SPEC["paths"]["/v1/events"]["get"]["responses"]["200"]["content"])
        self.assertIn("text/event-stream", SPEC["paths"]["/v1/servers/{server}/console"]["get"]["responses"]["200"]["content"])
        self.assertIn("post", SPEC["paths"]["/v1/servers/{server}/console"])

    def test_only_pairing_and_info_are_public(self):
        public = {op["operationId"] for _p, _m, op in operations() if op.get("security") == []}
        self.assertEqual(public, PUBLIC_OPERATIONS)

    def test_roles_follow_the_least_privilege_rule(self):
        by_id = {op["operationId"]: op["x-mcm-role"] for _p, _m, op in operations()}
        for oid in ("startServer", "stopServer", "sendConsoleCommand", "listOnlinePlayers", "createBackup", "kickPlayer"):
            self.assertIn(by_id[oid], ("viewer", "operator"), oid)
        for oid in ("restoreBackup", "setConfigValue", "installModpack", "revokeDevice", "applyUpdate", "createServer"):
            self.assertEqual(by_id[oid], "admin", oid)
        for path, method, op in operations():
            if method == "get" and op["operationId"] not in ("listPlayerList", "getRemoteStatus", "listDevices",
                                                              "listAuditLog", "streamConsole"):
                self.assertEqual(op["x-mcm-role"], "viewer", f"{method} {path}")


class TestSecrets(unittest.TestCase):

    def test_no_secret_property_in_any_response(self):
        for path, method, op in operations():
            for code, schema in response_schemas(op):
                for name, _sub in reachable_properties(schema):
                    if op["operationId"] == "pairDevice" and name == "token":
                        continue
                    self.assertFalse(secret_like(name), f"{op['operationId']} {code}: {name}")

    def test_device_token_only_in_the_pairing_response(self):
        carriers = set()
        for _p, _m, op in operations():
            for code, schema in response_schemas(op):
                if any(name == "token" for name, _ in reachable_properties(schema)):
                    carriers.add(op["operationId"])
        self.assertEqual(carriers, {"pairDevice"})

    def test_secret_fields_of_requests_are_write_only(self):
        checked = 0
        for _p, _m, op in operations():
            for schema in request_schemas(op):
                for name, sub in reachable_properties(schema):
                    if secret_like(name):
                        checked += 1
                        self.assertTrue(sub.get("writeOnly") is True, f"{op['operationId']}: {name}")
        self.assertGreaterEqual(checked, 8)

    def test_no_write_only_property_in_responses(self):
        for _p, _m, op in operations():
            for _code, schema in response_schemas(op):
                for name, sub in reachable_properties(schema):
                    self.assertNotIn("writeOnly", sub, f"{op['operationId']}: {name}")


NAMED_SECRETS = ("mcrcon_pass", "webhook_url", "access_key", "secret_key", "password", "key", "password_file",
                 "headers", "curseforge_api_key")


class TestNamedSecrets(unittest.TestCase):

    def test_no_response_schema_has_a_property_named_like_a_secret(self):
        checked = 0
        for path, method, op in operations():
            for code, schema in response_schemas(op):
                for name, sub in reachable_properties(schema):
                    checked += 1
                    if name == "key" and sub.get("$ref", "").endswith("/ConfigKey"):
                        continue
                    self.assertNotIn(name, NAMED_SECRETS, f"{op['operationId']} {code}")
        self.assertGreater(checked, 500)

    def test_no_component_outside_requests_has_a_property_named_like_a_secret(self):
        for name, schema in SPEC["components"]["schemas"].items():
            if name.endswith("Request"):
                continue
            for prop, sub in reachable_properties(schema):
                if prop == "key" and sub.get("$ref", "").endswith("/ConfigKey"):
                    continue
                self.assertNotIn(prop, NAMED_SECRETS, name)

    def test_the_masked_listings_declare_the_names_of_what_is_set(self):
        schemas = SPEC["components"]["schemas"]
        self.assertIn("secrets_set", schemas["BackupRemote"]["properties"])
        self.assertIn("secrets_set", schemas["AlertChannel"]["properties"])
        self.assertIn("header_names", schemas["AlertChannel"]["properties"])
        self.assertIn("secrets_set", schemas["ConfigDocument"]["allOf"][1]["properties"])
        self.assertNotIn("secrets_set", schemas["ServerConfig"]["properties"])



class TestExamples(unittest.TestCase):

    def test_success_examples_follow_their_schema(self):
        for path, method, op in operations():
            for code, response in op["responses"].items():
                if code[0] != "2":
                    continue
                for ctype, media in response["content"].items():
                    self.assertIn("example", media, f"{op['operationId']} {code} {ctype}")
                    if ctype == "application/json":
                        problems = validate(media["example"], media["schema"])
                        self.assertEqual(problems, [], f"{op['operationId']} {code}")
                        if media["schema"] != {"$ref": "#/components/schemas/Job"}:
                            self.assertIs(media["example"]["ok"], True)

    def test_request_examples_follow_their_schema(self):
        for _p, _m, op in operations():
            body = op.get("requestBody")
            if not body:
                continue
            media = body["content"]["application/json"]
            self.assertIn("example", media, op["operationId"])
            self.assertEqual(validate(media["example"], media["schema"]), [], op["operationId"])

    def test_error_examples(self):
        for name, response in SPEC["components"]["responses"].items():
            example = response["content"]["application/json"]["example"]
            self.assertEqual(validate(example, {"$ref": "#/components/schemas/Error"}), [], name)
            self.assertIs(example["ok"], False)

    def test_validator_catches_a_wrong_example(self):
        schema = {"$ref": "#/components/schemas/Error"}
        self.assertTrue(validate({"ok": True, "code": "x"}, schema))
        self.assertTrue(validate({"ok": False, "code": 3, "message": "m"}, schema))


class TestStatusTable(unittest.TestCase):

    def row(self, status):
        with open(README_PATH, "r", encoding="utf-8") as f:
            return next(line for line in f if line.startswith(f"| {status} |"))

    def test_codes_added_in_3_0_are_classified(self):
        self.assertIn("`no_log_file`", self.row(404))
        self.assertIn("`config_key_unset`", self.row(404))
        self.assertIn("`server_offline`", self.row(409))

    def test_error_alias_is_declared_obsolete(self):
        error = SPEC["components"]["schemas"]["Error"]["properties"]["error"]
        self.assertTrue(error["deprecated"])
        self.assertIn("message", SPEC["components"]["schemas"]["Error"]["required"])


class TestCoverageOfMcApi(unittest.TestCase):

    def public_functions(self):
        with open(MC_API_PATH, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())
        return {n.name for n in tree.body if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")}

    def test_every_public_function_is_covered_or_listed_as_not_exposed(self):
        covered = set()
        for _p, _m, op in operations():
            covered |= {s.split(".", 1)[1] for s in op["x-mcm-source"] if s.startswith("mc_api.")}
        with open(README_PATH, "r", encoding="utf-8") as f:
            readme = f.read()
        self.assertIn("Not exposed", readme)
        missing = []
        for name in sorted(self.public_functions() - covered):
            if f"`mc_api.{name}`" not in readme:
                missing.append(name)
        self.assertEqual(missing, [], "functions neither exposed nor listed in api/README.md")

    def test_sources_name_existing_mc_api_functions(self):
        known = self.public_functions()
        for _p, _m, op in operations():
            for source in op["x-mcm-source"]:
                if source.startswith("mc_api."):
                    self.assertIn(source.split(".", 1)[1], known, op["operationId"])

    def test_state_and_stop_reason_enums_match_the_code(self):
        sys.path.insert(0, os.path.join(ROOT, "core"))
        import mc_api
        schemas = SPEC["components"]["schemas"]
        self.assertEqual(tuple(schemas["ServerState"]["enum"]), mc_api.STATES)
        self.assertEqual(tuple(schemas["StopReason"]["enum"]), mc_api.STOP_REASONS)
        self.assertEqual(schemas["Result"]["properties"]["schema"]["enum"], [mc_api.SCHEMA_VERSION])

    def test_config_keys_match_settable_keys(self):
        sys.path.insert(0, os.path.join(ROOT, "core"))
        import mc_config
        self.assertEqual(sorted(SPEC["components"]["schemas"]["ConfigKey"]["enum"]), sorted(mc_config.SETTABLE_KEYS))

    def test_alert_events_match_the_code(self):
        sys.path.insert(0, os.path.join(ROOT, "core"))
        import mc_alert
        self.assertEqual(SPEC["components"]["schemas"]["AlertEvent"]["enum"], list(mc_alert.EVENTS) + ["*"])


CLI_SECRETS = ("LEAK-rcon-91", "LEAK-hook-92", "LEAK-s3-access-93", "LEAK-s3-secret-94", "LEAK-header-95")


class TestCliOutputsFollowTheContract(unittest.TestCase):
    """Real `mc ... --json` runs against a throw-away data folder; every document
    has to fit the response schema of the operation it stands for."""

    FAILURES = {"not_found", "no_active_server", "confirm_required", "rcon_failed", "server_offline"}

    @classmethod
    def setUpClass(cls):
        cls.data = tempfile.mkdtemp()
        cls.folder = tempfile.mkdtemp()
        cls.cfg = {"port": 1, "rcon_port": 2, "mcrcon_pass": CLI_SECRETS[0], "always_on": 1, "nom_serveur": "a",
                   "dossier_backup": os.path.join(cls.data, "bk")}
        cls.save()
        with open(os.path.join(cls.folder, "server.properties"), "w") as f:
            f.write("online-mode=false\nlevel-name=world\n")
        os.makedirs(os.path.join(cls.folder, "world", "region"))
        with open(os.path.join(cls.folder, "world", "level.dat"), "w") as f:
            f.write("x")
        os.makedirs(os.path.join(cls.folder, "logs"))
        with open(os.path.join(cls.folder, "logs", "latest.log"), "w") as f:
            f.write("[10:00:00] [Server thread/INFO]: Steve[/203.0.113.5:1] logged in with entity id 1 at (0, 0, 0)\n"
                    "[10:10:00] [Server thread/INFO]: Steve left the game\n")
        with open(os.path.join(cls.folder, "banned-players.json"), "w") as f:
            json.dump([{"uuid": "u", "name": "Steve", "created": "2026-01-02 03:04:05 +0000", "source": "x",
                        "expires": "forever", "reason": "r"}], f)
        os.makedirs(os.path.join(cls.folder, "mods"))
        with zipfile.ZipFile(os.path.join(cls.folder, "mods", "m.jar"), "w") as zf:
            zf.writestr("fabric.mod.json", json.dumps({"id": "m", "name": "M", "version": "1.2.3"}))
        with open(os.path.join(cls.data, "servers.json"), "w") as f:
            json.dump({"active": "a", "servers": {"a": {"id": 1, "dossier_serveur": cls.folder}}}, f)
        cls.env = dict(os.environ, MCMANAGER_DATA_DIR=cls.data, NO_COLOR="1")
        cls.env.pop("MCMANAGER_DEBUG", None)

    @classmethod
    def save(cls):
        with open(os.path.join(cls.folder, "config.json"), "w") as f:
            json.dump(cls.cfg, f)

    def cli(self, *argv):
        res = subprocess.run([sys.executable, os.path.join(ROOT, "core", "mc_cli.py"), *argv, "--json"],
                             capture_output=True, text=True, env=self.env, stdin=subprocess.DEVNULL, timeout=60)
        self.assertNotIn("Traceback", res.stderr)
        return res.returncode, json.loads(res.stdout)

    def response(self, operation_id, status):
        response = OPERATIONS[operation_id]["responses"][status]
        if "$ref" in response:
            response = resolve(response["$ref"])
        return response["content"]["application/json"]["schema"]

    def check(self, argv, target, status="200"):
        """target: an operationId, or '#Schema' for a result that travels inside a job."""
        _rc, doc = self.cli(*argv)
        schema = {"$ref": "#/components/schemas/" + target[1:]} if target.startswith("#") \
            else self.response(target, status)
        self.assertEqual(validate_strict(doc, schema), [], " ".join(argv))
        return doc

    def check_failure(self, argv, code):
        rc, doc = self.cli(*argv)
        self.assertEqual((doc["ok"], doc["code"]), (False, code), " ".join(argv))
        error = dict(resolve("#/components/schemas/Error"), required=["ok", "code"])
        self.assertEqual(validate_strict(doc, error), [], " ".join(argv))
        return rc, doc

    def test_the_read_only_documents(self):
        for argv, target in ((("status",), "listServers"), (("status", "a"), "listServers"),
                             (("active",), "getServer"),                              (("java", "list"), "listJava"), (("sleep", "status"), "getSleepSettings"),
                             (("logs",), "getServerLogs"), (("world", "list"), "listWorlds"),
                             (("datapack", "list"), "listDatapacks"), (("mod", "list"), "listMods"),
                             (("ban", "list"), "listPlayerList"), (("op", "list"), "listPlayerList"),
                             (("whitelist", "list"), "listPlayerList"), (("router", "status"), "getRouter"),
                             (("router", "route", "list"), "getRouter"), (("task", "list"), "listTasks")):
            with self.subTest(command=" ".join(argv)):
                self.check(argv, target)

    def test_history_freeze_resume_use_mode(self):
        doc = self.check(("players", "history", "--days", "3650"), "getPlayerHistory")
        self.assertEqual(len(doc["sessions"]), 1)
        doc = self.check(("freeze", "--max", "5m"), "freezeServer")
        self.assertEqual(doc["expires_ts"] - doc["since_ts"], 300)
        snapshot = self.check(("status",), "listServers")["servers"][0]
        self.assertEqual(snapshot["frozen_expires_ts"] - snapshot["frozen_since_ts"], 300)
        self.check(("thaw",), "thawServer")
        self.check(("mode", "maintenance"), "setServerMode")
        self.check(("resume",), "resumeServer")
        self.check(("use", "a"), "activateServer")

    def test_sleep_settings(self):
        doc = self.check(("sleep", "enable", "--after", "10m"), "setSleepSettings")
        self.assertEqual((doc["enabled"], doc["after_s"], doc["join_mode"]), (True, 600, "kick"))
        self.check(("sleep", "allow", "Alex"), "setSleepSettings")
        self.assertEqual(self.check(("sleep", "status"), "getSleepSettings")["allow"], ["Alex"])

    def test_tasks_backups_alerts_and_remotes(self):
        doc = self.check(("task", "add", "--cron", "*/5 * * * *", "--action", "backup"), "createTask", "201")
        self.assertIsInstance(doc["task"]["next_run_ts"], int)
        self.check(("task", "list"), "listTasks")
        doc = self.check(("backup",), "#BackupCreated")
        self.assertEqual((doc["code"], doc["ok"]), ("backup_created", True))
        self.check(("backup", "list"), "listBackups")
        type(self).cfg = dict(self.cfg, webhook_url="https://discord.example/api/" + CLI_SECRETS[1], alerts=[
            {"name": "wh", "type": "webhook", "events": ["*"], "url": "https://hook.example/x",
             "headers": {"Authorization": CLI_SECRETS[4]}}],
            backup_remotes=[{"name": "s3", "type": "s3", "bucket": "b", "access_key": CLI_SECRETS[2],
                             "secret_key": CLI_SECRETS[3]}])
        self.save()
        for argv, target in ((("alert", "list"), "listAlertChannels"),
                             (("backup", "remote", "list"), "listBackupRemotes")):
            _rc, doc = self.cli(*argv)
            self.assertEqual(validate_strict(doc, self.response(target, "200")), [], " ".join(argv))
            for secret in CLI_SECRETS:
                self.assertNotIn(secret, json.dumps(doc))
        _rc, doc = self.cli("alert", "list")
        self.assertNotIn("***", json.dumps(doc))
        for channel in doc["channels"]:
            self.assertFalse({"secret", "token", "password"} & set(channel))

    def test_router_and_status_page(self):
        doc = self.check(("router", "enable"), "enableRouter")
        self.assertIs(doc["config"]["enabled"], True)
        self.check(("router", "deny", "add", "203.0.113.0/24"), "editRouterAccess")
        self.check(("router", "disable"), "disableRouter")
        doc = self.check(("status-page", "enable"), "enableStatusPage")
        self.assertEqual(doc["interval"], 60)
        self.check(("status-page", "disable"), "disableStatusPage")
        self.check(("status-page", "disable"), "disableStatusPage")

    def test_config_documents_fit_the_contract(self):
        doc = self.check(("config", "get"), "getServerConfig")
        self.assertNotIn("mcrcon_pass", doc["config"])
        self.assertEqual(self.check(("config", "get", "port"), "getConfigValue")["value"], 1)
        secret = self.check(("config", "get", "mcrcon_pass"), "getConfigValue")
        self.assertEqual((secret["write_only"], "value" in secret), (True, False))
        self.assertNotIn(CLI_SECRETS[0], json.dumps(secret))

    def test_java_list_of_a_server_fits_the_contract(self):
        doc = self.check(("java", "list", "a"), "listServerJava")
        self.assertEqual([s["server"] for s in doc["servers"]], ["a"])

    def test_failures_fit_the_error_object(self):
        self.assertEqual(self.check_failure(("status", "zz"), "not_found")[0], 3)
        self.assertEqual(self.check_failure(("freeze", "zz"), "not_found")[0], 3)
        self.assertEqual(self.check_failure(("use", "zz"), "not_found")[0], 3)
        self.assertEqual(self.check_failure(("remove", "zz"), "not_found")[0], 3)
        self.assertEqual(self.check_failure(("remove", "a"), "confirm_required")[0], 2)
        rc, doc = self.check_failure(("status", "zz"), "not_found")
        self.assertEqual((doc["target"], doc["available"]), ("zz", ["1:a"]))
        self.assertTrue(doc["message"])

    def test_remove_then_nothing_is_active(self):
        other = tempfile.mkdtemp()
        data = tempfile.mkdtemp()
        with open(os.path.join(other, "config.json"), "w") as f:
            json.dump({"port": 1, "rcon_port": 2, "nom_serveur": "b"}, f)
        with open(os.path.join(data, "servers.json"), "w") as f:
            json.dump({"active": "b", "servers": {"b": {"id": 1, "dossier_serveur": other}}}, f)
        env = dict(self.env, MCMANAGER_DATA_DIR=data)

        def run(*argv):
            res = subprocess.run([sys.executable, os.path.join(ROOT, "core", "mc_cli.py"), *argv, "--json"],
                                 capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL, timeout=60)
            return json.loads(res.stdout)

        doc = run("remove", "b", "--yes")
        self.assertEqual(validate_strict(doc, self.response("unregisterServer", "200")), [])
        doc = run("active")
        self.assertEqual((doc["ok"], doc["code"]), (False, "no_active_server"))

    def test_rcon_failure_and_offline_players_fit_the_schemas(self):
        rc, offline = self.cli("players")
        self.assertEqual((rc, offline["ok"], offline["code"]), (1, False, "server_offline"))
        self.assertEqual((offline["online"], offline["max"], offline["state"]), (0, None, "stopped"))
        self.assertEqual(validate_strict(offline, self.response("listOnlinePlayers", "409")), [])
        failure = {"schema": 1, "ok": False, "code": "rcon_failed", "server": "a", "detail": "refused",
                   "message": "m", "error": {"code": "rcon_failed", "detail": "refused"}}
        self.assertEqual(validate_strict(failure, resolve("#/components/schemas/Error")), [])

    def test_stop_rcon_schedule_language_daemon_fit_the_contract(self):
        doc = self.check(("stop",), "stopServer")
        self.assertEqual((doc["code"], doc["reason"], doc["server"]), ("already_stopped", "user", "a"))
        self.check(("stop", "--reason", "maintenance", "--quiet"), "stopServer")
        doc = self.check(("schedule", "8", "30", "23", "0"), "#ScheduleUpdated")
        self.assertEqual((doc["code"], doc["open_hour"], doc["close_minute"]), ("schedule_updated", 8, 0))
        self.assertEqual(self.cli("config", "get", "always_on")[1]["value"], 0)
        doc = self.check(("language",), "#LanguageResult")
        self.assertIn(doc["language"], ("fr", "en"))

    def test_stop_rcon_schedule_failures_fit_the_error_object(self):
        self.assertEqual(self.check_failure(("stop", "zz"), "not_found")[0], 3)
        self.assertEqual(self.check_failure(("rcon", "list", "zz"), "not_found")[0], 3)
        self.assertEqual(self.check_failure(("schedule", "1", "0", "2", "0", "zz"), "not_found")[0], 3)
        rc, doc = self.check_failure(("rcon", "list"), "server_offline")
        self.assertEqual(rc, 1)
        self.assertTrue(doc["message"])
        rc, doc = self.check_failure(("schedule", "25", "0", "3", "0"), "invalid_time")
        self.assertEqual((rc, doc["detail"]), (2, "25"))
        self.assertEqual(self.check_failure(("schedule", "5", "10", "5", "10"), "schedule_same_time")[0], 2)

    def test_rcon_reply_is_cleaned_and_fits_the_contract(self):
        sys.path.insert(0, os.path.join(ROOT, "core"))
        import mc_api
        with mock.patch.object(mc_api.mc_core, "is_server_running", return_value=True), \
                mock.patch.object(mc_api, "rcon_exec", return_value=(True, "\x1b[0mThere are 0\r\nplayers\x1b[1;31m")):
            doc = mc_api.wire(mc_api.rcon_reply("a", {}, "list"))
        self.assertEqual(doc["reply"], "There are 0\nplayers")
        self.assertEqual((doc["code"], doc["command"]), ("rcon_reply", "list"))
        self.assertEqual(validate_strict(doc, resolve("#/components/schemas/RconReply")), [])
        with mock.patch.object(mc_api.mc_core, "is_server_running", return_value=True), \
                mock.patch.object(mc_api, "rcon_exec", return_value=(False, "refused")):
            doc = mc_api.wire(mc_api.rcon_reply("a", {}, "list"))
        self.assertEqual((doc["ok"], doc["code"], doc["detail"]), (False, "rcon_failed", "refused"))
        error = dict(resolve("#/components/schemas/Error"), required=["ok", "code", "message"])
        self.assertEqual(validate_strict(doc, error), [])

    def test_daemon_documents_fit_the_contract(self):
        sys.path.insert(0, os.path.join(ROOT, "core"))
        import mc_api
        schema = resolve("#/components/schemas/DaemonResult")
        error = dict(resolve("#/components/schemas/Error"), required=["ok", "code", "message"])
        with mock.patch.object(mc_api.plat, "service_installed", return_value=True, create=True), \
                mock.patch.object(mc_api.plat, "service_running", return_value=False, create=True):
            doc = mc_api.wire(mc_api.daemon_control("status"))
        self.assertEqual((doc["installed"], doc["running"]), (True, False))
        self.assertEqual(validate_strict(doc, schema), [])
        for outcome, code in ((("ok", ""), "daemon_restarted"), (("not_installed", "x"), "daemon_not_installed"),
                              (("no_permission", "x"), "daemon_no_permission"),
                              (("error", "3|boom"), "daemon_error")):
            with mock.patch.object(mc_api.plat, "service_control", return_value=outcome, create=True):
                doc = mc_api.wire(mc_api.daemon_control("restart"))
            self.assertEqual(doc["code"], code)
            self.assertEqual(validate_strict(doc, schema if doc["ok"] else error), [], code)
            self.assertEqual(bool(doc["ok"]), code == "daemon_restarted")

    def test_language_set_fits_the_contract(self):
        sys.path.insert(0, os.path.join(ROOT, "core"))
        import mc_api
        import mc_lang
        saved = mc_lang.current_language()
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(mc_lang, "_LANG_FILE", os.path.join(tmp, "l.txt")):
            doc = mc_api.wire(mc_api.language_document("en"))
        mc_lang._apply_language(saved)
        self.assertEqual((doc["code"], doc["language"]), ("language", "en"))
        self.assertEqual(validate_strict(doc, resolve("#/components/schemas/LanguageResult")), [])

    def test_doctor_report(self):
        sys.path.insert(0, os.path.join(ROOT, "core"))
        import contextlib
        import io
        from unittest import mock
        import mc_doctor
        import mc_servers
        checks = [("ok", "Java", "21", None), ("warn", "Port", "taken", "Free the port.")]
        buffer = io.StringIO()
        with mock.patch.object(mc_servers, "list_servers", return_value={"a": {"id": 1}}), \
                mock.patch.object(mc_doctor, "check_host", return_value=checks[:1]), \
                mock.patch.object(mc_doctor, "check_server", return_value=checks[1:]), \
                contextlib.redirect_stdout(buffer):
            mc_doctor.run_doctor(None, as_json=True)
        doc = json.loads(buffer.getvalue())
        self.assertEqual(validate_strict(doc, self.response("getDoctorReport", "200")), [])
        self.assertEqual((doc["errors"], doc["warnings"], doc["has_issues"]), (0, 1, True))

    def test_validator_notices_an_undeclared_field(self):
        schema = {"$ref": "#/components/schemas/SleepStatus"}
        doc = dict(self.cli("sleep", "status")[1], surprise=1)
        self.assertEqual(validate_strict(doc, schema), ["$: undeclared surprise"])


class TestFormatAndDrift(unittest.TestCase):

    def test_file_is_indented_sorted_json(self):
        text = load_text()
        again = json.dumps(json.loads(text), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        self.assertEqual(text, again)

    def test_openapi_json_is_the_output_of_the_build_script(self):
        self.assertEqual(load_text(), build_openapi.build())

    def test_build_refuses_a_path_conflict(self):
        parts = [("a.json", {"paths": {"/v1/x": {}}}), ("b.json", {"paths": {"/v1/x": {}}})]
        with self.assertRaises(build_openapi.MergeError):
            build_openapi.merge(parts)

    def test_build_refuses_a_component_conflict(self):
        parts = [("a.json", {"components": {"schemas": {"S": {}}}}), ("b.json", {"components": {"schemas": {"S": {}}}})]
        with self.assertRaises(build_openapi.MergeError):
            build_openapi.merge(parts)

    def test_build_refuses_a_field_conflict(self):
        with self.assertRaises(build_openapi.MergeError):
            build_openapi.merge([("a.json", {"openapi": "3.1.0"}), ("b.json", {"openapi": "3.1.0"})])

    def test_build_merges_disjoint_sources(self):
        doc = build_openapi.merge([("a.json", {"paths": {"/v1/a": {}}, "components": {"schemas": {"A": {}}}}),
                                   ("b.json", {"paths": {"/v1/b": {}}, "components": {"schemas": {"B": {}}}})])
        self.assertEqual(sorted(doc["paths"]), ["/v1/a", "/v1/b"])
        self.assertEqual(sorted(doc["components"]["schemas"]), ["A", "B"])

    def test_build_reads_a_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name, part in (("one.json", {"paths": {"/v1/a": {}}}), ("two.json", {"paths": {"/v1/a": {}}})):
                with open(os.path.join(tmp, name), "w", encoding="utf-8") as f:
                    json.dump(part, f)
            with self.assertRaises(build_openapi.MergeError):
                build_openapi.build(tmp)

    def test_sources_exist(self):
        names = sorted(os.listdir(os.path.join(API_DIR, "src")))
        self.assertGreaterEqual(len(names), 8)
        self.assertTrue(all(n.endswith(".json") for n in names))


if __name__ == "__main__":
    unittest.main()
