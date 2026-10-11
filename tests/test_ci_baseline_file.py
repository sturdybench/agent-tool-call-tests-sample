"""Checks for the baseline file reader in tests/ci_baseline.py. Offline, no pytest needed.

Each test writes its own temporary baseline. The shipped fixtures are only read.
Run: python -m pytest, or python3 -m unittest discover tests
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from ci_baseline import BaselineError, load_baseline, read_baseline, stale_totals  # noqa: E402

FIXTURES = HERE / "fixtures"
GOOD = {
    "responses": "examples/responses.example.json",
    "known_fails": {"a-001": "other_fail", "a-002": "other_fail", "b-001": "wrong_call"},
    "directions": {"over_call": 0, "missed_call": 0, "wrong_call": 1, "other_fail": 2},
}


class BaselineFileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def write(self, doc):
        path = Path(self.tmp.name) / "baseline.json"
        path.write_text(json.dumps(doc), encoding="utf-8")
        return path

    def test_stale_totals_are_reported(self):
        doc = json.loads(json.dumps(GOOD))
        doc["directions"]["other_fail"] = 5
        stale = stale_totals(read_baseline(self.write(doc)))
        self.assertEqual(stale, ["other_fail: stored 5, computed from known_fails 2"])

    def test_typo_direction_is_a_named_error(self):
        doc = json.loads(json.dumps(GOOD))
        doc["known_fails"]["b-001"] = "wrongcall"
        with self.assertRaises(BaselineError) as cm:
            load_baseline(self.write(doc))
        msg = str(cm.exception)
        for part in ("b-001", "'wrongcall'", "over_call, missed_call, wrong_call, other_fail"):
            self.assertIn(part, msg)

    def test_pass_is_not_a_known_fail_direction(self):
        doc = json.loads(json.dumps(GOOD))
        doc["known_fails"]["a-001"] = "pass"
        with self.assertRaises(BaselineError):
            load_baseline(self.write(doc))

    def test_valid_baseline_loads_unchanged(self):
        path = self.write(GOOD)
        self.assertEqual(load_baseline(path), GOOD["known_fails"])
        self.assertEqual(stale_totals(read_baseline(path)), [])
        self.assertEqual(load_baseline(None), {})

    def test_shipped_baselines_load_and_match(self):
        for name in ("ci_baseline.json", "ci_baseline_mcp_filesystem.json"):
            path = FIXTURES / name
            raw = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(load_baseline(path), raw["known_fails"], name)
            self.assertEqual(stale_totals(read_baseline(path)), [], name)


if __name__ == "__main__":
    unittest.main()
