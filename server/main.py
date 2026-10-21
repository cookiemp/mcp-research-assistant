"""MCP server entry point.

stdio (default), used by the CLI app and desktop hosts:

    python -m server.main

Streamable HTTP, used by remote clients. Requires bearer tokens and scopes:

    python -m server.main --transport streamable-http --port 8000

The server never writes to stdout: logs go to stderr.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

# Allow `python server/main.py` as well as `python -m server.main`.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from mcp.server import MCPServer  # noqa: E402

from server import auth, config  # noqa: E402
from server.tools import docs, web  # noqa: E402

logger = logging.getLogger("research_assistant.server")

INSTRUCTIONS = """\
You are connected to a personal research assistant server.

Workflow:
1. If the question is about the user's own notes or files, call
   search_documents, then read_document on the best match.
2. If the answer is missing locally or needs current information, call
   web_search and, when a snippet is not enough, fetch_url.
3. Cite the document path or URL you used for every claim.

All failures come back as error results with a message explaining how to fix
the call; read that message and retry with corrected arguments.
"""


def build_server(
    *,
    enable_auth: bool = False,
    host: str = "127.0.0.1",
    port: int = 8000,
    path: str = "/mcp",
    public_url: str | None = None,
) -> MCPServer:
    """Construct the MCP server with all tools, resources, and prompts."""
    auth_kwargs: dict = {}
    if enable_auth:
        verifier, settings = auth.build_auth(
            host=host, port=port, path=path, public_url=public_url
        )
        auth_kwargs = {
            "token_verifier": verifier,
            "auth": settings,
            "middleware": [auth.ToolScopeMiddleware()],
        }

    mcp = MCPServer(
        name="research-assistant",
        title="Research Assistant",
        description="Search local documents and the web for a personal research assistant.",
        version="1.1.0",
        instructions=INSTRUCTIONS,
        **auth_kwargs,
    )

    # --- Tools -------------------------------------------------------------
    mcp.add_tool(docs.search_documents)
    mcp.add_tool(docs.read_document)
    mcp.add_tool(web.web_search)
    mcp.add_tool(web.fetch_url)

    # --- Resource ----------------------------------------------------------
    @mcp.resource(
        "docs://index",
        name="document_index",
        description="Index of every readable document in the local docs folder.",
        mime_type="text/plain",
    )
    def document_index() -> str:
        """List the documents available to the tools."""
        return docs.document_index()

    # --- Prompt ------------------------------------------------------------
    @mcp.prompt(
        name="research_brief",
        description="Reusable template for a cited research brief on a topic.",
    )
    def research_brief(topic: str, audience: str = "a technical reader") -> str:
        """Build a research-brief prompt.

        Args:
            topic: The subject to research.
            audience: Who the brief is written for.
        """
        return (
            f"Write a short, cited brief on '{topic}' for {audience}.\n"
            "1. First search the local documents for existing notes.\n"
            "2. Then check the web for anything newer or missing.\n"
            "3. Cite each source (document path or URL) and list open questions."
        )

    return mcp


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="server",
        description="Run the research-assistant MCP server.",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default=os.getenv("MCP_TRANSPORT", "stdio"),
        help="Transport to serve (default: stdio).",
    )
    parser.add_argument("--host", default=os.getenv("MCP_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("MCP_PORT", "8000")))
    parser.add_argument("--path", default=os.getenv("MCP_PATH", "/mcp"))
    parser.add_argument(
        "--public-url",
        default=os.getenv("MCP_PUBLIC_URL") or None,
        help="Public base URL advertised in OAuth metadata (behind a proxy).",
    )
    parser.add_argument(
        "--json-response",
        action="store_true",
        help="Return plain JSON instead of SSE streams (HTTP only).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config.configure_logging()

    http_mode = args.transport == "streamable-http"
    try:
        server = build_server(
            enable_auth=http_mode,
            host=args.host,
            port=args.port,
            path=args.path,
            public_url=args.public_url,
        )
    except (RuntimeError, ValueError) as exc:
        logger.error("Cannot start server: %s", exc)
        print(f"Cannot start server: {exc}", file=sys.stderr)
        return 1

    if http_mode:
        logger.info(
            "Starting research-assistant MCP server on http://%s:%d%s",
            args.host,
            args.port,
            args.path,
        )
        server.run(
            transport="streamable-http",
            host=args.host,
            port=args.port,
            streamable_http_path=args.path,
            json_response=args.json_response,
        )
    else:
        logger.info("Starting research-assistant MCP server on stdio")
        server.run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
