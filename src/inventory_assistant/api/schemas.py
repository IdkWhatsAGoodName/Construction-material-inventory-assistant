"""Public response models for the JSON-reading MVP."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

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
    qty_available: int
    qty_shippable: int
    overallocated_by: int
    reorder_point: int
    min_order_qty: int
    primary_supplier_id: str
    warehouse: str
    discontinued: bool
    status: Literal["discontinued", "overallocated", "unavailable", "available"]
    conditions: list[
        Literal[
            "discontinued",
            "overallocated",
            "zero_on_hand",
            "fully_reserved",
            "reorder_required",
        ]
    ]


class MaterialListResponse(ApiModel):
    items: list[MaterialResponse]
    count: int
    total: int
    query: str


class HealthResponse(ApiModel):
    status: str


class MaterialCandidateResponse(ApiModel):
    sku: str
    description: str
    category: str
    warehouse: str
    status: str


class InventoryDetailResponse(MaterialResponse):
    message: str


class InventorySearchResponse(ApiModel):
    outcome: Literal["exact_match", "unique_match", "ambiguous", "no_match"]
    query: str
    message: str
    item: MaterialResponse | None = None
    candidates: list[MaterialCandidateResponse]


class InventoryAlertResponse(ApiModel):
    sku: str
    description: str
    warehouse: str
    qty_on_hand: int
    qty_reserved: int
    qty_available: int
    qty_shippable: int
    overallocated_by: int
    message: str


class InventoryAlertsResponse(ApiModel):
    count: int
    message: str
    items: list[InventoryAlertResponse]


class SupplierResponse(ApiModel):
    supplier_id: str
    name: str
    location: str
    standard_lead_time_days: int
    payment_terms: str


class SupplierDetailResponse(SupplierResponse):
    message: str


class SupplierSearchResponse(ApiModel):
    outcome: Literal["unique_match", "ambiguous", "no_match"]
    category: str
    message: str
    supplier: SupplierResponse | None = None
    candidates: list[SupplierResponse]
