"""Read and check a CI baseline file. Shared by test_ci_recorded.py and test_ci_mcp_filesystem.py.

It runs no tests and needs no pytest, so importing it is safe anywhere.
A baseline file has "known_fails" ({case_id: direction}) and "directions" (fail totals per direction).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "runner"))
import atp  # noqa: E402


class BaselineError(ValueError):
    """The baseline file cannot be used. The message names the file and what is wrong."""


def read_baseline(path):
    """Return the baseline document. Every known_fails value must be one of atp.DIRECTIONS."""
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except ValueError as e:
        raise BaselineError("BaselineError: %s is not valid JSON: %s" % (path, e)) from None
    known = doc.get("known_fails", {}) if isinstance(doc, dict) else None
    if not isinstance(known, dict):
        raise BaselineError("BaselineError: %s: known_fails must be an object {case_id: direction}" % path)
    for case_id, d in known.items():
        if d not in atp.DIRECTIONS:
            raise BaselineError("BaselineError: %s: case %s has direction %r. Valid values: %s." % (
                path, case_id, d, ", ".join(atp.DIRECTIONS)))
    return doc


def load_baseline(path):
    """Return {case_id: direction} for cases expected to fail. No file (None) means every case must pass."""
    if path is None:
        return {}
    return dict(read_baseline(path).get("known_fails", {}))


def totals(known):
    """Fail totals per direction, computed from {case_id: direction}."""
    d = dict.fromkeys(atp.DIRECTIONS, 0)
    for v in known.values():
        d[v] += 1
    return d


def stale_totals(doc):
    """Return one line per direction where the stored "directions" total differs from known_fails.
    A baseline with no "directions" object has nothing stored to go stale."""
    stored = doc.get("directions")
    if stored is None:
        return []
    computed = totals(doc.get("known_fails", {}))
    return ["%s: stored %s, computed from known_fails %d" % (k, stored.get(k, "missing"), computed[k])
            for k in atp.DIRECTIONS if stored.get(k) != computed[k]]
