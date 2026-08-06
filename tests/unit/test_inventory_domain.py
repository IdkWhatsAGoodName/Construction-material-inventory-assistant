from __future__ import annotations

from collections import Counter
from pathlib import Path

from inventory_assistant.data.json_repository import JsonInventoryRepository
from inventory_assistant.domain.inventory import InventoryItem, render_inventory_message

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_DATA = PROJECT_ROOT / "Requirements" / "inventory_data.json"


def inventory_items() -> tuple[InventoryItem, ...]:
    repository = JsonInventoryRepository.load(SOURCE_DATA)
    return tuple(InventoryItem.from_material(material) for material in repository.list_materials())


def test_all_source_records_use_the_mandated_availability_formulas() -> None:
    for item in inventory_items():
        assert item.qty_available == item.qty_on_hand - item.qty_reserved
        assert item.qty_shippable == max(item.qty_available, 0)
        assert item.overallocated_by == max(-item.qty_available, 0)


def test_snapshot_has_expected_primary_statuses_and_conditions() -> None:
    items = inventory_items()

    assert Counter(item.status for item in items) == {
        "available": 69,
        "unavailable": 5,
        "discontinued": 2,
        "overallocated": 1,
    }
    assert Counter(condition for item in items for condition in item.conditions) == {
        "reorder_required": 21,
        "zero_on_hand": 4,
        "fully_reserved": 2,
        "discontinued": 2,
        "overallocated": 1,
    }


def test_overallocated_message_never_calls_negative_stock_shippable() -> None:
    beam = next(item for item in inventory_items() if item.sku == "STL-W12X40-A992")

    assert beam.qty_available == -2
    assert beam.qty_shippable == 0
    assert beam.overallocated_by == 2
    assert beam.conditions == ("overallocated", "reorder_required")
    assert render_inventory_message(beam) == (
        "W12x40 wide flange beam, 40 ft length (STL-W12X40-A992): 0 each can ship "
        "from YARD-1. Inventory is over-allocated by 2 each: 4 on hand and 6 reserved."
    )


def test_fully_reserved_and_discontinued_are_classified_separately() -> None:
    items = {item.sku: item for item in inventory_items()}

    epoxy_rebar = items["RBR-20M-EPOXY"]
    assert epoxy_rebar.status == "unavailable"
    assert "fully_reserved" in epoxy_rebar.conditions
    assert epoxy_rebar.qty_shippable == 0

    plate = items["STL-PL38-A36"]
    assert plate.status == "discontinued"
    assert plate.qty_shippable == 4
    assert render_inventory_message(plate).endswith(
        "The material is discontinued and cannot be ordered."
    )
