from __future__ import annotations

import hashlib
import json
import sqlite3
from copy import deepcopy
from pathlib import Path

import pytest

from inventory_assistant.application.catalog import CatalogService
from inventory_assistant.application.inventory import InventoryService
from inventory_assistant.application.suppliers import SupplierService
from inventory_assistant.data import ingestion
from inventory_assistant.data.ingestion import InventoryIngestionError, ingest_inventory
from inventory_assistant.data.json_repository import (
    InventoryDataError,
    JsonInventoryRepository,
)
from inventory_assistant.data.sqlite_repository import (
    InventoryDatabaseError,
    SQLiteInventoryRepository,
    connect_database,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_DATA = PROJECT_ROOT / "Requirements" / "inventory_data.json"


@pytest.fixture(scope="module")
def source_payload() -> dict[str, object]:
    return json.loads(SOURCE_DATA.read_text(encoding="utf-8"))


def write_payload(tmp_path: Path, payload: object, name: str = "inventory.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_ingestion_preserves_complete_json_repository_parity(tmp_path: Path) -> None:
    database_path = tmp_path / "inventory.sqlite3"
    result = ingest_inventory(SOURCE_DATA, database_path)
    json_repository = JsonInventoryRepository.load(SOURCE_DATA)
    sqlite_repository = SQLiteInventoryRepository(database_path)

    assert sqlite_repository.meta == json_repository.meta
    assert sqlite_repository.list_suppliers() == json_repository.list_suppliers()
    assert sqlite_repository.list_materials() == json_repository.list_materials()
    assert sqlite_repository.get_material("stl-w12x40-a992") == json_repository.get_material(
        "stl-w12x40-a992"
    )
    assert sqlite_repository.get_supplier("sup-002") == json_repository.get_supplier("sup-002")
    assert result.database_path == database_path.resolve()
    assert result.supplier_count == 9
    assert result.material_count == 77


def test_json_and_sqlite_application_service_results_are_identical(tmp_path: Path) -> None:
    database_path = tmp_path / "inventory.sqlite3"
    ingest_inventory(SOURCE_DATA, database_path)
    json_repository = JsonInventoryRepository.load(SOURCE_DATA)
    sqlite_repository = SQLiteInventoryRepository(database_path)

    assert (
        CatalogService(sqlite_repository).get_summary()
        == CatalogService(json_repository).get_summary()
    )

    json_inventory = InventoryService(json_repository)
    sqlite_inventory = InventoryService(sqlite_repository)
    for query in ("STL-W12X40-A992", "W12x40 beams", "rebar", "not-real"):
        assert sqlite_inventory.search(query) == json_inventory.search(query)
    assert sqlite_inventory.list_overallocation_alerts() == (
        json_inventory.list_overallocation_alerts()
    )

    json_suppliers = SupplierService(json_repository)
    sqlite_suppliers = SupplierService(sqlite_repository)
    for category in ("rebar", "sheet metal", "not-real"):
        assert sqlite_suppliers.find_for_category(category) == json_suppliers.find_for_category(
            category
        )


def test_schema_is_strict_normalized_indexed_and_does_not_store_availability(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "inventory.sqlite3"
    ingest_inventory(SOURCE_DATA, database_path)

    with connect_database(database_path) as connection:
        tables = {
            row["name"]: row["strict"]
            for row in connection.execute("PRAGMA table_list")
            if row["name"] in {"inventory_snapshot", "suppliers", "materials"}
        }
        material_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(materials)")
        }
        indexes = {row["name"] for row in connection.execute("PRAGMA index_list(materials)")}
        beam_price = connection.execute(
            "SELECT unit_price_cents FROM materials WHERE sku = 'STL-W12X40-A992'"
        ).fetchone()[0]
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]

    assert tables == {"inventory_snapshot": 1, "suppliers": 1, "materials": 1}
    assert "qty_available" not in material_columns
    assert "currency" not in material_columns
    assert "unit_price_cents" in material_columns
    assert {
        "idx_materials_category",
        "idx_materials_supplier",
        "idx_materials_warehouse",
    } <= indexes
    assert beam_price == 74250
    assert journal_mode == "delete"


def test_ingestion_record_identifies_exact_source_bytes(tmp_path: Path) -> None:
    database_path = tmp_path / "inventory.sqlite3"
    source_bytes = SOURCE_DATA.read_bytes()
    ingest_inventory(SOURCE_DATA, database_path)

    record = SQLiteInventoryRepository(database_path).ingestion_record

    assert record.schema_version == 1
    assert record.source_filename == "inventory_data.json"
    assert record.source_sha256 == hashlib.sha256(source_bytes).hexdigest()
    assert record.source_size_bytes == len(source_bytes)
    assert record.ingested_at_utc.endswith("Z")
    assert record.supplier_count == 9
    assert record.material_count == 77


def test_constraints_and_foreign_keys_are_enforced(tmp_path: Path) -> None:
    database_path = tmp_path / "inventory.sqlite3"
    ingest_inventory(SOURCE_DATA, database_path)

    with connect_database(database_path, read_only=False) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE materials SET qty_on_hand = -1 WHERE sku = 'STL-W12X40-A992'"
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                UPDATE materials SET primary_supplier_id = 'SUP-404'
                WHERE sku = 'STL-W12X40-A992'
                """
            )

        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_repeated_ingestion_replaces_runtime_changes_with_source_values(tmp_path: Path) -> None:
    database_path = tmp_path / "inventory.sqlite3"
    ingest_inventory(SOURCE_DATA, database_path)
    with connect_database(database_path, read_only=False) as connection:
        connection.execute("UPDATE materials SET qty_reserved = 99 WHERE sku = 'STL-W12X40-A992'")

    assert (
        SQLiteInventoryRepository(database_path).get_material("STL-W12X40-A992").qty_reserved == 99
    )

    ingest_inventory(SOURCE_DATA, database_path)

    assert (
        SQLiteInventoryRepository(database_path).get_material("STL-W12X40-A992").qty_reserved == 6
    )


@pytest.mark.parametrize("failure_kind", ["invalid_json", "price_precision", "replace"])
def test_failed_ingestion_preserves_prior_database_and_cleans_temporary_files(
    tmp_path: Path,
    source_payload: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
    failure_kind: str,
) -> None:
    database_path = tmp_path / "inventory.sqlite3"
    ingest_inventory(SOURCE_DATA, database_path)
    original_bytes = database_path.read_bytes()

    if failure_kind == "invalid_json":
        failing_source = tmp_path / "invalid.json"
        failing_source.write_text("{invalid", encoding="utf-8")
        expected_error = InventoryDataError
    elif failure_kind == "price_precision":
        payload = deepcopy(source_payload)
        payload["materials"][0]["unit_price"] = 1.001
        failing_source = write_payload(tmp_path, payload, "precision.json")
        expected_error = InventoryIngestionError
    else:
        failing_source = SOURCE_DATA

        def fail_replace(source: Path, destination: Path) -> None:
            raise OSError("simulated replacement failure")

        monkeypatch.setattr(ingestion.os, "replace", fail_replace)
        expected_error = InventoryIngestionError

    with pytest.raises(expected_error):
        ingest_inventory(failing_source, database_path)

    assert database_path.read_bytes() == original_bytes
    assert list(tmp_path.glob(f".{database_path.name}.*.tmp")) == []


def test_ingestion_rejects_unsupported_sqlite_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sqlite3, "sqlite_version_info", (3, 36, 0))

    with pytest.raises(InventoryIngestionError, match="SQLite 3.37.0 or later"):
        ingest_inventory(SOURCE_DATA, tmp_path / "inventory.sqlite3")


def test_repository_rejects_missing_or_malformed_database(tmp_path: Path) -> None:
    with pytest.raises(InventoryDatabaseError, match="does not exist"):
        SQLiteInventoryRepository(tmp_path / "missing.sqlite3")

    malformed = tmp_path / "malformed.sqlite3"
    sqlite3.connect(malformed).close()
    with pytest.raises(InventoryDatabaseError, match="Invalid inventory database"):
        SQLiteInventoryRepository(malformed)
