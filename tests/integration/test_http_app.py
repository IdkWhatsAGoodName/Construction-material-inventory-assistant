from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from inventory_assistant.config import ConfigurationError
from inventory_assistant.data.json_repository import InventoryDataError
from inventory_assistant.main import create_app


def test_public_health_checks_do_not_require_authentication(client: TestClient) -> None:
    assert client.get("/health/live").json() == {"status": "alive"}
    assert client.get("/health/ready").json() == {"status": "ready"}


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/api/catalog/summary",
        "/api/catalog/materials",
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
    assert "qty_available" not in payload["items"][0]


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

    empty_page = client.get("/", params={"q": "definitely-not-a-real-sku"}, auth=auth)
    assert "No matching materials" in empty_page.text


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

    with pytest.raises(InventoryDataError), TestClient(create_app()):
        pass
