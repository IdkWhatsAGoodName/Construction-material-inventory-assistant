"""FastAPI application composition root."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Query, Request
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from inventory_assistant.api.auth import BasicAuthMiddleware
from inventory_assistant.api.routes import router as catalog_router
from inventory_assistant.api.schemas import HealthResponse
from inventory_assistant.application.catalog import CatalogService
from inventory_assistant.application.inventory import InventoryService
from inventory_assistant.application.orders import ConfirmationRegistry, OrderService
from inventory_assistant.application.suppliers import SupplierService
from inventory_assistant.config import Settings
from inventory_assistant.data.ingestion import ingest_inventory
from inventory_assistant.data.sqlite_repository import SQLiteInventoryRepository

LOGGER = logging.getLogger(__name__)
WEB_ROOT = Path(__file__).resolve().parent / "web"
TEMPLATES = Jinja2Templates(directory=WEB_ROOT / "templates")


def create_app() -> FastAPI:
    """Build an application whose external resources load during lifespan startup."""

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        application.state.ready = False
        settings = Settings.from_environment()
        ingestion = ingest_inventory(
            settings.inventory_data_path,
            settings.inventory_db_path,
        )
        repository = SQLiteInventoryRepository(ingestion.database_path)
        catalog_service = CatalogService(repository)
        inventory_service = InventoryService(repository)
        supplier_service = SupplierService(repository)
        confirmation_registry = ConfirmationRegistry()
        order_service = OrderService(repository, repository, confirmation_registry)

        application.state.settings = settings
        application.state.repository = repository
        application.state.catalog_service = catalog_service
        application.state.inventory_service = inventory_service
        application.state.supplier_service = supplier_service
        application.state.confirmation_registry = confirmation_registry
        application.state.order_service = order_service
        application.state.ready = True

        summary = catalog_service.get_summary()
        LOGGER.info(
            "SQLite inventory snapshot loaded: %d suppliers, %d materials (source sha256 %s)",
            summary.supplier_count,
            summary.material_count,
            ingestion.source_sha256,
        )
        try:
            yield
        finally:
            application.state.ready = False

    application = FastAPI(
        title="Construction Material Inventory Assistant",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    application.add_middleware(BasicAuthMiddleware)
    application.mount("/static", StaticFiles(directory=WEB_ROOT / "static"), name="static")
    application.include_router(catalog_router)

    @application.get("/health/live", response_model=HealthResponse, tags=["health"])
    def live() -> HealthResponse:
        return HealthResponse(status="alive")

    @application.get("/health/ready", response_model=HealthResponse, tags=["health"])
    def ready(request: Request) -> HealthResponse | JSONResponse:
        if not getattr(request.app.state, "ready", False):
            return JSONResponse(status_code=503, content={"status": "not_ready"})
        return HealthResponse(status="ready")

    @application.get("/", response_class=HTMLResponse, include_in_schema=False)
    def catalogue_page(
        request: Request,
        q: str = Query(default="", max_length=100),
    ) -> HTMLResponse:
        service = request.app.state.catalog_service
        materials = service.find_materials(q)
        alerts = request.app.state.inventory_service.list_overallocation_alerts()
        return TEMPLATES.TemplateResponse(
            request=request,
            name="catalogue.html",
            context={
                "summary": service.get_summary(),
                "materials": materials,
                "alerts": alerts,
                "query": " ".join(q.split()),
                "result_count": len(materials),
            },
        )

    @application.get("/openapi.json", include_in_schema=False)
    def openapi_schema() -> JSONResponse:
        return JSONResponse(application.openapi())

    @application.get("/docs", include_in_schema=False)
    def swagger_ui() -> HTMLResponse:
        return get_swagger_ui_html(
            openapi_url="/openapi.json",
            title=f"{application.title} - Swagger UI",
        )

    @application.get("/redoc", include_in_schema=False)
    def redoc_ui() -> HTMLResponse:
        return get_redoc_html(
            openapi_url="/openapi.json",
            title=f"{application.title} - ReDoc",
        )

    return application


app = create_app()
