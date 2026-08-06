from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from inventory_assistant.application.orders import (
    ConfirmationNotFound,
    ConfirmationRegistry,
    InvalidOrderQuantity,
    OrderConfirmation,
    OrderService,
    PendingOrder,
)
from inventory_assistant.data.json_repository import JsonInventoryRepository
from inventory_assistant.data.repository import ReservationRequest, ReservationResult

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_DATA = PROJECT_ROOT / "Requirements" / "inventory_data.json"


class FakeReservations:
    def __init__(self, repository: JsonInventoryRepository, *, stale: bool = False) -> None:
        self.repository = repository
        self.stale = stale
        self.requests: list[ReservationRequest] = []

    def reserve_if_unchanged(self, request: ReservationRequest) -> ReservationResult:
        self.requests.append(request)
        material = self.repository.get_material(request.sku)
        if material is None or self.stale:
            return ReservationResult(outcome="stale", material=material)
        return ReservationResult(
            outcome="reserved",
            material=material.model_copy(
                update={"qty_reserved": material.qty_reserved + request.quantity}
            ),
        )


@pytest.fixture
def repository() -> JsonInventoryRepository:
    return JsonInventoryRepository.load(SOURCE_DATA)


def build_service(
    repository: JsonInventoryRepository, *, stale: bool = False
) -> tuple[OrderService, FakeReservations]:
    reservations = FakeReservations(repository, stale=stale)
    registry = ConfirmationRegistry(token_factory=lambda: "test-confirmation-token")
    return OrderService(repository, reservations, registry), reservations


def test_evaluates_confirmable_order_with_exact_deterministic_total(
    repository: JsonInventoryRepository,
) -> None:
    service, _ = build_service(repository)

    result = service.evaluate("RBR-15M-400W", 10)

    assert result.outcome == "ready_for_confirmation"
    assert result.item is not None
    assert result.item.sku == "RBR-15M-400W"
    assert result.unit_price == Decimal("27.85")
    assert result.line_total == Decimal("278.50")
    assert result.currency == "CAD"
    assert result.confirmation_token == "test-confirmation-token"
    assert result.expires_at is not None
    assert "Confirm within 15 minutes" in result.message


def test_rejects_500_lengths_without_partial_fulfilment_and_reports_hypothetical_cost(
    repository: JsonInventoryRepository,
) -> None:
    service, _ = build_service(repository)

    result = service.evaluate("15M deformed rebar", 500)

    assert result.outcome == "insufficient_inventory"
    assert result.item is not None
    assert result.item.sku == "RBR-15M-400W"
    assert result.item.qty_shippable == 120
    assert result.line_total == Decimal("13925.00")
    assert result.confirmation_token is None
    assert "Only 120 each can ship" in result.message
    assert "13,925.00 CAD" in result.message
    assert "no partial order was placed" in result.message


def test_rejects_discontinued_plate_and_reports_hypothetical_cost(
    repository: JsonInventoryRepository,
) -> None:
    service, _ = build_service(repository)

    result = service.evaluate("3/8 inch steel plate", 3)

    assert result.outcome == "discontinued"
    assert result.item is not None
    assert result.item.sku == "STL-PL38-A36"
    assert result.item.qty_shippable == 4
    assert result.line_total == Decimal("904.50")
    assert result.confirmation_token is None
    assert "discontinued" in result.message
    assert "904.50 CAD" in result.message


@pytest.mark.parametrize(
    ("query", "outcome"),
    [("rebar", "ambiguous"), ("25M epoxy rebar", "no_match")],
)
def test_unresolved_materials_never_create_confirmation(
    repository: JsonInventoryRepository, query: str, outcome: str
) -> None:
    service, reservations = build_service(repository)

    result = service.evaluate(query, 1)

    assert result.outcome == outcome
    assert result.item is None
    assert result.confirmation_token is None
    assert reservations.requests == []


@pytest.mark.parametrize("quantity", [0, -1, True, 1.5, "1"])
def test_application_boundary_rejects_non_positive_integer_quantities(
    repository: JsonInventoryRepository, quantity: object
) -> None:
    service, _ = build_service(repository)

    with pytest.raises(InvalidOrderQuantity):
        service.evaluate("RBR-15M-400W", quantity)  # type: ignore[arg-type]


def test_customer_order_below_supplier_replenishment_minimum_is_allowed(
    repository: JsonInventoryRepository,
) -> None:
    service, _ = build_service(repository)

    result = service.evaluate("RBR-15M-400W", 1)

    assert result.item is not None
    assert result.item.min_order_qty == 25
    assert result.outcome == "ready_for_confirmation"


def test_confirmation_reserves_and_replay_returns_exact_cached_result(
    repository: JsonInventoryRepository,
) -> None:
    service, reservations = build_service(repository)
    evaluation = service.evaluate("RBR-15M-400W", 10)

    first = service.confirm(evaluation.confirmation_token or "")
    replay = service.confirm(evaluation.confirmation_token or "")

    assert first.outcome == "confirmed"
    assert first.item is not None
    assert first.item.qty_on_hand == 120
    assert first.item.qty_reserved == 10
    assert first.item.qty_shippable == 110
    assert replay == first
    assert len(reservations.requests) == 1


def test_cancellation_invalidates_pending_token_without_reserving(
    repository: JsonInventoryRepository,
) -> None:
    service, reservations = build_service(repository)
    evaluation = service.evaluate("RBR-15M-400W", 10)

    cancellation = service.cancel(evaluation.confirmation_token or "")

    assert cancellation.sku == "RBR-15M-400W"
    assert cancellation.requested_quantity == 10
    assert "No inventory was reserved" in cancellation.message
    assert reservations.requests == []
    with pytest.raises(ConfirmationNotFound):
        service.confirm(evaluation.confirmation_token or "")


def test_stale_confirmation_is_terminal_and_does_not_claim_success(
    repository: JsonInventoryRepository,
) -> None:
    service, reservations = build_service(repository, stale=True)
    evaluation = service.evaluate("RBR-15M-400W", 10)

    first = service.confirm(evaluation.confirmation_token or "")
    replay = service.confirm(evaluation.confirmation_token or "")

    assert first.outcome == "stale"
    assert "Evaluate the order again" in first.message
    assert replay == first
    assert len(reservations.requests) == 1


def test_registry_expires_pending_token_but_keeps_terminal_replay() -> None:
    monotonic_time = [100.0]
    utc_time = [datetime(2026, 8, 6, 12, 0, tzinfo=UTC)]
    registry = ConfirmationRegistry(
        ttl_seconds=900,
        monotonic=lambda: monotonic_time[0],
        now_utc=lambda: utc_time[0],
        token_factory=lambda: "token",
    )
    pending = PendingOrder(
        sku="SKU",
        requested_quantity=1,
        unit_price=Decimal("1.00"),
        line_total=Decimal("1.00"),
        currency="CAD",
        qty_on_hand=2,
        qty_reserved=0,
        discontinued=False,
    )
    token, expires_at = registry.create(pending)
    assert expires_at == datetime(2026, 8, 6, 12, 15, tzinfo=UTC)

    monotonic_time[0] = 1_000.0
    with pytest.raises(ConfirmationNotFound):
        registry.confirm(token, lambda _: _confirmed_result())

    monotonic_time[0] = 2_000.0
    token, _ = registry.create(pending)
    terminal = registry.confirm(token, lambda _: _confirmed_result())
    monotonic_time[0] = 3_000.0
    assert registry.confirm(token, lambda _: pytest.fail("must not execute")) == terminal


def _confirmed_result() -> OrderConfirmation:
    return OrderConfirmation(
        outcome="confirmed",
        message="confirmed",
        requested_quantity=1,
        unit_price=Decimal("1.00"),
        line_total=Decimal("1.00"),
        currency="CAD",
        item=None,
    )
