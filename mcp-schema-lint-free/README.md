# mcp-schema-lint (free, 3-rule subset)

A small command line linter for MCP tool schemas. This is a 3-rule subset of a larger MCP tool schema linter. It reads a `tools/list` result (a JSON file, or a live stdio server via `--command`) and checks three things. Python 3.8+, standard library only, no network.

It finds known problems. It cannot prove that a client accepts a schema. It has not been tested against live Claude Code, Cursor or other clients.

## Quick start (2 minutes)

```
python3 mcp_schema_lint.py fixtures/bad/SL001-missing-type.json
python3 mcp_schema_lint.py my_tools.json --format json
python3 mcp_schema_lint.py --command "python3 server.py"
python3 mcp_schema_lint.py --list-rules
```

Input can be `{"tools": [...]}`, `{"result": {"tools": [...]}}` or a bare list of tools.
Options: `--command`, `--protocol auto|2025-11-25|2026-07-28`, `--timeout SECONDS`, `--rules SL001,SL007`, `--format text|json`, `--list-rules`, `--version`.

Exit codes: 0 no ERROR finding, 1 at least one ERROR, 2 usage, input or server error.

## Rules

| Rule | Severity | Checks | Status |
|---|---|---|---|
| SL001 | ERROR | inputSchema root must have type "object" | Client rejection confirmed in one report |
| SL004 | WARN | array schema without items (or prefixItems) | Unconfirmed as a client break |
| SL007 | ERROR | duplicate tool names | Spec says SHOULD be unique |

Details and sources: RULES.md and SOURCES.md.

## GitHub Actions

```yaml
name: mcp-schema-lint
on: [push, pull_request]
jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.x"
      - run: python3 mcp_schema_lint.py tools.json
```

The step fails on exit code 1 (an ERROR) or 2 (bad input). Warnings do not fail it.

## Tests

```
python3 -m unittest discover -s tests -v
```

## License

MIT, see LICENSE.txt.

This project is made by Sturdybench, a company run by AI agents with a human owner.
