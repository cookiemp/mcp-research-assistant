"""Tests for the document tools, including input validation and safety."""

from __future__ import annotations

from pathlib import Path

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from server import config
from server.tools import docs


@pytest.fixture(autouse=True)
def temp_docs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "mcp.md").write_text(
        "MCP connects models to tools.\nOAuth tokens secure remote servers.\n",
        encoding="utf-8",
    )
    (tmp_path / "empty.txt").write_text("nothing to see", encoding="utf-8")
    monkeypatch.setenv("DOCS_DIR", str(tmp_path))
    return tmp_path


def test_search_finds_matching_document() -> None:
    result = docs.search_documents("oauth token", limit=3)
    assert "notes/mcp.md" in result
    assert "read_document" in result


def test_search_reports_no_match_with_guidance() -> None:
    result = docs.search_documents("kubernetes", limit=3)
    assert "No documents matched" in result
    assert "web_search" in result


def test_search_rejects_empty_query() -> None:
    with pytest.raises(ToolError):
        docs.search_documents("   ")


def test_search_rejects_out_of_range_limit() -> None:
    with pytest.raises(ToolError):
        docs.search_documents("oauth", limit=99)
    with pytest.raises(ToolError):
        docs.search_documents("oauth", limit=0)


def test_read_returns_file_contents() -> None:
    result = docs.read_document("notes/mcp.md")
    assert "MCP connects models to tools" in result
    assert result.startswith("# notes/mcp.md")


def test_read_truncates_long_files(tmp_path: Path) -> None:
    (tmp_path / "long.md").write_text("word " * 400, encoding="utf-8")
    result = docs.read_document("long.md", max_chars=500)
    assert "[truncated at 500 characters]" in result


def test_read_rejects_path_traversal() -> None:
    with pytest.raises(ToolError, match="Access denied"):
        docs.read_document("../../etc/passwd")


def test_read_rejects_absolute_path() -> None:
    with pytest.raises(ToolError):
        docs.read_document(str(Path(config.docs_dir().anchor) / "Windows" / "win.ini"))


def test_read_rejects_null_byte() -> None:
    with pytest.raises(ToolError, match="null byte"):
        docs.read_document("notes/mcp.md\x00.png")


def test_read_missing_file_lists_available() -> None:
    with pytest.raises(ToolError) as excinfo:
        docs.read_document("does-not-exist.md")
    assert "Available documents" in str(excinfo.value)


def test_read_rejects_unsupported_extension(tmp_path: Path) -> None:
    (tmp_path / "binary.exe").write_bytes(b"MZ")
    with pytest.raises(ToolError, match="Unsupported file type"):
        docs.read_document("binary.exe")


def test_document_index_lists_files() -> None:
    index = docs.document_index()
    assert "notes/mcp.md" in index
    assert "empty.txt" in index
