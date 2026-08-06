"""Public response models for the JSON-reading MVP."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


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


class OrderEvaluationRequest(ApiModel):
    material_query: str = Field(min_length=1, max_length=100)
    quantity: int = Field(strict=True, gt=0)

    @field_validator("material_query")
    @classmethod
    def normalize_material_query(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("material_query must contain non-whitespace characters")
        return cleaned


class OrderEvaluationResponse(ApiModel):
    outcome: Literal[
        "ready_for_confirmation",
        "insufficient_inventory",
        "discontinued",
        "ambiguous",
        "no_match",
    ]
    query: str
    requested_quantity: int
    message: str
    item: MaterialResponse | None = None
    candidates: list[MaterialCandidateResponse]
    unit_price: Decimal | None = None
    line_total: Decimal | None = None
    currency: str | None = None
    confirmation_token: str | None = None
    expires_at: datetime | None = None


class OrderConfirmationRequest(ApiModel):
    confirmation_token: str = Field(strict=True, min_length=20, max_length=200)

    @field_validator("confirmation_token")
    @classmethod
    def reject_surrounding_whitespace(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("confirmation_token must not contain surrounding whitespace")
        return value


class OrderConfirmationResponse(ApiModel):
    outcome: Literal["confirmed", "stale"]
    message: str
    requested_quantity: int
    unit_price: Decimal
    line_total: Decimal
    currency: str
    item: MaterialResponse | None


class ChatRequest(ApiModel):
    message: str = Field(strict=True, min_length=1, max_length=1_000)

    @field_validator("message")
    @classmethod
    def normalize_message(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("message must contain non-whitespace characters")
        return cleaned


class ChatVerifiedResultResponse(ApiModel):
    call_index: int
    tool: str
    status: Literal["success", "rejected", "invalid", "skipped", "error", "limit"]
    title: str
    message: str
    affected_skus: list[str]


class PendingOrderSummaryResponse(ApiModel):
    reference: str
    summary: str
    expires_at: datetime


class ChatResponse(ApiModel):
    orchestration_status: Literal["complete", "incomplete"]
    verified_results: list[ChatVerifiedResultResponse]
    commentary: str | None
    commentary_status: Literal["available", "unavailable", "omitted_unsafe", "not_requested"]
    pending_orders: list[PendingOrderSummaryResponse]
