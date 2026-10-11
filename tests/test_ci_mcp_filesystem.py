"""CI regression check for the MCP filesystem cases. Offline: it calls no model and needs no API key.

It scores examples/mcp-filesystem.responses.json against cases/mcp-filesystem/ and compares each
case with tests/fixtures/ci_baseline_mcp_filesystem.json. Same rules as tests/test_ci_recorded.py:
one pytest test per case, known fails are xfailed, any other fail names its direction.

The paths are fixed. ATP_RESPONSES, ATP_BASELINE and ATP_CASES do not change this file.
Rewrite the baseline on purpose, after you have reviewed the fails:
    ATP_RESPONSES=examples/mcp-filesystem.responses.json ATP_CASES=cases/mcp-filesystem \
        python3 tests/test_ci_recorded.py --write tests/fixtures/ci_baseline_mcp_filesystem.json
Run: python -m pytest
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CASES_DIR = ROOT / "cases" / "mcp-filesystem"
RESPONSES = ROOT / "examples" / "mcp-filesystem.responses.json"
BASELINE = Path(__file__).resolve().parent / "fixtures" / "ci_baseline_mcp_filesystem.json"
sys.path.insert(0, str(ROOT / "runner"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import atp  # noqa: E402
from ci_baseline import BaselineError, load_baseline, read_baseline, stale_totals, totals  # noqa: E402

try:
    import pytest  # noqa: E402
except ImportError:  # plain "python3 -m unittest discover tests" without pytest installed
    import unittest
    raise unittest.SkipTest("test_ci_mcp_filesystem.py needs pytest: pip install pytest")

WORDS = {
    "over_call": "called when it should not have",
    "missed_call": "did not call when it should have",
    "wrong_call": "wrong call (wrong tool, arguments or number of calls)",
    "other_fail": "other fail (no response, bad output, or reply text lacks the required words)",
    "pass": "pass",
}

CASES = atp.load_cases(str(CASES_DIR))
RESULTS = atp.run_cases(CASES, atp.responses_agent(str(RESPONSES)))
try:
    KNOWN = load_baseline(BASELINE)
    BAD_BASELINE = None
except BaselineError as e:  # a typo such as "wrongcall": one readable line, no KeyError later
    BAD_BASELINE = str(e)
if BAD_BASELINE:
    pytest.fail(BAD_BASELINE, pytrace=False)
BY_ID = {r["id"]: r for r in RESULTS}


@pytest.mark.parametrize("case_id", [c["id"] for c in CASES])
def test_case(case_id):
    r = BY_ID[case_id]
    want = KNOWN.get(case_id, "pass")
    got = r["direction"]
    if got == want == "pass":
        return
    if got == want:
        pytest.xfail("known fail in baseline %s: %s; %s" % (BASELINE.name, WORDS[got], "; ".join(r["reasons"])))
    if got == "pass":
        pytest.fail("%s now passes but the baseline %s lists it as a known fail (%s). "
                    "Update the baseline on purpose." % (case_id, BASELINE.name, WORDS[want]))
    head = "%s: %s." % (case_id, WORDS[got])
    head = ("REGRESSION " + head + " Expected pass.") if want == "pass" else \
        ("CHANGED " + head + " Baseline says: %s." % WORDS[want])
    pytest.fail("%s\n  reasons: %s\n  expected behavior: %s\n  responses: %s" % (
        head, "; ".join(r["reasons"]) or "none", r["scoring_note"], RESPONSES))


def test_baseline_totals_match_known_fails():
    """The stored "directions" totals must equal the totals computed from known_fails."""
    stale = stale_totals(read_baseline(BASELINE))
    assert not stale, "baseline %s has stale direction totals:\n  %s\n  Fix the totals or rewrite " \
        "the baseline with --write." % (BASELINE.name, "\n  ".join(stale))


def test_direction_counts():
    """Live fail counts per direction must not exceed the baseline's allowance.
    The allowance is computed from known_fails, which test_baseline_totals_match_known_fails
    ties to the stored totals. It is not independent of known_fails."""
    got = atp.directions(RESULTS)
    want = totals(KNOWN)
    over = ["%s: %d now, %d allowed" % (WORDS[k], got[k], want[k]) for k in atp.DIRECTIONS if got[k] > want[k]]
    assert not over, "more fails than the baseline allows:\n  " + "\n  ".join(over) + \
        "\n  " + atp.direction_line(got)
