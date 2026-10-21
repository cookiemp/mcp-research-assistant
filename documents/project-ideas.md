# Project Ideas

- **AskMyDocs**: a CLI research assistant over a local notes folder plus web
  search. Answers questions with citations.
- **Ticket triage agent**: reads an issue tracker and drafts replies.
- **Release notes bot**: watches a repo and summarizes merged PRs.
- **Home inventory**: query a local SQLite database of household items.

## Scoring rubric reminders

- Working integration: the app calls the server's tools through an MCP client.
- Tool design: clear names, descriptions, input schemas, and error handling.
- Client quality: the agent loop lists tools, calls the LLM, runs tools, and
  returns results.
- Safety: validate inputs and keep secrets out of code and logs.
- Clarity: the README lets someone else run the project.
