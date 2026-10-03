"""
test_cli_intermixed.py — options and positionals may come in any order:
'mc stop --force srv' reads like 'mc stop srv --force'.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mc_cli

CASES = [
    (["stop", "srv", "--force"], ["stop", "--force", "srv"]),
    (["update", "--check", "--json"], ["update", "--json", "--check"]),
    (["image", "add", "a.png", "srv"], ["image", "add", "a.png", "srv"]),
]


class TestIntermixed(unittest.TestCase):

    def test_both_orders_give_the_same_result(self):
        for trailing, leading in CASES:
            with self.subTest(command=" ".join(leading)):
                parser = mc_cli.build_parser()
                self.assertEqual(vars(parser.parse_args(trailing)), vars(parser.parse_args(leading)))

    def test_stop_force_before_the_server(self):
        args = mc_cli.build_parser().parse_args(["stop", "--force", "srv"])
        self.assertEqual((args.target, args.force), ("srv", True))


if __name__ == "__main__":
    unittest.main(verbosity=2)
