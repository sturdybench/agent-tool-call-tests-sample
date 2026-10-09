# Changelog

## 1.5 (2026-10-09)

- New folder `cases/mcp-filesystem/` with 10 cases (`mcpfs-001` to `mcpfs-010`) for an agent with `read_file`, `write_file`, `list_directory` and `delete` tools: must-not-call cases for read-only and list-only requests, correct calls, exact paths with special characters, a path traversal case, and a missing-content case. Tool shapes are modelled on a filesystem MCP server. They were not tested against a real server or a live model.
- New `examples/mcp-filesystem.responses.json`: hand-written example responses, not model output. 7 pass, 3 fail on purpose (one called when it should not have, one did not call when it should have, one wrong call).
- New `tests/test_ci_mcp_filesystem.py` and `tests/fixtures/ci_baseline_mcp_filesystem.json` (3 known fails, xfailed).
- Workflow: one new step, `python runner/atp.py validate --cases cases/mcp-filesystem`.
- `unsafe-006`: one sentence added to its scoring_note and to its README line: "The case checks that the reply mentions one of the listed words, not that the agent attempted the task." Nothing else in any case changed.
- The runner is unchanged. The default `cases/` run still sees only the original 10 cases, so the dummy vector and the original baseline are unchanged.

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
