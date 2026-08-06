from __future__ import annotations

from types import SimpleNamespace

import pytest

from inventory_assistant.agent.provider import GeminiInteractionsProvider


class FakeStep:
    type = "function_call"
    id = "call-1"
    name = "query_inventory"
    arguments = {"query": "W12x40"}

    def model_dump(self, **kwargs):
        return {
            "type": self.type,
            "id": self.id,
            "name": self.name,
            "arguments": self.arguments,
            "signature": "preserve-me",
        }


class FakeInteractions:
    def __init__(self) -> None:
        self.requests = []
        self.responses = [
            SimpleNamespace(steps=[FakeStep()]),
            SimpleNamespace(steps=[], output_text="The verified result is ready."),
        ]

    async def create(self, **kwargs):
        self.requests.append(kwargs)
        return self.responses.pop(0)


class FakeAsyncClient:
    def __init__(self) -> None:
        self.interactions = FakeInteractions()
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


class FakeClient:
    def __init__(self) -> None:
        self.aio = FakeAsyncClient()
        self.closed = False

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_adapter_uses_stateless_manual_calls_and_tools_disabled_commentary() -> None:
    provider = GeminiInteractionsProvider.__new__(GeminiInteractionsProvider)
    provider._model = "test-model"
    provider._client = FakeClient()
    history = [{"type": "user_input", "content": [{"type": "text", "text": "hello"}]}]
    tools = [{"type": "function", "name": "query_inventory", "parameters": {}}]

    turn = await provider.route(history=history, tools=tools, system_instruction="route")
    commentary = await provider.comment(user_message="hello", verified_results=["verified"])
    await provider.close()

    assert turn.calls[0].name == "query_inventory"
    assert turn.steps[0]["signature"] == "preserve-me"
    route_request, comment_request = provider._client.aio.interactions.requests
    assert route_request["store"] is False
    assert route_request["generation_config"] == {"tool_choice": "any"}
    assert route_request["input"] is history
    assert comment_request["store"] is False
    assert comment_request["tools"] == []
    assert comment_request["generation_config"] == {"tool_choice": "none"}
    assert commentary == "The verified result is ready."
    assert provider._client.aio.closed
    assert provider._client.closed
