"""Deterministic supplier lookup use cases."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from inventory_assistant.application.matching import all_tokens_match
from inventory_assistant.data.models import Supplier
from inventory_assistant.data.repository import InventoryRepository

SupplierSearchOutcome = Literal["unique_match", "ambiguous", "no_match"]


@dataclass(frozen=True, slots=True)
class SupplierSearchResult:
    outcome: SupplierSearchOutcome
    category: str
    message: str
    supplier: Supplier | None = None
    candidates: tuple[Supplier, ...] = ()


def render_supplier_message(supplier: Supplier) -> str:
    return (
        f"{supplier.name} ({supplier.supplier_id}) has payment terms "
        f"{supplier.payment_terms} and a standard lead time of "
        f"{supplier.standard_lead_time_days} days."
    )


class SupplierService:
    def __init__(self, repository: InventoryRepository) -> None:
        self._repository = repository

    def get_by_id(self, supplier_id: str) -> Supplier | None:
        return self._repository.get_supplier(supplier_id)

    def find_for_category(self, category: str) -> SupplierSearchResult:
        cleaned = " ".join(category.split())
        supplier_ids = {
            material.primary_supplier_id
            for material in self._repository.list_materials()
            if all_tokens_match(cleaned, (material.category,))
        }
        suppliers = tuple(
            supplier
            for supplier in self._repository.list_suppliers()
            if supplier.supplier_id in supplier_ids
        )

        if len(suppliers) == 1:
            supplier = suppliers[0]
            return SupplierSearchResult(
                outcome="unique_match",
                category=cleaned,
                message=render_supplier_message(supplier),
                supplier=supplier,
            )
        if not suppliers:
            return SupplierSearchResult(
                outcome="no_match",
                category=cleaned,
                message=f"No supplier is linked to catalogue category '{cleaned}'.",
            )

        candidate_names = ", ".join(
            f"{supplier.name} ({supplier.supplier_id})" for supplier in suppliers
        )
        return SupplierSearchResult(
            outcome="ambiguous",
            category=cleaned,
            message=f"Multiple suppliers serve category '{cleaned}': {candidate_names}.",
            candidates=suppliers,
        )
