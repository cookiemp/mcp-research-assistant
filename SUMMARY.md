# Summary: what I built and how the pieces fit together

## What it is

A **personal research assistant**: a CLI app that answers questions about a
user's own notes and the public web, always with citations. It is implemented as
an **MCP server** plus a **user-defined MCP client** feeding a Gemini model
through an agent loop, so the external resources are exposed as a reusable,
protocol-based integration rather than hard-wired code.

The server runs over **stdio** for local use and over **Streamable HTTP** for
remote use, where **bearer-token authentication and per-tool scopes** decide
which tools a caller may see and run.

## The pieces

| Piece | File | Responsibility |
| --- | --- | --- |
| MCP server | `server/main.py` | Declares tools, one resource, one prompt; serves stdio or HTTP. |
| Auth | `server/auth.py` | Scoped bearer tokens, per-tool scope checks, `tools/list` filtering. |
| Document tools | `server/tools/docs.py` | `search_documents`, `read_document` over a local folder. |
| Web tools | `server/tools/web.py` | `web_search` (DuckDuckGo), `fetch_url` (guarded HTTP). |
| Config | `server/config.py` | Reads env vars; routes all logging to **stderr**. |
| MCP client | `client/mcp_client.py` | Our own client; stdio subprocess or HTTP with a bearer token. |
| Agent loop | `app/agent.py` | Lists tools, calls the LLM, runs requested tools, feeds results back. |
| CLI | `app/main.py` | Argument parsing, `.env` loading, interactive mode, tool listing. |
| Tokens | `scripts/make_tokens.py` | Generates scoped demo tokens for `.env`. |

## How a request flows

1. `app/main.py` builds an MCP client: it either spawns `python -m server.main`
   over stdio, or connects to `http://host:port/mcp` with `Authorization:
   Bearer <token>`.
2. The agent calls `tools/list`. Over HTTP, the server filters the list to the
   tools the token's scopes allow.
3. Each tool's JSON Schema is converted into a Gemini function declaration and
   sent with the question.
4. If Gemini asks for a tool, the agent runs `tools/call`, receives the result,
   and appends it as a function response. Over HTTP, the tool itself re-checks
   the scope before doing any work.
5. Steps 3-4 repeat until the model answers with no more tool calls, or the
   `--max-steps` limit is hit.

The LLM never contacts the server directly. The agent loop is the messenger, so
it keeps control over validation, logging, scopes, and which tools a user sees.

## Design decisions that matter for the rubric

- **Two independent resources** (local files and the web) exposed as four
  focused tools, each with a distinct, descriptive name and a required scope.
- **Typed inputs** generated automatically from Python type hints and
  docstrings, so schemas always match the implementation.
- **Errors as results**: every failure is a `ToolError` that becomes an
  `isError` result containing recovery instructions, e.g. "limit must be
  between 1 and 10, got 99", "Access denied: ... is outside the documents
  folder", or "Permission denied: ... requires the 'web:read' scope".
- **Safety**: path-traversal guards, an SSRF guard on `fetch_url`, strict
  argument validation, bearer auth on HTTP, and a bounded loop.
- **Secrets**: `GEMINI_API_KEY` and MCP tokens are read only from the
  environment; `.env` is gitignored, tokens never appear in logs, and the
  server records only a SHA-256-derived client id.
- **stdio correctness**: the server writes nothing to stdout; logs go to
  stderr, because stdout carries the JSON-RPC stream.
- **Verified before connecting**: the server was run through the **MCP
  Inspector** (`tools/list`, `tools/call`, `--strict`) before the agent used it.

## Stretch goals included

- **Streamable HTTP transport** (`--transport streamable-http`) with JSON
  metadata endpoints, alongside the default stdio transport.
- **Authentication + scoped access**: tokens in `MCP_AUTH_TOKENS`, `docs:read`
  and `web:read` scopes, per-tool enforcement, scope-filtered `tools/list`, and
  a hard refusal to start HTTP without auth.
- **A resource** (`docs://index`) and **a prompt** (`research_brief`).
- **A user-defined MCP client** for both transports (not a built-in host).

## Verification performed

- **MCP Inspector**: `tools/list` (4 tools, valid schemas), `tools/call`
  (`search_documents` returned ranked results), `--strict` schema check (exit 0).
- **Automated tests**: `python -m pytest` -> **55 passed**, covering tools,
  validation, traversal and SSRF rejection, token parsing, scope checks,
  `tools/list` filtering, a real stdio round trip, a real HTTP round trip with
  valid / missing / invalid / under-scoped tokens, fail-fast startup without
  auth, and the agent loop (tool use, error recovery, unknown tool, max steps).
- **Live stdio demo** with Gemini: `search_documents` + `web_search`, cited
  `mcp-notes.md` and the spec URL.
- **Live HTTP demo** with a full-scope token: `search_documents` +
  `read_document` + `web_search`, all through the authenticated server, with
  citations.

## Known limitations / next steps

- TLS is not handled in-process; a remote deployment should terminate TLS at a
  proxy and set `MCP_PUBLIC_URL`.
- Tokens are static env-configured values rather than an OAuth 2.1 flow. The
  server exposes the standard protected-resource metadata, so swapping in an
  OAuth authorization server is the next step.
- The agent loop is single-turn per question with a step cap; persistent
  conversation history and per-user tool policy would be the next iteration.
