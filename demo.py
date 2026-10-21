"""Canned demo: one question that needs a local document tool *and* a web tool.

Run with:  python demo.py

It reuses the real CLI, so the output shows the agent listing tools, calling
search_documents/read_document on the local notes, then web_search/fetch_url
for anything current, and finally answering with citations.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.main import main

DEMO_QUESTION = (
    "Using my local notes, summarize how MCP stdio servers should handle logging. "
    "Then search the web for the latest MCP specification version and tell me which "
    "version is current. Cite every source you used."
)

if __name__ == "__main__":
    print("Demo question:")
    print(f"  {DEMO_QUESTION}\n")
    raise SystemExit(main([DEMO_QUESTION]))
