"""Read-only JSON inventory repository."""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from inventory_assistant.data.models import DatasetMeta, InventoryDataset, Material, Supplier


class InventoryDataError(RuntimeError):
    """Raised when the configured inventory source cannot be loaded safely."""


class JsonInventoryRepository:
    """Immutable, validated snapshot of the supplied inventory JSON."""

    def __init__(self, dataset: InventoryDataset) -> None:
        self._dataset = dataset
        self._materials = tuple(dataset.materials)
        self._suppliers = tuple(dataset.suppliers)
        self._materials_by_sku = {material.sku.casefold(): material for material in self._materials}
        self._suppliers_by_id = {
            supplier.supplier_id.casefold(): supplier for supplier in self._suppliers
        }

    @classmethod
    def load(cls, path: Path) -> JsonInventoryRepository:
        dataset, _ = read_inventory_source(path)
        return cls(dataset)

    @property
    def dataset(self) -> InventoryDataset:
        return self._dataset

    @property
    def meta(self) -> DatasetMeta:
        return self._dataset.meta

    def list_materials(self) -> tuple[Material, ...]:
        return self._materials

    def list_suppliers(self) -> tuple[Supplier, ...]:
        return self._suppliers

    def get_material(self, sku: str) -> Material | None:
        return self._materials_by_sku.get(sku.strip().casefold())

    def get_supplier(self, supplier_id: str) -> Supplier | None:
        return self._suppliers_by_id.get(supplier_id.strip().casefold())

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


def read_inventory_source(path: Path) -> tuple[InventoryDataset, bytes]:
    """Read and validate a source snapshot once, returning its exact bytes."""

    try:
        source = path.read_bytes()
    except OSError as error:
        raise InventoryDataError(f"Unable to read inventory data at {path}") from error

    try:
        dataset = InventoryDataset.model_validate_json(source, strict=True)
    except (ValidationError, ValueError) as error:
        raise InventoryDataError(f"Invalid inventory data at {path}: {error}") from error

    return dataset, source
