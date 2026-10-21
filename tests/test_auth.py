"""Unit tests for token parsing, scope checks, and the verifier."""

from __future__ import annotations

import pytest
from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken
from mcp.server.mcpserver.exceptions import ToolError

from server import auth


def test_load_tokens_from_json() -> None:
    tokens = auth.load_tokens(
        {"MCP_AUTH_TOKENS": '{"token-aaaaaaaa": ["docs:read"], "token-bbbbbbbb": ["web:read"]}'}
    )
    assert len(tokens) == 2
    assert tokens["token-aaaaaaaa"].scopes == {"docs:read"}
    assert tokens["token-bbbbbbbb"].scopes == {"web:read"}


def test_load_tokens_single_variable() -> None:
    tokens = auth.load_tokens(
        {"MCP_API_TOKEN": "token-cccccccc", "MCP_SCOPES": "docs:read, web:read"}
    )
    assert list(tokens) == ["token-cccccccc"]
    assert tokens["token-cccccccc"].scopes == {"docs:read", "web:read"}


def test_load_tokens_defaults_to_all_scopes() -> None:
    tokens = auth.load_tokens({"MCP_API_TOKEN": "token-dddddddd"})
    assert tokens["token-dddddddd"].scopes == set(auth.ALL_SCOPES)


def test_load_tokens_rejects_bad_json() -> None:
    with pytest.raises(ValueError, match="valid JSON"):
        auth.load_tokens({"MCP_AUTH_TOKENS": "{not json"})


def test_load_tokens_rejects_short_token() -> None:
    with pytest.raises(ValueError, match="at least 8"):
        auth.load_tokens({"MCP_AUTH_TOKENS": '{"short": ["docs:read"]}'})


def test_no_tokens_returns_empty() -> None:
    assert auth.load_tokens({}) == {}


async def test_verifier_accepts_known_token_and_rejects_unknown() -> None:
    tokens = auth.load_tokens({"MCP_AUTH_TOKENS": '{"token-eeeeeeee": ["docs:read"]}'})
    verifier = auth.ScopedTokenVerifier(tokens)

    accepted = await verifier.verify_token("token-eeeeeeee")
    assert accepted is not None
    assert accepted.scopes == ["docs:read"]
    assert await verifier.verify_token("wrong-token") is None


def test_tool_allowed_respects_scopes_and_wildcard() -> None:
    docs = frozenset({"docs:read"})
    assert auth.tool_allowed("search_documents", docs) is True
    assert auth.tool_allowed("web_search", docs) is False
    assert auth.tool_allowed("web_search", frozenset({"*"})) is True
    assert auth.tool_allowed("unknown_tool", docs) is True


def test_require_scope_passes_without_auth_layer() -> None:
    auth.require_scope(auth.SCOPE_WEB, "searching the web")


def _set_token(scopes: list[str]) -> object:
    token = AccessToken(token="secret-token", client_id="client", scopes=scopes)
    return auth_context_var.set(AuthenticatedUser(token))


def test_require_scope_allows_matching_scope() -> None:
    reset = _set_token(["web:read"])
    try:
        auth.require_scope(auth.SCOPE_WEB, "searching the web")
    finally:
        auth_context_var.reset(reset)


def test_require_scope_denies_missing_scope() -> None:
    reset = _set_token(["docs:read"])
    try:
        with pytest.raises(ToolError, match="Permission denied"):
            auth.require_scope(auth.SCOPE_WEB, "searching the web")
    finally:
        auth_context_var.reset(reset)


def test_wildcard_scope_allows_everything() -> None:
    reset = _set_token(["*"])
    try:
        auth.require_scope(auth.SCOPE_WEB, "searching the web")
        auth.require_scope(auth.SCOPE_DOCS, "reading docs")
    finally:
        auth_context_var.reset(reset)
