"""Bounded stateless Gemini orchestration over deterministic application services."""

from __future__ import annotations

import json
import logging
import re
import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Literal

from inventory_assistant.agent.provider import (
    ConversationProvider,
    ProposedCall,
    ProviderError,
)
from inventory_assistant.agent.sessions import (
    MAX_PENDING_ORDERS,
    ChatSession,
    PendingChatOrder,
)
from inventory_assistant.application.inventory import InventoryService
from inventory_assistant.application.orders import ConfirmationNotFound, OrderService
from inventory_assistant.application.suppliers import SupplierService
from inventory_assistant.data.sqlite_repository import ReservationPersistenceError

LOGGER = logging.getLogger(__name__)
MAX_ROUTING_ROUNDS = 5
MAX_TOOL_CALLS = 10
MAX_MESSAGE_LENGTH = 1_000
MAX_COMMENTARY_LENGTH = 1_500

ResultStatus = Literal["success", "rejected", "invalid", "skipped", "error", "limit"]


class ChatProviderUnavailable(RuntimeError):
    pass


class ChatProviderMalformed(RuntimeError):
    pass


class _PendingNoLongerActive(LookupError):
    pass


@dataclass(frozen=True, slots=True)
class VerifiedResult:
    call_index: int
    tool: str
    status: ResultStatus
    title: str
    message: str
    affected_skus: tuple[str, ...] = ()

    def public(self) -> dict[str, Any]:
        return {
            "call_index": self.call_index,
            "tool": self.tool,
            "status": self.status,
            "title": self.title,
            "message": self.message,
            "affected_skus": list(self.affected_skus),
        }


@dataclass(frozen=True, slots=True)
class ChatOutcome:
    orchestration_status: Literal["complete", "incomplete"]
    verified_results: tuple[VerifiedResult, ...]
    commentary: str | None
    commentary_status: Literal["available", "unavailable", "omitted_unsafe", "not_requested"]
    pending_orders: tuple[dict[str, Any], ...]

    def public(self) -> dict[str, Any]:
        return {
            "orchestration_status": self.orchestration_status,
            "verified_results": [result.public() for result in self.verified_results],
            "commentary": self.commentary,
            "commentary_status": self.commentary_status,
            "pending_orders": list(self.pending_orders),
        }


@dataclass(slots=True)
class _TurnState:
    session: ChatSession
    eligible_pending: frozenset[str]
    allowed_tools: frozenset[str]
    results: list[VerifiedResult] = field(default_factory=list)
    proposed_calls: int = 0


class ChatOrchestrator:
    def __init__(
        self,
        *,
        provider: ConversationProvider,
        inventory: InventoryService,
        suppliers: SupplierService,
        orders: OrderService,
    ) -> None:
        self._provider = provider
        self._inventory = inventory
        self._suppliers = suppliers
        self._orders = orders

    async def handle(self, session: ChatSession, message: str) -> ChatOutcome:
        cleaned = " ".join(message.split())
        if not cleaned or len(cleaned) > MAX_MESSAGE_LENGTH:
            raise ValueError(f"Message must contain 1 to {MAX_MESSAGE_LENGTH} characters")

        async with session.lock:
            session.prune_pending()
            eligible = frozenset(session.pending_orders)
            allowed = {"show_help", "query_inventory", "get_supplier_terms", "evaluate_order"}
            lowered = cleaned.casefold()
            if eligible and _confirmation_intent(lowered):
                allowed.add("place_confirmed_order")
            if eligible and _cancellation_intent(lowered):
                allowed.add("cancel_pending_order")
            state = _TurnState(
                session=session, eligible_pending=eligible, allowed_tools=frozenset(allowed)
            )
            history = [_user_input(cleaned)]
            system_instruction = self._system_instruction(session, state.allowed_tools)
            complete = False

            for round_number in range(1, MAX_ROUTING_ROUNDS + 1):
                tools = _tool_declarations(state.allowed_tools, allow_finish=bool(state.results))
                started = time.monotonic()
                try:
                    turn = await self._provider.route(
                        history=history,
                        tools=tools,
                        system_instruction=system_instruction,
                    )
                except ProviderError as error:
                    LOGGER.warning("Gemini routing failed in round %d", round_number)
                    if not state.results:
                        raise ChatProviderUnavailable from error
                    break
                LOGGER.info(
                    "Gemini routing round=%d latency_ms=%d proposed_calls=%d",
                    round_number,
                    round((time.monotonic() - started) * 1_000),
                    len(turn.calls),
                )
                history.extend(turn.steps)
                if not turn.calls:
                    if not state.results:
                        raise ChatProviderMalformed("Provider returned no function call")
                    break

                finish_calls = [call for call in turn.calls if call.name == "finish_turn"]
                if finish_calls and len(turn.calls) == 1 and state.results:
                    complete = True
                    break

                for call in turn.calls:
                    if call.name == "finish_turn":
                        result = self._result(
                            state,
                            call,
                            "invalid",
                            "Invalid completion request",
                            "finish_turn must be the only function call in its routing response.",
                            count_call=False,
                        )
                    elif state.proposed_calls >= MAX_TOOL_CALLS:
                        result = self._result(
                            state,
                            call,
                            "limit",
                            "Tool-call limit reached",
                            "This turn reached the best-effort limit of 10 application tool calls.",
                            count_call=False,
                        )
                        history.append(_function_result(call, result))
                        break
                    else:
                        result = self._execute(state, call)
                    history.append(_function_result(call, result))
                if state.proposed_calls >= MAX_TOOL_CALLS:
                    break

            if not complete:
                if not any(result.status == "limit" for result in state.results):
                    state.results.append(
                        VerifiedResult(
                            call_index=len(state.results) + 1,
                            tool="orchestration",
                            status="limit" if state.proposed_calls >= MAX_TOOL_CALLS else "error",
                            title="Conversation orchestration incomplete",
                            message=(
                                "The assistant stopped before it could prove the request was fully "
                                "handled. Review the verified results already completed."
                            ),
                        )
                    )
                outcome = self._finish(state, "incomplete", None, "not_requested")
            else:
                commentary, commentary_status = await self._comment(cleaned, state.results)
                outcome = self._finish(state, "complete", commentary, commentary_status)

            session.add_turn(
                {
                    "user_message": cleaned,
                    "verified_results": [item.public() for item in state.results],
                    "commentary": outcome.commentary,
                    "commentary_status": outcome.commentary_status,
                    "orchestration_status": outcome.orchestration_status,
                }
            )
            return outcome

    def _execute(self, state: _TurnState, call: ProposedCall) -> VerifiedResult:
        state.proposed_calls += 1
        if call.name not in state.allowed_tools:
            return self._result(
                state,
                call,
                "invalid",
                "Invalid tool request",
                f"Tool '{call.name}' is not available for this turn.",
                count_call=False,
            )
        try:
            if call.name == "show_help":
                _require_exact_arguments(call.arguments, set())
                _log_validated_call(call.name, {})
                return self._result(
                    state,
                    call,
                    "success",
                    "Assistant capabilities",
                    "I can check inventory, look up supplier terms, evaluate customer orders, "
                    "and explicitly confirm or cancel pending orders.",
                    count_call=False,
                )
            if call.name == "query_inventory":
                query = _text_argument(call.arguments, "query")
                _log_validated_call(call.name, {"query": query})
                search = self._inventory.search(query)
                status: ResultStatus = (
                    "success" if search.outcome in {"exact_match", "unique_match"} else "rejected"
                )
                return self._result(
                    state, call, status, "Inventory result", search.message, count_call=False
                )
            if call.name == "get_supplier_terms":
                category = _text_argument(call.arguments, "category")
                _log_validated_call(call.name, {"category": category})
                search = self._suppliers.find_for_category(category)
                status = "success" if search.outcome == "unique_match" else "rejected"
                return self._result(
                    state, call, status, "Supplier result", search.message, count_call=False
                )
            if call.name == "evaluate_order":
                query = _text_argument(
                    call.arguments,
                    "material_query",
                    expected={"material_query", "quantity"},
                )
                quantity = _integer_argument(call.arguments, "quantity")
                _log_validated_call(
                    call.name,
                    {"material_query": query, "quantity": quantity},
                )
                if len(state.session.pending_orders) >= MAX_PENDING_ORDERS:
                    return self._result(
                        state,
                        call,
                        "rejected",
                        "Order evaluation result",
                        "This chat already has 20 pending orders. Confirm, cancel, or let one "
                        "expire before evaluating another.",
                        count_call=False,
                    )
                evaluation = self._orders.evaluate(query, quantity)
                if evaluation.confirmation_token and evaluation.expires_at and evaluation.item:
                    reference = _new_reference(state.session)
                    state.session.pending_orders[reference] = PendingChatOrder(
                        reference=reference,
                        confirmation_token=evaluation.confirmation_token,
                        summary=evaluation.message,
                        sku=evaluation.item.sku,
                        expires_at=evaluation.expires_at,
                    )
                status = "success" if evaluation.outcome == "ready_for_confirmation" else "rejected"
                return self._result(
                    state,
                    call,
                    status,
                    "Order evaluation result",
                    evaluation.message,
                    count_call=False,
                )
            if call.name == "place_confirmed_order":
                reference = _text_argument(call.arguments, "pending_order_reference", max_length=40)
                _log_validated_call(call.name, {"pending_order_reference": reference})
                pending = self._eligible_pending(state, reference)
                try:
                    confirmation = self._orders.confirm(pending.confirmation_token)
                except ConfirmationNotFound:
                    state.session.pending_orders.pop(reference, None)
                    return self._result(
                        state,
                        call,
                        "skipped",
                        "Order confirmation result",
                        f"Pending order {reference} is unknown or expired. Evaluate it again.",
                        count_call=False,
                    )
                state.session.pending_orders.pop(reference, None)
                affected = (confirmation.item.sku,) if confirmation.item else ()
                status = "success" if confirmation.outcome == "confirmed" else "rejected"
                return self._result(
                    state,
                    call,
                    status,
                    "Order confirmation result",
                    confirmation.message,
                    affected_skus=affected,
                    count_call=False,
                )
            if call.name == "cancel_pending_order":
                reference = _text_argument(call.arguments, "pending_order_reference", max_length=40)
                _log_validated_call(call.name, {"pending_order_reference": reference})
                pending = self._eligible_pending(state, reference)
                try:
                    cancellation = self._orders.cancel(pending.confirmation_token)
                except ConfirmationNotFound:
                    state.session.pending_orders.pop(reference, None)
                    return self._result(
                        state,
                        call,
                        "skipped",
                        "Order cancellation result",
                        f"Pending order {reference} is unknown or expired and cannot be cancelled.",
                        count_call=False,
                    )
                state.session.pending_orders.pop(reference, None)
                return self._result(
                    state,
                    call,
                    "success",
                    "Order cancellation result",
                    cancellation.message,
                    count_call=False,
                )
        except _PendingNoLongerActive as error:
            return self._result(
                state,
                call,
                "skipped",
                "Pending order operation skipped",
                str(error),
                count_call=False,
            )
        except (TypeError, ValueError) as error:
            return self._result(
                state,
                call,
                "invalid",
                "Invalid tool arguments",
                str(error),
                count_call=False,
            )
        except ReservationPersistenceError:
            return self._result(
                state,
                call,
                "error",
                "Order operation unavailable",
                "Inventory reservation is temporarily unavailable. Try again.",
                count_call=False,
            )
        return self._result(
            state,
            call,
            "invalid",
            "Invalid tool request",
            f"Tool '{call.name}' is not implemented.",
            count_call=False,
        )

    def _eligible_pending(self, state: _TurnState, reference: str) -> PendingChatOrder:
        if reference not in state.eligible_pending:
            raise ValueError(
                f"Pending order reference '{reference}' was not eligible at turn start"
            )
        pending = state.session.pending_orders.get(reference)
        if pending is None:
            raise _PendingNoLongerActive(
                f"Pending order reference '{reference}' is no longer active; no action was taken."
            )
        return pending

    def _result(
        self,
        state: _TurnState,
        call: ProposedCall,
        status: ResultStatus,
        title: str,
        message: str,
        *,
        affected_skus: tuple[str, ...] = (),
        count_call: bool,
    ) -> VerifiedResult:
        result = VerifiedResult(
            call_index=len(state.results) + 1,
            tool=call.name,
            status=status,
            title=title,
            message=message,
            affected_skus=affected_skus,
        )
        state.results.append(result)
        LOGGER.info("Chat tool result name=%s status=%s", call.name, status)
        return result

    async def _comment(
        self, message: str, results: list[VerifiedResult]
    ) -> tuple[str | None, Literal["available", "unavailable", "omitted_unsafe"]]:
        verified = [result.message for result in results]
        try:
            commentary = await self._provider.comment(
                user_message=message,
                verified_results=verified,
            )
        except ProviderError:
            LOGGER.warning("Gemini commentary request failed")
            return None, "unavailable"
        if len(commentary) > MAX_COMMENTARY_LENGTH or not _commentary_is_safe(commentary, verified):
            LOGGER.warning("Gemini commentary omitted by factual-token validation")
            return None, "omitted_unsafe"
        return commentary, "available"

    def _finish(
        self,
        state: _TurnState,
        status: Literal["complete", "incomplete"],
        commentary: str | None,
        commentary_status: Literal["available", "unavailable", "omitted_unsafe", "not_requested"],
    ) -> ChatOutcome:
        state.session.prune_pending()
        pending = tuple(item.public() for item in state.session.pending_orders.values())
        return ChatOutcome(status, tuple(state.results), commentary, commentary_status, pending)

    def _system_instruction(self, session: ChatSession, allowed_tools: frozenset[str]) -> str:
        recent = [turn["user_message"] for turn in session.transcript[-4:]]
        pending = [item.public() for item in session.pending_orders.values()]
        return (
            "You route construction inventory requests exclusively through the declared tools. "
            "Never answer with model knowledge. Calls returned together must be independent; wait "
            "for function results before requesting dependent calls. Use show_help for greetings, "
            "unsupported, or clarification requests. Only call finish_turn after every part of the "
            "request has a verified result. Do not confirm an order evaluated in this same user "
            "turn. Available mutation tools are an application authorization boundary.\n"
            f"Allowed tool names: {sorted(allowed_tools)}\n"
            f"Recent user requests: {json.dumps(recent)}\n"
            f"Eligible pending orders: {json.dumps(pending)}"
        )


def _user_input(message: str) -> dict[str, Any]:
    return {"type": "user_input", "content": [{"type": "text", "text": message}]}


def _function_result(call: ProposedCall, result: VerifiedResult) -> dict[str, Any]:
    payload = json.dumps({"status": result.status, "message": result.message})
    return {
        "type": "function_result",
        "name": call.name,
        "call_id": call.id,
        "result": [{"type": "text", "text": payload}],
    }


def _tool_declarations(allowed: frozenset[str], *, allow_finish: bool) -> list[dict[str, Any]]:
    declarations = {
        "show_help": _tool("show_help", "Explain supported assistant capabilities.", {}),
        "query_inventory": _tool(
            "query_inventory",
            "Find exact or ambiguous inventory matches and report deterministic stock details.",
            {"query": _string("Material SKU or description")},
            ["query"],
        ),
        "get_supplier_terms": _tool(
            "get_supplier_terms",
            "Look up the supplier and terms for a catalogue category.",
            {"category": _string("Catalogue category")},
            ["category"],
        ),
        "evaluate_order": _tool(
            "evaluate_order",
            "Evaluate availability and exact price without reserving inventory.",
            {
                "material_query": _string("Exact material SKU or description"),
                "quantity": {"type": "integer", "minimum": 1},
            },
            ["material_query", "quantity"],
        ),
        "place_confirmed_order": _tool(
            "place_confirmed_order",
            "Confirm one previously evaluated, eligible pending order.",
            {"pending_order_reference": _string("Session-local pending order reference")},
            ["pending_order_reference"],
        ),
        "cancel_pending_order": _tool(
            "cancel_pending_order",
            "Cancel one eligible pending order without reserving inventory.",
            {"pending_order_reference": _string("Session-local pending order reference")},
            ["pending_order_reference"],
        ),
    }
    tools = [declarations[name] for name in declarations if name in allowed]
    if allow_finish:
        tools.append(
            _tool("finish_turn", "Finish after all requested work has verified results.", {})
        )
    return tools


def _tool(
    name: str,
    description: str,
    properties: dict[str, Any],
    required: list[str] | None = None,
) -> dict[str, Any]:
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": properties,
    }
    if required:
        parameters["required"] = required
    return {"type": "function", "name": name, "description": description, "parameters": parameters}


def _string(description: str) -> dict[str, Any]:
    return {"type": "string", "description": description, "minLength": 1, "maxLength": 100}


def _require_exact_arguments(arguments: dict[str, Any], required: set[str]) -> None:
    if set(arguments) != required:
        raise ValueError(f"Expected arguments {sorted(required)}")


def _text_argument(
    arguments: dict[str, Any],
    name: str,
    *,
    max_length: int = 100,
    expected: set[str] | None = None,
) -> str:
    _require_exact_arguments(arguments, expected or {name})
    value = arguments[name]
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    cleaned = " ".join(value.split())
    if not cleaned or len(cleaned) > max_length:
        raise ValueError(f"{name} must contain 1 to {max_length} characters")
    return cleaned


def _integer_argument(arguments: dict[str, Any], name: str) -> int:
    expected = {"material_query", "quantity"}
    _require_exact_arguments(arguments, expected)
    value = arguments[name]
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _new_reference(session: ChatSession) -> str:
    reference = f"order-{secrets.token_hex(3)}"
    while reference in session.pending_orders:
        reference = f"order-{secrets.token_hex(3)}"
    return reference


def _confirmation_intent(message: str) -> bool:
    if re.search(
        r"\b(?:do not|don't|not to)\s+(?:confirm|place|reserve)\b|\bwithout confirming\b",
        message,
    ):
        return False
    return bool(re.search(r"\b(confirm|place|reserve|proceed)\b|\bgo ahead\b", message))


def _cancellation_intent(message: str) -> bool:
    return bool(
        re.search(r"\b(cancel|discard)\b|\bnever mind\b|\bdo not place\b|\bdon't place\b", message)
    )


_FACT_TOKEN = re.compile(
    r"(?:[$€£]\s*\d[\d,.]*)|(?:\b\d[\d,.]*(?::\d{2})?(?:\s*[A-Z]{3})?\b)|"
    r"(?:\b[A-Z0-9]+(?:[-/][A-Z0-9.]+)+\b)"
)


def _commentary_is_safe(commentary: str, verified_results: list[str]) -> bool:
    source = "\n".join(verified_results).casefold()
    return all(match.group(0).casefold() in source for match in _FACT_TOKEN.finditer(commentary))


def _log_validated_call(name: str, arguments: dict[str, Any]) -> None:
    LOGGER.info("Chat tool name=%s validated_arguments=%s", name, arguments)
