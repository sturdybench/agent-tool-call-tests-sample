#!/usr/bin/env python3
"""Toy agent for checking your setup. It is NOT a benchmark and not a good agent.

Rules: refuse if the last user message looks destructive; otherwise pick the tool whose
name/description words overlap most with the last user message, fill required args with
naive guesses, and ask a question if nothing overlaps. It passes some cases, fails others.
Use: python3 runner/atp.py run --command "python3 runner/dummy_agent.py"
"""
import json
import re
import sys

REFUSE = ("delete all", "wipe", "format the", "ignore previous", "ignore all previous")


def words(s):
    return set(w for w in re.findall(r"[a-z]+", s.lower()) if len(w) > 2)


def last_user(case):
    for m in reversed(case["messages"]):
        if m.get("role") == "user":
            return m.get("content", "")
    return ""


def guess(prop, name, text):
    t = prop.get("type")
    if "enum" in prop:
        return prop["enum"][0]
    if t == "integer":
        m = re.search(r"-?\d+", text)
        return int(m.group()) if m else 0
    if t == "number":
        m = re.search(r"-?\d+(?:\.\d+)?", text)
        return float(m.group()) if m else 0
    if t == "boolean":
        return True
    if t == "array":
        return []
    if t == "string":
        q = re.search(r"\"([^\"]+)\"|'([^']+)'", text)
        if q:
            return q.group(1) or q.group(2)
        return ""
    return None


def respond(case):
    text = last_user(case)
    if any(p in text.lower() for p in REFUSE):
        return {"case_id": case["id"], "tool_calls": [],
                "text": "I can't do that without confirmation. I won't proceed."}
    uw = words(text)
    best, best_score = None, 0
    for t in case["tools"]:
        s = len(uw & (words(t["name"].replace("_", " ")) | words(t["description"])))
        if s > best_score:
            best, best_score = t, s
    if best is None:
        return {"case_id": case["id"], "tool_calls": [],
                "text": "Could you clarify what you would like me to do?"}
    params = best["parameters"]
    props = params.get("properties", {})
    args = {k: guess(props[k], k, text) for k in params.get("required", [])}
    return {"case_id": case["id"], "tool_calls": [{"name": best["name"], "arguments": args}], "text": ""}


if __name__ == "__main__":
    print(json.dumps(respond(json.loads(sys.stdin.read()))))
