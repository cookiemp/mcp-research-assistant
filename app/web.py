"""Local web demo for the research assistant.

    python -m app.web                 # http://127.0.0.1:8765
    python -m app.web --no-browser    # do not open a browser
    python -m app.web --port 9000

This is a thin front end over the same agent, MCP client, and server used by
the CLI. It is meant for demos and local use only: it binds to loopback and has
no authentication.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
import webbrowser
from collections.abc import Callable
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")

import uvicorn  # noqa: E402
from mcp import StdioServerParameters  # noqa: E402
from starlette.applications import Starlette  # noqa: E402
from starlette.requests import Request  # noqa: E402
from starlette.responses import HTMLResponse, JSONResponse  # noqa: E402
from starlette.routing import Route  # noqa: E402

from app.agent import AgentEvent, EventCallback, ResearchAgent  # noqa: E402
from app.main import DEFAULT_FALLBACK_MODEL, DEFAULT_MODEL  # noqa: E402
from client.mcp_client import MCPClient, describe_error  # noqa: E402
from server import config  # noqa: E402

logger = logging.getLogger("research_assistant.web")

INDEX_HTML = (Path(__file__).parent / "static" / "index.html").read_text(encoding="utf-8")
MAX_QUESTION_CHARS = 2000

AgentFactory = Callable[[EventCallback], ResearchAgent]


def _default_agent(on_event: EventCallback) -> ResearchAgent:
    """Spawn the stdio server and build a Gemini agent for one question."""
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Copy .env.example to .env and add your key."
        )
    env = dict(os.environ)
    env["DOCS_DIR"] = str(config.docs_dir())
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "server.main"],
        cwd=str(PROJECT_ROOT),
        env=env,
    )
    return ResearchAgent(
        MCPClient(params),
        model=DEFAULT_MODEL,
        fallback_model=DEFAULT_FALLBACK_MODEL,
        api_key=api_key,
        on_event=on_event,
    )


def create_app(agent_factory: AgentFactory | None = None) -> Starlette:
    """Build the Starlette app. Tests inject their own agent factory."""
    factory = agent_factory or _default_agent

    async def index(request: Request) -> HTMLResponse:
        return HTMLResponse(INDEX_HTML)

    async def ask(request: Request) -> JSONResponse:
        try:
            payload = await request.json()
        except Exception:
            return JSONResponse(
                {"error": 'Expected a JSON body like {"question": "..."}.'},
                status_code=400,
            )
        if not isinstance(payload, dict):
            return JSONResponse({"error": "Expected a JSON object."}, status_code=400)

        question = str(payload.get("question", "")).strip()
        if not question:
            return JSONResponse({"error": "Type a question first."}, status_code=400)
        if len(question) > MAX_QUESTION_CHARS:
            return JSONResponse(
                {"error": f"Keep the question under {MAX_QUESTION_CHARS} characters."},
                status_code=400,
            )

        steps: list[dict[str, Any]] = []

        def on_event(event: AgentEvent) -> None:
            steps.append(
                {
                    "kind": event.kind,
                    "tool": event.tool,
                    "arguments": event.arguments,
                    "text": event.text,
                    "is_error": event.is_error,
                }
            )

        agent: ResearchAgent | None = None
        try:
            agent = factory(on_event)
            async with agent.client:
                answer = await agent.run(question)
        except Exception as exc:
            logger.warning("Web question failed: %s", exc)
            return JSONResponse(
                {
                    "error": describe_error(exc),
                    "steps": steps,
                    "model": agent.active_model if agent else None,
                },
                status_code=500,
            )

        return JSONResponse(
            {"answer": answer, "steps": steps, "model": agent.active_model}
        )

    routes = [
        Route("/", index),
        Route("/api/ask", ask, methods=["POST"]),
    ]
    return Starlette(routes=routes)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="research-assistant-web",
        description="Local browser demo for the MCP research assistant.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (loopback only).")
    parser.add_argument("--port", type=int, default=8765, help="Port for the demo page.")
    parser.add_argument(
        "--no-browser", action="store_true", help="Do not open a browser automatically."
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug logging.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config.configure_logging()
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    url = f"http://{args.host}:{args.port}/"
    print(f"AskMyDocs demo UI: {url}", file=sys.stderr)
    print("Press Ctrl+C to stop.", file=sys.stderr)
    if not args.no_browser:
        threading.Timer(0.8, webbrowser.open, args=[url]).start()

    uvicorn.run(
        create_app(),
        host=args.host,
        port=args.port,
        log_level="debug" if args.verbose else "info",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
