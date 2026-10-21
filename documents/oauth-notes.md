# OAuth and Authorization Notes

Authentication answers "who are you?", authorization answers "what can you do?".

- Authenticate first, then authorize every tool call.
- A local stdio server uses environment credentials.
- A remote HTTP server uses OAuth 2.1: the client gets a token and the server
  validates it.

## When a server needs authorization

- It reads user-specific data.
- Actions need explicit user consent.
- You must audit who did what.
- Per-user rate limits or enterprise access controls apply.

## Least privilege

A leaked token or a wrong tool call should do as little harm as possible.
Scope tokens narrowly, store them encrypted, and never log secrets or full
tokens. Redact credentials from error messages before they reach the model.

## Client-side notes

A custom agent owns its own config: per-user tokens stored encrypted, and the
agent decides which tools each user can see. Desktop hosts instead show an
approval prompt and read credentials from environment variables in the config
file.
