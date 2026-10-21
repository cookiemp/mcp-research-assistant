"""Web tools: anonymous DuckDuckGo search plus a guarded URL fetcher.

Both tools validate model-supplied arguments and surface failures as
``ToolError`` so the agent can adapt instead of crashing.
"""

from __future__ import annotations

import html
import ipaddress
import logging
import re
import socket
from urllib.parse import urlparse

import httpx
from mcp.server.mcpserver.exceptions import ToolError

from server import config
from server.auth import SCOPE_WEB, require_scope

logger = logging.getLogger("research_assistant.web")

MAX_QUERY_LEN = 300
FETCH_TIMEOUT = 15.0
_SCRIPT_STYLE = re.compile(r"<(script|style|noscript)\b.*?</\1>", re.I | re.S)
_TAGS = re.compile(r"<[^>]+>")
_WS = re.compile(r"\n{3,}")


def _validate_url(raw_url: str) -> str:
    if not isinstance(raw_url, str) or not raw_url.strip():
        raise ToolError("url must be a non-empty string, e.g. 'https://example.com'.")
    url = raw_url.strip()
    if len(url) > 2048:
        raise ToolError("url is too long; provide a normal web address.")

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ToolError(
            f"Unsupported URL scheme {parsed.scheme!r}; only http and https are allowed."
        )
    if not parsed.hostname:
        raise ToolError("url is missing a host name.")
    if parsed.username or parsed.password:
        raise ToolError("urls with embedded credentials are not allowed.")

    _reject_private_host(parsed.hostname)
    return url


def _reject_private_host(hostname: str) -> None:
    """Block loopback / private / link-local targets (basic SSRF guard)."""
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise ToolError(f"Could not resolve host {hostname!r}: {exc}.") from exc

    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            logger.warning("Ignoring unparsable resolved address %r", info[4][0])
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise ToolError(
                f"Refusing to fetch {hostname!r}: it resolves to a private or local "
                "address. Provide a public URL."
            )


def _html_to_text(raw: str) -> str:
    text = _SCRIPT_STYLE.sub(" ", raw)
    text = _TAGS.sub(" ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = _WS.sub("\n\n", text)
    return text.strip()


def web_search(query: str, max_results: int = 5) -> str:
    """Search the public web and return titles, URLs, and short snippets.

    Use this when the answer is not in the local documents or the user asks for
    current information.

    Args:
        query: Search terms, e.g. "MCP streamable HTTP transport".
        max_results: Number of results to return (1-10).
    """
    require_scope(SCOPE_WEB, "searching the web")
    if not isinstance(query, str) or not query.strip():
        raise ToolError("query must be a non-empty string.")
    query = query.strip()
    if len(query) > MAX_QUERY_LEN:
        raise ToolError(f"query is too long; keep it under {MAX_QUERY_LEN} characters.")
    if not isinstance(max_results, int) or isinstance(max_results, bool):
        raise ToolError("max_results must be an integer between 1 and 10.")
    if not 1 <= max_results <= 10:
        raise ToolError(f"max_results must be between 1 and 10, got {max_results}.")

    from ddgs import DDGS  # imported lazily so the server starts even if unused

    try:
        raw = DDGS().text(query, max_results=max_results)
    except Exception as exc:  # network / rate-limit / parsing failures
        logger.warning("web_search failed for %r: %s", query, exc)
        raise ToolError(
            f"Web search failed for {query!r}: {exc}. Retry once, or answer from "
            "the local documents."
        ) from exc

    if not raw:
        return f"No web results for {query!r}. Try different or broader keywords."

    lines = []
    for item in raw[:max_results]:
        title = item.get("title") or "(untitled)"
        href = item.get("href") or item.get("url") or ""
        body = (item.get("body") or "").strip()
        lines.append(f"- {title}\n  {href}\n  {body}")
    return (
        f"Top {len(lines)} web result(s) for {query!r}. "
        "Use fetch_url to read a page in full.\n" + "\n".join(lines)
    )


def fetch_url(url: str, max_chars: int = 4000) -> str:
    """Fetch a web page and return it as plain text.

    Use this after web_search when a snippet is not enough.

    Args:
        url: Absolute http(s) URL to read, e.g. "https://modelcontextprotocol.io".
        max_chars: Maximum characters to return before truncating (500-20000).
    """
    require_scope(SCOPE_WEB, "fetching web pages")
    if not isinstance(max_chars, int) or isinstance(max_chars, bool):
        raise ToolError("max_chars must be an integer between 500 and 20000.")
    if not 500 <= max_chars <= 20000:
        raise ToolError(f"max_chars must be between 500 and 20000, got {max_chars}.")

    url = _validate_url(url)
    headers = {"User-Agent": config.HTTP_USER_AGENT, "Accept": "text/html,*/*"}
    try:
        response = httpx.get(
            url, headers=headers, timeout=FETCH_TIMEOUT, follow_redirects=True
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise ToolError(
            f"Fetching {url} failed with HTTP {exc.response.status_code}. "
            "Try a different URL."
        ) from exc
    except httpx.HTTPError as exc:
        raise ToolError(f"Could not fetch {url}: {exc}. Try a different URL.") from exc

    ctype = response.headers.get("content-type", "")
    if "html" in ctype or "xml" in ctype:
        text = _html_to_text(response.text)
    elif ctype.startswith("text/") or "json" in ctype:
        text = response.text
    else:
        raise ToolError(
            f"Refusing to read non-text content ({ctype or 'unknown type'}) from {url}."
        )

    if len(text) > max_chars:
        text = text[:max_chars] + f"\n\n[truncated at {max_chars} characters]"
    return f"# {url}\n\n{text}"
