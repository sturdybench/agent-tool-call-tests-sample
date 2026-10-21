#!/usr/bin/env python3
"""MCP stdio server starter. Python standard library only.

Written for Python 3.8 syntax. Speaks the MCP 2025-11-25 lifecycle
(initialize, notifications/initialized, tools/list, tools/call, ping)
over stdio: one JSON-RPC message per line on stdin and stdout.
Logs go to stderr only. See SOURCES.md for the spec pages used.

Run:
    python3 server_template.py --root /path/to/allowed/folder
or set MCP_STARTER_ROOT to the allowed folder.
"""

import argparse
import json
import logging
import os
import sys

SERVER_NAME = "mcp-server-starter"  # TODO: rename your server
SERVER_VERSION = "1.0.0"            # TODO: your version

# Protocol versions this server speaks. The first one is the latest.
SUPPORTED_PROTOCOL_VERSIONS = ["2025-11-25"]

MAX_LINE_BYTES = 1024 * 1024        # reject input lines bigger than 1 MiB
MAX_FILE_BYTES = 256 * 1024         # read_text_file size cap
MAX_TEXT_CHARS = 100000             # echo input cap

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

log = logging.getLogger(SERVER_NAME)


class ToolInputError(Exception):
    """Bad tool arguments. Returned to the model as isError: true."""


# ---------------------------------------------------------------------------
# Tools. Each tool has a name, a description, an inputSchema and a handler.
# The handler gets the validated arguments dict and returns a string.
# Raise ToolInputError for problems the caller can fix.
# ---------------------------------------------------------------------------

def tool_echo(args, ctx):
    return args["text"]


def tool_add_numbers(args, ctx):
    total = args["a"] + args["b"]
    return json.dumps(total)


def _inside(root, path):
    try:
        return os.path.commonpath([root, path]) == root
    except ValueError:
        # Different drives on Windows, or mixed absolute and relative.
        return False


def tool_read_text_file(args, ctx):
    root = ctx.get("root")
    if not root:
        raise ToolInputError(
            "No allowed folder is set. Start the server with --root or MCP_STARTER_ROOT.")
    rel = args["path"]
    if "\x00" in rel:
        raise ToolInputError("Path contains a NUL character.")
    if os.path.isabs(rel) or os.path.splitdrive(rel)[0]:
        raise ToolInputError("Give a path relative to the allowed folder, not an absolute path.")
    # realpath resolves "..", and every symlink, before the containment check.
    target = os.path.realpath(os.path.join(root, rel))
    if not _inside(root, target):
        raise ToolInputError("Path is outside the allowed folder.")
    if not os.path.isfile(target):
        raise ToolInputError("No such file: %s" % rel)
    size = os.path.getsize(target)
    if size > MAX_FILE_BYTES:
        raise ToolInputError("File is %d bytes. The limit is %d bytes." % (size, MAX_FILE_BYTES))
    with open(target, "rb") as f:
        data = f.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise ToolInputError("File is larger than %d bytes." % MAX_FILE_BYTES)
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise ToolInputError("File is not valid UTF-8 text.")


TOOLS = [
    {
        "name": "echo",
        "description": "Return the given text unchanged. Useful to check the connection.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text to send back.",
                         "maxLength": MAX_TEXT_CHARS},
            },
            "required": ["text"],
            "additionalProperties": False,
        },
        "handler": tool_echo,
    },
    {
        "name": "add_numbers",
        "description": "Add two numbers and return the sum.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "a": {"type": "number", "description": "First number."},
                "b": {"type": "number", "description": "Second number."},
            },
            "required": ["a", "b"],
            "additionalProperties": False,
        },
        "handler": tool_add_numbers,
    },
    {
        "name": "read_text_file",
        "description": ("Read a UTF-8 text file inside the allowed folder. "
                        "The path is relative to that folder. Files over %d bytes are refused."
                        % MAX_FILE_BYTES),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string",
                         "description": "File path relative to the allowed folder."},
            },
            "required": ["path"],
            "additionalProperties": False,
        },
        "handler": tool_read_text_file,
    },
    # TODO: add your own tools here. Copy one of the entries above, give it a
    # unique name, a clear description, an inputSchema, and a handler function.
]


# ---------------------------------------------------------------------------
# Small input validator. Covers the schema keywords used above:
# type (object, string, number, integer, boolean), required, properties,
# additionalProperties: false, maxLength. It is not a full JSON Schema
# validator. TODO: extend it if your tools use other keywords.
# ---------------------------------------------------------------------------

def _type_ok(value, expected):
    if expected == "string":
        return isinstance(value, str)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        # bool is a subclass of int in Python. true is not a number here.
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return False
        return value == value and value not in (float("inf"), float("-inf"))
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    return True


def validate_arguments(schema, args):
    if not isinstance(args, dict):
        raise ToolInputError("Arguments must be a JSON object.")
    props = schema.get("properties", {})
    for name in schema.get("required", []):
        if name not in args:
            raise ToolInputError("Missing required argument: %s" % name)
    if schema.get("additionalProperties") is False:
        extra = sorted(k for k in args if k not in props)
        if extra:
            raise ToolInputError("Unknown argument(s): %s" % ", ".join(extra))
    for name, value in args.items():
        spec = props.get(name)
        if not spec:
            continue
        expected = spec.get("type")
        if expected and not _type_ok(value, expected):
            raise ToolInputError("Argument %s must be of type %s." % (name, expected))
        max_len = spec.get("maxLength")
        if max_len is not None and isinstance(value, str) and len(value) > max_len:
            raise ToolInputError("Argument %s is longer than %d characters." % (name, max_len))


# ---------------------------------------------------------------------------
# JSON-RPC and MCP methods
# ---------------------------------------------------------------------------

class RpcError(Exception):
    def __init__(self, code, message):
        Exception.__init__(self, message)
        self.code = code
        self.message = message


def text_result(text, is_error=False):
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


class Server(object):
    def __init__(self, root=None):
        self.root = root
        self.tools = dict((t["name"], t) for t in TOOLS)

    # MCP methods ----------------------------------------------------------

    def m_initialize(self, params):
        requested = params.get("protocolVersion")
        if requested in SUPPORTED_PROTOCOL_VERSIONS:
            version = requested
        else:
            version = SUPPORTED_PROTOCOL_VERSIONS[0]
        log.info("initialize: client asked for %r, answering %s", requested, version)
        return {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        }

    def m_ping(self, params):
        return {}

    def m_tools_list(self, params):
        listed = []
        for t in TOOLS:
            listed.append({"name": t["name"], "description": t["description"],
                           "inputSchema": t["inputSchema"]})
        return {"tools": listed}

    def m_tools_call(self, params):
        name = params.get("name")
        if not isinstance(name, str):
            raise RpcError(INVALID_PARAMS, "params.name must be a string")
        tool = self.tools.get(name)
        if tool is None:
            raise RpcError(INVALID_PARAMS, "Unknown tool: %s" % name)
        args = params.get("arguments", {})
        if args is None:
            args = {}
        if not isinstance(args, dict):
            raise RpcError(INVALID_PARAMS, "params.arguments must be an object")
        try:
            validate_arguments(tool["inputSchema"], args)
            text = tool["handler"](args, {"root": self.root})
        except ToolInputError as exc:
            return text_result(str(exc), is_error=True)
        except Exception:
            log.exception("tool %s failed", name)
            return text_result("Tool %s failed with an internal error." % name, is_error=True)
        return text_result(text)

    METHODS = {
        "initialize": m_initialize,
        "ping": m_ping,
        "tools/list": m_tools_list,
        "tools/call": m_tools_call,
    }

    # Message handling -----------------------------------------------------

    def handle_line(self, line):
        """Handle one input line. Return a response dict, or None for no reply."""
        try:
            msg = json.loads(line)
        except ValueError:
            return error_response(None, PARSE_ERROR, "Parse error")
        if not isinstance(msg, dict):
            # Arrays (JSON-RPC batches) are not part of current MCP.
            return error_response(None, INVALID_REQUEST, "Invalid Request")

        has_id = "id" in msg
        msg_id = msg.get("id")
        method = msg.get("method")

        if method is None:
            # A response from the client. This server sends no requests, so ignore it.
            if has_id and ("result" in msg or "error" in msg):
                return None
            return error_response(msg_id if _valid_id(msg_id) else None,
                                  INVALID_REQUEST, "Invalid Request")
        if msg.get("jsonrpc") != "2.0" or not isinstance(method, str):
            return error_response(msg_id if _valid_id(msg_id) else None,
                                  INVALID_REQUEST, "Invalid Request")

        if not has_id:
            # Notification: never answered.
            if method == "notifications/initialized":
                log.info("client finished initialization")
            else:
                log.info("notification ignored: %s", method)
            return None

        if not _valid_id(msg_id):
            # MCP: id must be a string or number, never null.
            return error_response(None, INVALID_REQUEST, "Invalid Request: bad id")

        params = msg.get("params", {})
        if params is None:
            params = {}
        if not isinstance(params, dict):
            return error_response(msg_id, INVALID_PARAMS, "params must be an object")

        func = self.METHODS.get(method)
        if func is None:
            return error_response(msg_id, METHOD_NOT_FOUND, "Method not found: %s" % method)
        try:
            result = func(self, params)
        except RpcError as exc:
            return error_response(msg_id, exc.code, exc.message)
        except Exception:
            log.exception("internal error in %s", method)
            return error_response(msg_id, INTERNAL_ERROR, "Internal error")
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _valid_id(value):
    if isinstance(value, bool):
        return False
    return isinstance(value, (str, int, float))


def error_response(msg_id, code, message):
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def write_message(out, obj):
    # json.dumps escapes newlines inside strings, so each message is one line.
    data = json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n"
    out.write(data.encode("utf-8"))
    out.flush()


def serve(server, inp, out):
    while True:
        raw = inp.readline(MAX_LINE_BYTES + 1)
        if not raw:
            log.info("stdin closed, exiting")
            return
        if len(raw) > MAX_LINE_BYTES and not raw.endswith(b"\n"):
            # Drop the rest of the oversized line, then report it.
            while True:
                chunk = inp.readline(MAX_LINE_BYTES)
                if not chunk or chunk.endswith(b"\n"):
                    break
            write_message(out, error_response(None, INVALID_REQUEST, "Message too large"))
            continue
        try:
            line = raw.decode("utf-8").strip()
        except UnicodeDecodeError:
            write_message(out, error_response(None, PARSE_ERROR, "Parse error: not UTF-8"))
            continue
        if not line:
            continue
        try:
            response = server.handle_line(line)
        except Exception:
            # Last line of defence: one bad message never stops the loop.
            log.exception("unexpected error")
            response = error_response(None, INTERNAL_ERROR, "Internal error")
        if response is not None:
            write_message(out, response)


def main(argv=None):
    parser = argparse.ArgumentParser(description="MCP stdio server starter")
    parser.add_argument("--root", help="folder read_text_file may read from "
                        "(default: env MCP_STARTER_ROOT)")
    parser.add_argument("--log-level", default="INFO")
    opts = parser.parse_args(argv)

    logging.basicConfig(stream=sys.stderr, level=getattr(logging, opts.log_level.upper(), logging.INFO),
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")

    root = opts.root or os.environ.get("MCP_STARTER_ROOT")
    if root:
        root = os.path.realpath(root)
        if not os.path.isdir(root):
            log.error("allowed folder does not exist: %s", root)
            return 2
        log.info("allowed folder: %s", root)
    else:
        log.warning("no allowed folder set, read_text_file will refuse every call")

    out = sys.stdout.buffer
    # Anything that calls print() by mistake goes to stderr, not into the protocol stream.
    sys.stdout = sys.stderr
    try:
        serve(Server(root), sys.stdin.buffer, out)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
