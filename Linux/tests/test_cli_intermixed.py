"""
test_cli_intermixed.py — options and positionals may come in any order:
'mc sleep enable --after 5m srv' reads like 'mc sleep enable srv --after 5m'.
"""
import contextlib
import io
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mc_cli

CASES = [
    (["sleep", "enable", "srv", "--after", "5m"], ["sleep", "enable", "--after", "5m", "srv"]),
    (["sleep", "status", "srv", "--json"], ["sleep", "--json", "status", "srv"]),
    (["sleep", "allow", "Steve", "srv", "--json"], ["sleep", "allow", "--json", "Steve", "srv"]),
    (["datapack", "enable", "pack", "srv", "--first"], ["datapack", "enable", "--first", "pack", "srv"]),
    (["datapack", "list", "srv", "--json"], ["datapack", "list", "--json", "srv"]),
    (["mod", "add", "sodium", "srv", "--server-only"], ["mod", "add", "--server-only", "sodium", "srv"]),
    (["mod", "remove", "sodium", "srv", "--yes"], ["mod", "remove", "--yes", "sodium", "srv"]),
    (["mod", "list", "srv", "--json"], ["mod", "list", "--json", "srv"]),
    (["stop", "srv", "--force"], ["stop", "--force", "srv"]),
    (["status", "srv", "--json"], ["status", "--json", "srv"]),
    (["upgrade", "1.21.1", "srv", "--json"], ["upgrade", "--json", "1.21.1", "srv"]),
    (["java", "install", "21", "--json"], ["java", "--json", "install", "21"]),
    (["modpack", "install", "pack", "--name", "n", "--ram", "6G"],
     ["modpack", "install", "--name", "n", "--ram", "6G", "pack"]),
    (["freeze", "srv", "--max", "1h"], ["freeze", "--max", "1h", "srv"]),
    (["image", "add", "a.png", "srv"], ["image", "add", "a.png", "srv"]),
]


class TestIntermixed(unittest.TestCase):

    def test_both_orders_give_the_same_result(self):
        for trailing, leading in CASES:
            with self.subTest(command=" ".join(leading)):
                parser = mc_cli.build_parser()
                self.assertEqual(vars(parser.parse_args(trailing)), vars(parser.parse_args(leading)))

    def test_sleep_after_before_the_server(self):
        args = mc_cli.build_parser().parse_args(["sleep", "enable", "--after", "5m", "srv"])
        self.assertEqual((args.args, args.after), (["srv"], "5m"))

    def test_unknown_option_is_still_refused(self):
        with self.assertRaises(SystemExit) as ctx, contextlib.redirect_stderr(io.StringIO()):
            mc_cli.build_parser().parse_args(["sleep", "enable", "--nope", "srv"])
        self.assertEqual(ctx.exception.code, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
