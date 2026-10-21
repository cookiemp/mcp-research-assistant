"""Call one MCP tool directly - no LLM involved.

Examples (stdio, the default):

    python scripts/call_tool.py search_documents --args "{\"query\": \"oauth\"}"
    python scripts/call_tool.py read_document --args "{\"path\": \"../secret.md\"}"
    python scripts/call_tool.py --list

Examples (Streamable HTTP with a scoped token):

    python scripts/call_tool.py --transport http --url http://127.0.0.1:8000/mcp \
        --token "$env:MCP_TOKEN" web_search --args "{\"query\": \"mcp\"}"

Exit code is 0 for a successful tool result and 1 for an error result.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")

from mcp import StdioServerParameters  # noqa: E402

from client.mcp_client import (  # noqa: E402
    MCPClient,
    describe_error,
    tool_signature,
    tool_to_text,
)
from server import config  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Call one MCP tool directly.")
    parser.add_argument("tool", nargs="?", help="Tool name to call.")
    parser.add_argument("--args", default="{}", help="JSON object of tool arguments.")
    parser.add_argument(
        "--arg",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Repeatable key=value argument (values are parsed as JSON when possible). "
        "Useful on Windows PowerShell, where JSON quoting is awkward.",
    )
    parser.add_argument("--list", action="store_true", help="Only list tools.")
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    parser.add_argument("--url", default=os.getenv("MCP_URL", "http://127.0.0.1:8000/mcp"))
    parser.add_argument("--token", default=os.getenv("MCP_TOKEN"))
    parser.add_argument(
        "--no-token",
        action="store_true",
        help="Send no bearer token (for testing 401 responses).",
    )
    parser.add_argument("--docs-dir", default=None)
    return parser.parse_args()


def build_client(args: argparse.Namespace) -> MCPClient:
    if args.transport == "http":
        token = None if args.no_token else args.token
        return MCPClient(url=args.url, token=token)
    env = dict(os.environ)
    docs = Path(args.docs_dir).resolve() if args.docs_dir else config.docs_dir()
    env["DOCS_DIR"] = str(docs)
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "server.main"],
        cwd=str(PROJECT_ROOT),
        env=env,
    )
    return MCPClient(params)


async def run(args: argparse.Namespace) -> int:
    if not args.list and not args.tool:
        print("Provide a tool name or --list.", file=sys.stderr)
        return 2
    try:
        arguments = json.loads(args.args)
    except json.JSONDecodeError as exc:
        print(f"--args must be valid JSON: {exc}", file=sys.stderr)
        return 2
    if not isinstance(arguments, dict):
        print("--args must be a JSON object.", file=sys.stderr)
        return 2

    for pair in args.arg:
        key, sep, raw = pair.partition("=")
        if not sep or not key:
            print(f"--arg expects KEY=VALUE, got {pair!r}.", file=sys.stderr)
            return 2
        try:
            arguments[key] = json.loads(raw)
        except json.JSONDecodeError:
            arguments[key] = raw

    try:
        return await _call(args, arguments)
    except Exception as exc:
        print(f"Connection or protocol error: {describe_error(exc)}", file=sys.stderr)
        return 1


async def _call(args: argparse.Namespace, arguments: dict) -> int:
    async with build_client(args) as client:
        tools = await client.list_tools()
        print(f"Transport: {client.transport_name}")
        for tool in tools:
            print(f"  - {tool_signature(tool)}")
        if args.list:
            return 0

        result = await client.call_tool(args.tool, arguments)
        print(f"\n{args.tool} -> is_error={result.is_error}")
        print(tool_to_text(result))
        return 0 if not result.is_error else 1


def main() -> int:
    config.configure_logging()
    return asyncio.run(run(parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
