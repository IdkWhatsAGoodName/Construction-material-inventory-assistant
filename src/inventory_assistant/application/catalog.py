"""Read-only catalogue use cases shared by HTTP and future agent tools."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from inventory_assistant.data.json_repository import JsonInventoryRepository
from inventory_assistant.data.models import Material


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

    def __init__(self, repository: JsonInventoryRepository) -> None:
        self._repository = repository

    def get_summary(self) -> CatalogSummary:
        dataset = self._repository.dataset
        return CatalogSummary(
            dataset_name=dataset.meta.dataset_name,
            as_of_date=dataset.meta.as_of_date,
            currency=dataset.meta.currency,
            notes=dataset.meta.notes,
            supplier_count=len(dataset.suppliers),
            material_count=len(dataset.materials),
        )

    def find_materials(self, query: str = "") -> tuple[Material, ...]:
        return self._repository.search_materials(query)
