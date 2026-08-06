"""Persistence-independent inventory repository contracts."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, Protocol

from inventory_assistant.data.models import DatasetMeta, Material, Supplier


class InventoryRepository(Protocol):
    """Data operations required by deterministic read-only application services."""

    @property
    def meta(self) -> DatasetMeta: ...

    def list_materials(self) -> tuple[Material, ...]: ...

    def list_suppliers(self) -> tuple[Supplier, ...]: ...

    def get_material(self, sku: str) -> Material | None: ...

    def get_supplier(self, supplier_id: str) -> Supplier | None: ...


@dataclass(frozen=True, slots=True)
class ReservationRequest:
    """Expected snapshot and requested mutation for an atomic reservation."""

    sku: str
    quantity: int
    expected_unit_price: Decimal
    expected_qty_on_hand: int
    expected_qty_reserved: int
    expected_discontinued: bool


@dataclass(frozen=True, slots=True)
class ReservationResult:
    outcome: Literal["reserved", "stale"]
    material: Material | None


class ReservationRepository(Protocol):
    """Write capability required only by confirmed customer orders."""

    def reserve_if_unchanged(self, request: ReservationRequest) -> ReservationResult: ...
