"""Deterministic two-step customer-order workflow."""

from __future__ import annotations

import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from threading import Lock
from typing import Literal

from inventory_assistant.application.inventory import InventoryService
from inventory_assistant.data.repository import (
    InventoryRepository,
    ReservationRepository,
    ReservationRequest,
)
from inventory_assistant.domain.inventory import InventoryItem

CONFIRMATION_TTL_SECONDS = 15 * 60

EvaluationOutcome = Literal[
    "ready_for_confirmation",
    "insufficient_inventory",
    "discontinued",
    "ambiguous",
    "no_match",
]
ConfirmationOutcome = Literal["confirmed", "stale"]


class InvalidOrderQuantity(ValueError):
    """Raised when application callers provide a non-positive or non-integer quantity."""


class ConfirmationNotFound(LookupError):
    """Raised for unknown, expired, or process-lost confirmation tokens."""


@dataclass(frozen=True, slots=True)
class OrderEvaluation:
    outcome: EvaluationOutcome
    query: str
    requested_quantity: int
    message: str
    item: InventoryItem | None = None
    candidates: tuple[InventoryItem, ...] = ()
    unit_price: Decimal | None = None
    line_total: Decimal | None = None
    currency: str | None = None
    confirmation_token: str | None = None
    expires_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class PendingOrder:
    sku: str
    requested_quantity: int
    unit_price: Decimal
    line_total: Decimal
    currency: str
    qty_on_hand: int
    qty_reserved: int
    discontinued: bool


@dataclass(frozen=True, slots=True)
class OrderConfirmation:
    outcome: ConfirmationOutcome
    message: str
    requested_quantity: int
    unit_price: Decimal
    line_total: Decimal
    currency: str
    item: InventoryItem | None


@dataclass(frozen=True, slots=True)
class _PendingEntry:
    order: PendingOrder
    expires_at: datetime
    deadline: float


class ConfirmationRegistry:
    """Concurrency-safe process-memory pending and terminal confirmation state."""

    def __init__(
        self,
        *,
        ttl_seconds: int = CONFIRMATION_TTL_SECONDS,
        monotonic: Callable[[], float] = time.monotonic,
        now_utc: Callable[[], datetime] | None = None,
        token_factory: Callable[[], str] | None = None,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._monotonic = monotonic
        self._now_utc = now_utc or (lambda: datetime.now(UTC))
        self._token_factory = token_factory or (lambda: secrets.token_urlsafe(32))
        self._pending: dict[str, _PendingEntry] = {}
        self._terminal: dict[str, OrderConfirmation] = {}
        self._lock = Lock()

    def create(self, order: PendingOrder) -> tuple[str, datetime]:
        now = self._now_utc()
        expires_at = now + timedelta(seconds=self._ttl_seconds)
        deadline = self._monotonic() + self._ttl_seconds
        with self._lock:
            self._prune_expired_locked()
            token = self._token_factory()
            while token in self._pending or token in self._terminal:
                token = self._token_factory()
            self._pending[token] = _PendingEntry(order, expires_at, deadline)
        return token, expires_at

    def confirm(
        self,
        token: str,
        operation: Callable[[PendingOrder], OrderConfirmation],
    ) -> OrderConfirmation:
        with self._lock:
            terminal = self._terminal.get(token)
            if terminal is not None:
                return terminal

            entry = self._pending.get(token)
            if entry is None or entry.deadline <= self._monotonic():
                self._pending.pop(token, None)
                raise ConfirmationNotFound(token)

            result = operation(entry.order)
            self._pending.pop(token, None)
            self._terminal[token] = result
            return result

    def _prune_expired_locked(self) -> None:
        now = self._monotonic()
        expired = [token for token, entry in self._pending.items() if entry.deadline <= now]
        for token in expired:
            del self._pending[token]


class OrderService:
    """Evaluate quotes and execute only explicitly confirmed reservations."""

    def __init__(
        self,
        inventory_repository: InventoryRepository,
        reservation_repository: ReservationRepository,
        registry: ConfirmationRegistry,
    ) -> None:
        self._inventory = InventoryService(inventory_repository)
        self._reservations = reservation_repository
        self._registry = registry

    def evaluate(self, material_query: str, quantity: int) -> OrderEvaluation:
        quantity = _validate_quantity(quantity)
        search = self._inventory.search(material_query)
        if search.outcome == "no_match":
            return OrderEvaluation(
                outcome="no_match",
                query=search.query,
                requested_quantity=quantity,
                message=(
                    f"Cannot evaluate an order for '{search.query}': no catalogue material "
                    "matches it. No substitute was selected."
                ),
            )
        if search.outcome == "ambiguous":
            candidate_skus = ", ".join(item.sku for item in search.candidates)
            return OrderEvaluation(
                outcome="ambiguous",
                query=search.query,
                requested_quantity=quantity,
                message=(
                    f"Cannot evaluate an order for '{search.query}' because it matches multiple "
                    f"materials: {candidate_skus}. Select an exact material."
                ),
                candidates=search.candidates,
            )

        item = search.item
        if item is None:  # Defensive: search outcomes above exhaust unresolved results.
            raise RuntimeError("Resolved inventory search did not include a material")

        line_total = item.unit_price * quantity
        common = {
            "query": search.query,
            "requested_quantity": quantity,
            "item": item,
            "unit_price": item.unit_price,
            "line_total": line_total,
            "currency": item.currency,
        }
        price = _format_money(line_total, item.currency)
        unit = item.unit_of_measure
        if item.discontinued:
            return OrderEvaluation(
                outcome="discontinued",
                message=(
                    f"Cannot order {quantity} {unit} of {item.description} ({item.sku}) because "
                    f"the material is discontinued. The hypothetical requested total is {price}; "
                    "no inventory was reserved."
                ),
                **common,
            )
        if quantity > item.qty_shippable:
            return OrderEvaluation(
                outcome="insufficient_inventory",
                message=(
                    f"Cannot fulfil {quantity} {unit} of {item.description} ({item.sku}). "
                    f"Only {item.qty_shippable} {unit} can ship; no partial order was placed. "
                    f"The hypothetical requested total is {price}."
                ),
                **common,
            )

        pending = PendingOrder(
            sku=item.sku,
            requested_quantity=quantity,
            unit_price=item.unit_price,
            line_total=line_total,
            currency=item.currency,
            qty_on_hand=item.qty_on_hand,
            qty_reserved=item.qty_reserved,
            discontinued=item.discontinued,
        )
        token, expires_at = self._registry.create(pending)
        return OrderEvaluation(
            outcome="ready_for_confirmation",
            message=(
                f"Ready to reserve {quantity} {unit} of {item.description} ({item.sku}) at "
                f"{_format_money(item.unit_price, item.currency)} each for {price}. "
                "Confirm within 15 minutes; no inventory has been reserved yet."
            ),
            confirmation_token=token,
            expires_at=expires_at,
            **common,
        )

    def confirm(self, confirmation_token: str) -> OrderConfirmation:
        return self._registry.confirm(confirmation_token, self._confirm_pending)

    def _confirm_pending(self, pending: PendingOrder) -> OrderConfirmation:
        reservation = self._reservations.reserve_if_unchanged(
            ReservationRequest(
                sku=pending.sku,
                quantity=pending.requested_quantity,
                expected_unit_price=pending.unit_price,
                expected_qty_on_hand=pending.qty_on_hand,
                expected_qty_reserved=pending.qty_reserved,
                expected_discontinued=pending.discontinued,
            )
        )
        item = (
            InventoryItem.from_material(reservation.material)
            if reservation.material is not None
            else None
        )
        if reservation.outcome != "reserved":
            current = (
                f" Current shippable quantity is {item.qty_shippable} {item.unit_of_measure}."
                if item is not None
                else " The material is no longer present."
            )
            return OrderConfirmation(
                outcome="stale",
                message=(
                    "The evaluated order is stale because its price or inventory state changed."
                    f"{current} Evaluate the order again; no inventory was reserved."
                ),
                requested_quantity=pending.requested_quantity,
                unit_price=pending.unit_price,
                line_total=pending.line_total,
                currency=pending.currency,
                item=item,
            )

        if item is None:  # Defensive: a successful reservation must return its material.
            raise RuntimeError("Successful reservation did not return a material")
        return OrderConfirmation(
            outcome="confirmed",
            message=(
                f"Order confirmed: reserved {pending.requested_quantity} {item.unit_of_measure} "
                f"of {item.description} ({item.sku}) for "
                f"{_format_money(pending.line_total, pending.currency)}. "
                f"{item.qty_shippable} {item.unit_of_measure} can still ship."
            ),
            requested_quantity=pending.requested_quantity,
            unit_price=pending.unit_price,
            line_total=pending.line_total,
            currency=pending.currency,
            item=item,
        )


def _validate_quantity(quantity: int) -> int:
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
        raise InvalidOrderQuantity("Order quantity must be a positive integer")
    return quantity


def _format_money(value: Decimal, currency: str) -> str:
    return f"{value:,.2f} {currency}"
