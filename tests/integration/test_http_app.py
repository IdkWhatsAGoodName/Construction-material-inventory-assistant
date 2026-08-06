from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from inventory_assistant.config import ConfigurationError
from inventory_assistant.data.json_repository import InventoryDataError
from inventory_assistant.data.sqlite_repository import connect_database
from inventory_assistant.main import create_app

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_DATA = PROJECT_ROOT / "Requirements" / "inventory_data.json"


def test_public_health_checks_do_not_require_authentication(client: TestClient) -> None:
    assert client.get("/health/live").json() == {"status": "alive"}
    assert client.get("/health/ready").json() == {"status": "ready"}


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/api/catalog/summary",
        "/api/catalog/materials",
        "/api/inventory/search?q=rebar",
        "/api/inventory/STL-W12X40-A992",
        "/api/inventory/alerts",
        "/api/suppliers?category=rebar",
        "/api/suppliers/SUP-002",
        "/openapi.json",
        "/docs",
        "/redoc",
        "/static/styles.css",
        "/not-a-route",
    ],
)
def test_every_non_health_path_requires_authentication(client: TestClient, path: str) -> None:
    response = client.get(path)

    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}
    assert response.headers["www-authenticate"] == "Basic"
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "authorization",
    [
        "NotBasic abc",
        "Basic !!!not-base64!!!",
        "Basic bm8tY29sb24=",
        "Basic /w==",
    ],
)
def test_malformed_authorization_is_rejected_generically(
    client: TestClient, authorization: str
) -> None:
    response = client.get("/", headers={"Authorization": authorization})

    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}


@pytest.mark.parametrize(
    "credentials",
    [
        ("wrong-user", "correct horse battery staple"),
        ("demo-user", "wrong-password"),
    ],
)
def test_wrong_credentials_are_rejected_generically(
    client: TestClient, credentials: tuple[str, str]
) -> None:
    response = client.get("/", auth=credentials)

    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}


def test_authorized_catalogue_and_documentation_are_available(
    client: TestClient, auth: tuple[str, str]
) -> None:
    assert client.get("/", auth=auth).status_code == 200
    assert client.get("/openapi.json", auth=auth).status_code == 200
    assert client.get("/docs", auth=auth).status_code == 200
    assert client.get("/redoc", auth=auth).status_code == 200
    assert client.get("/static/styles.css", auth=auth).status_code == 200
    assert client.get("/not-a-route", auth=auth).status_code == 404


def test_catalogue_summary_reports_source_metadata(
    client: TestClient, auth: tuple[str, str]
) -> None:
    response = client.get("/api/catalog/summary", auth=auth)

    assert response.status_code == 200
    assert response.json() == {
        "dataset_name": "Inventory sample data",
        "as_of_date": "2026-08-01",
        "currency": "CAD",
        "notes": "Synthetic data. Stands in for a supplier ERP feed. Not real inventory.",
        "supplier_count": 9,
        "material_count": 77,
    }


def test_material_api_returns_all_source_records(client: TestClient, auth: tuple[str, str]) -> None:
    response = client.get("/api/catalog/materials", auth=auth)
    payload = response.json()

    assert response.status_code == 200
    assert payload["count"] == 77
    assert payload["total"] == 77
    assert payload["query"] == ""
    assert len(payload["items"]) == 77
    assert payload["items"][0]["unit_price"] == "742.5"
    assert payload["items"][0]["qty_available"] == -2
    assert payload["items"][0]["qty_shippable"] == 0
    assert payload["items"][0]["overallocated_by"] == 2
    assert payload["items"][0]["status"] == "overallocated"
    assert payload["items"][0]["conditions"] == ["overallocated", "reorder_required"]


def test_material_api_filters_without_substitution(
    client: TestClient, auth: tuple[str, str]
) -> None:
    response = client.get("/api/catalog/materials", params={"q": "  W12X40  "}, auth=auth)
    payload = response.json()

    assert response.status_code == 200
    assert payload["count"] == 1
    assert payload["query"] == "W12X40"
    assert payload["items"][0]["sku"] == "STL-W12X40-A992"

    no_match = client.get(
        "/api/catalog/materials",
        params={"q": "definitely-not-a-real-sku"},
        auth=auth,
    ).json()
    assert no_match["items"] == []
    assert no_match["count"] == 0


def test_catalogue_page_displays_counts_and_empty_state(
    client: TestClient, auth: tuple[str, str]
) -> None:
    page = client.get("/", auth=auth)
    assert "Suppliers" in page.text
    assert ">9<" in page.text
    assert "Materials" in page.text
    assert ">77<" in page.text
    assert "Inventory discrepancy requires attention" in page.text
    assert "over-allocated by 2 each" in page.text
    assert 'href="/?q=STL-W12X40-A992#material-STL-W12X40-A992"' in page.text
    assert "Raw availability" in page.text
    assert "Can ship" in page.text

    empty_page = client.get("/", params={"q": "definitely-not-a-real-sku"}, auth=auth)
    assert "No matching materials" in empty_page.text
    assert "No substitute was selected" in empty_page.text


@pytest.mark.parametrize(
    ("query", "outcome", "sku"),
    [
        ("W12x40 beams", "unique_match", "STL-W12X40-A992"),
        ("20M epoxy rebars", "unique_match", "RBR-20M-EPOXY"),
        ("25M epoxy rebars", "no_match", None),
        ("rebar", "ambiguous", None),
    ],
)
def test_inventory_search_endpoint_returns_explicit_outcomes(
    client: TestClient,
    auth: tuple[str, str],
    query: str,
    outcome: str,
    sku: str | None,
) -> None:
    response = client.get("/api/inventory/search", params={"q": query}, auth=auth)
    payload = response.json()

    assert response.status_code == 200
    assert payload["outcome"] == outcome
    assert (payload["item"]["sku"] if payload["item"] else None) == sku


def test_inventory_resource_returns_raw_and_shippable_quantities(
    client: TestClient, auth: tuple[str, str]
) -> None:
    response = client.get("/api/inventory/stl-w12x40-a992", auth=auth)
    payload = response.json()

    assert response.status_code == 200
    assert payload["qty_available"] == -2
    assert payload["qty_shippable"] == 0
    assert payload["overallocated_by"] == 2
    assert payload["status"] == "overallocated"
    assert payload["conditions"] == ["overallocated", "reorder_required"]
    assert "0 each can ship" in payload["message"]

    missing = client.get("/api/inventory/NOT-REAL", auth=auth)
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "material_not_found"


def test_inventory_alert_endpoint_reports_only_overallocation(
    client: TestClient, auth: tuple[str, str]
) -> None:
    response = client.get("/api/inventory/alerts", auth=auth)
    payload = response.json()

    assert response.status_code == 200
    assert payload["count"] == 1
    assert [item["sku"] for item in payload["items"]] == ["STL-W12X40-A992"]
    assert payload["items"][0]["qty_available"] == -2
    assert "no correction workflow" in payload["message"].casefold()


def test_alert_endpoint_and_banner_are_clear_when_no_discrepancy_exists(
    configured_environment: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    auth: tuple[str, str],
) -> None:
    payload = json.loads(SOURCE_DATA.read_text(encoding="utf-8"))
    beam = next(
        material for material in payload["materials"] if material["sku"] == "STL-W12X40-A992"
    )
    beam["qty_reserved"] = beam["qty_on_hand"]
    source = tmp_path / "no-overallocation.json"
    source.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("INVENTORY_DATA_PATH", str(source))

    with TestClient(create_app()) as no_alert_client:
        alerts = no_alert_client.get("/api/inventory/alerts", auth=auth).json()
        page = no_alert_client.get("/", auth=auth)

    assert alerts["count"] == 0
    assert alerts["items"] == []
    assert "No inventory over-allocation" in alerts["message"]
    assert "Inventory discrepancy requires attention" not in page.text


def test_supplier_endpoints_return_unique_ambiguous_and_missing_outcomes(
    client: TestClient, auth: tuple[str, str]
) -> None:
    rebar = client.get("/api/suppliers", params={"category": "rebar"}, auth=auth).json()
    assert rebar["outcome"] == "unique_match"
    assert rebar["supplier"]["supplier_id"] == "SUP-002"
    assert rebar["supplier"]["payment_terms"] == "NET30"
    assert rebar["supplier"]["standard_lead_time_days"] == 7

    sheet_metal = client.get("/api/suppliers", params={"category": "sheet metal"}, auth=auth).json()
    assert sheet_metal["outcome"] == "ambiguous"
    assert [supplier["supplier_id"] for supplier in sheet_metal["candidates"]] == [
        "SUP-003",
        "SUP-009",
    ]

    supplier = client.get("/api/suppliers/sup-002", auth=auth)
    assert supplier.status_code == 200
    assert "standard lead time of 7 days" in supplier.json()["message"]

    missing = client.get("/api/suppliers/SUP-404", auth=auth)
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "supplier_not_found"


def test_startup_fails_without_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEMO_USERNAME", raising=False)
    monkeypatch.delenv("DEMO_PASSWORD", raising=False)

    with pytest.raises(ConfigurationError), TestClient(create_app()):
        pass


def test_startup_fails_with_invalid_data(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    invalid_source = tmp_path / "inventory.json"
    invalid_source.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("DEMO_USERNAME", "user")
    monkeypatch.setenv("DEMO_PASSWORD", "password")
    monkeypatch.setenv("INVENTORY_DATA_PATH", str(invalid_source))
    monkeypatch.setenv("INVENTORY_DB_PATH", str(tmp_path / "inventory.sqlite3"))

    with pytest.raises(InventoryDataError), TestClient(create_app()):
        pass


def test_startup_builds_sqlite_snapshot_and_resets_session_changes(
    configured_environment: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "inventory.sqlite3"
    monkeypatch.setenv("INVENTORY_DB_PATH", str(database_path))

    with TestClient(create_app()):
        pass

    with connect_database(database_path, read_only=False) as connection:
        connection.execute("UPDATE materials SET qty_reserved = 99 WHERE sku = 'STL-W12X40-A992'")

    with TestClient(create_app()) as restarted_client:
        material = restarted_client.app.state.repository.get_material("STL-W12X40-A992")

    assert material is not None
    assert material.qty_reserved == 6


def test_failed_startup_preserves_prior_valid_database(
    configured_environment: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "inventory.sqlite3"
    monkeypatch.setenv("INVENTORY_DB_PATH", str(database_path))
    with TestClient(create_app()):
        pass
    original_database = database_path.read_bytes()

    invalid_source = tmp_path / "invalid.json"
    invalid_source.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("INVENTORY_DATA_PATH", str(invalid_source))

    with pytest.raises(InventoryDataError), TestClient(create_app()):
        pass

    assert database_path.read_bytes() == original_database
