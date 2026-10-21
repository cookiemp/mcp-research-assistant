# Step-by-step testing guide

Everything below is written for **Windows PowerShell** (the environment this was
built in). macOS/Linux notes are included where commands differ. Run every
command from the project root:

```
cd C:\Users\shime\Desktop\1\icog\training10\mcp-research-assistant
```

You do **not** need an LLM key for steps 1-3 and 5.1-5.5. Only the live agent
demos (4 and 5.6) call Gemini.

---

## 0. One-time setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1          # macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt

copy .env.example .env              # macOS/Linux: cp .env.example .env
notepad .env
```

In `.env` set at least:

```
GEMINI_API_KEY=<your key from https://aistudio.google.com/apikey>
```

Keep `.env.example`'s `MCP_AUTH_TOKENS` line for now; step 5 replaces it with
real random tokens.

Verify the install:

```powershell
python -c "import mcp, google.genai, ddgs; print('deps ok')"
```

Expected: `deps ok`.

---

## 1. Automated test suite (55 tests, no LLM, no keys)

```powershell
python -m pytest
```

Expected:

```
55 passed
```

What is covered:

- document search/read, truncation, bad arguments;
- path traversal (`../`), absolute paths, null bytes, bad extensions;
- web URL validation, SSRF blocking, HTML stripping;
- token JSON parsing, single-token mode, scope checks, wildcard `*`,
  `tools/list` filtering;
- a real stdio client <-> server round trip;
- a real HTTP round trip with valid, missing, invalid, and under-scoped tokens;
- HTTP startup refusal when no auth is configured;
- the agent loop: tool call, error recovery, unknown tool, max steps.

---

## 2. Call tools directly over stdio (no LLM)

List what the server exposes:

```powershell
python -m app.main --list-tools --show-prompt
```

Expected: 4 tools, resource `docs://index` listing 3 documents, and the
`research_brief` prompt.

Successful document search:

```powershell
python scripts/call_tool.py search_documents --arg query="oauth token" --arg limit=2
```

Expected: `is_error=False` and matches in `oauth-notes.md` / `mcp-notes.md`.

Read a document:

```powershell
python scripts/call_tool.py read_document --arg path=mcp-notes.md --arg max_chars=500
```

Expected: `is_error=False` and the file contents.

Web search (needs internet, no API key):

```powershell
python scripts/call_tool.py web_search --arg query="model context protocol" --arg max_results=3
```

Fetch a page:

```powershell
python scripts/call_tool.py fetch_url --arg url=https://modelcontextprotocol.io --arg max_chars=500
```

### Error / safety checks (each should print `is_error=True`)

```powershell
# out-of-range input, with a message the model could act on
python scripts/call_tool.py search_documents --arg query=oauth --arg limit=99

# path traversal is refused
python scripts/call_tool.py read_document --arg path=../secret.md

# unsupported URL scheme
python scripts/call_tool.py fetch_url --arg url=file:///etc/passwd

# SSRF guard: localhost is refused
python scripts/call_tool.py fetch_url --arg url=http://127.0.0.1:8000/
```

Expected messages include `limit must be between 1 and 10`,
`Access denied`, `Unsupported URL scheme`, and `private or local address`.

> `--arg KEY=VALUE` exists because PowerShell 5.1 mangles double quotes inside
> JSON arguments. `--args '{"query": "oauth"}'` also works in cmd.exe or bash.

---

## 3. MCP Inspector (required workflow check)

> Use `npx.cmd` on Windows if PowerShell blocks `npx.ps1`.

List tools:

```powershell
npx.cmd -y @modelcontextprotocol/inspector --cli --cwd . --method tools/list --format text -- python -m server.main
```

Expected: JSON with all 4 tools and their `inputSchema`.

Call a tool:

```powershell
npx.cmd -y @modelcontextprotocol/inspector --cli --cwd . --method tools/call --tool-name search_documents --tool-arg query=oauth limit=2 --format text -- python -m server.main
```

Expected: `"isError": false` and ranked results.

Read the resource:

```powershell
npx.cmd -y @modelcontextprotocol/inspector --cli --cwd . --method resources/read --uri docs://index --format text -- python -m server.main
```

Schema portability check:

```powershell
npx.cmd -y @modelcontextprotocol/inspector --cli --cwd . --method tools/list --strict --format text -- python -m server.main
```

Expected: exit code `0` and no error-severity schema issues.

---

## 4. Live agent demo over stdio (uses Gemini)

```powershell
python demo.py
```

Expected, roughly:

```
  -> search_documents(query='MCP stdio servers logging')
     [ok] Found 3 document(s) ...
  -> read_document(path='mcp-notes.md')
     [ok] ...
  -> web_search(query='MCP specification version')
     [ok] ...
A: ... log to stderr ... (Source: mcp-notes.md)
   ... 2026-07-28 (Source: https://modelcontextprotocol.io/...)
```

At least **two tools** must run. If you see `GEMINI_API_KEY is not set`, fix
`.env` and retry.

You can also ask your own question:

```powershell
python -m app.main "What do my notes say about authorization, and what is the current MCP spec version?"
```

Interactive mode: `python -m app.main`, then type questions, `exit` to quit.

---

## 5. Streamable HTTP + bearer auth + scopes

Your `.env` already contains **real generated tokens**:

```
MCP_AUTH_TOKENS={"<docs-only-token>": ["docs:read"], "<full-token>": ["docs:read", "web:read"]}
MCP_TOKEN=<full-token>
```

Open `.env` to copy them: the token mapped to `["docs:read"]` is the **docs
token**, the one mapped to `["docs:read", "web:read"]` is the **full token**.
`MCP_TOKEN` is already the full token, so the CLI can connect without `--token`.

### 5.1 (Optional) Rotate the tokens

```powershell
python scripts/make_tokens.py
```

Replace the `MCP_AUTH_TOKENS` line in `.env` with the printed one, and optionally
set `MCP_TOKEN` to the full token. Restart the server afterwards.

### 5.2 Start the HTTP server (terminal 1)

```powershell
python -m server.main --transport streamable-http --port 8000
```

Expected on **stderr**:

```
Scoped bearer auth enabled for 2 token(s); scopes: docs:read, web:read
Starting research-assistant MCP server on http://127.0.0.1:8000/mcp
Uvicorn running on http://127.0.0.1:8000
```

Leave it running. Open a second terminal for the next steps.

### 5.3 List tools with each token (terminal 2)

```powershell
# full token: 4 tools
python -m app.main --transport http --url http://127.0.0.1:8000/mcp --token <FULL_TOKEN> --list-tools

# docs-only token: only search_documents + read_document
python -m app.main --transport http --url http://127.0.0.1:8000/mcp --token <DOCS_TOKEN> --list-tools
```

### 5.4 Scoped access is enforced on the call, not just the list

```powershell
python scripts/call_tool.py --transport http --url http://127.0.0.1:8000/mcp --token <DOCS_TOKEN> web_search --arg query=mcp
```

Expected:

```
web_search -> is_error=True
Error executing tool web_search: Permission denied: searching the web requires
the 'web:read' scope. This token has ['docs:read']. ...
```

The docs-only token **can** still use document tools:

```powershell
python scripts/call_tool.py --transport http --url http://127.0.0.1:8000/mcp --token <DOCS_TOKEN> search_documents --arg query=oauth
```

### 5.5 Authentication is required

```powershell
# no token -> 401 and a clean error
# (--no-token overrides the MCP_TOKEN value loaded from .env)
python scripts/call_tool.py --transport http --url http://127.0.0.1:8000/mcp --no-token --list

# wrong token -> 401
python scripts/call_tool.py --transport http --url http://127.0.0.1:8000/mcp --token definitely-wrong --list
```

Expected: `Connection or protocol error: Server returned an error response`
and `401 Unauthorized` in the log lines.

Also verify the server refuses to run HTTP with no auth at all:

```powershell
$env:MCP_AUTH_TOKENS=''
$env:MCP_API_TOKEN=''
python -m server.main --transport streamable-http --port 8001
```

Expected: exit code `1` and
`The Streamable HTTP transport requires authentication.`

### 5.6 Live agent demo over HTTP (full token)

`MCP_TOKEN` already holds the full token, so `--token` is optional here:

```powershell
python -m app.main --transport http --url http://127.0.0.1:8000/mcp "Using my local notes, summarize how MCP stdio servers should handle logging. Then search the web for the current MCP specification version. Cite every source."
```

Expected: tool calls for `search_documents`, `read_document`, and `web_search`,
then a cited answer. This proves the whole chain: LLM -> custom client ->
authenticated HTTP server -> tools -> results -> LLM.

### 5.7 Inspector over HTTP with a bearer token

```powershell
npx.cmd -y @modelcontextprotocol/inspector --cli --server-url http://127.0.0.1:8000/mcp --header "Authorization: Bearer <FULL_TOKEN>" --method tools/list --format text
```

Expected: all 4 tools. With `<DOCS_TOKEN>`: only 2 tools.

> The Inspector checks `tools/list` before calling, so a hidden tool reports
> `tool_not_found` there. Use `scripts/call_tool.py` (5.4) to see the server's
> `Permission denied` message.

### 5.8 Stop the server

In terminal 1 press `Ctrl+C`. Optional cleanup:

```powershell
Remove-Item Env:MCP_AUTH_TOKENS -ErrorAction SilentlyContinue
```

---

## 6. What "pass" looks like

| Check | Pass condition |
| --- | --- |
| `python -m pytest` | `55 passed` |
| Inspector `tools/list` | 4 tools with JSON schemas |
| Inspector `--strict` | exit code 0 |
| stdio demo | >= 2 tools, cited answer |
| HTTP full token | 4 tools, agent works |
| HTTP docs token | 2 tools, `web_search` -> `Permission denied` |
| HTTP no/wrong token | 401, no tools listed |
| HTTP without auth config | server exits with code 1 |
| traversal / SSRF tests | `is_error=True` with a clear message |

---

## 7. Troubleshooting

| Symptom | Fix |
| --- | --- |
| `GEMINI_API_KEY is not set` | Add it to `.env` in the project root. |
| `npx.ps1 cannot be loaded` | Use `npx.cmd` instead of `npx`. |
| JSON arguments mangled in PowerShell | Use `--arg key=value` (see step 2). |
| `401 Unauthorized` | Token is not in `MCP_AUTH_TOKENS`, or `.env` was not reloaded; restart the server after editing `.env`. |
| Only 2 tools listed | You are using the docs-only token; that is correct scoped behavior. |
| `Address already in use` | Use another `--port`, and update `--url`. |
| Web search fails | DuckDuckGo can rate-limit; retry once or answer from local docs. |
| Server prints nothing to stdout | Correct: stdio mode logs to stderr and reserves stdout for JSON-RPC. |
