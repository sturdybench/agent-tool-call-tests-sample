# Rules

## SL001 (ERROR): inputSchema root type must be "object"
Flags a tool whose inputSchema is missing, has no `type`, or has a `type` other than "object".
Status: client rejection CONFIRMED in anthropics/claude-code #28620 (a Kilo CLI error: expected "object" at tools[20].inputSchema.type). The spec examples and no-parameter guidance use `type: object`, but the spec prose does not literally say "MUST". Treat as a strong convention.
Fix: set `"type": "object"` at the root of inputSchema.

## SL004 (WARN): array without items
Flags an array schema (in inputSchema or outputSchema, at any depth) with neither `items` nor `prefixItems`.
Status: UNCONFIRMED as a client break. No source found that documents a client failure. Spec examples always include `items`. Best practice only, so it is a warning and does not change the exit code.
Fix: add `items` (or `prefixItems` for tuples).

## SL007 (ERROR): duplicate tool names
Flags a tool name that appears more than once in the list.
Status: CONFIRMED as a SHOULD in the spec ("Tool names SHOULD be unique within a server"). No source shows a client failure caused by duplicates.
Fix: give each tool a unique name.
