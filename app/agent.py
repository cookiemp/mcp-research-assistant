"""The agent loop: list MCP tools, call the LLM, run tool calls, repeat.

The LLM never talks to the MCP server directly. This code is the waiter that
passes messages between the customer (the LLM) and the kitchen (the server).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from google import genai
from google.genai import types as genai_types
from mcp import types as mcp_types

from client.mcp_client import MCPClient, tool_to_text

logger = logging.getLogger("research_assistant.agent")

SYSTEM_INSTRUCTION = """\
You are a research assistant. Answer questions using the tools you are given.

- Prefer the user's local documents for questions about their own notes.
- Use web tools for anything current or missing from the local documents.
- You may call several tools in one turn. After each result, decide whether you
  have enough to answer.
- Always cite the document path or URL behind each claim.
- If a tool returns an error, read the message and retry with fixed arguments
  or choose a different tool. Never invent tool output.
"""


@dataclass
class AgentEvent:
    """A single observable step in the agent loop, for logging and the CLI."""

    kind: str  # "tool_call" | "tool_result" | "answer"
    text: str = ""
    tool: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)
    is_error: bool = False


EventCallback = Callable[[AgentEvent], None]


class MaxStepsExceeded(RuntimeError):
    """Raised when the model keeps calling tools past the step limit."""


def tools_to_gemini(tools: list[mcp_types.Tool]) -> genai_types.Tool:
    """Convert MCP tool schemas into Gemini function declarations."""
    declarations = []
    for tool in tools:
        declarations.append(
            genai_types.FunctionDeclaration(
                name=tool.name,
                description=tool.description or "",
                parameters_json_schema=tool.input_schema,
            )
        )
    return genai_types.Tool(function_declarations=declarations)


class ResearchAgent:
    """Drives one MCP client and one Gemini model in a tool-calling loop."""

    def __init__(
        self,
        client: MCPClient,
        *,
        model: str = "gemini-2.5-flash",
        api_key: str | None = None,
        max_steps: int = 8,
        on_event: EventCallback | None = None,
        llm_client: Any | None = None,
    ) -> None:
        self.client = client
        self.model = model
        self.max_steps = max_steps
        self.on_event = on_event
        if llm_client is not None:
            self._genai = llm_client
        else:
            self._genai = genai.Client(api_key=api_key) if api_key else genai.Client()
        self._tools: list[mcp_types.Tool] = []

    def _emit(self, event: AgentEvent) -> None:
        if self.on_event:
            self.on_event(event)

    async def run(self, question: str) -> str:
        """Answer a question, calling tools as needed, and return the final text."""
        self._tools = await self.client.list_tools()
        if not self._tools:
            raise RuntimeError("The MCP server exposed no tools.")

        config = genai_types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            tools=[tools_to_gemini(self._tools)],
            temperature=0.2,
        )
        contents: list[genai_types.Content] = [
            genai_types.Content(
                role="user", parts=[genai_types.Part.from_text(text=question)]
            )
        ]

        for step in range(1, self.max_steps + 1):
            response = self._genai.models.generate_content(
                model=self.model, contents=contents, config=config
            )
            calls = list(response.function_calls or [])

            if not calls:
                answer = response.text or "(the model returned no text)"
                self._emit(AgentEvent(kind="answer", text=answer))
                return answer

            if response.candidates and response.candidates[0].content:
                contents.append(response.candidates[0].content)

            response_parts: list[genai_types.Part] = []
            for call in calls:
                arguments = dict(call.args or {})
                self._emit(
                    AgentEvent(
                        kind="tool_call",
                        tool=call.name or "",
                        arguments=arguments,
                        text=f"{call.name}({arguments})",
                    )
                )
                result = await self._run_tool_call(call)
                response_parts.append(result)
                await _yield_to_event_loop()

            contents.append(
                genai_types.Content(role="user", parts=response_parts)
            )
            logger.debug("Completed agent step %d of %d", step, self.max_steps)

        raise MaxStepsExceeded(
            f"The model still wanted tools after {self.max_steps} steps. "
            "Raise max_steps or simplify the question."
        )

    async def _run_tool_call(self, call: genai_types.FunctionCall) -> genai_types.Part:
        """Run one tool call and package its result (or error) for the model."""
        name = call.name or ""
        arguments = dict(call.args or {})

        if name not in {t.name for t in self._tools}:
            message = (
                f"Unknown tool {name!r}. Available tools: "
                f"{', '.join(t.name for t in self._tools)}."
            )
            self._emit(AgentEvent(kind="tool_result", tool=name, text=message, is_error=True))
            return _function_response(call, message, is_error=True)

        try:
            result = await self.client.call_tool(name, arguments)
        except Exception as exc:  # transport-level failure
            message = f"Tool {name!r} crashed: {exc}. Try a different tool."
            logger.exception("Tool %s raised", name)
            self._emit(AgentEvent(kind="tool_result", tool=name, text=message, is_error=True))
            return _function_response(call, message, is_error=True)

        text = tool_to_text(result)
        if result.is_error:
            text = f"ERROR: {text}\nFix the arguments and try again, or use another tool."
        self._emit(
            AgentEvent(kind="tool_result", tool=name, text=text, is_error=bool(result.is_error))
        )
        return _function_response(call, text, is_error=bool(result.is_error))


def _function_response(
    call: genai_types.FunctionCall, text: str, *, is_error: bool
) -> genai_types.Part:
    """Build the function-response part sent back to Gemini."""
    response = genai_types.FunctionResponse(
        id=call.id,
        name=call.name,
        response={"result": text, "is_error": is_error},
    )
    return genai_types.Part(function_response=response)


async def _yield_to_event_loop() -> None:
    """Give the stdio transport a chance to flush between tool calls."""
    await asyncio.sleep(0)
