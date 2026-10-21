"""Shared configuration for the MCP research assistant server.

Everything is read from environment variables (optionally via a local .env
file). No secrets are ever hard-coded here.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv

    if os.getenv("MCP_SKIP_DOTENV", "").strip().lower() not in {"1", "true", "yes"}:
        load_dotenv()
except ModuleNotFoundError:  # dotenv is optional at runtime
    pass

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        logging.getLogger("research_assistant").warning(
            "Invalid integer for %s=%r, using default %d", name, raw, default
        )
        return default


def docs_dir() -> Path:
    """Absolute, resolved directory the document tools are allowed to read."""
    raw = os.getenv("DOCS_DIR", "").strip()
    path = Path(raw) if raw else Path("documents")
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


MAX_SEARCH_RESULTS = _int_env("MAX_SEARCH_RESULTS", 10)
MAX_FETCH_CHARS = _int_env("MAX_FETCH_CHARS", 8000)
HTTP_USER_AGENT = os.getenv("HTTP_USER_AGENT", "research-assistant/1.0")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()


def configure_logging() -> None:
    """Send every log record to stderr.

    A stdio MCP server must never write to stdout: stdout carries the
    JSON-RPC stream and stray output corrupts it.
    """
    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
