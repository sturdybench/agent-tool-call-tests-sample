"""Tests for mcp_schema_lint.py (free 3-rule subset). Standard library only.

Run from the product folder:  python3 -m unittest discover -s tests -v
"""

import json
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPT = os.path.join(ROOT, "mcp_schema_lint.py")
FIX = os.path.join(ROOT, "fixtures")
SERVERS = os.path.join(HERE, "servers")
sys.path.insert(0, ROOT)

import mcp_schema_lint as L  # noqa: E402

with open(os.path.join(HERE, "expected.json"), encoding="utf-8") as fh:
    EXPECTED = json.load(fh)


def run(args, timeout=60):
    p = subprocess.run([sys.executable, SCRIPT] + args, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, timeout=timeout, cwd=ROOT)
    return p.returncode, p.stdout.decode("utf-8"), p.stderr.decode("utf-8")


def flagged(report):
    return sorted(set(f["rule"] for f in report["findings"] if f["severity"] != "INFO"))


class FixtureTests(unittest.TestCase):
    def test_fixture_counts(self):
        self.assertEqual(len(os.listdir(os.path.join(FIX, "bad"))), 5)
        self.assertEqual(len(os.listdir(os.path.join(FIX, "good"))), 3)
        self.assertEqual(len(EXPECTED), 8)

    def test_every_rule_has_bad_fixture(self):
        rules = set()
        for exp in EXPECTED.values():
            rules.update(exp["rules"])
        self.assertEqual(rules, set(L.RULE_IDS))

    def test_each_fixture(self):
        for rel, exp in sorted(EXPECTED.items()):
            with self.subTest(fixture=rel):
                code, out, err = run([os.path.join(FIX, rel), "--format", "json"])
                self.assertEqual(code, exp["exit"], err)
                self.assertEqual(flagged(json.loads(out)), exp["rules"])


class OutputTests(unittest.TestCase):
    def test_json_schema(self):
        code, out, _ = run([os.path.join(FIX, "bad", "SL001-missing-type.json"), "--format", "json"])
        r = json.loads(out)
        for key in ("tool_count", "payload_bytes", "findings", "errors", "warnings", "source", "version"):
            self.assertIn(key, r)
        for f in r["findings"]:
            self.assertEqual(sorted(f), ["message", "path", "rule", "severity", "tool"])
            self.assertIn(f["severity"], ("ERROR", "WARN"))

    def test_text_output(self):
        code, out, _ = run([os.path.join(FIX, "bad", "SL007-duplicate-name.json")])
        self.assertEqual(code, 1)
        self.assertIn("ERROR SL007 search/name", out)
        self.assertIn("1 error(s)", out)

    def test_sl004_is_warning(self):
        code, out, _ = run([os.path.join(FIX, "bad", "SL004-array-no-items.json"), "--format", "json"])
        r = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(r["errors"], 0)
        self.assertGreaterEqual(r["warnings"], 1)


class InputShapeTests(unittest.TestCase):
    TOOL = {"name": "x", "inputSchema": {"type": "string"}}

    def test_shapes(self):
        for data in ({"tools": [self.TOOL]}, {"result": {"tools": [self.TOOL]}}, [self.TOOL]):
            self.assertIn("SL001", flagged(L.lint(data)))

    def test_bad_shape(self):
        with self.assertRaises(L.InputError):
            L.lint({"nothing": 1})

    def test_prefix_items_ok(self):
        data = [{"name": "x", "inputSchema": {"type": "object", "properties": {
            "p": {"type": "array", "prefixItems": [{"type": "string"}]}}}}]
        self.assertEqual(flagged(L.lint(data)), [])


class CliTests(unittest.TestCase):
    def test_help(self):
        code, out, _ = run(["--help"])
        self.assertEqual(code, 0)
        self.assertIn("cannot prove", out)
        for gone in ("--spec-era", "--max-payload-bytes", "--instructions-file"):
            self.assertNotIn(gone, out)

    def test_list_rules(self):
        code, out, _ = run(["--list-rules"])
        self.assertEqual(code, 0)
        lines = [l for l in out.splitlines() if l.strip()]
        self.assertEqual(len(lines), 3)
        self.assertEqual([l.split()[0] for l in lines], ["SL001", "SL004", "SL007"])

    def test_missing_file(self):
        self.assertEqual(run(["no-such-file.json"])[0], 2)

    def test_no_input(self):
        self.assertEqual(run([])[0], 2)

    def test_bad_json(self):
        self.assertEqual(run([os.path.join(FIX, "INDEX.md")])[0], 2)

    def test_unknown_rule(self):
        good = os.path.join(FIX, "good", "good-SL001-object-root.json")
        self.assertEqual(run([good, "--rules", "SL002"])[0], 2)
        self.assertEqual(run([good, "--rules", "SL999"])[0], 2)

    def test_rule_selection(self):
        f = os.path.join(FIX, "bad", "SL001-missing-type.json")
        self.assertEqual(run([f, "--rules", "SL004,SL007"])[0], 0)
        self.assertEqual(run([f, "--rules", "sl001"])[0], 1)


class CommandTests(unittest.TestCase):
    S25 = "%s %s" % (sys.executable, os.path.join(SERVERS, "server_2025.py"))
    S26 = "%s %s" % (sys.executable, os.path.join(SERVERS, "server_2026.py"))
    HANG = "%s %s" % (sys.executable, os.path.join(SERVERS, "hang_server.py"))

    def check(self, cmd, protocol, era):
        code, out, err = run(["--command", cmd, "--protocol", protocol, "--format", "json"])
        self.assertEqual(code, 0, err)
        r = json.loads(out)
        self.assertEqual(r["tool_count"], 3)
        self.assertIn(era, r["source"])

    def test_2025_explicit(self):
        self.check(self.S25, "2025-11-25", "2025-11-25")

    def test_2025_auto(self):
        self.check(self.S25, "auto", "2025-11-25")

    def test_2026_explicit(self):
        self.check(self.S26, "2026-07-28", "2026-07-28")

    def test_2026_auto(self):
        self.check(self.S26, "auto", "2026-07-28")

    def test_wrong_era(self):
        self.assertEqual(run(["--command", self.S26, "--protocol", "2025-11-25", "--timeout", "3"])[0], 2)

    def test_hang_times_out(self):
        code, _, err = run(["--command", self.HANG, "--timeout", "1"], timeout=30)
        self.assertEqual(code, 2)
        self.assertIn("did not answer", err)

    def test_bad_command(self):
        self.assertEqual(run(["--command", "no-such-binary-xyz"])[0], 2)


if __name__ == "__main__":
    unittest.main()
