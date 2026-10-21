#!/usr/bin/env python3
"""MCP Tool Schema Linter, free 3-rule subset (SL001, SL004, SL007). Standard library only, no network.

Reads a tools/list result from a JSON file, or starts an MCP stdio server
with --command and asks it for tools/list. Then runs rule checks SL001,
SL004 and SL007 on the tool schemas. This is a 3-rule subset.

This tool finds known problems. It cannot prove that any client (Claude Code,
Cursor or another) will accept a schema. See RULES.md for the source and the
status of each rule.

Exit codes: 0 no ERROR finding, 1 at least one ERROR finding,
2 usage, input or server error.
"""

import argparse
import json
import queue
import shlex
import subprocess
import sys
import threading

VERSION = "1.0.0"

RULES = [
    ("SL001", "ERROR", "inputSchema root must have type \"object\""),
    ("SL004", "WARN", "array schema without items (or prefixItems)"),
    ("SL007", "ERROR", "duplicate tool names"),
]
RULE_IDS = [r[0] for r in RULES]
SEVERITY = dict((r[0], r[1]) for r in RULES)
SPEC_ERAS = ("2025-11-25", "2026-07-28")


class InputError(Exception):
    pass


def finding(rule, tool, path, message, severity=None):
    return {"rule": rule, "severity": severity or SEVERITY[rule], "tool": tool,
            "path": path, "message": message}


def extract_tools(data):
    """Accept {"tools": [...]}, {"result": {"tools": [...]}} or a bare list."""
    if isinstance(data, list):
        return data, None
    if isinstance(data, dict):
        if isinstance(data.get("result"), dict):
            data = data["result"]
        if isinstance(data.get("tools"), list):
            return data["tools"], data.get("instructions")
    raise InputError("input is not a tools/list result: expected {\"tools\": [...]}, "
                     "{\"result\": {\"tools\": [...]}} or a list")


def walk(schema, path, visit):
    """Call visit(subschema, path) on every subschema, recursively."""
    if not isinstance(schema, dict):
        return
    visit(schema, path)
    for key in ("properties", "$defs", "definitions", "patternProperties"):
        sub = schema.get(key)
        if isinstance(sub, dict):
            for name in sorted(sub):
                walk(sub[name], path + "/" + key + "/" + name, visit)
    for key in ("items", "additionalProperties", "not", "contains", "if", "then", "else"):
        sub = schema.get(key)
        if isinstance(sub, dict):
            walk(sub, path + "/" + key, visit)
        elif key == "items" and isinstance(sub, list):
            for i, s in enumerate(sub):
                walk(s, path + "/items/" + str(i), visit)
    for key in ("prefixItems", "oneOf", "anyOf", "allOf"):
        sub = schema.get(key)
        if isinstance(sub, list):
            for i, s in enumerate(sub):
                walk(s, path + "/" + key + "/" + str(i), visit)


def is_array(schema):
    t = schema.get("type")
    return t == "array" or (isinstance(t, list) and "array" in t)


def check_tool(tool, idx, rules):
    out = []
    name = tool.get("name") if isinstance(tool, dict) else None
    label = name if isinstance(name, str) else "#%d" % idx
    if not isinstance(tool, dict):
        return [finding("SL001", label, "", "tool entry is not an object")] if "SL001" in rules else []
    schema = tool.get("inputSchema")
    base = "/inputSchema"

    if "SL001" in rules:
        if not isinstance(schema, dict):
            out.append(finding("SL001", label, base, "inputSchema is missing or not an object"))
        elif "type" not in schema:
            out.append(finding("SL001", label, base, "inputSchema has no type; set \"type\": \"object\""))
        elif schema.get("type") != "object":
            out.append(finding("SL001", label, base + "/type",
                               "inputSchema type is %s, expected \"object\"" % json.dumps(schema.get("type"))))

    if "SL004" in rules:
        for key in ("inputSchema", "outputSchema"):
            s = tool.get(key)
            if not isinstance(s, dict):
                continue

            def visit(sub, path, _out=out):
                if is_array(sub) and "items" not in sub and "prefixItems" not in sub:
                    _out.append(finding("SL004", label, path, "array without items"))
            walk(s, "/" + key, visit)
    return out


def lint(data, rules=None):
    rules = set(rules or RULE_IDS)
    tools, _instr = extract_tools(data)
    findings = []
    for i, tool in enumerate(tools):
        findings.extend(check_tool(tool, i, rules))
    if "SL007" in rules:
        seen = {}
        for t in tools:
            n = t.get("name") if isinstance(t, dict) else None
            if isinstance(n, str):
                seen[n] = seen.get(n, 0) + 1
        for n in sorted(seen):
            if seen[n] > 1:
                findings.append(finding("SL007", n, "/name", "tool name appears %d times" % seen[n]))
    size = len(json.dumps({"tools": tools}, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    order = dict((r, i) for i, r in enumerate(RULE_IDS))
    findings.sort(key=lambda f: (order[f["rule"]], str(f["tool"]), f["path"]))
    return {"tool_count": len(tools), "payload_bytes": size, "findings": findings,
            "errors": sum(1 for f in findings if f["severity"] == "ERROR"),
            "warnings": sum(1 for f in findings if f["severity"] == "WARN")}


# stdio client ---------------------------------------------------------------

class StdioServer(object):
    def __init__(self, argv, timeout):
        self.timeout = timeout
        try:
            self.proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=subprocess.PIPE)
        except OSError as e:
            raise InputError("cannot start server: %s" % e)
        self.lines = queue.Queue()
        self.next_id = 1
        threading.Thread(target=self._read, daemon=True).start()
        threading.Thread(target=self._drain, daemon=True).start()

    def _read(self):
        for line in iter(self.proc.stdout.readline, b""):
            self.lines.put(line)
        self.lines.put(None)

    def _drain(self):
        for _ in iter(self.proc.stderr.readline, b""):
            pass

    def send(self, obj):
        try:
            self.proc.stdin.write((json.dumps(obj) + "\n").encode("utf-8"))
            self.proc.stdin.flush()
        except (OSError, ValueError):
            raise InputError("server closed its input")

    def request(self, method, params=None):
        msg_id = self.next_id
        self.next_id += 1
        msg = {"jsonrpc": "2.0", "id": msg_id, "method": method}
        if params is not None:
            msg["params"] = params
        self.send(msg)
        while True:
            try:
                line = self.lines.get(timeout=self.timeout)
            except queue.Empty:
                raise InputError("server did not answer %s within %s seconds" % (method, self.timeout))
            if line is None:
                raise InputError("server closed stdout during %s" % method)
            try:
                reply = json.loads(line.decode("utf-8"))
            except ValueError:
                continue  # not JSON-RPC; ignore stray output
            if isinstance(reply, dict) and reply.get("id") == msg_id:
                return reply

    def close(self):
        try:
            self.proc.stdin.close()
        except Exception:
            pass
        try:
            self.proc.wait(timeout=2)
        except Exception:
            self.proc.kill()


def meta_2026():
    return {"io.modelcontextprotocol/protocolVersion": "2026-07-28",
            "io.modelcontextprotocol/clientCapabilities": {},
            "io.modelcontextprotocol/clientInfo": {"name": "mcp-schema-lint", "version": VERSION}}


def fetch_2026(argv, timeout):
    srv = StdioServer(argv, timeout)
    try:
        d = srv.request("server/discover", {"_meta": meta_2026()})
        if "result" not in d:
            raise InputError("server/discover failed: %s" % json.dumps(d.get("error")))
        instr = d["result"].get("instructions") if isinstance(d["result"], dict) else None
        return list_all(srv, lambda p: dict(p, _meta=meta_2026())), instr
    finally:
        srv.close()


def fetch_2025(argv, timeout):
    srv = StdioServer(argv, timeout)
    try:
        r = srv.request("initialize", {"protocolVersion": "2025-11-25", "capabilities": {},
                                       "clientInfo": {"name": "mcp-schema-lint", "version": VERSION}})
        if "result" not in r:
            raise InputError("initialize failed: %s" % json.dumps(r.get("error")))
        srv.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        instr = r["result"].get("instructions") if isinstance(r["result"], dict) else None
        return list_all(srv, lambda p: p), instr
    finally:
        srv.close()


def list_all(srv, wrap):
    tools, cursor = [], None
    for _ in range(100):
        params = {"cursor": cursor} if cursor else {}
        r = srv.request("tools/list", wrap(params))
        if "result" not in r or not isinstance(r["result"].get("tools"), list):
            raise InputError("tools/list failed: %s" % json.dumps(r.get("error")))
        tools.extend(r["result"]["tools"])
        cursor = r["result"].get("nextCursor")
        if not cursor:
            break
    return {"tools": tools}


def fetch_from_command(command, protocol, timeout):
    argv = shlex.split(command)
    if not argv:
        raise InputError("--command is empty")
    if protocol == "2026-07-28":
        return fetch_2026(argv, timeout) + ("2026-07-28",)
    if protocol == "2025-11-25":
        return fetch_2025(argv, timeout) + ("2025-11-25",)
    try:
        return fetch_2026(argv, timeout) + ("2026-07-28",)
    except InputError:
        return fetch_2025(argv, timeout) + ("2025-11-25",)


# output ---------------------------------------------------------------------

def format_text(report, source):
    lines = ["mcp-schema-lint %s: %s" % (VERSION, source),
             "tools: %d, payload: %d bytes" % (report["tool_count"], report["payload_bytes"])]
    for f in report["findings"]:
        where = (f["tool"] or "(server)") + (f["path"] or "")
        lines.append("%-5s %s %s: %s" % (f["severity"], f["rule"], where, f["message"]))
    lines.append("%d error(s), %d warning(s)" % (report["errors"], report["warnings"]))
    return "\n".join(lines)


def build_parser():
    p = argparse.ArgumentParser(
        prog="mcp_schema_lint.py",
        description="Lint MCP tool schemas from a tools/list result. It finds known problems "
                    "(rules SL001, SL004, SL007). It cannot prove that a client accepts a schema.",
        epilog="Exit codes: 0 no ERROR, 1 at least one ERROR, 2 usage, input or server error.")
    p.add_argument("file", nargs="?", help="JSON file with a tools/list result")
    p.add_argument("--command", help="start this MCP stdio server and call tools/list")
    p.add_argument("--protocol", choices=("auto",) + SPEC_ERAS, default="auto",
                   help="handshake for --command (auto tries 2026-07-28 server/discover, then initialize)")
    p.add_argument("--timeout", type=float, default=10.0, help="seconds to wait per server reply")
    p.add_argument("--rules", help="comma separated rule ids to run, e.g. SL001,SL004")
    p.add_argument("--list-rules", action="store_true", help="list rules and exit")
    p.add_argument("--format", choices=("text", "json"), default="text")
    p.add_argument("--version", action="version", version=VERSION)
    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.list_rules:
        for rid, sev, text in RULES:
            print("%s %-5s %s" % (rid, sev, text))
        return 0
    rules = None
    if args.rules:
        rules = [r.strip().upper() for r in args.rules.split(",") if r.strip()]
        bad = [r for r in rules if r not in RULE_IDS]
        if bad or not rules:
            sys.stderr.write("error: unknown rule id(s): %s\n" % ", ".join(bad or ["(none)"]))
            return 2
    if bool(args.file) == bool(args.command):
        sys.stderr.write("error: give exactly one of FILE or --command\n")
        return 2
    try:
        if args.command:
            data, instr, era = fetch_from_command(args.command, args.protocol, args.timeout)
            source = "--command (%s)" % era
        else:
            with open(args.file, encoding="utf-8") as fh:
                data = json.load(fh)
            source = args.file
        report = lint(data, rules)
    except (OSError, ValueError, InputError) as e:
        sys.stderr.write("error: %s\n" % e)
        return 2
    report["source"] = source
    report["version"] = VERSION
    if args.format == "json":
        print(json.dumps(report, indent=2))
    else:
        print(format_text(report, source))
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
