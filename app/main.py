"""CLI entry point for the research assistant.

    python -m app.main "How does MCP handle authorization?"
    python -m app.main --list-tools
    python -m app.main --transport http --url http://127.0.0.1:8000/mcp
    python -m app.main            # interactive prompt
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from collections.abc import Callable
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")

from mcp import StdioServerParameters  # noqa: E402

from app.agent import AgentEvent, MaxStepsExceeded, ResearchAgent  # noqa: E402
from client.mcp_client import MCPClient, describe_error, tool_signature  # noqa: E402
from server import config  # noqa: E402

logger = logging.getLogger("research_assistant.cli")

DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
DEFAULT_FALLBACK_MODEL = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-3.5-flash-lite")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="research-assistant",
        description="Ask questions across your local documents and the web via MCP.",
    )
    parser.add_argument(
        "question",
        nargs="*",
        help="The question to ask. Omit it to start an interactive session.",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Gemini model name.")
    parser.add_argument(
        "--fallback-model",
        default=DEFAULT_FALLBACK_MODEL,
        help="Used automatically on rate limits (429) or 503s. Pass '' to disable.",
    )
    parser.add_argument("--max-steps", type=int, default=8, help="Max agent steps.")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default=os.getenv("MCP_CLIENT_TRANSPORT", "stdio"),
        help="Connect to the server over stdio (local) or Streamable HTTP (remote).",
    )
    parser.add_argument(
        "--url",
        default=os.getenv("MCP_URL", "http://127.0.0.1:8000/mcp"),
        help="Streamable HTTP endpoint (with --transport http).",
    )
    parser.add_argument(
        "--token",
        default=os.getenv("MCP_TOKEN"),
        help="Bearer token for HTTP (prefer MCP_TOKEN in the environment over this flag).",
    )
    parser.add_argument("--docs-dir", default=None, help="Folder of documents (stdio only).")
    parser.add_argument(
        "--list-tools",
        action="store_true",
        help="List the server's tools, resources, and prompts, then exit.",
    )
    parser.add_argument(
        "--show-prompt",
        action="store_true",
        help="Print the server's research_brief prompt, then exit.",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug logging.")
    return parser.parse_args(argv)


def _server_params(docs_dir: str | None) -> StdioServerParameters:
    env = dict(os.environ)
    resolved_docs = Path(docs_dir).resolve() if docs_dir else config.docs_dir()
    if not resolved_docs.is_dir():
        logger.warning("Documents folder %s does not exist yet.", resolved_docs)
    env["DOCS_DIR"] = str(resolved_docs)
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "server.main"],
        cwd=str(PROJECT_ROOT),
        env=env,
    )


def build_client(args: argparse.Namespace) -> MCPClient:
    if args.transport == "http":
        if args.docs_dir:
            logger.warning("--docs-dir is ignored for HTTP; the server owns DOCS_DIR.")
        return MCPClient(url=args.url, token=args.token)
    return MCPClient(_server_params(args.docs_dir))


def make_printer() -> Callable[[AgentEvent], None]:
    def print_event(event: AgentEvent) -> None:
        if event.kind == "tool_call":
            print(f"  -> {event.tool}({_short(event.arguments)})", file=sys.stdout)
        elif event.kind == "tool_result":
            label = "error" if event.is_error else "ok"
            first = event.text.strip().splitlines()[0] if event.text.strip() else ""
            print(f"     [{label}] {first[:160]}", file=sys.stdout)
        elif event.kind == "notice":
            print(f"     [note] {event.text}", file=sys.stdout)

    return print_event


def _short(arguments: dict) -> str:
    parts = [f"{k}={v!r}" for k, v in arguments.items()]
    joined = ", ".join(parts)
    return joined if len(joined) <= 100 else joined[:97] + "..."


async def _list_everything(client: MCPClient, show_prompt: bool) -> None:
    async with client:
        print(f"Transport: {client.transport_name}")
        print("Tools:")
        for tool in await client.list_tools():
            first_line = (tool.description or "").strip().splitlines()
            summary = first_line[0] if first_line else "(no description)"
            print(f"  - {tool_signature(tool)}: {summary}")
        print("\nResources:")
        for resource in await client.list_resources():
            print(f"  - {resource.uri}: {resource.description or resource.name}")
        print("\nIndex resource body:")
        index = await client.read_resource("docs://index")
        for line in index.splitlines():
            print(f"  {line}")
        if show_prompt:
            print("\nresearch_brief prompt:")
            print(await client.get_prompt("research_brief", {"topic": "MCP security"}))


async def _ask(agent: ResearchAgent, question: str) -> bool:
    print(f"\nQ: {question}")
    try:
        answer = await agent.run(question)
    except MaxStepsExceeded as exc:
        print(f"Stopped: {exc}", file=sys.stderr)
        return False
    except Exception as exc:  # keep the REPL alive on API errors
        print(f"Error: {describe_error(exc)}", file=sys.stderr)
        return False
    print(f"\nA: {answer}\n")
    return True


async def main_async(args: argparse.Namespace) -> int:
    client = build_client(args)

    if args.list_tools:
        try:
            await _list_everything(client, args.show_prompt)
        except Exception as exc:
            print(f"Could not query the server: {describe_error(exc)}", file=sys.stderr)
            return 1
        return 0

    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        print(
            "GEMINI_API_KEY is not set. Copy .env.example to .env and add your key "
            "from https://aistudio.google.com/apikey.",
            file=sys.stderr,
        )
        return 2

    question = " ".join(args.question).strip()

    try:
        async with client:
            agent = ResearchAgent(
                client,
                model=args.model,
                fallback_model=args.fallback_model.strip() or None,
                api_key=api_key,
                max_steps=args.max_steps,
                on_event=make_printer(),
            )

            if question:
                return 0 if await _ask(agent, question) else 1

            print("Research assistant. Type a question, or 'exit' to quit.")
            while True:
                try:
                    line = input("you> ").strip()
                except (EOFError, KeyboardInterrupt):
                    print()
                    break
                if line.lower() in {"exit", "quit"}:
                    break
                if line:
                    await _ask(agent, line)
    except Exception as exc:
        print(f"Could not use the server: {describe_error(exc)}", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config.configure_logging()
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    try:
        return asyncio.run(main_async(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
