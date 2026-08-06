"""Public response models for the JSON-reading MVP."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class CatalogSummaryResponse(ApiModel):
    dataset_name: str
    as_of_date: date
    currency: str
    notes: str
    supplier_count: int
    material_count: int


class MaterialResponse(ApiModel):
    sku: str
    description: str
    category: str
    spec_grade: str | None
    unit_of_measure: str
    unit_price: Decimal
    currency: str
    qty_on_hand: int
    qty_reserved: int
    reorder_point: int
    min_order_qty: int
    primary_supplier_id: str
    warehouse: str
    discontinued: bool


class MaterialListResponse(ApiModel):
    items: list[MaterialResponse]
    count: int
    total: int
    query: str


class HealthResponse(ApiModel):
    status: str
