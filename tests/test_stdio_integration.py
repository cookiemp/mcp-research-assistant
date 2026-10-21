"""End-to-end test: our client talks to our server over real stdio."""

from __future__ import annotations

import sys
from pathlib import Path

from mcp import StdioServerParameters

from client.mcp_client import MCPClient, tool_signature

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def server_params() -> StdioServerParameters:
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "server.main"],
        cwd=str(PROJECT_ROOT),
        env={"DOCS_DIR": str(PROJECT_ROOT / "documents"), "PATH": "", "PYTHONPATH": str(PROJECT_ROOT)},
    )


async def test_client_lists_all_tools_over_stdio() -> None:
    async with MCPClient(server_params()) as client:
        tools = await client.list_tools()
    names = {tool.name for tool in tools}
    assert names == {"search_documents", "read_document", "web_search", "fetch_url"}
    for tool in tools:
        assert tool.description and tool.input_schema


async def test_client_reads_resource_and_prompt() -> None:
    async with MCPClient(server_params()) as client:
        index = await client.read_resource("docs://index")
        prompt = await client.get_prompt("research_brief", {"topic": "MCP"})
    assert "mcp-notes.md" in index
    assert "MCP" in prompt


async def test_client_tool_call_and_error_result() -> None:
    async with MCPClient(server_params()) as client:
        ok = await client.call_tool("search_documents", {"query": "oauth", "limit": 2})
        bad = await client.call_tool("read_document", {"path": "../secret.txt"})
        signature = tool_signature((await client.list_tools())[0])
    assert ok.is_error is False
    assert "oauth-notes.md" in ok.content[0].text
    assert bad.is_error is True
    assert "Access denied" in bad.content[0].text
    assert "(" in signature
