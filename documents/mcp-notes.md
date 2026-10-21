# MCP Working Notes

Model Context Protocol (MCP) connects LLM applications to external tools and
data. It turns N x M custom integrations into N + M: each model implements one
MCP client, each system exposes one MCP server.

## Transports

- **stdio**: the host launches the server as a local subprocess. Credentials
  come from environment variables. Use it for desktop hosts like Claude Desktop
  and Cursor.
- **Streamable HTTP**: the server is remote and serves many clients. Use a
  Bearer token or OAuth 2.1.

Both transports carry the same JSON-RPC 2.0 messages, so a tool behaves the
same over either one.

## Server primitives

- **Tools**: functions the AI app can call to take action.
- **Resources**: data that gives the app context.
- **Prompts**: reusable templates that structure interactions.

Discover with `*/list`, fetch with `*/get`, and run tools with `tools/call`.

## Hard rule for stdio servers

Never print to stdout. stdout carries the JSON-RPC stream. Log to stderr or a
file instead, or the protocol is corrupted.

## Request flow

1. `server/discover` - the server returns versions and capabilities.
2. `tools/list` - names, descriptions, and JSON Schema inputs.
3. `tools/call` - send a name and arguments, get content back.
4. `list_changed` - opt in with `subscriptions/listen`, then list again.
