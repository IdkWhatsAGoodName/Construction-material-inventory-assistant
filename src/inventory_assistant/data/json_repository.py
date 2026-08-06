"""Read-only JSON inventory repository."""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from inventory_assistant.data.models import InventoryDataset, Material


class InventoryDataError(RuntimeError):
    """Raised when the configured inventory source cannot be loaded safely."""


class JsonInventoryRepository:
    """Immutable, validated snapshot of the supplied inventory JSON."""

    def __init__(self, dataset: InventoryDataset) -> None:
        self._dataset = dataset
        self._materials = tuple(dataset.materials)

    @classmethod
    def load(cls, path: Path) -> JsonInventoryRepository:
        try:
            source = path.read_text(encoding="utf-8")
        except OSError as error:
            raise InventoryDataError(f"Unable to read inventory data at {path}") from error

        try:
            dataset = InventoryDataset.model_validate_json(source, strict=True)
        except (ValidationError, ValueError) as error:
            raise InventoryDataError(f"Invalid inventory data at {path}: {error}") from error

        return cls(dataset)

    @property
    def dataset(self) -> InventoryDataset:
        return self._dataset

    def list_materials(self) -> tuple[Material, ...]:
        return self._materials

    def search_materials(self, query: str) -> tuple[Material, ...]:
        normalized = _normalize(query)
        if not normalized:
            return self._materials

        matches = []
        for material in self._materials:
            fields = (
                material.sku,
                material.description,
                material.category,
                material.spec_grade or "",
                material.warehouse,
            )
            if any(normalized in _normalize(field) for field in fields):
                matches.append(material)
        return tuple(matches)


def _normalize(value: str) -> str:
    return " ".join(value.split()).casefold()
