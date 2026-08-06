from __future__ import annotations

import copy
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from inventory_assistant.agent.provider import ProposedCall, ProviderError, ProviderTurn
from inventory_assistant.main import create_app


class ScriptedProvider:
    def __init__(self, turns: list[ProviderTurn | Callable[..., ProviderTurn]]) -> None:
        self.turns = turns
        self.histories: list[list[dict[str, Any]]] = []
        self.tool_names: list[list[str]] = []
        self.comments: list[tuple[str, list[str]]] = []
        self.commentary = "The verified results above address your request."
        self.comment_error = False
        self.closed = False

    async def route(self, *, history, tools, system_instruction) -> ProviderTurn:
        self.histories.append(copy.deepcopy(history))
        self.tool_names.append([tool["name"] for tool in tools])
        if not self.turns:
            raise AssertionError("No scripted provider turn remains")
        turn = self.turns.pop(0)
        return (
            turn(history=history, tools=tools, system_instruction=system_instruction)
            if callable(turn)
            else turn
        )

    async def comment(self, *, user_message: str, verified_results: list[str]) -> str:
        self.comments.append((user_message, verified_results))
        if self.comment_error:
            raise ProviderError("comment unavailable")
        return self.commentary

    async def close(self) -> None:
        self.closed = True


def call(call_id: str, name: str, arguments: dict[str, Any]) -> ProviderTurn:
    step = {
        "type": "function_call",
        "id": call_id,
        "name": name,
        "arguments": arguments,
        "signature": f"signature-{call_id}",
    }
    return ProviderTurn(
        steps=(step,),
        calls=(ProposedCall(id=call_id, name=name, arguments=arguments),),
    )


def calls(*items: tuple[str, str, dict[str, Any]]) -> ProviderTurn:
    steps = tuple(
        {
            "type": "function_call",
            "id": call_id,
            "name": name,
            "arguments": arguments,
            "signature": f"signature-{call_id}",
        }
        for call_id, name, arguments in items
    )
    proposed = tuple(ProposedCall(call_id, name, arguments) for call_id, name, arguments in items)
    return ProviderTurn(steps=steps, calls=proposed)


@pytest.fixture
def chat_client(
    configured_environment: None,
) -> Iterator[tuple[TestClient, ScriptedProvider]]:
    provider = ScriptedProvider([])
    with TestClient(create_app(conversation_provider=provider)) as client:
        yield client, provider
    assert provider.closed


def test_chat_is_protected_and_missing_provider_degrades_only_chat(
    client: TestClient, auth: tuple[str, str]
) -> None:
    assert client.post("/api/chat", json={"message": "hello"}).status_code == 401
    response = client.post("/api/chat", auth=auth, json={"message": "hello"})
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "chat_unavailable"
    page = client.get("/", auth=auth)
    assert page.status_code == 200
    assert 'id="chat-form"' in page.text
    assert "Chat unavailable" in page.text
    assert client.get("/static/chat.js", auth=auth).status_code == 200
    assert client.get("/api/inventory/search?q=W12x40", auth=auth).status_code == 200


def test_iterative_chat_circulates_exact_steps_and_restores_transcript(
    chat_client: tuple[TestClient, ScriptedProvider], auth: tuple[str, str]
) -> None:
    client, provider = chat_client
    provider.turns.extend(
        [
            call("call-1", "query_inventory", {"query": "W12x40"}),
            call("call-2", "finish_turn", {}),
        ]
    )

    response = client.post(
        "/api/chat", auth=auth, json={"message": "What is the availability of W12x40?"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["orchestration_status"] == "complete"
    assert body["verified_results"][0]["tool"] == "query_inventory"
    assert "0 each can ship" in body["verified_results"][0]["message"]
    assert body["commentary_status"] == "available"
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "finish_turn" not in provider.tool_names[0]
    assert "finish_turn" in provider.tool_names[1]
    assert provider.histories[1][1]["signature"] == "signature-call-1"
    function_result = provider.histories[1][2]
    assert function_result["type"] == "function_result"
    assert function_result["call_id"] == "call-1"
    page = client.get("/", auth=auth)
    assert "What is the availability of W12x40?" in page.text
    assert "Verified application result" in page.text


def test_compound_independent_calls_execute_in_returned_order(
    chat_client: tuple[TestClient, ScriptedProvider], auth: tuple[str, str]
) -> None:
    client, provider = chat_client
    provider.turns.extend(
        [
            calls(
                ("call-1", "get_supplier_terms", {"category": "Rebar"}),
                ("call-2", "query_inventory", {"query": "20M epoxy coated rebar"}),
            ),
            call("call-3", "finish_turn", {}),
        ]
    )

    body = client.post(
        "/api/chat",
        auth=auth,
        json={"message": "Give me rebar supplier terms and check 20M epoxy coated stock."},
    ).json()

    assert [item["tool"] for item in body["verified_results"]] == [
        "get_supplier_terms",
        "query_inventory",
    ]
    assert "NET30" in body["verified_results"][0]["message"]
    assert "0 each can ship" in body["verified_results"][1]["message"]
    assert len(provider.comments) == 1
    assert len(provider.comments[0][1]) == 2


def test_evaluation_cannot_unlock_same_turn_confirmation_but_next_turn_can(
    chat_client: tuple[TestClient, ScriptedProvider], auth: tuple[str, str]
) -> None:
    client, provider = chat_client
    provider.turns.extend(
        [
            call(
                "call-1",
                "evaluate_order",
                {"material_query": "RBR-10M-400W", "quantity": 1},
            ),
            call(
                "call-2",
                "place_confirmed_order",
                {"pending_order_reference": "made-up"},
            ),
            call("call-3", "finish_turn", {}),
        ]
    )
    first = client.post(
        "/api/chat",
        auth=auth,
        json={"message": "Evaluate one length of RBR-10M-400W and confirm it."},
    ).json()
    assert first["verified_results"][0]["status"] == "success"
    assert first["verified_results"][1]["status"] == "invalid"
    reference = first["pending_orders"][0]["reference"]

    provider.turns.extend(
        [
            call(
                "call-4",
                "place_confirmed_order",
                {"pending_order_reference": reference},
            ),
            call("call-5", "finish_turn", {}),
        ]
    )
    second = client.post(
        "/api/chat", auth=auth, json={"message": "Confirm the pending rebar order."}
    ).json()
    assert second["verified_results"][0]["status"] == "success"
    assert "Order confirmed" in second["verified_results"][0]["message"]
    assert second["pending_orders"] == []


def test_unsafe_commentary_is_omitted(
    chat_client: tuple[TestClient, ScriptedProvider], auth: tuple[str, str]
) -> None:
    client, provider = chat_client
    provider.commentary = "There are 999 imaginary units available."
    provider.turns.extend([call("call-1", "show_help", {}), call("call-2", "finish_turn", {})])
    body = client.post("/api/chat", auth=auth, json={"message": "hello"}).json()
    assert body["commentary"] is None
    assert body["commentary_status"] == "omitted_unsafe"


def test_malformed_initial_provider_response_is_502(
    chat_client: tuple[TestClient, ScriptedProvider], auth: tuple[str, str]
) -> None:
    client, provider = chat_client
    provider.turns.append(ProviderTurn(steps=(), calls=()))
    response = client.post("/api/chat", auth=auth, json={"message": "hello"})
    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "chat_provider_response_invalid"


def test_invalid_call_can_be_corrected_in_a_later_round(
    chat_client: tuple[TestClient, ScriptedProvider], auth: tuple[str, str]
) -> None:
    client, provider = chat_client
    provider.turns.extend(
        [
            call("call-1", "query_inventory", {"wrong": "W12x40"}),
            call("call-2", "query_inventory", {"query": "W12x40"}),
            call("call-3", "finish_turn", {}),
        ]
    )

    body = client.post("/api/chat", auth=auth, json={"message": "Check W12x40."}).json()

    assert [item["status"] for item in body["verified_results"]] == ["invalid", "success"]
    assert provider.histories[1][-1]["type"] == "function_result"
    assert "Expected arguments" in provider.histories[1][-1]["result"][0]["text"]


def test_provider_failure_after_execution_returns_visible_partial_results(
    chat_client: tuple[TestClient, ScriptedProvider], auth: tuple[str, str]
) -> None:
    client, provider = chat_client

    def fail(**kwargs) -> ProviderTurn:
        raise ProviderError("temporary failure")

    provider.turns.extend([call("call-1", "query_inventory", {"query": "W12x40"}), fail])
    response = client.post("/api/chat", auth=auth, json={"message": "Check W12x40."})

    assert response.status_code == 200
    body = response.json()
    assert body["orchestration_status"] == "incomplete"
    assert body["verified_results"][0]["tool"] == "query_inventory"
    assert body["commentary_status"] == "not_requested"


def test_tool_call_budget_executes_ten_and_reports_one_limit_result(
    chat_client: tuple[TestClient, ScriptedProvider], auth: tuple[str, str]
) -> None:
    client, provider = chat_client
    provider.turns.append(calls(*[(f"call-{index}", "show_help", {}) for index in range(1, 12)]))

    body = client.post("/api/chat", auth=auth, json={"message": "Help repeatedly."}).json()

    assert body["orchestration_status"] == "incomplete"
    assert len(body["verified_results"]) == 11
    assert sum(item["status"] == "success" for item in body["verified_results"]) == 10
    assert body["verified_results"][-1]["status"] == "limit"


def test_pending_order_can_be_cancelled_and_isolated_by_cookie(
    chat_client: tuple[TestClient, ScriptedProvider], auth: tuple[str, str]
) -> None:
    client, provider = chat_client
    provider.turns.extend(
        [
            call(
                "call-1",
                "evaluate_order",
                {"material_query": "RBR-15M-400W", "quantity": 1},
            ),
            call("call-2", "finish_turn", {}),
        ]
    )
    evaluated = client.post(
        "/api/chat", auth=auth, json={"message": "Evaluate one RBR-15M-400W."}
    ).json()
    reference = evaluated["pending_orders"][0]["reference"]

    original_cookie = client.cookies.get("sidian_chat_session")
    client.cookies.clear()
    provider.turns.extend(
        [
            call(
                "call-3",
                "cancel_pending_order",
                {"pending_order_reference": reference},
            ),
            call("call-4", "finish_turn", {}),
        ]
    )
    isolated = client.post(
        "/api/chat", auth=auth, json={"message": "Cancel the pending rebar order."}
    ).json()
    assert isolated["verified_results"][0]["status"] == "invalid"

    client.cookies.set("sidian_chat_session", original_cookie)
    provider.turns.extend(
        [
            call(
                "call-5",
                "cancel_pending_order",
                {"pending_order_reference": reference},
            ),
            call("call-6", "finish_turn", {}),
        ]
    )
    cancelled = client.post(
        "/api/chat", auth=auth, json={"message": "Cancel the pending rebar order."}
    ).json()
    assert cancelled["verified_results"][0]["status"] == "success"
    assert "No inventory was reserved" in cancelled["verified_results"][0]["message"]
    assert cancelled["pending_orders"] == []


def test_explicit_bulk_confirmation_places_multiple_existing_pending_orders(
    chat_client: tuple[TestClient, ScriptedProvider], auth: tuple[str, str]
) -> None:
    client, provider = chat_client
    provider.turns.extend(
        [
            calls(
                (
                    "call-1",
                    "evaluate_order",
                    {"material_query": "RBR-15M-400W", "quantity": 1},
                ),
                (
                    "call-2",
                    "evaluate_order",
                    {"material_query": "RBR-10M-400W", "quantity": 2},
                ),
            ),
            call("call-3", "finish_turn", {}),
        ]
    )
    evaluated = client.post(
        "/api/chat",
        auth=auth,
        json={
            "message": (
                "Evaluate one length of RBR-15M-400W and two lengths of RBR-10M-400W "
                "as separate orders."
            )
        },
    ).json()
    references = [order["reference"] for order in evaluated["pending_orders"]]
    assert len(references) == 2

    provider.turns.extend(
        [
            calls(
                (
                    "call-4",
                    "place_confirmed_order",
                    {"pending_order_reference": references[0]},
                ),
                (
                    "call-5",
                    "place_confirmed_order",
                    {"pending_order_reference": references[1]},
                ),
            ),
            call("call-6", "finish_turn", {}),
        ]
    )
    confirmed = client.post(
        "/api/chat", auth=auth, json={"message": "Confirm both pending rebar orders."}
    ).json()

    assert [item["status"] for item in confirmed["verified_results"]] == [
        "success",
        "success",
    ]
    assert confirmed["pending_orders"] == []
    first_inventory = client.get("/api/inventory/RBR-15M-400W", auth=auth).json()
    second_inventory = client.get("/api/inventory/RBR-10M-400W", auth=auth).json()
    assert first_inventory["qty_reserved"] == 1
    assert second_inventory["qty_reserved"] == 2
