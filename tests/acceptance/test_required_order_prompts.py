from __future__ import annotations

from fastapi.testclient import TestClient


def test_500_lengths_of_15m_rebar_cannot_be_fulfilled_or_partially_reserved(
    client: TestClient, auth: tuple[str, str]
) -> None:
    response = client.post(
        "/api/orders/evaluate",
        auth=auth,
        json={"material_query": "15M deformed rebar", "quantity": 500},
    )
    body = response.json()

    assert response.status_code == 200
    assert body["outcome"] == "insufficient_inventory"
    assert body["item"]["sku"] == "RBR-15M-400W"
    assert body["item"]["qty_shippable"] == 120
    assert body["line_total"] == "13925.00"
    assert body["confirmation_token"] is None
    assert "13,925.00 CAD" in body["message"]
    assert "no partial order was placed" in body["message"]


def test_three_discontinued_plate_sheets_cannot_be_ordered(
    client: TestClient, auth: tuple[str, str]
) -> None:
    response = client.post(
        "/api/orders/evaluate",
        auth=auth,
        json={"material_query": "3/8 inch steel plate", "quantity": 3},
    )
    body = response.json()

    assert response.status_code == 200
    assert body["outcome"] == "discontinued"
    assert body["item"]["sku"] == "STL-PL38-A36"
    assert body["item"]["qty_shippable"] == 4
    assert body["confirmation_token"] is None
    assert "904.50 CAD" in body["message"]
