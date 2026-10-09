#!/usr/bin/env python3
"""Template: plug your own agent in. Run with:
  python3 runner/atp.py run --command "python3 examples/my_agent_template.py"

The runner writes ONE case as JSON on stdin and expects ONE JSON object on stdout:
  {"case_id": "...", "tool_calls": [{"name": "...", "arguments": {...}}], "text": "..."}
"arguments" may be an object or a JSON string. Print nothing else to stdout (logs go to stderr).
"""
import json
import sys


def my_agent(messages, tools):
    """Replace this stub with a call to your own model or agent.

    messages: list of {"role": "user"|"assistant"|"tool", "content": ..., ...}
    tools:    list of {"name", "description", "parameters": <JSON Schema>}
    Return (tool_calls, text). Convert tools to your provider's format here.
    """
    # TODO: call your agent here (this template makes no API calls).
    return [], "stub: no tool calls"


def main():
    case = json.loads(sys.stdin.read())
    tool_calls, text = my_agent(case["messages"], case["tools"])
    print(json.dumps({"case_id": case["id"], "tool_calls": tool_calls, "text": text}))


if __name__ == "__main__":
    main()
