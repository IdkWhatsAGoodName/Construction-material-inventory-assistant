from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from inventory_assistant.agent.provider import ProposedCall, ProviderTurn
from inventory_assistant.main import create_app


class RequiredPromptProvider:
    async def route(self, *, history, tools, system_instruction) -> ProviderTurn:
        if any(step.get("type") == "function_result" for step in history):
            return _turn(("finish", "finish_turn", {}))
        message = history[0]["content"][0]["text"]
        if message.startswith("What is the availability"):
            return _turn(("inventory", "query_inventory", {"query": "W12x40 beams"}))
        if message.startswith("Do you have any 25M"):
            return _turn(("inventory", "query_inventory", {"query": "25M epoxy rebars"}))
        if message.startswith("I want to order 500"):
            return _turn(
                (
                    "evaluation",
                    "evaluate_order",
                    {"material_query": "15M deformed rebar", "quantity": 500},
                )
            )
        if message.startswith("Can I order 3 sheets"):
            return _turn(
                (
                    "evaluation",
                    "evaluate_order",
                    {"material_query": "3/8 inch steel plate", "quantity": 3},
                )
            )
        return _turn(
            ("supplier", "get_supplier_terms", {"category": "rebar"}),
            ("inventory", "query_inventory", {"query": "20M epoxy rebars"}),
        )

    async def comment(self, *, user_message: str, verified_results: list[str]) -> str:
        return "The verified results above address the complete request."

    async def close(self) -> None:
        return None


def _turn(*items: tuple[str, str, dict[str, Any]]) -> ProviderTurn:
    steps = tuple(
        {"type": "function_call", "id": call_id, "name": name, "arguments": arguments}
        for call_id, name, arguments in items
    )
    calls = tuple(ProposedCall(call_id, name, arguments) for call_id, name, arguments in items)
    return ProviderTurn(steps=steps, calls=calls)


@pytest.mark.parametrize(
    ("prompt", "expected_tools", "expected_text"),
    [
        (
            "What is the availability of W12x40 beams? Which warehouse are they in?",
            ["query_inventory"],
            "over-allocated by 2 each",
        ),
        (
            "Do you have any 25M epoxy coated rebar?",
            ["query_inventory"],
            "No catalogue material matches",
        ),
        (
            "I want to order 500 lengths of 15M rebar. "
            "Can you fulfil that, and what would it cost?",
            ["evaluate_order"],
            "13,925.00 CAD",
        ),
        (
            "Can I order 3 sheets of 3/8 inch steel plate?",
            ["evaluate_order"],
            "material is discontinued",
        ),
        (
            "Who supplies our rebar and what are their terms? "
            "Also, how many 20M epoxy coated rebars can we ship?",
            ["get_supplier_terms", "query_inventory"],
            "NET30",
        ),
    ],
)
def test_required_prompt_through_chat_tool_contract(
    configured_environment: None,
    auth: tuple[str, str],
    prompt: str,
    expected_tools: list[str],
    expected_text: str,
) -> None:
    with TestClient(create_app(conversation_provider=RequiredPromptProvider())) as client:
        response = client.post("/api/chat", auth=auth, json={"message": prompt})

    assert response.status_code == 200
    body = response.json()
    assert body["orchestration_status"] == "complete"
    assert [result["tool"] for result in body["verified_results"]] == expected_tools
    assert expected_text in "\n".join(result["message"] for result in body["verified_results"])
    assert body["commentary_status"] == "available"
