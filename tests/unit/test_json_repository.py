from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from inventory_assistant.data.json_repository import InventoryDataError, JsonInventoryRepository

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_DATA = PROJECT_ROOT / "Requirements" / "inventory_data.json"


@pytest.fixture(scope="module")
def source_payload() -> dict[str, object]:
    return json.loads(SOURCE_DATA.read_text(encoding="utf-8"))


def write_payload(tmp_path: Path, payload: object) -> Path:
    path = tmp_path / "inventory.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_loads_expected_source_snapshot() -> None:
    repository = JsonInventoryRepository.load(SOURCE_DATA)

    assert len(repository.dataset.suppliers) == 9
    assert len(repository.dataset.materials) == 77
    assert len(repository.list_materials()) == 77
    assert repository.dataset.meta.currency == "CAD"


@pytest.mark.parametrize(
    ("query", "expected_sku"),
    [
        ("stl-w12x40", "STL-W12X40-A992"),
        ("wide flange beam", "STL-W12X40-A992"),
        ("structural_steel", "STL-W12X40-A992"),
        ("astm a992", "STL-W12X40-A992"),
        ("  yard-1  ", "STL-W12X40-A992"),
    ],
)
def test_searches_literal_source_fields_case_insensitively(query: str, expected_sku: str) -> None:
    repository = JsonInventoryRepository.load(SOURCE_DATA)

    matches = repository.search_materials(query)

    assert expected_sku in {material.sku for material in matches}


def test_empty_search_returns_every_material() -> None:
    repository = JsonInventoryRepository.load(SOURCE_DATA)

    assert repository.search_materials("  \t ") == repository.list_materials()


def test_no_match_does_not_substitute_a_material() -> None:
    repository = JsonInventoryRepository.load(SOURCE_DATA)

    assert repository.search_materials("definitely-not-a-real-sku") == ()


def test_overallocated_source_record_is_valid() -> None:
    repository = JsonInventoryRepository.load(SOURCE_DATA)
    beam = next(
        material for material in repository.list_materials() if material.sku == "STL-W12X40-A992"
    )

    assert beam.qty_reserved > beam.qty_on_hand


def test_missing_file_fails_loading(tmp_path: Path) -> None:
    with pytest.raises(InventoryDataError, match="Unable to read inventory data"):
        JsonInventoryRepository.load(tmp_path / "missing.json")


def test_malformed_json_fails_loading(tmp_path: Path) -> None:
    path = tmp_path / "inventory.json"
    path.write_text("{not-json", encoding="utf-8")

    with pytest.raises(InventoryDataError, match="Invalid inventory data"):
        JsonInventoryRepository.load(path)


@pytest.mark.parametrize(
    "mutator",
    [
        lambda payload: payload["materials"][0].update(qty_on_hand=-1),
        lambda payload: payload["materials"][0].update(qty_on_hand="4"),
        lambda payload: payload["materials"][1].update(sku=payload["materials"][0]["sku"]),
        lambda payload: payload["materials"][0].update(primary_supplier_id="SUP-404"),
        lambda payload: payload["materials"][0].update(currency="USD"),
        lambda payload: payload["materials"][0].pop("warehouse"),
        lambda payload: payload.update(unexpected=True),
    ],
)
def test_invalid_source_data_fails_loading(
    tmp_path: Path,
    source_payload: dict[str, object],
    mutator,
) -> None:
    payload = deepcopy(source_payload)
    mutator(payload)

    with pytest.raises(InventoryDataError, match="Invalid inventory data"):
        JsonInventoryRepository.load(write_payload(tmp_path, payload))
