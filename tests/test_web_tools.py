"""Tests for the web tools, focusing on URL validation and SSRF guards."""

from __future__ import annotations

import socket

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from server.tools import web


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/file",
        "javascript:alert(1)",
        "https://",
    ],
)
def test_validate_url_rejects_bad_schemes_and_hosts(url: str) -> None:
    with pytest.raises(ToolError):
        web._validate_url(url)


def test_validate_url_rejects_embedded_credentials() -> None:
    with pytest.raises(ToolError, match="credentials"):
        web._validate_url("https://user:pass@example.com")


@pytest.mark.parametrize(
    ("host", "ip"),
    [
        ("localhost", "127.0.0.1"),
        ("internal.example", "10.0.0.5"),
        ("169.254.1.1", "169.254.1.1"),
    ],
)
def test_validate_url_blocks_private_targets(
    host: str, ip: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_getaddrinfo(name: str, port: object) -> list[tuple]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]

    monkeypatch.setattr(web.socket, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(ToolError, match="private or local"):
        web._validate_url(f"http://{host}/sensitive")


def test_validate_url_blocks_loopback_ipv6(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        web.socket,
        "getaddrinfo",
        lambda name, port: [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("::1", 0, 0, 0))],
    )
    with pytest.raises(ToolError, match="private or local"):
        web._validate_url("http://[::1]/sensitive")


def test_validate_url_accepts_public_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        web.socket,
        "getaddrinfo",
        lambda name, port: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))],
    )
    assert web._validate_url("https://example.com/page?a=1") == "https://example.com/page?a=1"


def test_html_to_text_strips_markup_and_scripts() -> None:
    raw = "<html><head><style>x{}</style></head><body><h1>Hi</h1><script>bad()</script><p>Text &amp; more</p></body></html>"
    text = web._html_to_text(raw)
    assert "Hi" in text
    assert "Text & more" in text
    assert "bad()" not in text
    assert "x{}" not in text


def test_web_search_rejects_bad_query() -> None:
    with pytest.raises(ToolError):
        web.web_search("")
    with pytest.raises(ToolError):
        web.web_search("ok", max_results=50)


def test_fetch_url_rejects_bad_max_chars() -> None:
    with pytest.raises(ToolError):
        web.fetch_url("https://example.com", max_chars=10)
