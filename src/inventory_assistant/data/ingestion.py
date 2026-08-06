"""Repeatable construction of a validated SQLite inventory snapshot."""

from __future__ import annotations

import hashlib
import os
import sqlite3
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from inventory_assistant.data.json_repository import (
    InventoryDataError,
    read_inventory_source,
)
from inventory_assistant.data.models import InventoryDataset, Material
from inventory_assistant.data.sqlite_repository import (
    SCHEMA_VERSION,
    InventoryDatabaseError,
    SQLiteInventoryRepository,
    connect_database,
)

MINIMUM_SQLITE_VERSION = (3, 37, 0)


class InventoryIngestionError(InventoryDataError):
    """Raised when a replacement SQLite snapshot cannot be built safely."""


@dataclass(frozen=True, slots=True)
class IngestionResult:
    database_path: Path
    source_filename: str
    source_sha256: str
    supplier_count: int
    material_count: int


SCHEMA_STATEMENTS = (
    """
    CREATE TABLE inventory_snapshot (
        snapshot_id INTEGER PRIMARY KEY CHECK (snapshot_id = 1),
        schema_version INTEGER NOT NULL CHECK (schema_version = 1),
        dataset_name TEXT NOT NULL CHECK (length(trim(dataset_name)) > 0),
        as_of_date TEXT NOT NULL CHECK (length(trim(as_of_date)) > 0),
        currency TEXT NOT NULL CHECK (length(trim(currency)) > 0),
        notes TEXT NOT NULL CHECK (length(trim(notes)) > 0),
        definition_qty_on_hand TEXT NOT NULL CHECK (length(trim(definition_qty_on_hand)) > 0),
        definition_qty_reserved TEXT NOT NULL CHECK (length(trim(definition_qty_reserved)) > 0),
        definition_qty_available TEXT NOT NULL CHECK (length(trim(definition_qty_available)) > 0),
        definition_min_order_qty TEXT NOT NULL CHECK (length(trim(definition_min_order_qty)) > 0),
        definition_reorder_point TEXT NOT NULL CHECK (length(trim(definition_reorder_point)) > 0),
        source_filename TEXT NOT NULL CHECK (length(trim(source_filename)) > 0),
        source_sha256 TEXT NOT NULL CHECK (length(source_sha256) = 64),
        source_size_bytes INTEGER NOT NULL CHECK (source_size_bytes >= 0),
        ingested_at_utc TEXT NOT NULL CHECK (length(trim(ingested_at_utc)) > 0),
        supplier_count INTEGER NOT NULL CHECK (supplier_count > 0),
        material_count INTEGER NOT NULL CHECK (material_count > 0)
    ) STRICT
    """,
    """
    CREATE TABLE suppliers (
        supplier_id TEXT COLLATE NOCASE PRIMARY KEY,
        snapshot_id INTEGER NOT NULL CHECK (snapshot_id = 1)
            REFERENCES inventory_snapshot(snapshot_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
        source_order INTEGER NOT NULL UNIQUE CHECK (source_order >= 0),
        name TEXT NOT NULL CHECK (length(trim(name)) > 0),
        location TEXT NOT NULL CHECK (length(trim(location)) > 0),
        standard_lead_time_days INTEGER NOT NULL CHECK (standard_lead_time_days >= 0),
        payment_terms TEXT NOT NULL CHECK (length(trim(payment_terms)) > 0)
    ) STRICT
    """,
    """
    CREATE TABLE materials (
        sku TEXT COLLATE NOCASE PRIMARY KEY,
        snapshot_id INTEGER NOT NULL CHECK (snapshot_id = 1)
            REFERENCES inventory_snapshot(snapshot_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
        source_order INTEGER NOT NULL UNIQUE CHECK (source_order >= 0),
        description TEXT NOT NULL CHECK (length(trim(description)) > 0),
        category TEXT NOT NULL CHECK (length(trim(category)) > 0),
        spec_grade TEXT,
        unit_of_measure TEXT NOT NULL CHECK (length(trim(unit_of_measure)) > 0),
        unit_price_cents INTEGER NOT NULL CHECK (unit_price_cents >= 0),
        qty_on_hand INTEGER NOT NULL CHECK (qty_on_hand >= 0),
        qty_reserved INTEGER NOT NULL CHECK (qty_reserved >= 0),
        reorder_point INTEGER NOT NULL CHECK (reorder_point >= 0),
        min_order_qty INTEGER NOT NULL CHECK (min_order_qty > 0),
        primary_supplier_id TEXT COLLATE NOCASE NOT NULL
            REFERENCES suppliers(supplier_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
        warehouse TEXT NOT NULL CHECK (length(trim(warehouse)) > 0),
        discontinued INTEGER NOT NULL CHECK (discontinued IN (0, 1))
    ) STRICT
    """,
    "CREATE INDEX idx_materials_category ON materials(category)",
    "CREATE INDEX idx_materials_supplier ON materials(primary_supplier_id)",
    "CREATE INDEX idx_materials_warehouse ON materials(warehouse)",
)


def ingest_inventory(source_path: Path, database_path: Path) -> IngestionResult:
    """Build and validate a sibling database before replacing the session snapshot."""

    if sqlite3.sqlite_version_info < MINIMUM_SQLITE_VERSION:
        required = ".".join(str(part) for part in MINIMUM_SQLITE_VERSION)
        raise InventoryIngestionError(
            f"SQLite {required} or later is required; found {sqlite3.sqlite_version}"
        )

    resolved_source = source_path.resolve()
    resolved_database = database_path.resolve()
    try:
        dataset, source_bytes = read_inventory_source(resolved_source)
        resolved_database.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            dir=resolved_database.parent,
            prefix=f".{resolved_database.name}.",
            suffix=".tmp",
        )
        os.close(descriptor)
    except InventoryDataError:
        raise
    except OSError as error:
        raise InventoryIngestionError(
            f"Unable to prepare inventory database at {resolved_database}: {error}"
        ) from error

    temporary_path = Path(temporary_name)
    source_sha256 = hashlib.sha256(source_bytes).hexdigest()
    try:
        _build_database(
            temporary_path,
            dataset,
            source_filename=resolved_source.name,
            source_sha256=source_sha256,
            source_size_bytes=len(source_bytes),
        )
        _validate_database(temporary_path, dataset, source_sha256)
        os.replace(temporary_path, resolved_database)
    except InventoryIngestionError:
        raise
    except (OSError, sqlite3.Error, ValueError, InventoryDatabaseError) as error:
        raise InventoryIngestionError(
            f"Unable to build inventory database at {resolved_database}: {error}"
        ) from error
    finally:
        with suppress(OSError):
            temporary_path.unlink(missing_ok=True)

    return IngestionResult(
        database_path=resolved_database,
        source_filename=resolved_source.name,
        source_sha256=source_sha256,
        supplier_count=len(dataset.suppliers),
        material_count=len(dataset.materials),
    )


def _build_database(
    database_path: Path,
    dataset: InventoryDataset,
    *,
    source_filename: str,
    source_sha256: str,
    source_size_bytes: int,
) -> None:
    with connect_database(database_path, read_only=False) as connection:
        journal_mode = connection.execute("PRAGMA journal_mode = DELETE").fetchone()[0]
        if journal_mode.casefold() != "delete":
            raise InventoryIngestionError(
                f"Unable to enable SQLite rollback journal mode; found {journal_mode}"
            )
        connection.execute("PRAGMA synchronous = FULL")
        connection.execute("BEGIN IMMEDIATE")
        try:
            for statement in SCHEMA_STATEMENTS:
                connection.execute(statement)
            _insert_snapshot(
                connection,
                dataset,
                source_filename=source_filename,
                source_sha256=source_sha256,
                source_size_bytes=source_size_bytes,
            )
            _insert_suppliers(connection, dataset)
            _insert_materials(connection, dataset)
            connection.execute("COMMIT")
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise


def _insert_snapshot(
    connection: sqlite3.Connection,
    dataset: InventoryDataset,
    *,
    source_filename: str,
    source_sha256: str,
    source_size_bytes: int,
) -> None:
    meta = dataset.meta
    definitions = meta.definitions
    connection.execute(
        """
        INSERT INTO inventory_snapshot (
            snapshot_id, schema_version, dataset_name, as_of_date, currency, notes,
            definition_qty_on_hand, definition_qty_reserved, definition_qty_available,
            definition_min_order_qty, definition_reorder_point, source_filename,
            source_sha256, source_size_bytes, ingested_at_utc, supplier_count,
            material_count
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            1,
            SCHEMA_VERSION,
            meta.dataset_name,
            meta.as_of_date.isoformat(),
            meta.currency,
            meta.notes,
            definitions.qty_on_hand,
            definitions.qty_reserved,
            definitions.qty_available,
            definitions.min_order_qty,
            definitions.reorder_point,
            source_filename,
            source_sha256,
            source_size_bytes,
            datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            len(dataset.suppliers),
            len(dataset.materials),
        ),
    )


def _insert_suppliers(connection: sqlite3.Connection, dataset: InventoryDataset) -> None:
    connection.executemany(
        """
        INSERT INTO suppliers (
            supplier_id, snapshot_id, source_order, name, location,
            standard_lead_time_days, payment_terms
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            (
                supplier.supplier_id,
                1,
                source_order,
                supplier.name,
                supplier.location,
                supplier.standard_lead_time_days,
                supplier.payment_terms,
            )
            for source_order, supplier in enumerate(dataset.suppliers)
        ),
    )


def _insert_materials(connection: sqlite3.Connection, dataset: InventoryDataset) -> None:
    connection.executemany(
        """
        INSERT INTO materials (
            sku, snapshot_id, source_order, description, category, spec_grade,
            unit_of_measure, unit_price_cents, qty_on_hand, qty_reserved, reorder_point,
            min_order_qty, primary_supplier_id, warehouse, discontinued
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            (
                material.sku,
                1,
                source_order,
                material.description,
                material.category,
                material.spec_grade,
                material.unit_of_measure,
                _price_in_cents(material),
                material.qty_on_hand,
                material.qty_reserved,
                material.reorder_point,
                material.min_order_qty,
                material.primary_supplier_id,
                material.warehouse,
                int(material.discontinued),
            )
            for source_order, material in enumerate(dataset.materials)
        ),
    )


def _price_in_cents(material: Material) -> int:
    cents = material.unit_price * Decimal(100)
    if cents != cents.to_integral_value():
        raise InventoryIngestionError(
            f"Material {material.sku} unit_price has more than two fractional digits"
        )
    return int(cents)


def _validate_database(
    database_path: Path,
    dataset: InventoryDataset,
    source_sha256: str,
) -> None:
    with connect_database(database_path) as connection:
        integrity = [row[0] for row in connection.execute("PRAGMA integrity_check")]
        if integrity != ["ok"]:
            raise InventoryIngestionError(f"SQLite integrity check failed: {', '.join(integrity)}")
        foreign_key_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
        if foreign_key_errors:
            raise InventoryIngestionError("SQLite foreign-key check failed")

    repository = SQLiteInventoryRepository(database_path)
    record = repository.ingestion_record
    if record.source_sha256 != source_sha256:
        raise InventoryIngestionError("SQLite source hash does not match the input snapshot")
    if repository.meta != dataset.meta:
        raise InventoryIngestionError("SQLite metadata does not match the input snapshot")
    if repository.list_suppliers() != dataset.suppliers:
        raise InventoryIngestionError("SQLite suppliers do not match the input snapshot")
    if repository.list_materials() != dataset.materials:
        raise InventoryIngestionError("SQLite materials do not match the input snapshot")
