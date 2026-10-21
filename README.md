# Research Assistant (MCP server + MCP client)

**Use case (in one sentence):** A command-line research assistant that answers a
developer's or researcher's questions by searching their own local notes and the
public web, returning every answer with citations. It is built as a real
**MCP server** plus a **user-defined MCP client** that plugs the server's tools
into a Gemini LLM through an agent loop.

```
you ──> CLI (app/main.py)
          │  agent loop (app/agent.py)
          │      ├── list tools   ─┐
          │      ├── call Gemini   │  our MCP client (client/mcp_client.py)
          │      └── run tool  <───┘        │  stdio  or  Streamable HTTP + bearer token
          │                                 ▼
          └──────────────────────> MCP server (server/main.py)
                                       ├── search_documents / read_document  (local files)
                                       └── web_search / fetch_url            (DuckDuckGo + HTTP)
```

## Why MCP here

Instead of hard-wiring "read files" and "search the web" into the app, the app
exposes them as an MCP server. The same server can be dropped into Claude
Desktop, Cursor, or any other MCP host, and the app talks to it only through the
protocol. The LLM never touches the server: the agent loop passes messages
between them.

---

## Repository layout

```
mcp-research-assistant/
├── server/
│   ├── main.py            # MCP server: tools, resource, prompt; stdio or HTTP
│   ├── auth.py            # scoped bearer tokens, tools/list filtering
│   ├── config.py          # env-driven settings, stderr-only logging
│   └── tools/
│       ├── docs.py        # search_documents, read_document  (+ path guards)
│       └── web.py         # web_search, fetch_url            (+ SSRF guards)
├── client/
│   └── mcp_client.py      # our own MCP client: stdio + Streamable HTTP
├── app/
│   ├── agent.py           # agent loop: list -> LLM -> tool calls -> repeat
│   └── main.py            # CLI entry point
├── scripts/
│   ├── make_tokens.py     # generates scoped demo tokens
│   └── call_tool.py       # call one tool directly, no LLM needed
├── documents/             # sample notes the doc tools read
├── tests/                 # 55 tests (tools, safety, auth, HTTP, agent, stdio)
├── demo.py                # canned demo question (uses >= 2 tools)
├── DEMO.md                # 2-minute recording script + real transcript
├── TESTING.md             # step-by-step manual test guide
├── requirements.txt
├── .env.example
├── README.md
└── SUMMARY.md
```

---

## Setup

Requires **Python 3.10+** and, only for the optional Inspector step, **Node.js**.

```bash
# 1. Create and activate a virtual environment
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

# 2. Install dependencies (mcp 2.x, google-genai, ddgs, httpx, ...)
pip install -r requirements.txt

# 3. Configure secrets - never commit .env
copy .env.example .env      # Windows
cp .env.example .env        # macOS / Linux
# edit .env and set GEMINI_API_KEY (free: https://aistudio.google.com/apikey)

# 4. Optional: replace the example auth tokens with real random ones
python scripts/make_tokens.py
```


`.env` values:

| Variable              | Required      | Default            | Purpose                                              |
| --------------------- | ------------- | ------------------ | ---------------------------------------------------- |
| `GEMINI_API_KEY`      | for the agent | -                  | LLM key. Read from env, never in code.               |
| `GEMINI_MODEL`        | no            | `gemini-2.5-flash` | Model name.                                          |
| `DOCS_DIR`            | no            | `./documents`      | Folder the document tools may read.                  |
| `MAX_SEARCH_RESULTS`  | no            | `10`               | Upper bound for `max_results` / `limit`.             |
| `MAX_FETCH_CHARS`     | no            | `8000`             | Upper bound for fetch/read sizes.                    |
| `LOG_LEVEL`           | no            | `INFO`             | `DEBUG` for verbose **stderr** logging.              |
| `HTTP_USER_AGENT`     | no            | built-in           | User-Agent for `fetch_url`.                          |
| `MCP_AUTH_TOKENS`     | for HTTP      | -                  | JSON map `{"<token>": ["docs:read", "web:read"]}`.   |
| `MCP_API_TOKEN`       | for HTTP      | -                  | Single-token alternative to `MCP_AUTH_TOKENS`.       |
| `MCP_SCOPES`          | no            | all scopes         | Scopes for `MCP_API_TOKEN`.                          |
| `MCP_TRANSPORT`       | no            | `stdio`            | Server transport default.                            |
| `MCP_HOST` / `MCP_PORT` / `MCP_PATH` | no | `127.0.0.1` / `8000` / `/mcp` | HTTP bind settings.        |
| `MCP_PUBLIC_URL`      | no            | -                  | Public base URL when behind a proxy.                 |
| `MCP_CLIENT_TRANSPORT`| no            | `stdio`            | CLI client transport default.                        |
| `MCP_URL`             | no            | `http://127.0.0.1:8000/mcp` | CLI HTTP endpoint.                          |
| `MCP_TOKEN`           | for HTTP      | -                  | CLI bearer token (preferred over `--token`).         |

Web search uses **DuckDuckGo** through `ddgs`, so it needs **no API key**.

---

## Run

### stdio (local, easiest)

```bash
# Ask one question
python -m app.main "How does MCP handle authorization in remote servers?"

# Interactive session
python -m app.main

# Inspect the server without an LLM (no API key needed)
python -m app.main --list-tools --show-prompt

# Canned demo that needs a local-doc tool and a web tool
python demo.py
```

### Streamable HTTP (remote, authenticated)

```bash
# 1. Generate tokens and put MCP_AUTH_TOKENS in .env
python scripts/make_tokens.py

# 2. Start the server (refuses to start if no tokens are configured)
python -m server.main --transport streamable-http --port 8000

# 3. In another terminal, point the CLI at it
#    (MCP_TOKEN is read from .env or the environment)
python -m app.main --transport http --url http://127.0.0.1:8000/mcp \
    "Search my notes for OAuth, then check the web for the current MCP spec."

# List only what this token may use
python -m app.main --transport http --url http://127.0.0.1:8000/mcp --list-tools
```

> HTTP is for localhost/demo use here. For a real remote deployment, terminate
> TLS at a proxy and set `MCP_PUBLIC_URL=https://...`.

### Test the server with the MCP Inspector (before wiring the client)

```bash
# list tools
npx -y @modelcontextprotocol/inspector --cli --cwd . --method tools/list --format text -- python -m server.main

# call a tool
npx -y @modelcontextprotocol/inspector --cli --cwd . --method tools/call \
    --tool-name search_documents --tool-arg query=oauth limit=2 --format text -- python -m server.main

# read the resource / prompt
npx -y @modelcontextprotocol/inspector --cli --cwd . --method resources/read --uri docs://index --format text -- python -m server.main
```

> On Windows PowerShell, use `npx.cmd` if script execution is disabled.

---

## Tools and required scopes

Every tool has a unique name, a description that says **what it does and when to
use it**, typed inputs (JSON Schema generated from Python type hints), and it
returns failures as an `isError` result whose text tells the model how to
recover.

| Tool | Inputs | Scope |
| --- | --- | --- |
| `search_documents` | `query: str`, `limit: int = 5` | `docs:read` |
| `read_document` | `path: str`, `max_chars: int = 6000` | `docs:read` |
| `web_search` | `query: str`, `max_results: int = 5` | `web:read` |
| `fetch_url` | `url: str`, `max_chars: int = 4000` | `web:read` |

### 1. `search_documents(query, limit=5)`

Search the local docs folder (case-insensitive, ranked by term frequency).

```json
{ "query": "oauth token validation", "limit": 3 }
```
```
Found 2 document(s) for 'oauth token validation'. ...
- oauth-notes.md (score 7)
    L7: - Authenticate first, then authorize every tool call. ...
```

### 2. `read_document(path, max_chars=6000)`

Read one document in full, with truncation.

```json
{ "path": "mcp-notes.md", "max_chars": 500 }
```
Error example (returned to the model, not raised to the user):
```json
{ "isError": true, "content": "Access denied: '../../etc/passwd' is outside the documents folder. ..." }
```

### 3. `web_search(query, max_results=5)`

Anonymous DuckDuckGo search returning titles, URLs, and snippets.

```json
{ "query": "MCP specification version", "max_results": 3 }
```

### 4. `fetch_url(url, max_chars=4000)`

Fetch a public page as plain text (HTML stripped). Rejects non-http(s) schemes,
embedded credentials, and any host that resolves to a private/loopback address.

```json
{ "url": "https://modelcontextprotocol.io/specification", "max_chars": 2000 }
```

### Resource: `docs://index` (scope `docs:read`)

Lists every readable document with its size. Readable with `resources/read`,
e.g. via the Inspector (see above).

### Prompt: `research_brief(topic, audience="a technical reader")`

A reusable template the host can offer to users: search local docs, then the
web, then produce a cited brief.

### Example of the model recovering from a bad call

```
model: search_documents(query="oauth", limit=99)
result: isError -> "limit must be between 1 and 10, got 99."
model: search_documents(query="oauth", limit=3)   # corrected, succeeds
```

### Example of scoped access over HTTP

```
docs-only token -> tools/list shows only search_documents + read_document
docs-only token -> web_search  => isError "Permission denied: searching the web
                                  requires the 'web:read' scope ..."
full token      -> all four tools
```

---

## Stretch goals (all implemented)

- [x] **Streamable HTTP transport** instead of stdio (`--transport streamable-http`).
- [x] **Authentication and scoped access**: bearer tokens from env, per-tool
      `docs:read` / `web:read` scopes, scoped `tools/list`, fail-fast when HTTP
      starts without auth.
- [x] **Resource and prompt** in addition to tools (`docs://index`,
      `research_brief`).
- [x] **User-defined MCP client** (stdio *and* HTTP) instead of a built-in host.

---

## Safety

- **Authentication**: the HTTP transport refuses to start without tokens, and
  rejects missing/unknown/expired bearer tokens.
- **Authorization**: every tool checks its scope; `tools/list` only shows tools
  the token can use. Tokens are matched by exact value; logs only show a
  hashed client id, never a token.
- **Input validation** on every tool: empty/oversized strings, out-of-range
  numbers, wrong types, and null bytes are rejected with a helpful message.
- **Path traversal guard**: document paths are resolved and must stay inside
  `DOCS_DIR`; `..`, absolute paths, and disallowed extensions are refused.
- **SSRF guard**: `fetch_url` refuses non-http(s) schemes, credentials in the
  URL, and private/loopback/link-local/reserved addresses.
- **Secrets**: the Gemini key and MCP tokens come only from the environment
  (`.env` is gitignored); they are never logged or embedded in tool output.
- **stdio hygiene**: the server never writes to **stdout** (that would corrupt
  the JSON-RPC stream); all logging goes to **stderr**.
- **Bounded agent loop**: `--max-steps` (default 8) stops runaway tool use.

---

## Tests

```bash
python -m pytest        # 55 tests, no LLM call required
```

Covers:

- tool behaviour and argument validation,
- path-traversal and SSRF rejection,
- token parsing, scope enforcement, wildcard scopes, `tools/list` filtering,
- real stdio client <-> server round trip,
- real Streamable HTTP round trip with valid, missing, invalid, and
  under-scoped tokens, plus fail-fast startup without auth,
- the agent loop (tool call, error recovery, unknown tool, max steps).

See **TESTING.md** for a step-by-step manual checklist.

See **DEMO.md** for the 2-minute recording script and the real demo transcript
(stdio: search + read + web search; HTTP: auth and scopes).
