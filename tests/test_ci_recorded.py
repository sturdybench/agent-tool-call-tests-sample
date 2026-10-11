"""CI regression check on recorded agent outputs. Offline: it calls no model and needs no API key.

It scores a recorded responses file against cases/ and compares each case with a baseline.
One pytest test per case, so a failure names the case and says which way it failed.

Environment variables:
    ATP_RESPONSES  recorded responses file (default: examples/responses.example.json)
    ATP_BASELINE   baseline file: which cases are known to fail, and how
                   (default: tests/fixtures/ci_baseline.json, used only with the default responses)
    ATP_CASES      case folder (default: cases/)

With ATP_RESPONSES set and no ATP_BASELINE, every case must pass.
Write a baseline for your own file on purpose, after you have reviewed the fails:
    ATP_RESPONSES=my_responses.json python3 tests/test_ci_recorded.py --write my_baseline.json
Run: python -m pytest
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RESPONSES = ROOT / "examples" / "responses.example.json"
DEFAULT_BASELINE = Path(__file__).resolve().parent / "fixtures" / "ci_baseline.json"
sys.path.insert(0, str(ROOT / "runner"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import atp  # noqa: E402
from ci_baseline import BaselineError, load_baseline, read_baseline, stale_totals, totals  # noqa: E402

WORDS = {
    "over_call": "called when it should not have",
    "missed_call": "did not call when it should have",
    "wrong_call": "wrong call (wrong tool, arguments or number of calls)",
    "other_fail": "other fail (no response, bad output, or reply text lacks the required words)",
    "pass": "pass",
}


def _path(value):
    p = Path(value)
    return p if p.is_absolute() else Path.cwd() / p


def settings():
    """Return (responses path, baseline path or None, cases dir)."""
    env_resp = os.environ.get("ATP_RESPONSES")
    env_base = os.environ.get("ATP_BASELINE")
    responses = _path(env_resp) if env_resp else DEFAULT_RESPONSES
    if env_base:
        baseline = _path(env_base)
    else:
        baseline = None if env_resp else DEFAULT_BASELINE
    cases = _path(os.environ["ATP_CASES"]) if os.environ.get("ATP_CASES") else ROOT / "cases"
    return responses, baseline, cases


def run():
    responses, baseline, cases_dir = settings()
    cases = atp.load_cases(str(cases_dir))
    results = atp.run_cases(cases, atp.responses_agent(str(responses)))
    return cases, results, responses, baseline


def baseline_doc(results, responses):
    fails = {r["id"]: r["direction"] for r in results if not r["passed"]}
    try:
        responses = Path(responses).resolve().relative_to(ROOT)
    except ValueError:
        pass
    return {"responses": str(responses), "known_fails": dict(sorted(fails.items())),
            "directions": atp.directions(results)}


if __name__ == "__main__" and len(sys.argv) == 3 and sys.argv[1] == "--write":
    _, res, resp, _ = run()
    Path(sys.argv[2]).write_text(json.dumps(baseline_doc(res, resp), indent=2) + "\n", encoding="utf-8")
    print("wrote %s: %d known fail(s)" % (sys.argv[2], sum(1 for r in res if not r["passed"])))
    sys.exit(0)

try:
    import pytest  # noqa: E402
except ImportError:  # plain "python3 -m unittest discover tests" without pytest installed
    import unittest
    raise unittest.SkipTest("test_ci_recorded.py needs pytest: pip install pytest")

CASES, RESULTS, RESPONSES, BASELINE = run()
try:
    KNOWN = load_baseline(BASELINE)
    BAD_BASELINE = None
except BaselineError as e:  # a typo such as "wrongcall": one readable line, no KeyError later
    BAD_BASELINE = str(e)
if BAD_BASELINE:
    pytest.fail(BAD_BASELINE, pytrace=False)
BY_ID = {r["id"]: r for r in RESULTS}


def failure_message(r, want):
    got = r["direction"]
    head = "%s: %s." % (r["id"], WORDS[got])
    if want == "pass":
        head = "REGRESSION " + head + " Expected pass."
    else:
        head = "CHANGED " + head + " Baseline says: %s." % WORDS[want]
    return "%s\n  reasons: %s\n  expected behavior: %s\n  responses: %s" % (
        head, "; ".join(r["reasons"]) or "none", r["scoring_note"], RESPONSES)


@pytest.mark.parametrize("case_id", [c["id"] for c in CASES])
def test_case(case_id):
    r = BY_ID[case_id]
    want = KNOWN.get(case_id, "pass")
    got = r["direction"]
    if got == want == "pass":
        return
    if got == want:
        pytest.xfail("known fail in baseline %s: %s; %s" % (BASELINE, WORDS[got], "; ".join(r["reasons"])))
    if got == "pass":
        pytest.fail("%s now passes but the baseline %s lists it as a known fail (%s). "
                    "Good news. Update the baseline on purpose." % (case_id, BASELINE, WORDS[want]))
    pytest.fail(failure_message(r, want))


def test_baseline_totals_match_known_fails():
    """The stored "directions" totals must equal the totals computed from known_fails."""
    if BASELINE is None:
        return
    stale = stale_totals(read_baseline(BASELINE))
    assert not stale, "baseline %s has stale direction totals:\n  %s\n  Fix the totals or rewrite " \
        "the baseline with --write." % (BASELINE, "\n  ".join(stale))


def test_direction_counts():
    """Live fail counts per direction must not exceed the baseline's allowance.
    The allowance is computed from known_fails, which test_baseline_totals_match_known_fails
    ties to the stored totals. It is not independent of known_fails."""
    got = atp.directions(RESULTS)
    want = totals(KNOWN)
    over = ["%s: %d now, %d allowed" % (WORDS[k], got[k], want[k]) for k in atp.DIRECTIONS if got[k] > want[k]]
    assert not over, "more fails than the baseline allows:\n  " + "\n  ".join(over) + \
        "\n  " + atp.direction_line(got)
