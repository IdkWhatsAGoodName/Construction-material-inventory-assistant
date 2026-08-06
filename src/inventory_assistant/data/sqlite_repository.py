"""SQLite-backed inventory repository."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from inventory_assistant.data.models import DatasetMeta, Definitions, Material, Supplier

SCHEMA_VERSION = 1
BUSY_TIMEOUT_MS = 5_000


class InventoryDatabaseError(RuntimeError):
    """Raised when a SQLite inventory snapshot cannot be read safely."""


@dataclass(frozen=True, slots=True)
class IngestionRecord:
    schema_version: int
    source_filename: str
    source_sha256: str
    source_size_bytes: int
    ingested_at_utc: str
    supplier_count: int
    material_count: int


class SQLiteInventoryRepository:
    """Read a validated SQLite inventory snapshot using operation-scoped connections."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path.resolve()
        self._validate_snapshot()

    @property
    def database_path(self) -> Path:
        return self._database_path

    @property
    def meta(self) -> DatasetMeta:
        with connect_database(self._database_path) as connection:
            row = _fetch_snapshot(connection)
        return _meta_from_row(row)

    @property
    def ingestion_record(self) -> IngestionRecord:
        with connect_database(self._database_path) as connection:
            row = _fetch_snapshot(connection)
        return IngestionRecord(
            schema_version=row["schema_version"],
            source_filename=row["source_filename"],
            source_sha256=row["source_sha256"],
            source_size_bytes=row["source_size_bytes"],
            ingested_at_utc=row["ingested_at_utc"],
            supplier_count=row["supplier_count"],
            material_count=row["material_count"],
        )

    def list_materials(self) -> tuple[Material, ...]:
        with connect_database(self._database_path) as connection:
            rows = connection.execute(
                """
                SELECT materials.*, inventory_snapshot.currency
                FROM materials
                JOIN inventory_snapshot USING (snapshot_id)
                ORDER BY materials.source_order
                """
            ).fetchall()
        return tuple(_material_from_row(row) for row in rows)

    def list_suppliers(self) -> tuple[Supplier, ...]:
        with connect_database(self._database_path) as connection:
            rows = connection.execute("SELECT * FROM suppliers ORDER BY source_order").fetchall()
        return tuple(_supplier_from_row(row) for row in rows)

    def get_material(self, sku: str) -> Material | None:
        with connect_database(self._database_path) as connection:
            row = connection.execute(
                """
                SELECT materials.*, inventory_snapshot.currency
                FROM materials
                JOIN inventory_snapshot USING (snapshot_id)
                WHERE materials.sku = ? COLLATE NOCASE
                """,
                (sku.strip(),),
            ).fetchone()
        return _material_from_row(row) if row else None

    def get_supplier(self, supplier_id: str) -> Supplier | None:
        with connect_database(self._database_path) as connection:
            row = connection.execute(
                "SELECT * FROM suppliers WHERE supplier_id = ? COLLATE NOCASE",
                (supplier_id.strip(),),
            ).fetchone()
        return _supplier_from_row(row) if row else None

    def _validate_snapshot(self) -> None:
        if not self._database_path.is_file():
            raise InventoryDatabaseError(
                f"Inventory database does not exist at {self._database_path}"
            )
        try:
            with connect_database(self._database_path) as connection:
                row = _fetch_snapshot(connection)
                if row["schema_version"] != SCHEMA_VERSION:
                    raise InventoryDatabaseError(
                        f"Unsupported inventory database schema version: {row['schema_version']}"
                    )
        except InventoryDatabaseError:
            raise
        except sqlite3.Error as error:
            raise InventoryDatabaseError(
                f"Invalid inventory database at {self._database_path}: {error}"
            ) from error


@contextmanager
def connect_database(
    database_path: Path, *, read_only: bool = True
) -> Iterator[sqlite3.Connection]:
    """Open a configured connection without sharing it across request threads."""

    resolved = database_path.resolve()
    if read_only:
        connection = sqlite3.connect(
            f"{resolved.as_uri()}?mode=ro",
            uri=True,
            autocommit=True,
            timeout=BUSY_TIMEOUT_MS / 1_000,
        )
    else:
        connection = sqlite3.connect(
            resolved,
            autocommit=True,
            timeout=BUSY_TIMEOUT_MS / 1_000,
        )
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        foreign_keys = connection.execute("PRAGMA foreign_keys").fetchone()[0]
        if foreign_keys != 1:
            raise InventoryDatabaseError("SQLite foreign-key enforcement is unavailable")
        connection.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        if read_only:
            connection.execute("PRAGMA query_only = ON")
        yield connection
    finally:
        connection.close()


def _fetch_snapshot(connection: sqlite3.Connection) -> sqlite3.Row:
    rows = connection.execute("SELECT * FROM inventory_snapshot").fetchall()
    if len(rows) != 1:
        raise InventoryDatabaseError(
            f"Inventory database must contain exactly one snapshot; found {len(rows)}"
        )
    return rows[0]


def _meta_from_row(row: sqlite3.Row) -> DatasetMeta:
    return DatasetMeta(
        dataset_name=row["dataset_name"],
        as_of_date=row["as_of_date"],
        currency=row["currency"],
        notes=row["notes"],
        definitions=Definitions(
            qty_on_hand=row["definition_qty_on_hand"],
            qty_reserved=row["definition_qty_reserved"],
            qty_available=row["definition_qty_available"],
            min_order_qty=row["definition_min_order_qty"],
            reorder_point=row["definition_reorder_point"],
        ),
    )


def _supplier_from_row(row: sqlite3.Row) -> Supplier:
    return Supplier(
        supplier_id=row["supplier_id"],
        name=row["name"],
        location=row["location"],
        standard_lead_time_days=row["standard_lead_time_days"],
        payment_terms=row["payment_terms"],
    )


def _material_from_row(row: sqlite3.Row) -> Material:
    return Material(
        sku=row["sku"],
        description=row["description"],
        category=row["category"],
        spec_grade=row["spec_grade"],
        unit_of_measure=row["unit_of_measure"],
        unit_price=Decimal(row["unit_price_cents"]) / Decimal(100),
        currency=row["currency"],
        qty_on_hand=row["qty_on_hand"],
        qty_reserved=row["qty_reserved"],
        reorder_point=row["reorder_point"],
        min_order_qty=row["min_order_qty"],
        primary_supplier_id=row["primary_supplier_id"],
        warehouse=row["warehouse"],
        discontinued=bool(row["discontinued"]),
    )
