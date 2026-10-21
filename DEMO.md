# Demo (2 minutes)

This file is both the **recording script** and the **fallback transcript** for
the required deliverable:

> A short demo showing the application using at least two tools to complete a task.

The demo must prove, on screen:

1. the app is an AI agent (Gemini) talking to an **MCP server through our own
   MCP client**;
2. it uses **at least two tools** in one task (`search_documents`,
   `read_document`, `web_search`);
3. the final answer **cites** the local document and the web URL;
4. *(bonus)* the HTTP transport enforces **authentication and scopes**.

---

## Before you record

```powershell
cd C:\Users\shime\Desktop\1\icog\training10\mcp-research-assistant

# stop any stale server on port 8000
Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue |
  ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }

# confirm you are ready (4 tools should print)
python -m app.main --list-tools

# clear the screen and make the font readable
Clear-Host
```

- Record only the terminal window (Win+G, OBS, or PowerPoint screen recording).
- **Never show `.env`** on screen; copy the docs token beforehand if you need it.
- 2 terminals: one for the agent (stdio part needs one), one for the HTTP server.

---

## Take 1 - stdio demo (about 75 seconds)

**0:00-0:10** - Show the tools.

```powershell
python -m app.main --list-tools
```

Say: *"The server exposes four tools: two for local documents and two for the
web. It also has a resource and a prompt."*

**0:10-1:00** - Run the canned task.

```powershell
python demo.py
```

Say while it runs: *"The agent lists the tools, converts their schemas for
Gemini, and the model chooses search_documents. The result comes back through
our MCP client, the model asks to read the file, then it searches the web."*

**1:00-1:15** - Point at the answer.

Say: *"The answer cites mcp-notes.md and the specification URL. Three tools were
used, through the MCP server."*

Expected transcript (this is the actual output from this repo):

```
Q: Using my local notes, summarize how MCP stdio servers should handle logging.
   Then search the web for the latest MCP specification version and tell me
   which version is current. Cite every source you used.
  -> search_documents(query='MCP stdio servers logging')
     [ok] Found 3 document(s) for 'MCP stdio servers logging'. ...
  -> read_document(path='mcp-notes.md')
     [ok] # mcp-notes.md
  -> web_search(query='latest MCP specification version')
     [ok] Top 5 web result(s) for 'latest MCP specification version'. ...

A: Based on your local notes, MCP stdio servers should **never print to stdout**
   because stdout carries the JSON-RPC stream. Instead, logging should be
   directed to **stderr or a file** to prevent corruption of the protocol
   (Source: `mcp-notes.md`).
   The latest MCP specification version is **2026-07-28**
   (Source: https://modelcontextprotocol.io/specification/2026-07-28).
```

---

## Take 2 - HTTP + auth + scopes (about 45 seconds, optional but strong)

**1:15-1:20** - Terminal 1: start the authenticated server.

```powershell
python -m server.main --transport streamable-http --port 8000
```

Say: *"The HTTP transport requires bearer tokens; it refuses to start without
them."*

**1:20-1:35** - Terminal 2: same agent, remote transport.

```powershell
python -m app.main --transport http --url http://127.0.0.1:8000/mcp --list-tools
```

Say: *"MCP_TOKEN from the environment is the full-scope token, so all four tools
are available."*

**1:35-1:50** - Scope enforcement with the docs-only token.

```powershell
python scripts/call_tool.py --transport http --url http://127.0.0.1:8000/mcp `
  --token <DOCS_TOKEN_FROM_ENV> web_search --arg query=mcp
```

Say: *"This token only has docs:read. It sees two tools, and the server refuses
the web tool with a clear permission error."*

Expected:

```
Transport: streamable-http
  - search_documents(query, limit)
  - read_document(path, max_chars)

web_search -> is_error=True
Error executing tool web_search: Permission denied: searching the web requires
the 'web:read' scope. This token has ['docs:read']. ...
```

**1:50-2:00** - No token at all.

```powershell
python scripts/call_tool.py --transport http --url http://127.0.0.1:8000/mcp --no-token --list
```

Say: *"Without a token the server returns 401. That is authentication plus
scoped authorization."*

Expected:

```
... HTTP Request: POST http://127.0.0.1:8000/mcp "HTTP/1.1 401 Unauthorized"
Connection or protocol error: Server returned an error response
```

Stop the server with `Ctrl+C` in terminal 1.

---

## Optional third take - error recovery (20 seconds)

```powershell
python scripts/call_tool.py search_documents --arg query=oauth --arg limit=99
python scripts/call_tool.py read_document --arg path=../secret.md
```

Say: *"Failures come back as results, not crashes, so the model can correct
itself. Path traversal is refused."*

Expected error text includes `limit must be between 1 and 10` and
`Access denied: ... outside the documents folder`.

---

## If you cannot record a video

Submit this file together with `README.md` and `SUMMARY.md`. The transcript
above is the real output of the commands; the automated suite
(`python -m pytest` -> 55 passed) independently verifies the same behavior.

## What each part demonstrates

| Requirement | Where it appears |
| --- | --- |
| Agent loop: list -> LLM -> tools -> repeat | Take 1, `app/agent.py` |
| At least two tools used in one task | Take 1: search + read + web search |
| Citations | Take 1 final answer |
| Custom MCP client (not a built-in host) | Takes 1 and 2, `client/mcp_client.py` |
| Streamable HTTP transport | Take 2 |
| Authentication + scoped access | Take 2, docs-only token and 401 |
| Errors as recoverable results | Take 3 |
| Resource + prompt | `python -m app.main --list-tools --show-prompt` |
