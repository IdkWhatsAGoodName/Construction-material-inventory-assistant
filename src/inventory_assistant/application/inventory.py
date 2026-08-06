"""Deterministic read-only inventory use cases."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from inventory_assistant.application.matching import all_tokens_match, normalize_text
from inventory_assistant.data.models import Material
from inventory_assistant.data.repository import InventoryRepository
from inventory_assistant.domain.inventory import InventoryItem, render_inventory_message

SearchOutcome = Literal["exact_match", "unique_match", "ambiguous", "no_match"]


@dataclass(frozen=True, slots=True)
class InventorySearchResult:
    outcome: SearchOutcome
    query: str
    message: str
    item: InventoryItem | None = None
    candidates: tuple[InventoryItem, ...] = ()


class InventoryService:
    """Read inventory through conservative matching and derived domain rules."""

    def __init__(self, repository: InventoryRepository) -> None:
        self._repository = repository

    def list_materials(self, query: str = "") -> tuple[InventoryItem, ...]:
        materials = self._repository.list_materials()
        if query.strip():
            materials = tuple(
                material for material in materials if _matches_material(query, material)
            )
        return tuple(InventoryItem.from_material(material) for material in materials)

    def get_by_sku(self, sku: str) -> InventoryItem | None:
        material = self._repository.get_material(sku)
        return InventoryItem.from_material(material) if material else None

    def search(self, query: str) -> InventorySearchResult:
        cleaned = " ".join(query.split())
        exact = self._find_exact(cleaned)
        if exact is not None:
            item = InventoryItem.from_material(exact)
            return InventorySearchResult(
                outcome="exact_match",
                query=cleaned,
                message=render_inventory_message(item),
                item=item,
            )

        matches = self.list_materials(cleaned)
        if len(matches) == 1:
            item = matches[0]
            return InventorySearchResult(
                outcome="unique_match",
                query=cleaned,
                message=render_inventory_message(item),
                item=item,
            )
        if not matches:
            return InventorySearchResult(
                outcome="no_match",
                query=cleaned,
                message=f"No catalogue material matches '{cleaned}'. No substitute was selected.",
            )

        candidate_skus = ", ".join(item.sku for item in matches)
        return InventorySearchResult(
            outcome="ambiguous",
            query=cleaned,
            message=f"Multiple catalogue materials match '{cleaned}': {candidate_skus}.",
            candidates=matches,
        )

    def list_overallocation_alerts(self) -> tuple[InventoryItem, ...]:
        return tuple(item for item in self.list_materials() if "overallocated" in item.conditions)

    def _find_exact(self, query: str) -> Material | None:
        normalized_query = normalize_text(query)
        if not normalized_query:
            return None

        direct = self._repository.get_material(query)
        if direct is not None:
            return direct

        description_matches = tuple(
            material
            for material in self._repository.list_materials()
            if normalize_text(material.description) == normalized_query
        )
        return description_matches[0] if len(description_matches) == 1 else None


def _matches_material(query: str, material: Material) -> bool:
    return all_tokens_match(
        query,
        (
            material.sku,
            material.description,
            material.category,
            material.spec_grade or "",
            material.unit_of_measure,
        ),
    )
