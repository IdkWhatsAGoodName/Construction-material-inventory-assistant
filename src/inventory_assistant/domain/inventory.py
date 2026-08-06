"""Derived inventory quantities and status classification."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from inventory_assistant.data.models import Material

InventoryPrimaryStatus = Literal["discontinued", "overallocated", "unavailable", "available"]
InventoryCondition = Literal[
    "discontinued",
    "overallocated",
    "zero_on_hand",
    "fully_reserved",
    "reorder_required",
]


@dataclass(frozen=True, slots=True)
class InventoryItem:
    """A source material with all deterministic inventory facts derived from it."""

    sku: str
    description: str
    category: str
    spec_grade: str | None
    unit_of_measure: str
    unit_price: Decimal
    currency: str
    qty_on_hand: int
    qty_reserved: int
    qty_available: int
    qty_shippable: int
    overallocated_by: int
    reorder_point: int
    min_order_qty: int
    primary_supplier_id: str
    warehouse: str
    discontinued: bool
    status: InventoryPrimaryStatus
    conditions: tuple[InventoryCondition, ...]

    @classmethod
    def from_material(cls, material: Material) -> InventoryItem:
        qty_available = material.qty_on_hand - material.qty_reserved
        qty_shippable = max(qty_available, 0)
        overallocated_by = max(-qty_available, 0)

        conditions: list[InventoryCondition] = []
        if material.discontinued:
            conditions.append("discontinued")
        if overallocated_by:
            conditions.append("overallocated")
        if material.qty_on_hand == 0:
            conditions.append("zero_on_hand")
        if material.qty_on_hand > 0 and qty_available == 0:
            conditions.append("fully_reserved")
        if qty_available <= material.reorder_point:
            conditions.append("reorder_required")

        if material.discontinued:
            status: InventoryPrimaryStatus = "discontinued"
        elif overallocated_by:
            status = "overallocated"
        elif qty_shippable == 0:
            status = "unavailable"
        else:
            status = "available"

        return cls(
            sku=material.sku,
            description=material.description,
            category=material.category,
            spec_grade=material.spec_grade,
            unit_of_measure=material.unit_of_measure,
            unit_price=material.unit_price,
            currency=material.currency,
            qty_on_hand=material.qty_on_hand,
            qty_reserved=material.qty_reserved,
            qty_available=qty_available,
            qty_shippable=qty_shippable,
            overallocated_by=overallocated_by,
            reorder_point=material.reorder_point,
            min_order_qty=material.min_order_qty,
            primary_supplier_id=material.primary_supplier_id,
            warehouse=material.warehouse,
            discontinued=material.discontinued,
            status=status,
            conditions=tuple(conditions),
        )


def render_inventory_message(item: InventoryItem) -> str:
    """Render inventory facts without model-authored arithmetic or interpretation."""

    unit = item.unit_of_measure
    if item.overallocated_by:
        return (
            f"{item.description} ({item.sku}): 0 {unit} can ship from {item.warehouse}. "
            f"Inventory is over-allocated by {item.overallocated_by} {unit}: "
            f"{item.qty_on_hand} on hand and {item.qty_reserved} reserved."
        )

    base = (
        f"{item.description} ({item.sku}): {item.qty_shippable} {unit} can ship from "
        f"{item.warehouse} ({item.qty_on_hand} on hand minus {item.qty_reserved} reserved)."
    )
    if item.discontinued:
        return f"{base} The material is discontinued and cannot be ordered."
    return base
