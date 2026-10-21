"""A small, user-defined MCP client.

This is our own client rather than a built-in host. It speaks JSON-RPC 2.0
through the official SDK and supports both transports:

- **stdio**: spawns the server as a local subprocess (desktop/CLI use).
- **Streamable HTTP**: connects to a remote server and sends a bearer token
  (remote/multi-user use).

It exposes the operations the agent loop needs.
"""

from __future__ import annotations

import logging
from contextlib import AsyncExitStack
from types import TracebackType
from typing import Any

from mcp import Client, StdioServerParameters
from mcp import types as mcp_types

logger = logging.getLogger("research_assistant.client")

DEFAULT_TIMEOUT = 30.0


class MCPClient:
    """Connect to one MCP server and let callers use its tools."""

    def __init__(
        self,
        params: StdioServerParameters | None = None,
        *,
        url: str | None = None,
        token: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        if (params is None) == (url is None):
            raise ValueError("Provide exactly one of 'params' (stdio) or 'url' (HTTP).")
        self.params = params
        self.url = url
        self.token = token
        self.timeout = timeout
        self._stack = AsyncExitStack()
        self._client: Client | None = None

    @property
    def transport_name(self) -> str:
        return "stdio" if self.params is not None else "streamable-http"

    async def __aenter__(self) -> "MCPClient":
        if self.params is not None:
            logger.debug("Connecting to MCP server over stdio: %s", self.params.command)
            self._client = await self._stack.enter_async_context(Client(self.params))
        else:
            self._client = await self._connect_http()
        info = self._client.server_info
        logger.info(
            "Connected over %s to MCP server %s version %s",
            self.transport_name,
            getattr(info, "name", "unknown"),
            getattr(info, "version", "unknown"),
        )
        return self

    async def _connect_http(self) -> Client:
        import httpx2
        from mcp.client.streamable_http import streamable_http_client

        headers = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        else:
            logger.warning("Connecting over HTTP without a bearer token")

        http_client = httpx2.AsyncClient(
            headers=headers, timeout=httpx2.Timeout(self.timeout)
        )
        await self._stack.enter_async_context(http_client)
        transport = streamable_http_client(self.url, http_client=http_client)
        return await self._stack.enter_async_context(Client(transport))

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self._stack.aclose()
        self._client = None

    @property
    def _conn(self) -> Client:
        if self._client is None:
            raise RuntimeError("MCPClient is not connected; use 'async with'.")
        return self._client

    async def list_tools(self) -> list[mcp_types.Tool]:
        """Return the server's tools (name, description, JSON Schema inputs)."""
        return list((await self._conn.list_tools()).tools)

    async def call_tool(
        self, name: str, arguments: dict[str, Any] | None = None
    ) -> mcp_types.CallToolResult:
        """Run a tool. Failures come back with ``is_error=True`` and a message."""
        return await self._conn.call_tool(name, arguments or {})

    async def list_resources(self) -> list[mcp_types.Resource]:
        return list((await self._conn.list_resources()).resources)

    async def read_resource(self, uri: str) -> str:
        result = await self._conn.read_resource(uri)
        parts = []
        for content in result.contents:
            text = getattr(content, "text", None)
            if text:
                parts.append(text)
        return "\n".join(parts)

    async def get_prompt(self, name: str, arguments: dict[str, str] | None = None) -> str:
        result = await self._conn.get_prompt(name, arguments or {})
        parts = []
        for message in result.messages:
            text = getattr(message.content, "text", None)
            if text:
                parts.append(text)
        return "\n".join(parts)


def tool_to_text(result: mcp_types.CallToolResult) -> str:
    """Flatten a tool result's content into plain text for the LLM."""
    chunks = []
    for content in result.content:
        text = getattr(content, "text", None)
        if text:
            chunks.append(text)
    if not chunks:
        return "(the tool returned no text content)"
    return "\n".join(chunks)


def tool_signature(tool: mcp_types.Tool) -> str:
    """One-line description of a tool, for logs and CLI output."""
    schema = tool.input_schema or {}
    props = ", ".join((schema.get("properties") or {}).keys())
    return f"{tool.name}({props})"


def describe_error(exc: BaseException) -> str:
    """Reduce nested ExceptionGroups to the useful root message."""
    current: BaseException = exc
    while True:
        inner = getattr(current, "exceptions", None)
        if not inner:
            break
        current = inner[0]
    return str(current) or current.__class__.__name__
