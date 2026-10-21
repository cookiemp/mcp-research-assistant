"""Tests for the local web demo page (no network, no API key)."""

from __future__ import annotations

from typing import Any

from starlette.testclient import TestClient

from app.agent import AgentEvent
from app.web import create_app


class FakeClient:
    async def __aenter__(self) -> "FakeClient":
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False


class FakeAgent:
    def __init__(
        self,
        on_event: Any,
        *,
        answer: str = "Cited answer.",
        error: BaseException | None = None,
    ) -> None:
        self.on_event = on_event
        self.client = FakeClient()
        self.active_model = "fake-model"
        self.answer = answer
        self.error = error
        self.questions: list[str] = []

    async def run(self, question: str) -> str:
        self.questions.append(question)
        self.on_event(
            AgentEvent(
                kind="tool_call",
                tool="search_documents",
                arguments={"query": question},
            )
        )
        self.on_event(
            AgentEvent(
                kind="tool_result",
                tool="search_documents",
                text="Found 1 document(s) for 'notes'.",
            )
        )
        self.on_event(AgentEvent(kind="answer", text=self.answer))
        if self.error is not None:
            raise self.error
        return self.answer


def make_app(**kwargs: Any):
    state: dict[str, FakeAgent] = {}

    def factory(on_event: Any) -> FakeAgent:
        agent = FakeAgent(on_event, **kwargs)
        state["agent"] = agent
        return agent

    return create_app(factory), state


def test_page_renders() -> None:
    app, _ = make_app()
    response = TestClient(app).get("/")
    assert response.status_code == 200
    assert "AskMyDocs" in response.text
    assert "MCP tool calls" in response.text


def test_ask_returns_steps_and_answer() -> None:
    app, state = make_app()
    response = TestClient(app).post(
        "/api/ask", json={"question": "  what do my notes say?  "}
    )

    assert response.status_code == 200
    data = response.json()
    assert data["answer"] == "Cited answer."
    assert data["model"] == "fake-model"
    assert [step["kind"] for step in data["steps"]] == [
        "tool_call",
        "tool_result",
        "answer",
    ]
    assert data["steps"][0]["tool"] == "search_documents"
    assert data["steps"][1]["is_error"] is False
    assert state["agent"].questions == ["what do my notes say?"]


def test_blank_question_is_rejected() -> None:
    app, state = make_app()
    response = TestClient(app).post("/api/ask", json={"question": "   "})
    assert response.status_code == 400
    assert "question" in response.json()["error"].lower()
    assert "agent" not in state


def test_invalid_json_is_rejected() -> None:
    app, _ = make_app()
    response = TestClient(app).post(
        "/api/ask", content=b"not json", headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 400
    assert "JSON" in response.json()["error"]


def test_agent_failure_returns_500_with_partial_steps() -> None:
    app, _ = make_app(error=RuntimeError("429 RESOURCE_EXHAUSTED: quota"))
    response = TestClient(app).post("/api/ask", json={"question": "hello"})

    assert response.status_code == 500
    data = response.json()
    assert data["error"]
    assert data["steps"]
    assert data["steps"][0]["kind"] == "tool_call"
