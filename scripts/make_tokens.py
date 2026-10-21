"""Generate two scoped demo tokens and print ready-to-paste .env lines.

    python scripts/make_tokens.py

Prints:
  - a docs-only token   (docs:read)
  - a full token        (docs:read, web:read)

The tokens are random and only exist in this output; paste them into .env and
never commit that file.
"""

from __future__ import annotations

import json
import secrets


def main() -> None:
    docs_token = secrets.token_urlsafe(32)
    full_token = secrets.token_urlsafe(32)
    tokens = {
        docs_token: ["docs:read"],
        full_token: ["docs:read", "web:read"],
    }

    print("# Paste these two lines into .env (do not commit .env)")
    print(f"MCP_AUTH_TOKENS={json.dumps(tokens)}")
    print()
    print("# Use one of these with the CLI:")
    print(f"# docs-only (cannot search the web): MCP_TOKEN={docs_token}")
    print(f"# full access (docs + web):          MCP_TOKEN={full_token}")


if __name__ == "__main__":
    main()
