"""Scoped bearer-token authorization for the Streamable HTTP transport.

Tokens and their scopes come from the environment, never from code:

    MCP_AUTH_TOKENS={"<token>": ["docs:read", "web:read"]}

or, for a single token:

    MCP_API_TOKEN=<token>
    MCP_SCOPES=docs:read,web:read

stdio servers do not use this layer: the host owns the process and the
credentials, so scope checks pass through when no authenticated token exists.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass
from typing import Any

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver.exceptions import ToolError
from mcp import types as mcp_types

logger = logging.getLogger("research_assistant.auth")

SCOPE_DOCS = "docs:read"
SCOPE_WEB = "web:read"
ALL_SCOPES = (SCOPE_DOCS, SCOPE_WEB)
WILDCARD = "*"

TOOL_SCOPES: dict[str, str] = {
    "search_documents": SCOPE_DOCS,
    "read_document": SCOPE_DOCS,
    "web_search": SCOPE_WEB,
    "fetch_url": SCOPE_WEB,
}


@dataclass(frozen=True)
class TokenRecord:
    client_id: str
    scopes: frozenset[str]


def _client_id_for(token: str) -> str:
    """Stable, non-reversible identifier for logs (never the token itself)."""
    return "token-" + hashlib.sha256(token.encode("utf-8")).hexdigest()[:8]


def _parse_scopes(value: Any, source: str) -> frozenset[str]:
    if value is None:
        return frozenset(ALL_SCOPES)
    if isinstance(value, str):
        items = [part.strip() for part in value.split(",") if part.strip()]
    elif isinstance(value, list) and all(isinstance(item, str) for item in value):
        items = [item.strip() for item in value if item.strip()]
    else:
        raise ValueError(f"{source}: scopes must be a string or a list of strings")

    unknown = sorted(set(items) - set(ALL_SCOPES) - {WILDCARD})
    if unknown:
        logger.warning("%s: ignoring unknown scopes %s", source, unknown)
    return frozenset(items)


def load_tokens(environ: dict[str, str] | None = None) -> dict[str, TokenRecord]:
    """Read scoped tokens from the environment. Raises ValueError on bad config."""
    env = os.environ if environ is None else environ
    raw = (env.get("MCP_AUTH_TOKENS") or "").strip()

    if raw:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(
                "MCP_AUTH_TOKENS must be valid JSON, e.g. "
                '{"<token>": ["docs:read", "web:read"]}'
            ) from exc
        if not isinstance(parsed, dict):
            raise ValueError("MCP_AUTH_TOKENS must be a JSON object of token -> scopes")

        tokens: dict[str, TokenRecord] = {}
        for token, scopes in parsed.items():
            if not isinstance(token, str) or len(token) < 8:
                raise ValueError("every token must be a string of at least 8 characters")
            tokens[token] = TokenRecord(
                client_id=_client_id_for(token),
                scopes=_parse_scopes(scopes, "MCP_AUTH_TOKENS"),
            )
        return tokens

    single = (env.get("MCP_API_TOKEN") or "").strip()
    if single:
        if len(single) < 8:
            raise ValueError("MCP_API_TOKEN must be at least 8 characters")
        scopes = _parse_scopes(env.get("MCP_SCOPES"), "MCP_SCOPES")
        return {single: TokenRecord(_client_id_for(single), scopes)}

    return {}


class ScopedTokenVerifier(TokenVerifier):
    """Checks a bearer token against the configured token table."""

    def __init__(self, tokens: dict[str, TokenRecord]) -> None:
        self._tokens = tokens

    async def verify_token(self, token: str) -> AccessToken | None:
        record = self._tokens.get(token)
        if record is None:
            logger.warning("Rejected an unknown bearer token")
            return None
        logger.info("Accepted bearer token for client %s", record.client_id)
        return AccessToken(
            token=token,
            client_id=record.client_id,
            scopes=sorted(record.scopes),
        )


def build_auth(
    *, host: str, port: int, path: str, public_url: str | None = None
) -> tuple[ScopedTokenVerifier, AuthSettings]:
    """Build the verifier and auth settings for the HTTP transport."""
    tokens = load_tokens()
    if not tokens:
        raise RuntimeError(
            "The Streamable HTTP transport requires authentication. Set "
            'MCP_AUTH_TOKENS (JSON) or MCP_API_TOKEN before starting the server. '
            "Run 'python scripts/make_tokens.py' to generate demo tokens."
        )

    base = (public_url or f"http://{host}:{port}").rstrip("/")
    settings = AuthSettings(
        issuer_url=base,
        resource_server_url=f"{base}{path}",
        required_scopes=None,
        validate_token_resource=False,
    )
    logger.info(
        "Scoped bearer auth enabled for %d token(s); scopes: %s",
        len(tokens),
        ", ".join(sorted({scope for record in tokens.values() for scope in record.scopes})),
    )
    return ScopedTokenVerifier(tokens), settings


def current_scopes() -> frozenset[str] | None:
    """Scopes of the current request, or None outside the auth layer (stdio)."""
    access_token = get_access_token()
    if access_token is None:
        return None
    return frozenset(access_token.scopes or ())


def has_scope(scope: str, scopes: frozenset[str] | None = None) -> bool:
    active = current_scopes() if scopes is None else scopes
    if active is None:
        return True  # stdio mode: the host already controls access
    return WILDCARD in active or scope in active


def require_scope(scope: str, action: str) -> None:
    """Raise a model-readable ToolError when the token lacks ``scope``."""
    active = current_scopes()
    if active is None or WILDCARD in active or scope in active:
        return
    raise ToolError(
        f"Permission denied: {action} requires the {scope!r} scope. This token "
        f"has {sorted(active)}. Ask the server operator for a token with the "
        f"{scope!r} scope."
    )


def tool_allowed(tool_name: str, scopes: frozenset[str]) -> bool:
    required = TOOL_SCOPES.get(tool_name)
    if required is None:
        return True
    return WILDCARD in scopes or required in scopes


def _name_of(tool: Any) -> str:
    if isinstance(tool, dict):
        return str(tool.get("name", ""))
    return str(getattr(tool, "name", ""))


class ToolScopeMiddleware:
    """Hide tools the caller's scopes do not allow from ``tools/list``."""

    async def __call__(self, ctx: Any, call_next: Any) -> Any:
        result = await call_next(ctx)
        if ctx.method != "tools/list":
            return result
        active = current_scopes()
        if active is None:
            return result

        if isinstance(result, dict):
            tools = result.get("tools") or []
            allowed = [tool for tool in tools if tool_allowed(_name_of(tool), active)]
            if len(allowed) == len(tools):
                return result
            logger.debug(
                "Filtered tools/list from %d to %d tool(s) for scopes %s",
                len(tools),
                len(allowed),
                sorted(active),
            )
            return {**result, "tools": allowed}

        if isinstance(result, mcp_types.ListToolsResult):
            allowed = [tool for tool in result.tools if tool_allowed(tool.name, active)]
            if len(allowed) == len(result.tools):
                return result
            logger.debug(
                "Filtered tools/list from %d to %d tool(s) for scopes %s",
                len(result.tools),
                len(allowed),
                sorted(active),
            )
            return result.model_copy(update={"tools": allowed})

        return result
