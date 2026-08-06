"""Validated source-data models."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

NonEmptyText = Annotated[str, Field(min_length=1)]
NonNegativeInt = Annotated[int, Field(ge=0)]
NonNegativeDecimal = Annotated[Decimal, Field(ge=0)]
PositiveInt = Annotated[int, Field(gt=0)]


class SourceModel(BaseModel):
    """Base model that rejects unrecognized source fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class Definitions(SourceModel):
    qty_on_hand: NonEmptyText
    qty_reserved: NonEmptyText
    qty_available: NonEmptyText
    min_order_qty: NonEmptyText
    reorder_point: NonEmptyText


class DatasetMeta(SourceModel):
    dataset_name: NonEmptyText
    as_of_date: date
    currency: NonEmptyText
    notes: NonEmptyText
    definitions: Definitions


class Supplier(SourceModel):
    supplier_id: NonEmptyText
    name: NonEmptyText
    location: NonEmptyText
    standard_lead_time_days: NonNegativeInt
    payment_terms: NonEmptyText


class Material(SourceModel):
    sku: NonEmptyText
    description: NonEmptyText
    category: NonEmptyText
    spec_grade: str | None
    unit_of_measure: NonEmptyText
    unit_price: NonNegativeDecimal
    currency: NonEmptyText
    qty_on_hand: NonNegativeInt
    qty_reserved: NonNegativeInt
    reorder_point: NonNegativeInt
    min_order_qty: PositiveInt
    primary_supplier_id: NonEmptyText
    warehouse: NonEmptyText
    discontinued: bool


class InventoryDataset(SourceModel):
    meta: DatasetMeta
    suppliers: tuple[Supplier, ...] = Field(min_length=1)
    materials: tuple[Material, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_relationships(self) -> InventoryDataset:
        supplier_ids = [supplier.supplier_id for supplier in self.suppliers]
        if len(supplier_ids) != len(set(supplier_ids)):
            raise ValueError("supplier_id values must be unique")
        if len(supplier_ids) != len({supplier_id.casefold() for supplier_id in supplier_ids}):
            raise ValueError("supplier_id values must be unique case-insensitively")

        skus = [material.sku for material in self.materials]
        if len(skus) != len(set(skus)):
            raise ValueError("material sku values must be unique")
        if len(skus) != len({sku.casefold() for sku in skus}):
            raise ValueError("material sku values must be unique case-insensitively")

        known_suppliers = set(supplier_ids)
        missing_references = sorted(
            {
                material.primary_supplier_id
                for material in self.materials
                if material.primary_supplier_id not in known_suppliers
            }
        )
        if missing_references:
            missing = ", ".join(missing_references)
            raise ValueError(f"materials reference unknown suppliers: {missing}")

        mismatched_currencies = sorted(
            {
                material.currency
                for material in self.materials
                if material.currency != self.meta.currency
            }
        )
        if mismatched_currencies:
            currencies = ", ".join(mismatched_currencies)
            raise ValueError(f"material currencies do not match dataset currency: {currencies}")

        return self
