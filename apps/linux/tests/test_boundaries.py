import ast
import glob
import os
import unittest

PACKAGE = os.path.join(os.path.dirname(__file__), "..", "mcmanager_app")
FORBIDDEN = {"mc_config", "mc_servers", "mc_ipc", "mc_core", "mc_daemon", "mc_cli", "mc_api", "mc_apiops"}
ALLOWED_CORE = {"mc_remoteclient", "mc_httpapi"}


def sources():
    return sorted(glob.glob(os.path.join(PACKAGE, "**", "*.py"), recursive=True))


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def imported(path):
    tree = ast.parse(read(path))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


class TestBoundaries(unittest.TestCase):
    def test_app_never_imports_the_core_data_layer(self):
        for path in sources():
            self.assertFalse(imported(path) & FORBIDDEN, path)

    def test_only_the_transport_modules_of_the_core_are_used(self):
        for path in sources():
            core = {n for n in imported(path) if n.startswith("mc_")}
            self.assertLessEqual(core, ALLOWED_CORE, path)

    def test_core_imports_stay_in_client_module(self):
        for path in sources():
            if os.path.basename(path) != "client.py":
                self.assertFalse({n for n in imported(path) if n.startswith("mc_")}, path)

    def test_no_file_is_opened_outside_the_app_settings(self):
        for path in sources():
            for node in ast.walk(ast.parse(read(path))):
                if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "open":
                    self.assertTrue(path.endswith(os.path.join("ui", "application.py")), path)

    def test_views_compile(self):
        for path in sources():
            compile(read(path), path, "exec")

    def test_importing_the_logic_needs_no_gtk(self):
        import importlib
        for name in ("mcmanager_app.client", "mcmanager_app.models", "mcmanager_app.i18n"):
            importlib.import_module(name)


if __name__ == "__main__":
    unittest.main()
