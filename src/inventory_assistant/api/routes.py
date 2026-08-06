"""HTTP routes for catalogue browsing and source metadata."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request

from inventory_assistant.api.schemas import (
    CatalogSummaryResponse,
    MaterialListResponse,
    MaterialResponse,
)
from inventory_assistant.application.catalog import CatalogService

router = APIRouter(prefix="/api/catalog", tags=["catalog"])


def get_catalog_service(request: Request) -> CatalogService:
    return request.app.state.catalog_service


@router.get("/summary", response_model=CatalogSummaryResponse)
def catalog_summary(request: Request) -> CatalogSummaryResponse:
    service = get_catalog_service(request)
    return CatalogSummaryResponse.model_validate(service.get_summary())


@router.get("/materials", response_model=MaterialListResponse)
def list_materials(
    request: Request,
    q: str = Query(default="", max_length=100),
) -> MaterialListResponse:
    service = get_catalog_service(request)
    materials = service.find_materials(q)
    total = service.get_summary().material_count
    return MaterialListResponse(
        items=[MaterialResponse.model_validate(material) for material in materials],
        count=len(materials),
        total=total,
        query=" ".join(q.split()),
    )
