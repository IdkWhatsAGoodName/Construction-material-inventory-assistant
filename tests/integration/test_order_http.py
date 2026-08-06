from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from inventory_assistant.data.sqlite_repository import (
    ReservationPersistenceError,
    connect_database,
)
from inventory_assistant.main import create_app


def evaluate(
    client: TestClient,
    auth: tuple[str, str],
    material_query: str,
    quantity: int,
):
    return client.post(
        "/api/orders/evaluate",
        auth=auth,
        json={"material_query": material_query, "quantity": quantity},
    )


def test_order_endpoints_require_authentication(client: TestClient) -> None:
    evaluation = client.post(
        "/api/orders/evaluate",
        json={"material_query": "RBR-15M-400W", "quantity": 1},
    )
    confirmation = client.post(
        "/api/orders/confirm",
        json={"confirmation_token": "a" * 32},
    )

    assert evaluation.status_code == 401
    assert confirmation.status_code == 401
    assert evaluation.headers["cache-control"] == "no-store"
    assert confirmation.headers["cache-control"] == "no-store"


def test_evaluation_returns_confirmable_quote_without_mutating_inventory(
    client: TestClient, auth: tuple[str, str]
) -> None:
    response = evaluate(client, auth, "RBR-15M-400W", 10)
    payload = response.json()

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert payload["outcome"] == "ready_for_confirmation"
    assert payload["requested_quantity"] == 10
    assert payload["unit_price"] == "27.85"
    assert payload["line_total"] == "278.50"
    assert payload["currency"] == "CAD"
    assert len(payload["confirmation_token"]) >= 20
    assert payload["expires_at"].endswith("Z")
    assert payload["item"]["qty_reserved"] == 0
    assert client.get("/api/inventory/RBR-15M-400W", auth=auth).json()["qty_reserved"] == 0


def test_required_rebar_and_plate_rejections_are_complete_and_non_mutating(
    client: TestClient, auth: tuple[str, str]
) -> None:
    rebar = evaluate(client, auth, "15M deformed rebar", 500).json()
    plate = evaluate(client, auth, "3/8 inch steel plate", 3).json()

    assert rebar["outcome"] == "insufficient_inventory"
    assert rebar["item"]["sku"] == "RBR-15M-400W"
    assert rebar["item"]["qty_shippable"] == 120
    assert rebar["line_total"] == "13925.00"
    assert rebar["confirmation_token"] is None
    assert "no partial order was placed" in rebar["message"]

    assert plate["outcome"] == "discontinued"
    assert plate["item"]["sku"] == "STL-PL38-A36"
    assert plate["line_total"] == "904.5"
    assert "904.50 CAD" in plate["message"]
    assert plate["confirmation_token"] is None


@pytest.mark.parametrize(
    ("query", "outcome", "candidate_count"),
    [("rebar", "ambiguous", 10), ("25M epoxy rebar", "no_match", 0)],
)
def test_unresolved_order_evaluations_are_explicit_and_never_confirmable(
    client: TestClient,
    auth: tuple[str, str],
    query: str,
    outcome: str,
    candidate_count: int,
) -> None:
    response = evaluate(client, auth, query, 1)
    body = response.json()

    assert response.status_code == 200
    assert body["outcome"] == outcome
    assert len(body["candidates"]) == candidate_count
    assert body["item"] is None
    assert body["confirmation_token"] is None


@pytest.mark.parametrize(
    "body",
    [
        {"material_query": "RBR-15M-400W", "quantity": 0},
        {"material_query": "RBR-15M-400W", "quantity": "1"},
        {"material_query": "   ", "quantity": 1},
        {"material_query": "RBR-15M-400W", "quantity": True},
    ],
)
def test_order_request_validation_is_strict(
    client: TestClient, auth: tuple[str, str], body: dict[str, object]
) -> None:
    response = client.post("/api/orders/evaluate", auth=auth, json=body)

    assert response.status_code == 422
    assert "no-store" in response.headers["cache-control"]


def test_confirmation_mutates_once_and_replay_returns_identical_body(
    client: TestClient, auth: tuple[str, str]
) -> None:
    evaluation = evaluate(client, auth, "RBR-15M-400W", 10).json()
    request = {"confirmation_token": evaluation["confirmation_token"]}

    first = client.post("/api/orders/confirm", auth=auth, json=request)
    replay = client.post("/api/orders/confirm", auth=auth, json=request)

    assert first.status_code == 200
    assert first.headers["cache-control"] == "no-store"
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert first.json()["outcome"] == "confirmed"
    assert first.json()["item"]["qty_on_hand"] == 120
    assert first.json()["item"]["qty_reserved"] == 10
    assert first.json()["item"]["qty_shippable"] == 110
    inventory = client.get("/api/inventory/RBR-15M-400W", auth=auth).json()
    assert inventory["qty_reserved"] == 10


def test_changed_inventory_returns_cached_stale_conflict(
    client: TestClient, auth: tuple[str, str]
) -> None:
    evaluation = evaluate(client, auth, "RBR-15M-400W", 10).json()
    database_path: Path = client.app.state.repository.database_path
    with connect_database(database_path, read_only=False) as connection:
        connection.execute("UPDATE materials SET qty_reserved = 1 WHERE sku = 'RBR-15M-400W'")
    request = {"confirmation_token": evaluation["confirmation_token"]}

    first = client.post("/api/orders/confirm", auth=auth, json=request)
    replay = client.post("/api/orders/confirm", auth=auth, json=request)

    assert first.status_code == 409
    assert first.headers["cache-control"] == "no-store"
    assert replay.status_code == 409
    assert replay.json() == first.json()
    assert first.json()["outcome"] == "stale"
    assert first.json()["item"]["qty_reserved"] == 1


def test_unknown_confirmation_is_generic(client: TestClient, auth: tuple[str, str]) -> None:
    response = client.post(
        "/api/orders/confirm",
        auth=auth,
        json={"confirmation_token": "unknown-confirmation-token-value"},
    )

    assert response.status_code == 404
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["detail"]["code"] == "confirmation_not_found"


def test_transient_persistence_failure_returns_503_and_token_remains_retryable(
    client: TestClient,
    auth: tuple[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evaluation = evaluate(client, auth, "RBR-15M-400W", 10).json()
    token = evaluation["confirmation_token"]
    repository = client.app.state.repository
    original = repository.reserve_if_unchanged

    def fail_once(request):
        raise ReservationPersistenceError("sensitive detail")

    monkeypatch.setattr(repository, "reserve_if_unchanged", fail_once)
    failed = client.post("/api/orders/confirm", auth=auth, json={"confirmation_token": token})
    monkeypatch.setattr(repository, "reserve_if_unchanged", original)
    retried = client.post("/api/orders/confirm", auth=auth, json={"confirmation_token": token})

    assert failed.status_code == 503
    assert failed.json()["detail"] == {
        "code": "reservation_unavailable",
        "message": "Inventory reservation is temporarily unavailable. Try again.",
    }
    assert "sensitive" not in failed.text
    assert retried.status_code == 200
    assert retried.json()["outcome"] == "confirmed"


def test_concurrent_same_token_confirmation_returns_one_cached_terminal_result(
    client: TestClient, auth: tuple[str, str]
) -> None:
    evaluation = evaluate(client, auth, "RBR-15M-400W", 10).json()
    service = client.app.state.order_service
    token = evaluation["confirmation_token"]

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(service.confirm, (token, token)))

    assert results[0] == results[1]
    assert results[0].outcome == "confirmed"
    material = client.app.state.repository.get_material("RBR-15M-400W")
    assert material is not None
    assert material.qty_reserved == 10


def test_confirmation_registry_and_reservations_reset_with_process(
    configured_environment: None,
    auth: tuple[str, str],
) -> None:
    with TestClient(create_app()) as first_process:
        evaluation = evaluate(first_process, auth, "RBR-15M-400W", 10).json()
        token = evaluation["confirmation_token"]
        confirmed = first_process.post(
            "/api/orders/confirm", auth=auth, json={"confirmation_token": token}
        )
        assert confirmed.status_code == 200

    with TestClient(create_app()) as restarted_process:
        lost = restarted_process.post(
            "/api/orders/confirm", auth=auth, json={"confirmation_token": token}
        )
        material = restarted_process.get("/api/inventory/RBR-15M-400W", auth=auth).json()

    assert lost.status_code == 404
    assert material["qty_reserved"] == 0
