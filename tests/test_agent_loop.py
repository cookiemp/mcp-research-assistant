"""Tests for the agent loop using a scripted fake LLM and fake MCP client.

No network and no API key are required.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from google.genai import types as genai_types
from mcp import types as mcp_types

from app.agent import MaxStepsExceeded, ResearchAgent, tools_to_gemini


class FakeModels:
    def __init__(self, scripted: list[Any]) -> None:
        self._scripted = list(scripted)
        self.requests: list[list[Any]] = []

    def generate_content(self, *, model: str, contents: list, config: Any) -> Any:
        self.requests.append(contents)
        if not self._scripted:
            raise AssertionError("FakeModels ran out of scripted responses")
        return self._scripted.pop(0)


class FakeLLM:
    def __init__(self, scripted: list[Any]) -> None:
        self.models = FakeModels(scripted)


class FakeMCPClient:
    def __init__(self, tools: list[mcp_types.Tool], results: dict[str, Any]) -> None:
        self._tools = tools
        self._results = results
        self.calls: list[tuple[str, dict]] = []

    async def list_tools(self) -> list[mcp_types.Tool]:
        return self._tools

    async def call_tool(self, name: str, arguments: dict | None = None) -> Any:
        self.calls.append((name, arguments or {}))
        if name not in self._results:
            raise AssertionError(f"unexpected tool call {name}")
        return self._results[name]


def make_tool(name: str = "search_documents") -> mcp_types.Tool:
    return mcp_types.Tool(
        name=name,
        description="Search local documents.",
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    )


def text_result(text: str, is_error: bool = False) -> mcp_types.CallToolResult:
    return mcp_types.CallToolResult(
        content=[mcp_types.TextContent(type="text", text=text)], is_error=is_error
    )


def answer_response(text: str) -> Any:
    content = genai_types.Content(
        role="model", parts=[genai_types.Part.from_text(text=text)]
    )
    return SimpleNamespace(function_calls=[], candidates=[SimpleNamespace(content=content)], text=text)


def tool_call_response(name: str, args: dict, call_id: str = "call-1") -> Any:
    call = genai_types.FunctionCall(id=call_id, name=name, args=args)
    content = genai_types.Content(
        role="model", parts=[genai_types.Part(function_call=call)]
    )
    return SimpleNamespace(
        function_calls=[call], candidates=[SimpleNamespace(content=content)], text=None
    )


def build_agent(scripted: list[Any], client: FakeMCPClient, **kwargs: Any):
    events = []
    agent = ResearchAgent(
        client,
        llm_client=FakeLLM(scripted),
        on_event=events.append,
        **kwargs,
    )
    return agent, events


def test_tools_to_gemini_maps_schema() -> None:
    tool = tools_to_gemini([make_tool("web_search")])
    declaration = tool.function_declarations[0]
    assert declaration.name == "web_search"
    assert declaration.parameters_json_schema["required"] == ["query"]


async def test_answers_without_tools() -> None:
    client = FakeMCPClient([make_tool()], {})
    agent, events = build_agent([answer_response("No tools needed.")], client)

    answer = await agent.run("hello")
    assert answer == "No tools needed."
    assert client.calls == []
    assert events[-1].kind == "answer"


async def test_runs_a_tool_then_answers() -> None:
    client = FakeMCPClient(
        [make_tool()], {"search_documents": text_result("found: mcp.md")}
    )
    agent, events = build_agent(
        [
            tool_call_response("search_documents", {"query": "mcp"}),
            answer_response("According to mcp.md, MCP connects models to tools."),
        ],
        client,
    )

    answer = await agent.run("what do my notes say about mcp?")
    assert client.calls == [("search_documents", {"query": "mcp"})]
    assert "mcp.md" in answer

    kinds = [e.kind for e in events]
    assert kinds == ["tool_call", "tool_result", "answer"]
    assert events[1].is_error is False


async def test_tool_error_is_returned_to_model_for_recovery() -> None:
    client = FakeMCPClient(
        [make_tool()],
        {"search_documents": text_result("limit must be between 1 and 10", is_error=True)},
    )
    fake_llm = FakeLLM(
        [
            tool_call_response("search_documents", {"query": "x", "limit": 99}),
            answer_response("Recovered after the error."),
        ]
    )
    agent = ResearchAgent(client, llm_client=fake_llm)
    assert await agent.run("bad args") == "Recovered after the error."

    second_turn = fake_llm.models.requests[1]
    function_response = second_turn[-1].parts[0].function_response
    assert function_response.response["is_error"] is True
    assert "ERROR" in function_response.response["result"]


async def test_unknown_tool_does_not_crash() -> None:
    client = FakeMCPClient([make_tool()], {})
    agent = ResearchAgent(
        client,
        llm_client=FakeLLM(
            [
                tool_call_response("delete_everything", {"path": "/"}),
                answer_response("I will not do that."),
            ]
        ),
    )
    assert await agent.run("delete stuff") == "I will not do that."
    assert client.calls == []


async def test_max_steps_is_enforced() -> None:
    client = FakeMCPClient([make_tool()], {"search_documents": text_result("again")})
    endless = [
        tool_call_response("search_documents", {"query": "loop"}) for _ in range(5)
    ]
    agent = ResearchAgent(client, llm_client=FakeLLM(endless), max_steps=3)
    with pytest.raises(MaxStepsExceeded):
        await agent.run("loop forever")


async def test_no_tools_raises() -> None:
    client = FakeMCPClient([], {})
    agent = ResearchAgent(client, llm_client=FakeLLM([]))
    with pytest.raises(RuntimeError, match="no tools"):
        await agent.run("anything")
