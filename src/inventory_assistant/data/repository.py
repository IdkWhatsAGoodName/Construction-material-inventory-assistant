"""Persistence-independent read-only inventory repository contract."""

from __future__ import annotations

from typing import Protocol

from inventory_assistant.data.models import DatasetMeta, Material, Supplier


class InventoryRepository(Protocol):
    """Data operations required by deterministic read-only application services."""

    @property
    def meta(self) -> DatasetMeta: ...

    def list_materials(self) -> tuple[Material, ...]: ...

    def list_suppliers(self) -> tuple[Supplier, ...]: ...

    def get_material(self, sku: str) -> Material | None: ...

    def get_supplier(self, supplier_id: str) -> Supplier | None: ...
