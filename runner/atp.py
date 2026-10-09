#!/usr/bin/env python3
"""Agent Test Pack runner. Standard library only.

Usage:
  python3 runner/atp.py list [--cases DIR] [--theme T]
  python3 runner/atp.py validate [--cases DIR]
  python3 runner/atp.py run (--agent dummy | --responses FILE | --command CMD)
        [--cases DIR] [--theme T] [--report out.json|out.md] [--verbose] [--timeout 30]
Exit codes: 0 all pass, 1 any fail, 2 usage error or invalid case file.
"""
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

DEFAULT_CASES = HERE.parent / "cases"
ROLES = ("user", "assistant", "tool")
EXPECTED_TYPES = ("tool_calls", "no_call", "text_contains")
SCHEMA_TYPES = ("string", "integer", "number", "boolean", "array", "object", "null")


class CaseError(Exception):
    pass


# ---------------------------------------------------------------- schema
def json_type_ok(value, t):
    if t == "string":
        return isinstance(value, str)
    if t == "boolean":
        return isinstance(value, bool)
    if t == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if t == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if t == "array":
        return isinstance(value, list)
    if t == "object":
        return isinstance(value, dict)
    if t == "null":
        return value is None
    return False


def json_type_name(value):
    for t in ("null", "boolean", "integer", "number", "string", "array", "object"):
        if json_type_ok(value, t):
            return t
    return "unknown"


def schema_errors(value, schema, path="value"):
    """Return list of error strings; empty if value is valid for schema."""
    errs = []
    if not isinstance(schema, dict):
        return errs
    t = schema.get("type")
    if t is not None:
        types = t if isinstance(t, list) else [t]
        if not any(json_type_ok(value, x) for x in types):
            return ["%s: expected type %s, got %s (%r)" % (path, t, json_type_name(value), value)]
    if "enum" in schema and not any(strict_eq(value, e, False) for e in schema["enum"]):
        errs.append("%s: %r not in enum %r" % (path, value, schema["enum"]))
    if json_type_ok(value, "number"):
        if "minimum" in schema and value < schema["minimum"]:
            errs.append("%s: %r below minimum %r" % (path, value, schema["minimum"]))
        if "maximum" in schema and value > schema["maximum"]:
            errs.append("%s: %r above maximum %r" % (path, value, schema["maximum"]))
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errs.append("%s: shorter than minLength %r" % (path, schema["minLength"]))
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errs.append("%s: longer than maxLength %r" % (path, schema["maxLength"]))
    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        for i, v in enumerate(value):
            errs.extend(schema_errors(v, schema["items"], "%s[%d]" % (path, i)))
    if isinstance(value, dict):
        props = schema.get("properties", {})
        for r in schema.get("required", []):
            if r not in value:
                errs.append("%s: missing required key %r" % (path, r))
        for k, v in value.items():
            if k in props:
                errs.extend(schema_errors(v, props[k], "%s.%s" % (path, k)))
            elif schema.get("additionalProperties") is False:
                errs.append("%s: unknown key %r" % (path, k))
    return errs


def strict_eq(a, b, number_ok):
    """Type-sensitive JSON equality. int vs float equal only if number_ok."""
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if type(a) is not type(b) and not number_ok:
            return False
        return a == b
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(strict_eq(a[k], b[k], number_ok) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(strict_eq(x, y, number_ok) for x, y in zip(a, b))
    return type(a) is type(b) and a == b


def prop_number_ok(schema):
    t = schema.get("type") if isinstance(schema, dict) else None
    return t == "number" or (isinstance(t, list) and "number" in t)


# ---------------------------------------------------------------- validation
def _bad(fname, cid, msg):
    return CaseError("%s: case %s: %s" % (fname, cid, msg))


def validate_tool(fname, cid, tool):
    if not isinstance(tool, dict):
        raise _bad(fname, cid, "tool must be an object")
    for k in ("name", "description", "parameters"):
        if k not in tool:
            raise _bad(fname, cid, "tool missing %r" % k)
    if not isinstance(tool["name"], str) or not tool["name"]:
        raise _bad(fname, cid, "tool name must be a non-empty string")
    if not isinstance(tool["description"], str):
        raise _bad(fname, cid, "tool %s description must be a string" % tool["name"])
    p = tool["parameters"]
    if not isinstance(p, dict) or p.get("type") != "object" or not isinstance(p.get("properties", {}), dict):
        raise _bad(fname, cid, "tool %s parameters must be an object schema" % tool["name"])
    for r in p.get("required", []):
        if r not in p.get("properties", {}):
            raise _bad(fname, cid, "tool %s required key %r not in properties" % (tool["name"], r))


def validate_matcher(fname, cid, key, m):
    if not isinstance(m, dict) or not m:
        raise _bad(fname, cid, "arguments_match %r must be a non-empty object" % key)
    kinds = [k for k in ("contains", "regex", "one_of", "any") if k in m]
    if len(kinds) != 1:
        raise _bad(fname, cid, "arguments_match %r needs exactly one of contains/regex/one_of/any" % key)
    extra = set(m) - set(kinds) - {"type"}
    if extra:
        raise _bad(fname, cid, "arguments_match %r has unknown matcher keys %s" % (key, sorted(extra)))
    if "contains" in m and not isinstance(m["contains"], str):
        raise _bad(fname, cid, "arguments_match %r contains must be a string" % key)
    if "regex" in m:
        try:
            re.compile(m["regex"])
        except (re.error, TypeError) as e:
            raise _bad(fname, cid, "arguments_match %r bad regex: %s" % (key, e))
    if "one_of" in m and not (isinstance(m["one_of"], list) and m["one_of"]):
        raise _bad(fname, cid, "arguments_match %r one_of must be a non-empty list" % key)
    if "type" in m and m["type"] not in SCHEMA_TYPES:
        raise _bad(fname, cid, "arguments_match %r has invalid type %r" % (key, m["type"]))


def validate_case(fname, case, theme, seen):
    cid = case.get("id", "<no id>") if isinstance(case, dict) else "<not an object>"
    if not isinstance(case, dict):
        raise _bad(fname, cid, "case must be an object")
    for k in ("id", "theme", "description", "tools", "messages", "expected", "scoring_note"):
        if k not in case:
            raise _bad(fname, cid, "missing field %r" % k)
    if not isinstance(case["id"], str) or not case["id"]:
        raise _bad(fname, cid, "id must be a non-empty string")
    if case["id"] in seen:
        raise _bad(fname, cid, "duplicate id (also in %s)" % seen[case["id"]])
    seen[case["id"]] = fname
    if case["theme"] != theme:
        raise _bad(fname, cid, "theme %r does not match file theme %r" % (case["theme"], theme))
    for k in ("description", "scoring_note"):
        if not isinstance(case[k], str) or not case[k].strip():
            raise _bad(fname, cid, "%s must be a non-empty string" % k)
    tools = case["tools"]
    if not isinstance(tools, list) or not tools:
        raise _bad(fname, cid, "tools must be a non-empty list")
    names = {}
    for t in tools:
        validate_tool(fname, cid, t)
        if t["name"] in names:
            raise _bad(fname, cid, "duplicate tool name %r" % t["name"])
        names[t["name"]] = t
    msgs = case["messages"]
    if not isinstance(msgs, list) or not msgs:
        raise _bad(fname, cid, "messages must be a non-empty list")
    for i, m in enumerate(msgs):
        if not isinstance(m, dict) or m.get("role") not in ROLES:
            raise _bad(fname, cid, "message %d has invalid role (allowed %s)" % (i, "/".join(ROLES)))
        if not isinstance(m.get("content", ""), str):
            raise _bad(fname, cid, "message %d content must be a string" % i)
        if "tool_calls" in m:
            if m["role"] != "assistant" or not isinstance(m["tool_calls"], list):
                raise _bad(fname, cid, "message %d tool_calls only valid as a list on assistant messages" % i)
    exp = case["expected"]
    if not isinstance(exp, dict) or exp.get("type") not in EXPECTED_TYPES:
        raise _bad(fname, cid, "expected.type must be one of %s" % ", ".join(EXPECTED_TYPES))
    if "ordered" in exp and not isinstance(exp["ordered"], bool):
        raise _bad(fname, cid, "expected.ordered must be a boolean")
    ta = exp.get("text_any")
    if ta is not None and not (isinstance(ta, list) and ta and all(isinstance(s, str) and s for s in ta)):
        raise _bad(fname, cid, "text_any must be a non-empty list of non-empty strings")
    if exp["type"] == "text_contains" and ta is None:
        raise _bad(fname, cid, "text_contains requires text_any")
    if "text_any_in_question" in exp:
        if not isinstance(exp["text_any_in_question"], bool):
            raise _bad(fname, cid, "text_any_in_question must be a boolean")
        if exp["text_any_in_question"] and ta is None:
            raise _bad(fname, cid, "text_any_in_question requires text_any")
    for ft in exp.get("forbidden_tools", []):
        if ft not in names:
            raise _bad(fname, cid, "forbidden_tools name %r not in tools" % ft)
    if exp["type"] == "tool_calls":
        calls = exp.get("calls")
        if not isinstance(calls, list) or not calls:
            raise _bad(fname, cid, "tool_calls needs a non-empty calls list")
        for c in calls:
            if not isinstance(c, dict) or c.get("name") not in names:
                raise _bad(fname, cid, "expected call name %r not in tools" % (c.get("name") if isinstance(c, dict) else c))
            args = c.get("arguments")
            if not isinstance(args, dict):
                raise _bad(fname, cid, "expected call %s arguments must be an object" % c["name"])
            matchers = c.get("arguments_match", {})
            if not isinstance(matchers, dict):
                raise _bad(fname, cid, "arguments_match must be an object")
            schema = names[c["name"]]["parameters"]
            props = schema.get("properties", {})
            for k, m in matchers.items():
                if k not in props:
                    raise _bad(fname, cid, "arguments_match key %r not in %s schema" % (k, c["name"]))
                if k in args:
                    raise _bad(fname, cid, "key %r in both arguments and arguments_match" % k)
                validate_matcher(fname, cid, k, m)
            for r in schema.get("required", []):
                if r not in args and r not in matchers:
                    raise _bad(fname, cid, "expected call %s lacks required %r" % (c["name"], r))
            errs = []
            for k, v in args.items():
                if k not in props:
                    errs.append("unknown key %r" % k)
                else:
                    errs.extend(schema_errors(v, props[k], k))
            if errs:
                raise _bad(fname, cid, "expected arguments for %s invalid: %s" % (c["name"], "; ".join(errs)))
    return case


def load_cases(cases_dir, theme=None):
    """Load and validate all case files. Returns list of cases (sorted by file, in order)."""
    d = Path(cases_dir)
    if not d.is_dir():
        raise CaseError("cases folder not found: %s" % d)
    files = sorted(d.glob("*.json"))
    seen = {}
    out = []
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (ValueError, OSError) as e:
            raise CaseError("%s: not valid JSON: %s" % (f.name, e))
        if not isinstance(data, dict) or not isinstance(data.get("theme"), str) \
                or not isinstance(data.get("cases"), list):
            raise CaseError("%s: must be an object with string 'theme' and list 'cases'" % f.name)
        for c in data["cases"]:
            out.append(validate_case(f.name, c, data["theme"], seen))
    if theme:
        out = [c for c in out if c["theme"] == theme]
        if not out:
            raise CaseError("no cases for theme %r" % theme)
    return out


def theme_counts(cases):
    counts = {}
    for c in cases:
        counts[c["theme"]] = counts.get(c["theme"], 0) + 1
    return counts


# ---------------------------------------------------------------- scoring
def normalize_calls(resp):
    """Return (calls, error). calls = list of (name, args dict)."""
    raw = resp.get("tool_calls", [])
    if raw is None:
        raw = []
    if not isinstance(raw, list):
        return None, "tool_calls is not a list"
    calls = []
    for i, c in enumerate(raw):
        if not isinstance(c, dict) or not isinstance(c.get("name"), str):
            return None, "tool call %d has no name" % i
        args = c.get("arguments", {})
        if isinstance(args, str):
            try:
                args = json.loads(args) if args.strip() else {}
            except ValueError:
                return None, "tool call %d (%s): arguments string is not valid JSON" % (i, c["name"])
        if args is None:
            args = {}
        if not isinstance(args, dict):
            return None, "tool call %d (%s): arguments is not an object" % (i, c["name"])
        calls.append((c["name"], args))
    return calls, None


def scored_payload(resp):
    """Return (payload, error). With the optional "raw" field, the raw tool calls are scored."""
    if "raw" not in resp:
        return resp, None
    raw = resp["raw"]
    if not isinstance(raw, dict):
        return None, "raw is not a JSON object"
    if not isinstance(raw.get("tool_calls", []), list):
        return None, "raw tool_calls is not a list"
    _, err = normalize_calls(raw)
    if err:
        return None, "raw " + err
    payload = dict(resp)
    del payload["raw"]
    payload["tool_calls"] = raw.get("tool_calls", [])
    return payload, None


def adapter_diff(resp):
    """True if raw and normalized tool calls differ. Type sensitive: 5, 5.0 and "5" all differ."""
    if not isinstance(resp.get("raw"), dict):
        return True
    a, aerr = normalize_calls(resp["raw"])
    b, berr = normalize_calls(resp)
    if aerr or berr:
        return True
    return not strict_eq([[n, x] for n, x in a], [[n, x] for n, x in b], False)


def check_matcher(value, m, schema):
    if "type" in m and not json_type_ok(value, m["type"]):
        return "expected type %s, got %s" % (m["type"], json_type_name(value))
    if "contains" in m:
        if not isinstance(value, str) or m["contains"].lower() not in value.lower():
            return "%r does not contain %r" % (value, m["contains"])
    elif "regex" in m:
        if not isinstance(value, str) or not re.search(m["regex"], value):
            return "%r does not match /%s/" % (value, m["regex"])
    elif "one_of" in m:
        nok = prop_number_ok(schema)
        if not any(strict_eq(value, o, nok) for o in m["one_of"]):
            return "%r not one of %r" % (value, m["one_of"])
    return None


def call_mismatch(exp, got_name, got_args, tools_by_name):
    """Return list of reasons the actual call does not match expected call; [] if it matches."""
    if got_name != exp["name"]:
        return ["called %s, expected %s" % (got_name, exp["name"])]
    schema = tools_by_name[exp["name"]]["parameters"]
    props = schema.get("properties", {})
    exact = exp.get("arguments", {})
    matchers = exp.get("arguments_match", {})
    reasons = []
    for r in schema.get("required", []):
        if r not in got_args:
            reasons.append("%s: missing required argument %r" % (got_name, r))
    for k, v in got_args.items():
        if k not in props:
            reasons.append("%s: unknown argument %r" % (got_name, k))
            continue
        errs = schema_errors(v, props[k], k)
        if errs:
            reasons.append("%s: %s" % (got_name, "; ".join(errs)))
            continue
        if k in matchers:
            r = check_matcher(v, matchers[k], props[k])
            if r:
                reasons.append("%s.%s: %s" % (got_name, k, r))
        elif k in exact:
            if not strict_eq(v, exact[k], prop_number_ok(props[k])):
                reasons.append("%s.%s: got %r, expected %r" % (got_name, k, v, exact[k]))
        elif k in schema.get("required", []):
            reasons.append("%s: required argument %r not covered by expected call" % (got_name, k))
        # else: optional, schema-valid extra key is allowed
    for k in list(exact) + list(matchers):
        if k not in got_args and k not in schema.get("required", []):
            reasons.append("%s: missing expected argument %r" % (got_name, k))
    return reasons


def _bipartite(compat, n):
    """compat[i] = list of j. Return True if perfect matching of n expected exists."""
    match_to = {}

    def try_(i, seen):
        for j in compat[i]:
            if j in seen:
                continue
            seen.add(j)
            if j not in match_to or try_(match_to[j], seen):
                match_to[j] = i
                return True
        return False

    return all(try_(i, set()) for i in range(n))


def question_sentences(text):
    """Return the parts of text that end in a question mark, one per sentence."""
    return re.findall(r"[^.!?\n]*\?", text)


def text_reasons(exp, text):
    """Check text_any and text_any_in_question. Every reason starts with 'text '."""
    ta = exp.get("text_any")
    if not ta:
        return []
    if exp.get("text_any_in_question"):
        qs = [q.lower() for q in question_sentences(text)]
        if not qs:
            return ["text has no question (needs a question mark)"]
        if not any(s.lower() in q for q in qs for s in ta):
            return ["text has no question that contains any of %r" % ta]
        return []
    if not any(s.lower() in text.lower() for s in ta):
        return ["text lacks any of %r" % ta]
    return []


def score(case, resp):
    """Score a response dict against a case. Returns (passed, reasons)."""
    reasons = []
    if not isinstance(resp, dict):
        return False, ["response is not a JSON object"]
    resp, err = scored_payload(resp)
    if err:
        return False, [err]
    calls, err = normalize_calls(resp)
    if err:
        return False, [err]
    exp = case["expected"]
    tools_by_name = {t["name"]: t for t in case["tools"]}
    text = resp.get("text") or ""
    if not isinstance(text, str):
        text = str(text)

    for name, _ in calls:
        if name in exp.get("forbidden_tools", []):
            reasons.append("called forbidden tool %s" % name)
        elif name not in tools_by_name:
            reasons.append("called unknown tool %s" % name)

    if exp["type"] == "tool_calls":
        want = exp["calls"]
        if len(calls) != len(want):
            reasons.append("expected %d tool call(s), got %d" % (len(want), len(calls)))
        elif not reasons:
            if exp.get("ordered", False):
                for i, (e, (n, a)) in enumerate(zip(want, calls)):
                    r = call_mismatch(e, n, a, tools_by_name)
                    reasons.extend("call %d: %s" % (i + 1, x) for x in r)
            else:
                compat = [[j for j, (n, a) in enumerate(calls)
                           if not call_mismatch(e, n, a, tools_by_name)] for e in want]
                if not _bipartite(compat, len(want)):
                    # explain using best-effort per-expected-call first mismatch
                    for i, e in enumerate(want):
                        if not compat[i]:
                            why = [call_mismatch(e, n, a, tools_by_name) for n, a in calls]
                            why = min(why, key=len) if why else ["no calls"]
                            reasons.append("no call matches expected %s: %s" % (e["name"], "; ".join(why)))
                    if not reasons:
                        reasons.append("calls cannot be matched one-to-one with expected calls")
        reasons.extend(text_reasons(exp, text))
    else:
        if calls:
            reasons.append("expected no tool call, got %d (%s)" % (len(calls), ", ".join(n for n, _ in calls)))
        reasons.extend(text_reasons(exp, text))
    return (not reasons), reasons


# ---------------------------------------------------------------- agents
def command_agent(cmd, timeout):
    def respond(case):
        try:
            p = subprocess.run(cmd, shell=True, input=json.dumps(case), stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, universal_newlines=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return None, "timeout after %ss" % timeout
        if p.returncode != 0:
            return None, "command exited %d: %s" % (p.returncode, (p.stderr or "").strip()[:200])
        try:
            data = json.loads(p.stdout)
        except ValueError:
            return None, "command output is not valid JSON: %r" % p.stdout[:100]
        if not isinstance(data, dict):
            return None, "command output is not a JSON object"
        return data, None
    return respond


def responses_agent(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise CaseError("cannot read responses file %s: %s" % (path, e))
    if not isinstance(data, dict) or not isinstance(data.get("responses"), list):
        raise CaseError("%s: must be an object with a 'responses' list" % path)
    by_id = {r.get("case_id"): r for r in data["responses"] if isinstance(r, dict)}

    def respond(case):
        r = by_id.get(case["id"])
        return (r, None) if r is not None else (None, "no response")
    return respond


def dummy_agent():
    import dummy_agent as da
    return lambda case: (da.respond(case), None)


DIRECTIONS = ("over_call", "missed_call", "wrong_call", "other_fail")


def direction(case, resp, err, passed, reasons):
    """Which way a result failed: pass, over_call, missed_call, wrong_call or other_fail."""
    if passed:
        return "pass"
    if err or not isinstance(resp, dict):
        return "other_fail"
    resp, cerr = scored_payload(resp)
    if cerr:
        return "other_fail"
    calls, cerr = normalize_calls(resp)
    if cerr:
        return "other_fail"
    exp = case["expected"]
    if any(n in exp.get("forbidden_tools", []) for n, _ in calls):
        return "over_call"
    if exp["type"] != "tool_calls":
        return "over_call" if calls else "other_fail"
    if not calls:
        return "missed_call"
    if any(not r.startswith("text ") for r in reasons):
        return "wrong_call"
    return "other_fail"


def run_cases(cases, agent):
    results = []
    for c in cases:
        resp, err = agent(c)
        if err:
            passed, reasons = False, [err]
        else:
            passed, reasons = score(c, resp)
        r = {"id": c["id"], "theme": c["theme"], "passed": passed, "reasons": reasons,
             "description": c["description"], "scoring_note": c["scoring_note"],
             "direction": direction(c, resp, err, passed, reasons)}
        if not err and isinstance(resp, dict) and "raw" in resp:
            raw = resp["raw"]
            r["raw"] = raw.get("tool_calls", []) if isinstance(raw, dict) else raw
            r["normalized"] = resp.get("tool_calls", [])
            if adapter_diff(resp):
                r["adapter_diff"] = True
        results.append(r)
    return results


def adapter_count(results):
    """None if no result had raw, else how many results have adapter_diff."""
    if not any("raw" in r for r in results):
        return None
    return sum(1 for r in results if r.get("adapter_diff"))


def summarize(results):
    themes = {}
    for r in results:
        t = themes.setdefault(r["theme"], {"passed": 0, "total": 0})
        t["total"] += 1
        t["passed"] += 1 if r["passed"] else 0
    return themes, sum(t["passed"] for t in themes.values()), len(results)


def directions(results):
    """Count failed results by direction. Keys: over_call, missed_call, wrong_call, other_fail."""
    d = dict.fromkeys(DIRECTIONS, 0)
    for r in results:
        k = r.get("direction", "pass")
        if k in d:
            d[k] += 1
    return d


def direction_line(d):
    return ("Called when it should not have: %d. Did not call when it should have: %d. "
            "Wrong call: %d. Other fails: %d." % (d["over_call"], d["missed_call"], d["wrong_call"], d["other_fail"]))


def write_report(path, results, agent_label):
    themes, p, n = summarize(results)
    if str(path).lower().endswith(".md"):
        lines = ["# Agent Test Pack report", "", "Agent: %s" % agent_label, "",
                 "Total: %d/%d passed" % (p, n), "", direction_line(directions(results)), "",
                 "| Theme | Passed | Total |", "|---|---|---|"]
        ac = adapter_count(results)
        if ac is not None:
            lines[8:8] = ["Adapter differences: %d" % ac, ""]
        for t, v in sorted(themes.items()):
            lines.append("| %s | %d | %d |" % (t, v["passed"], v["total"]))
        lines += ["", "| Case | Theme | Result | Reasons |", "|---|---|---|---|"]
        for r in results:
            why = "; ".join(r["reasons"])
            if r.get("adapter_diff"):
                why = (why + "; " if why else "") + "Adapter diff: raw and normalized tool calls differ"
            lines.append("| %s | %s | %s | %s |" % (r["id"], r["theme"], "PASS" if r["passed"] else "FAIL",
                                                   why.replace("|", "\\|").replace("\n", " ")))
        Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    elif str(path).lower().endswith(".json"):
        out = {"agent": agent_label, "total": n, "passed": p, "themes": themes,
               "cases": [{k: r[k] for k in ("id", "theme", "passed", "reasons", "direction",
                                            "raw", "normalized", "adapter_diff") if k in r} for r in results],
               "directions": directions(results)}
        Path(path).write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    else:
        raise CaseError("--report must end in .json or .md")


# ---------------------------------------------------------------- CLI
def build_parser():
    ap = argparse.ArgumentParser(prog="atp", description="Agent Test Pack runner")
    sub = ap.add_subparsers(dest="cmd")
    for name in ("list", "validate", "run"):
        sp = sub.add_parser(name)
        sp.add_argument("--cases", default=str(DEFAULT_CASES))
        if name != "validate":
            sp.add_argument("--theme")
        if name == "run":
            g = sp.add_mutually_exclusive_group(required=True)
            g.add_argument("--agent", choices=["dummy"])
            g.add_argument("--responses")
            g.add_argument("--command")
            sp.add_argument("--report")
            sp.add_argument("--verbose", action="store_true")
            sp.add_argument("--timeout", type=float, default=30)
    return ap


def main(argv=None):
    ap = build_parser()
    try:
        args = ap.parse_args(argv)
    except SystemExit as e:
        return 2 if e.code else 0
    if not args.cmd:
        ap.print_usage(sys.stderr)
        return 2
    try:
        cases = load_cases(args.cases, getattr(args, "theme", None))
        if args.cmd == "validate":
            counts = theme_counts(cases)
            for t, n in sorted(counts.items()):
                print("%-28s %d" % (t, n))
            print("total: %d cases in %d themes, all valid" % (len(cases), len(counts)))
            return 0
        if args.cmd == "list":
            for c in cases:
                print("%s  %s" % (c["id"], c["description"]))
            print()
            for t, n in sorted(theme_counts(cases).items()):
                print("%-28s %d" % (t, n))
            print("total: %d" % len(cases))
            return 0
        if args.agent == "dummy":
            agent, label = dummy_agent(), "dummy"
        elif args.responses:
            agent, label = responses_agent(args.responses), "responses:" + args.responses
        else:
            agent, label = command_agent(args.command, args.timeout), "command:" + args.command
        results = run_cases(cases, agent)
        for r in results:
            if r["passed"]:
                print("PASS %s%s" % (r["id"], ("  " + r["description"]) if args.verbose else ""))
            else:
                print("FAIL %s  %s" % (r["id"], "; ".join(r["reasons"])))
                if args.verbose:
                    print("     expected: %s" % r["scoring_note"])
        themes, p, n = summarize(results)
        print()
        for t, v in sorted(themes.items()):
            print("%-28s %d/%d" % (t, v["passed"], v["total"]))
        print("%d/%d passed" % (p, n))
        print(direction_line(directions(results)))
        ac = adapter_count(results)
        if ac is not None:
            print("Adapter differences: %d" % ac)
        if args.report:
            write_report(args.report, results, label)
        return 0 if p == n else 1
    except CaseError as e:
        print("error: %s" % e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
