"""Chairman eligibility, fallback, and closed failure."""
import unittest

import importlib.util
from helpers import PLUGIN_ROOT

spec = importlib.util.spec_from_file_location("chairman", PLUGIN_ROOT / "scripts" / "chairman.py")
chairman = importlib.util.module_from_spec(spec)
spec.loader.exec_module(chairman)


class ChairmanTests(unittest.TestCase):
    def test_general_frontier_and_fallback(self):
        rows = [
            dict(id="future", provider="claude", available=True, restricted=False, frontier=True, rank=5),
            dict(id="older", provider="claude", available=True, restricted=False, frontier=False, rank=3),
            dict(id="mythos", provider="claude", available=True, restricted=False, frontier=True, rank=99),
            dict(id="gated", provider="claude", available=True, restricted=True, frontier=True, rank=100),
        ]
        self.assertEqual(chairman.resolve(rows)["model"], "future")
        rows[0]["available"] = False
        self.assertEqual(chairman.resolve(rows), {
            "class": "latest-frontier-claude", "model": "older", "fallback": True, "aliases": []})
        rows[1]["restricted"] = None
        with self.assertRaises(ValueError):
            chairman.resolve(rows)


class ReservationTests(unittest.TestCase):
    def test_aliases_are_preserved(self):
        row = dict(id="new-model", provider="claude", available=True,
                   restricted=False, frontier=True, rank=1, aliases=["fable"])
        self.assertEqual(chairman.resolve([row])["aliases"], ["fable"])
