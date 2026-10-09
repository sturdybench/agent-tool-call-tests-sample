# Changelog

## 1.4 (2026-10-09)

- New `.github/workflows/tool-call-tests.yml`. On every pull request and push it validates the cases and runs `python -m pytest`. No model calls, no API key, no secrets. The only network use is installing pytest.
- New `tests/test_ci_recorded.py`. It scores a recorded responses file against the cases, one test per case, and names the direction of each fail: called when it should not have, did not call when it should have, wrong call, or other fail. `test_direction_counts` fails if any direction has more fails than the baseline allows.
- New `tests/fixtures/ci_baseline.json`: the 8 known fails of `examples/responses.example.json`, reported as xfailed.
- Settings: `ATP_RESPONSES` (your recorded file), `ATP_BASELINE` (your known fails), `ATP_CASES` (case folder). Write a baseline with `python3 tests/test_ci_recorded.py --write FILE`.
- New `pytest.ini` (test folder only).
- README: new "Run in CI" section.
- No case changed. The runner is unchanged. Still 10 cases. `python3 -m unittest discover tests` still works without pytest; it skips the CI test file.

## 1.3

- New `tests/test_dummy_vector.py` and `tests/fixtures/dummy_vector.json`. The test fails when a case edit changes which cases the dummy agent passes, and names each case that moved. Regenerate on purpose with `python3 tests/test_dummy_vector.py --write`.

## 1.2

- New optional response field `raw` for the model's original tool calls. When present, the runner scores `raw`. Reports show `raw`, `normalized` and `adapter_diff`. README: "Adapter boundary" section.

## 1.1

- First public version of this repo. 10 cases, one per theme, and the standard library runner.
- The run summary splits fails by direction: called when it should not have, did not call when it should have, wrong call, other fails.
