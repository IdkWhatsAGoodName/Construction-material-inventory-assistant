from __future__ import annotations

from pathlib import Path

import pytest

from inventory_assistant.application.inventory import InventoryService
from inventory_assistant.application.suppliers import SupplierService
from inventory_assistant.data.json_repository import JsonInventoryRepository

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_DATA = PROJECT_ROOT / "Requirements" / "inventory_data.json"


@pytest.fixture(scope="module")
def repository() -> JsonInventoryRepository:
    return JsonInventoryRepository.load(SOURCE_DATA)


@pytest.mark.parametrize(
    ("query", "outcome", "sku"),
    [
        ("STL-W12X40-A992", "exact_match", "STL-W12X40-A992"),
        ("W12x40 beams", "unique_match", "STL-W12X40-A992"),
        ("20M epoxy rebars", "unique_match", "RBR-20M-EPOXY"),
        ("3/8 inch steel plate", "unique_match", "STL-PL38-A36"),
    ],
)
def test_inventory_search_resolves_exact_and_unique_matches(
    repository: JsonInventoryRepository, query: str, outcome: str, sku: str
) -> None:
    result = InventoryService(repository).search(query)

    assert result.outcome == outcome
    assert result.item is not None
    assert result.item.sku == sku


def test_inventory_search_does_not_substitute_missing_variant(
    repository: JsonInventoryRepository,
) -> None:
    result = InventoryService(repository).search("25M epoxy rebars")

    assert result.outcome == "no_match"
    assert result.item is None
    assert result.candidates == ()
    assert "No substitute was selected" in result.message


def test_inventory_search_reports_ambiguity(repository: JsonInventoryRepository) -> None:
    result = InventoryService(repository).search("rebar")

    assert result.outcome == "ambiguous"
    assert result.item is None
    assert len(result.candidates) == 10


def test_overallocation_alerts_contain_only_discrepancies(
    repository: JsonInventoryRepository,
) -> None:
    alerts = InventoryService(repository).list_overallocation_alerts()

    assert [alert.sku for alert in alerts] == ["STL-W12X40-A992"]


@pytest.mark.parametrize(
    ("category", "outcome", "supplier_id", "candidate_ids"),
    [
        ("rebar", "unique_match", "SUP-002", []),
        ("sheet metal", "ambiguous", None, ["SUP-003", "SUP-009"]),
        ("imaginary category", "no_match", None, []),
    ],
)
def test_supplier_category_outcomes(
    repository: JsonInventoryRepository,
    category: str,
    outcome: str,
    supplier_id: str | None,
    candidate_ids: list[str],
) -> None:
    result = SupplierService(repository).find_for_category(category)

    assert result.outcome == outcome
    assert (result.supplier.supplier_id if result.supplier else None) == supplier_id
    assert [candidate.supplier_id for candidate in result.candidates] == candidate_ids


def test_supplier_lookup_is_case_insensitive(repository: JsonInventoryRepository) -> None:
    supplier = SupplierService(repository).get_by_id("sup-002")

    assert supplier is not None
    assert supplier.name == "Grand River Rebar Ltd."
    assert supplier.payment_terms == "NET30"
    assert supplier.standard_lead_time_days == 7
