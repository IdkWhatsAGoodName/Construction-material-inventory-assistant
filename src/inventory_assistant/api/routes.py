"""HTTP routes for deterministic inventory and order behavior."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse

from inventory_assistant.api.schemas import (
    CatalogSummaryResponse,
    InventoryAlertResponse,
    InventoryAlertsResponse,
    InventoryDetailResponse,
    InventorySearchResponse,
    MaterialCandidateResponse,
    MaterialListResponse,
    MaterialResponse,
    OrderConfirmationRequest,
    OrderConfirmationResponse,
    OrderEvaluationRequest,
    OrderEvaluationResponse,
    SupplierDetailResponse,
    SupplierResponse,
    SupplierSearchResponse,
)
from inventory_assistant.application.catalog import CatalogService
from inventory_assistant.application.inventory import InventoryService
from inventory_assistant.application.orders import (
    ConfirmationNotFound,
    OrderConfirmation,
    OrderEvaluation,
    OrderService,
)
from inventory_assistant.application.suppliers import SupplierService, render_supplier_message
from inventory_assistant.data.sqlite_repository import ReservationPersistenceError
from inventory_assistant.domain.inventory import render_inventory_message

router = APIRouter()
LOGGER = logging.getLogger(__name__)


def get_catalog_service(request: Request) -> CatalogService:
    return request.app.state.catalog_service


def get_inventory_service(request: Request) -> InventoryService:
    return request.app.state.inventory_service


def get_supplier_service(request: Request) -> SupplierService:
    return request.app.state.supplier_service


def get_order_service(request: Request) -> OrderService:
    return request.app.state.order_service


@router.get("/api/catalog/summary", response_model=CatalogSummaryResponse, tags=["catalog"])
def catalog_summary(request: Request) -> CatalogSummaryResponse:
    service = get_catalog_service(request)
    return CatalogSummaryResponse.model_validate(service.get_summary())


@router.get("/api/catalog/materials", response_model=MaterialListResponse, tags=["catalog"])
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


@router.get("/api/inventory/search", response_model=InventorySearchResponse, tags=["inventory"])
def search_inventory(
    request: Request,
    q: str = Query(min_length=1, max_length=100),
) -> InventorySearchResponse:
    result = get_inventory_service(request).search(q)
    return InventorySearchResponse(
        outcome=result.outcome,
        query=result.query,
        message=result.message,
        item=MaterialResponse.model_validate(result.item) if result.item else None,
        candidates=[
            MaterialCandidateResponse.model_validate(candidate) for candidate in result.candidates
        ],
    )


@router.get("/api/inventory/alerts", response_model=InventoryAlertsResponse, tags=["inventory"])
def inventory_alerts(request: Request) -> InventoryAlertsResponse:
    alerts = get_inventory_service(request).list_overallocation_alerts()
    return InventoryAlertsResponse(
        count=len(alerts),
        message=(
            "Inventory over-allocation requires correction. This demo has no correction workflow."
            if alerts
            else "No inventory over-allocation discrepancies are present."
        ),
        items=[
            InventoryAlertResponse(
                sku=item.sku,
                description=item.description,
                warehouse=item.warehouse,
                qty_on_hand=item.qty_on_hand,
                qty_reserved=item.qty_reserved,
                qty_available=item.qty_available,
                qty_shippable=item.qty_shippable,
                overallocated_by=item.overallocated_by,
                message=render_inventory_message(item),
            )
            for item in alerts
        ],
    )


@router.get("/api/inventory/{sku}", response_model=InventoryDetailResponse, tags=["inventory"])
def inventory_by_sku(request: Request, sku: str) -> InventoryDetailResponse:
    item = get_inventory_service(request).get_by_sku(sku)
    if item is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "material_not_found",
                "message": f"No material exists with SKU '{sku}'.",
            },
        )
    return InventoryDetailResponse.model_validate(
        {
            **MaterialResponse.model_validate(item).model_dump(),
            "message": render_inventory_message(item),
        }
    )


@router.get("/api/suppliers", response_model=SupplierSearchResponse, tags=["suppliers"])
def suppliers_by_category(
    request: Request,
    category: str = Query(min_length=1, max_length=100),
) -> SupplierSearchResponse:
    result = get_supplier_service(request).find_for_category(category)
    return SupplierSearchResponse(
        outcome=result.outcome,
        category=result.category,
        message=result.message,
        supplier=SupplierResponse.model_validate(result.supplier) if result.supplier else None,
        candidates=[SupplierResponse.model_validate(candidate) for candidate in result.candidates],
    )


@router.get(
    "/api/suppliers/{supplier_id}",
    response_model=SupplierDetailResponse,
    tags=["suppliers"],
)
def supplier_by_id(request: Request, supplier_id: str) -> SupplierDetailResponse:
    supplier = get_supplier_service(request).get_by_id(supplier_id)
    if supplier is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "supplier_not_found",
                "message": f"No supplier exists with ID '{supplier_id}'.",
            },
        )
    return SupplierDetailResponse.model_validate(
        {
            **SupplierResponse.model_validate(supplier).model_dump(),
            "message": render_supplier_message(supplier),
        }
    )


@router.post(
    "/api/orders/evaluate",
    response_model=OrderEvaluationResponse,
    tags=["orders"],
)
def evaluate_order(
    request: Request,
    payload: OrderEvaluationRequest,
    response: Response,
) -> OrderEvaluationResponse:
    response.headers["Cache-Control"] = "no-store"
    result = get_order_service(request).evaluate(payload.material_query, payload.quantity)
    return _evaluation_response(result)


@router.post(
    "/api/orders/confirm",
    response_model=OrderConfirmationResponse,
    responses={404: {"description": "Unknown or expired confirmation"}, 409: {}, 503: {}},
    tags=["orders"],
)
def confirm_order(
    request: Request,
    payload: OrderConfirmationRequest,
    response: Response,
) -> OrderConfirmationResponse | JSONResponse:
    response.headers["Cache-Control"] = "no-store"
    try:
        result = get_order_service(request).confirm(payload.confirmation_token)
    except ConfirmationNotFound as error:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "confirmation_not_found",
                "message": "The confirmation is unknown or expired. Evaluate the order again.",
            },
            headers={"Cache-Control": "no-store"},
        ) from error
    except ReservationPersistenceError:
        LOGGER.error("Order confirmation could not access reservation persistence")
        raise HTTPException(
            status_code=503,
            detail={
                "code": "reservation_unavailable",
                "message": "Inventory reservation is temporarily unavailable. Try again.",
            },
            headers={"Cache-Control": "no-store"},
        ) from None

    model = _confirmation_response(result)
    if result.outcome == "stale":
        return JSONResponse(
            status_code=409,
            content=model.model_dump(mode="json"),
            headers={"Cache-Control": "no-store"},
        )
    return model


def _evaluation_response(result: OrderEvaluation) -> OrderEvaluationResponse:
    return OrderEvaluationResponse(
        outcome=result.outcome,
        query=result.query,
        requested_quantity=result.requested_quantity,
        message=result.message,
        item=MaterialResponse.model_validate(result.item) if result.item else None,
        candidates=[
            MaterialCandidateResponse.model_validate(candidate) for candidate in result.candidates
        ],
        unit_price=result.unit_price,
        line_total=result.line_total,
        currency=result.currency,
        confirmation_token=result.confirmation_token,
        expires_at=result.expires_at,
    )


def _confirmation_response(result: OrderConfirmation) -> OrderConfirmationResponse:
    return OrderConfirmationResponse(
        outcome=result.outcome,
        message=result.message,
        requested_quantity=result.requested_quantity,
        unit_price=result.unit_price,
        line_total=result.line_total,
        currency=result.currency,
        item=MaterialResponse.model_validate(result.item) if result.item else None,
    )
