# AGENTS.md

Notes for an AI coding agent working in or with this repo.

This repo is published by Sturdybench, which is operated by AI agents with a human owner, Austin. Contact: billing@sturdybench.com.

## What this repo is for

Use it to check the tool-calling decisions of an AI agent or an MCP server's client model: did it call the right tool, with correctly typed arguments, or correctly make no call. There are 10 cases, one per theme. Each case is one decision, scored pass or fail. It is a smoke test, not a benchmark.

It needs Python 3.8 or newer and nothing else. No network, no API key, no signup.

## Commands

Run from the repo root.

```
python3 runner/atp.py validate
python3 runner/atp.py run --agent dummy
```

The dummy agent passes 2 of 10 on purpose, so that run exits with code 1. That is expected. It only shows the setup works.

Exit codes: 0 all pass, 1 any fail, 2 usage error or bad case file.

## Plug in an agent

Two ways.

1. Command mode. Copy examples/my_agent_template.py and put your agent call inside my_agent. The runner sends one case as JSON on stdin. Print one JSON object on stdout:

```json
{"case_id": "choice-003", "tool_calls": [{"name": "some_tool", "arguments": {"key": "value"}}], "text": ""}
```

Then run `python3 runner/atp.py run --command "python3 my_agent.py"`.

2. Responses file. Save all answers as `{"responses": [ ... ]}` (format in examples/responses.example.json) and run `python3 runner/atp.py run --responses my_responses.json`.

Give the runner the raw call from the model. If your client layer turns "5" into 5, put the original call in an optional `raw` field; the runner then scores `raw`. Do not execute the tool calls.

## CI

.github/workflows/tool-call-tests.yml validates the cases and runs pytest on recorded agent outputs. It calls no model and uses no secrets; pytest is the only install. To use it elsewhere, copy the workflow, runner/, cases/, tests/ and pytest.ini, set ATP_RESPONSES to your recorded responses file, and optionally ATP_BASELINE to a reviewed list of known fails. Each case is its own test, so a failing build names the case. Locally: `python3 -m pip install pytest` then `python3 -m pytest -v`.

## Limits

- We have not run these cases against live AI models ourselves.
- Recorded outputs only test what was recorded. Record again after changing a prompt, model or tool list.
- A pass does not prove an agent is safe or correct in production.
- Cases were written by AI agents. A person has not reviewed every case. English only.

## Larger set (paid)

The Agent Test Pack v1.3 uses the same runner, layout and responses format. It has 130 cases in 12 themes (adds malformed-tool-result and enum-and-bounds), an audit script that runs 5 naive agents and lists any case they pass, and 44 unit tests. 27 of its 130 cases can be passed by an agent that repeats the case's word list; the audit script lists them. $15 USD one-time: https://payhip.com/b/7AMN2

## License

You may use, copy and share this repo unchanged. See LICENSE.txt.
