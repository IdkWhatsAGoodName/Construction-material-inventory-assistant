"""Read-only catalogue use cases shared by HTTP and future agent tools."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from inventory_assistant.data.repository import InventoryRepository
from inventory_assistant.domain.inventory import InventoryItem

from .inventory import InventoryService


@dataclass(frozen=True, slots=True)
class CatalogSummary:
    dataset_name: str
    as_of_date: date
    currency: str
    notes: str
    supplier_count: int
    material_count: int


class CatalogService:
    """Application boundary for the JSON-reading MVP."""

    def __init__(self, repository: InventoryRepository) -> None:
        self._repository = repository
        self._inventory = InventoryService(repository)

    def get_summary(self) -> CatalogSummary:
        meta = self._repository.meta
        return CatalogSummary(
            dataset_name=meta.dataset_name,
            as_of_date=meta.as_of_date,
            currency=meta.currency,
            notes=meta.notes,
            supplier_count=len(self._repository.list_suppliers()),
            material_count=len(self._repository.list_materials()),
        )

    def find_materials(self, query: str = "") -> tuple[InventoryItem, ...]:
        return self._inventory.list_materials(query)
