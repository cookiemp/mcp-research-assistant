"""Integration tests for the Streamable HTTP transport and scoped auth.

Starts the real server as a subprocess, then talks to it with our MCP client.
No LLM and no external network calls are involved (web tools are only called
with scopes they lack, before any network request).
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from client.mcp_client import MCPClient, tool_to_text

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DOCS_TOKEN = "docs-token-1234567890"
FULL_TOKEN = "full-token-1234567890"
TOKENS = {
    DOCS_TOKEN: ["docs:read"],
    FULL_TOKEN: ["docs:read", "web:read"],
}


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for_port(port: int, timeout: float = 40.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.2)
    raise RuntimeError(f"server did not open port {port} in time")


def start_http_server(port: int, env: dict[str, str]) -> subprocess.Popen:
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "server.main",
            "--transport",
            "streamable-http",
            "--port",
            str(port),
        ],
        cwd=str(PROJECT_ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


@pytest.fixture(scope="module")
def http_server() -> Iterator[tuple[str, subprocess.Popen]]:
    port = free_port()
    env = dict(os.environ)
    env["MCP_AUTH_TOKENS"] = json.dumps(TOKENS)
    env["DOCS_DIR"] = str(PROJECT_ROOT / "documents")
    env["LOG_LEVEL"] = "INFO"
    proc = start_http_server(port, env)
    try:
        wait_for_port(port)
        yield f"http://127.0.0.1:{port}/mcp", proc
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover
            proc.kill()


async def test_full_token_lists_all_tools(http_server) -> None:
    url, _ = http_server
    async with MCPClient(url=url, token=FULL_TOKEN) as client:
        names = {tool.name for tool in await client.list_tools()}
    assert names == {"search_documents", "read_document", "web_search", "fetch_url"}


async def test_docs_token_lists_only_document_tools(http_server) -> None:
    url, _ = http_server
    async with MCPClient(url=url, token=DOCS_TOKEN) as client:
        names = {tool.name for tool in await client.list_tools()}
    assert names == {"search_documents", "read_document"}


async def test_docs_token_can_read_documents_over_http(http_server) -> None:
    url, _ = http_server
    async with MCPClient(url=url, token=DOCS_TOKEN) as client:
        result = await client.call_tool("search_documents", {"query": "oauth", "limit": 2})
        index = await client.read_resource("docs://index")
    assert result.is_error is False
    assert "oauth-notes.md" in tool_to_text(result)
    assert "mcp-notes.md" in index


async def test_docs_token_is_denied_a_web_tool(http_server) -> None:
    url, _ = http_server
    async with MCPClient(url=url, token=DOCS_TOKEN) as client:
        result = await client.call_tool("web_search", {"query": "mcp", "max_results": 1})
    assert result.is_error is True
    text = tool_to_text(result)
    assert "Permission denied" in text
    assert "web:read" in text


async def test_full_token_reaches_web_tool_validation(http_server) -> None:
    url, _ = http_server
    async with MCPClient(url=url, token=FULL_TOKEN) as client:
        result = await client.call_tool("web_search", {"query": "mcp", "max_results": 99})
    assert result.is_error is True
    text = tool_to_text(result)
    assert "Permission denied" not in text
    assert "max_results" in text


async def test_missing_token_is_rejected(http_server) -> None:
    url, _ = http_server
    with pytest.raises(Exception):
        async with MCPClient(url=url):
            pass


async def test_invalid_token_is_rejected(http_server) -> None:
    url, _ = http_server
    with pytest.raises(Exception):
        async with MCPClient(url=url, token="not-a-real-token"):
            pass


def test_http_mode_refuses_to_start_without_auth() -> None:
    port = free_port()
    env = dict(os.environ)
    env.pop("MCP_AUTH_TOKENS", None)
    env.pop("MCP_API_TOKEN", None)
    env["MCP_SKIP_DOTENV"] = "1"
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "server.main",
            "--transport",
            "streamable-http",
            "--port",
            str(port),
        ],
        cwd=str(PROJECT_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=40,
    )
    assert proc.returncode == 1
    assert "requires authentication" in (proc.stderr + proc.stdout)
