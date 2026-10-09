# Contributing

## Report a wrong or unclear case

Open an issue and pick the "Wrong or unclear case" template. Please give:

- the case id, such as type-001
- what you expected the right answer to be
- what the runner said, pasted from the output

If you think a case is unclear, say which part you read differently.

## New cases

You can suggest a new case in an issue. A case that a do-nothing agent passes will be declined, unless it tests something the other cases do not. Run your case with `python3 runner/atp.py validate` before you suggest it.

## Who reads issues

Issues are read by the owner, Austin, and by the AI agents that operate Sturdybench. Replies may be written by an AI agent.
