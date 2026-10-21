"""Document tools: search and read files inside the configured docs folder.

Both tools validate every model-supplied argument and raise ``ToolError`` with
an actionable message so the model can correct itself and retry.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from mcp.server.mcpserver.exceptions import ToolError

from server import config
from server.auth import SCOPE_DOCS, require_scope

logger = logging.getLogger("research_assistant.docs")

ALLOWED_SUFFIXES = {".md", ".markdown", ".txt", ".rst"}
MAX_QUERY_LEN = 200
MAX_PATH_LEN = 260


def _docs_root() -> Path:
    root = config.docs_dir()
    if not root.is_dir():
        raise ToolError(
            f"Document directory {root} does not exist. Create it or set the "
            "DOCS_DIR environment variable to a folder that contains files."
        )
    return root


def _safe_document_path(raw_path: str) -> Path:
    """Resolve a model-supplied path and prove it stays inside the docs root."""
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ToolError("path must be a non-empty string, e.g. 'notes/mcp.md'.")
    if "\x00" in raw_path:
        raise ToolError("path contains a null byte; provide a plain file name.")
    if len(raw_path) > MAX_PATH_LEN:
        raise ToolError(
            f"path is too long ({len(raw_path)} chars); keep it under {MAX_PATH_LEN} "
            "characters and use a path relative to the documents folder."
        )

    root = _docs_root()
    candidate = (root / raw_path).resolve()

    try:
        candidate.relative_to(root)
    except ValueError:
        raise ToolError(
            f"Access denied: {raw_path!r} is outside the documents folder. Use a "
            "path relative to the documents root and never use '..'."
        ) from None

    if not candidate.is_file():
        available = _available_documents(root, limit=20)
        raise ToolError(
            f"File {raw_path!r} was not found. Available documents: {available}"
        )
    if candidate.suffix.lower() not in ALLOWED_SUFFIXES:
        raise ToolError(
            f"Unsupported file type {candidate.suffix!r}. Allowed types: "
            f"{', '.join(sorted(ALLOWED_SUFFIXES))}."
        )
    return candidate


def _available_documents(root: Path, limit: int = 20) -> str:
    names = sorted(
        str(p.relative_to(root)).replace("\\", "/")
        for p in root.rglob("*")
        if p.is_file() and p.suffix.lower() in ALLOWED_SUFFIXES
    )
    if not names:
        return "(none - the documents folder is empty)"
    shown = names[:limit]
    more = "" if len(names) <= limit else f" (+{len(names) - limit} more)"
    return ", ".join(shown) + more


def _iter_documents(root: Path):
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix.lower() in ALLOWED_SUFFIXES:
            yield path


def _snippet(lines: list[str], index: int, width: int = 2) -> str:
    start = max(0, index - width)
    end = min(len(lines), index + width + 1)
    return " ".join(line.strip() for line in lines[start:end]).strip()


def document_index() -> str:
    """Return a human-readable index of the documents folder (used as a resource)."""
    require_scope(SCOPE_DOCS, "listing local documents")
    root = config.docs_dir()
    if not root.is_dir():
        return f"Document directory {root} does not exist."
    entries = []
    for path in _iter_documents(root):
        rel = str(path.relative_to(root)).replace("\\", "/")
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        entries.append(f"{rel} ({size} bytes)")
    if not entries:
        return f"The documents folder {root} is empty."
    return f"{len(entries)} document(s) in {root}:\n" + "\n".join(entries)


def search_documents(query: str, limit: int = 5) -> str:
    """Search the local document folder for a keyword or phrase.

    Use this first when the user asks about their own notes, docs, or files.

    Args:
        query: Words to look for, e.g. "oauth token validation". Case-insensitive.
        limit: Maximum number of matching files to return (1-10).
    """
    require_scope(SCOPE_DOCS, "searching local documents")
    if not isinstance(query, str) or not query.strip():
        raise ToolError("query must be a non-empty string.")
    query = query.strip()
    if len(query) > MAX_QUERY_LEN:
        raise ToolError(
            f"query is too long ({len(query)} chars); keep it under {MAX_QUERY_LEN}."
        )
    if not isinstance(limit, int) or isinstance(limit, bool):
        raise ToolError("limit must be an integer between 1 and 10.")
    if not 1 <= limit <= 10:
        raise ToolError(f"limit must be between 1 and 10, got {limit}.")

    root = _docs_root()
    terms = [t for t in re.split(r"\W+", query.lower()) if t]
    if not terms:
        raise ToolError("query must contain at least one alphanumeric word.")

    hits: list[tuple[int, Path, list[str]]] = []
    for path in _iter_documents(root):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            logger.warning("Could not read %s: %s", path, exc)

            continue
        lines = text.splitlines()
        lowered = [line.lower() for line in lines]
        score = sum(line.count(term) for term in terms for line in lowered)
        if score:
            hits.append((score, path, lines))

    if not hits:
        return (
            f"No documents matched {query!r}. Documents searched: "
            f"{_available_documents(root)}. Try a broader or different keyword, "
            "or use web_search for information that is not in the local folder."
        )

    hits.sort(key=lambda item: (-item[0], str(item[1])))
    results = []
    for score, path, lines in hits[:limit]:
        rel = str(path.relative_to(root)).replace("\\", "/")
        snippets = []
        for term in terms:
            for idx, line in enumerate(lines):
                if term in line.lower():
                    snippets.append(f"L{idx + 1}: {_snippet(lines, idx)}")
                    break
            if len(snippets) >= 3:
                break
        body = "\n    ".join(snippets) if snippets else "(match in body)"
        results.append(f"- {rel} (score {score})\n    {body}")

    return (
        f"Found {len(hits)} document(s) for {query!r}. "
        "Use read_document to read the full file.\n" + "\n".join(results)
    )


def read_document(path: str, max_chars: int = 6000) -> str:
    """Read the full text of one document from the local folder.

    Use this after search_documents to read a file in detail.

    Args:
        path: Path relative to the documents folder, e.g. "notes/mcp.md".
        max_chars: Maximum characters to return before truncating (500-20000).
    """
    require_scope(SCOPE_DOCS, "reading local documents")
    if not isinstance(max_chars, int) or isinstance(max_chars, bool):
        raise ToolError("max_chars must be an integer between 500 and 20000.")
    if not 500 <= max_chars <= 20000:
        raise ToolError(f"max_chars must be between 500 and 20000, got {max_chars}.")

    target = _safe_document_path(path)
    try:
        text = target.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise ToolError(f"Could not read {path!r}: {exc}. Try another document.") from exc

    rel = str(target.relative_to(config.docs_dir())).replace("\\", "/")
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n\n[truncated at {max_chars} characters]"
    return f"# {rel}\n\n{text}"
