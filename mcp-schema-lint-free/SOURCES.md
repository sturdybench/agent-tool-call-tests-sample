# Sources (excerpt for SL001, SL004, SL007)

| Rule | Source | What it says | Status |
|---|---|---|---|
| SL001 | https://github.com/anthropics/claude-code/issues/28620 | Opened 2026-02-25, closed not planned 2026-03-26. A tool with root `anyOf` and no root `type` gave a Kilo CLI error at ["tools",20,"inputSchema","type"]: expected "object". The reporter claims the spec requires root type object (reporter's claim). | Client rejection CONFIRMED; spec claim REPORTED |
| SL001 | https://modelcontextprotocol.io/specification/2025-11-25/server/tools | inputSchema "MUST be a valid JSON Schema object (not null)"; no-parameter tools use `{ "type": "object" }`. Prose does not literally say root type MUST be object. | CONFIRMED (official), partly |
| SL001 | https://modelcontextprotocol.io/specification/2026-07-28/server/tools | Same wording and examples. | CONFIRMED (official), partly |
| SL004 | https://modelcontextprotocol.io/specification/2026-07-28/server/tools | The outputSchema example with `type: array` includes `items`. No client failure documented. | UNCONFIRMED as a client break; best practice |
| SL007 | https://modelcontextprotocol.io/specification/2025-11-25/server/tools | "Tool names SHOULD be unique within a server". | CONFIRMED as SHOULD |
| SL007 | https://modelcontextprotocol.io/specification/2026-07-28/server/tools | Still SHOULD be unique; a note on cross-server collisions in aggregators. No client failure source. | CONFIRMED as SHOULD |

Checked in the course of building the full linter; not re-verified for this subset.
