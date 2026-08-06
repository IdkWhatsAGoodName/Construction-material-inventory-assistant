from __future__ import annotations

from fastapi.testclient import TestClient


def test_w12x40_beam_reports_zero_shippable_and_overallocation(
    client: TestClient, auth: tuple[str, str]
) -> None:
    payload = client.get("/api/inventory/search", params={"q": "W12x40 beams"}, auth=auth).json()

    assert payload["outcome"] == "unique_match"
    assert payload["item"]["sku"] == "STL-W12X40-A992"
    assert payload["item"]["warehouse"] == "YARD-1"
    assert payload["item"]["qty_available"] == -2
    assert payload["item"]["qty_shippable"] == 0
    assert payload["item"]["overallocated_by"] == 2


def test_missing_25m_epoxy_variant_is_not_substituted(
    client: TestClient, auth: tuple[str, str]
) -> None:
    payload = client.get(
        "/api/inventory/search", params={"q": "25M epoxy rebars"}, auth=auth
    ).json()

    assert payload["outcome"] == "no_match"
    assert payload["item"] is None
    assert payload["candidates"] == []


def test_generic_15m_rebar_is_ambiguous_and_standard_grade_facts_are_exact(
    client: TestClient, auth: tuple[str, str]
) -> None:
    ambiguous = client.get("/api/inventory/search", params={"q": "15M rebar"}, auth=auth).json()
    standard = client.get("/api/inventory/RBR-15M-400W", auth=auth).json()

    assert ambiguous["outcome"] == "ambiguous"
    assert [candidate["sku"] for candidate in ambiguous["candidates"]] == [
        "RBR-15M-400W",
        "RBR-15M-EPOXY",
    ]
    assert standard["qty_shippable"] == 120
    assert standard["unit_price"] == "27.85"
    assert standard["currency"] == "CAD"


def test_discontinued_plate_exposes_stock_but_forbids_ordering_language(
    client: TestClient, auth: tuple[str, str]
) -> None:
    payload = client.get(
        "/api/inventory/search", params={"q": "3/8 inch steel plate"}, auth=auth
    ).json()

    assert payload["outcome"] == "unique_match"
    assert payload["item"]["sku"] == "STL-PL38-A36"
    assert payload["item"]["qty_shippable"] == 4
    assert payload["item"]["status"] == "discontinued"
    assert "cannot be ordered" in payload["message"]


def test_rebar_supplier_terms_and_fully_reserved_20m_epoxy_stock(
    client: TestClient, auth: tuple[str, str]
) -> None:
    supplier = client.get("/api/suppliers", params={"category": "rebar"}, auth=auth).json()
    inventory = client.get(
        "/api/inventory/search", params={"q": "20M epoxy rebars"}, auth=auth
    ).json()

    assert supplier["outcome"] == "unique_match"
    assert supplier["supplier"]["supplier_id"] == "SUP-002"
    assert supplier["supplier"]["payment_terms"] == "NET30"
    assert supplier["supplier"]["standard_lead_time_days"] == 7
    assert inventory["item"]["qty_on_hand"] == 18
    assert inventory["item"]["qty_reserved"] == 18
    assert inventory["item"]["qty_shippable"] == 0
    assert "fully_reserved" in inventory["item"]["conditions"]
