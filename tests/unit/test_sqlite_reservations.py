from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

import pytest

from inventory_assistant.data import sqlite_repository
from inventory_assistant.data.ingestion import ingest_inventory
from inventory_assistant.data.repository import ReservationRequest
from inventory_assistant.data.sqlite_repository import (
    ReservationPersistenceError,
    SQLiteInventoryRepository,
    connect_database,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_DATA = PROJECT_ROOT / "Requirements" / "inventory_data.json"
SKU = "RBR-15M-400W"


@pytest.fixture
def repository(tmp_path: Path) -> SQLiteInventoryRepository:
    database_path = tmp_path / "inventory.sqlite3"
    ingest_inventory(SOURCE_DATA, database_path)
    return SQLiteInventoryRepository(database_path)


def request_for_source(*, quantity: int = 10) -> ReservationRequest:
    return ReservationRequest(
        sku=SKU,
        quantity=quantity,
        expected_unit_price=Decimal("27.85"),
        expected_qty_on_hand=120,
        expected_qty_reserved=0,
        expected_discontinued=False,
    )


def test_atomic_reservation_increases_reserved_without_changing_on_hand(
    repository: SQLiteInventoryRepository,
) -> None:
    result = repository.reserve_if_unchanged(request_for_source())

    assert result.outcome == "reserved"
    assert result.material is not None
    assert result.material.qty_on_hand == 120
    assert result.material.qty_reserved == 10
    persisted = repository.get_material(SKU)
    assert persisted == result.material


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("qty_on_hand", 121),
        ("qty_reserved", 1),
        ("unit_price_cents", 2_800),
        ("discontinued", 1),
    ],
)
def test_changed_bound_state_returns_stale_without_mutating(
    repository: SQLiteInventoryRepository,
    column: str,
    value: int,
) -> None:
    with connect_database(repository.database_path, read_only=False) as connection:
        connection.execute(f"UPDATE materials SET {column} = ? WHERE sku = ?", (value, SKU))
    before = repository.get_material(SKU)

    result = repository.reserve_if_unchanged(request_for_source())

    assert result.outcome == "stale"
    assert result.material == before
    assert repository.get_material(SKU) == before


def test_revalidation_rejects_quantity_above_unchanged_availability(
    repository: SQLiteInventoryRepository,
) -> None:
    result = repository.reserve_if_unchanged(request_for_source(quantity=121))

    assert result.outcome == "stale"
    assert result.material is not None
    assert result.material.qty_reserved == 0


@pytest.mark.parametrize("quantity", [0, -1, True])
def test_transaction_revalidates_positive_integer_quantity(
    repository: SQLiteInventoryRepository, quantity: int
) -> None:
    result = repository.reserve_if_unchanged(request_for_source(quantity=quantity))

    assert result.outcome == "stale"
    assert result.material is not None
    assert result.material.qty_reserved == 0


def test_missing_material_returns_stale(repository: SQLiteInventoryRepository) -> None:
    request = request_for_source()
    missing = ReservationRequest(
        sku="NOT-REAL",
        quantity=request.quantity,
        expected_unit_price=request.expected_unit_price,
        expected_qty_on_hand=request.expected_qty_on_hand,
        expected_qty_reserved=request.expected_qty_reserved,
        expected_discontinued=request.expected_discontinued,
    )

    result = repository.reserve_if_unchanged(missing)

    assert result.outcome == "stale"
    assert result.material is None


def test_concurrent_identical_snapshot_requests_reserve_at_most_once(
    repository: SQLiteInventoryRepository,
) -> None:
    request = request_for_source()
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(repository.reserve_if_unchanged, (request, request)))

    assert sorted(result.outcome for result in results) == ["reserved", "stale"]
    material = repository.get_material(SKU)
    assert material is not None
    assert material.qty_reserved == 10


def test_sqlite_failure_is_generic_and_leaves_existing_state(
    repository: SQLiteInventoryRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @contextmanager
    def failing_connection(*args: object, **kwargs: object):
        raise sqlite3.OperationalError("sensitive database detail")
        yield  # pragma: no cover

    monkeypatch.setattr(sqlite_repository, "connect_database", failing_connection)

    with pytest.raises(ReservationPersistenceError, match="Unable to reserve inventory") as error:
        repository.reserve_if_unchanged(request_for_source())

    assert "sensitive" not in str(error.value)
