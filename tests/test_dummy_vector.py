"""Reference vector: which sample cases the dummy agent passes.

The expected vector is stored in tests/fixtures/dummy_vector.json. If a case edit changes it,
this test fails. Review the case edit. If the new vector is what you want, regenerate on purpose:
    python3 tests/test_dummy_vector.py --write
Run the test: python3 -m unittest discover tests
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "dummy_vector.json"
sys.path.insert(0, str(ROOT / "runner"))
import atp  # noqa: E402
import dummy_agent  # noqa: E402

REGEN = "python3 tests/test_dummy_vector.py --write"


def dummy_vector():
    cases = atp.load_cases(str(ROOT / "cases"))
    return {"cases": {c["id"]: atp.score(c, dummy_agent.respond(c))[0] for c in cases}}


class DummyVector(unittest.TestCase):
    def test_dummy_vector_matches_fixture(self):
        self.assertTrue(FIXTURE.exists(), "missing fixture %s. Create it with: %s" % (FIXTURE, REGEN))
        want = json.loads(FIXTURE.read_text()).get("cases", {})
        got = dummy_vector()["cases"]
        lines = ["  %s: fixture %s, now %s" % (cid, json.dumps(want.get(cid, "missing")),
                                               json.dumps(got.get(cid, "missing")))
                 for cid in sorted(set(want) | set(got)) if want.get(cid, "missing") != got.get(cid, "missing")]
        if lines:
            self.fail("dummy_vector.json drifted from tests/fixtures/dummy_vector.json (%d case(s)):\n%s\n"
                      "A case edit changed which cases the dummy agent passes. Review the case edit. "
                      "If the new vector is intended, regenerate on purpose with: %s"
                      % (len(lines), "\n".join(lines), REGEN))


if __name__ == "__main__":
    if "--write" in sys.argv[1:]:
        FIXTURE.parent.mkdir(exist_ok=True)
        FIXTURE.write_text(json.dumps(dummy_vector(), indent=2, sort_keys=True) + "\n")
        print("wrote tests/fixtures/dummy_vector.json")
    else:
        unittest.main()
