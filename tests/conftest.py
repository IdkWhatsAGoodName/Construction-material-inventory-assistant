from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from inventory_assistant.main import create_app

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DATA = PROJECT_ROOT / "Requirements" / "inventory_data.json"
USERNAME = "demo-user"
PASSWORD = "correct horse battery staple"


@pytest.fixture
def configured_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMO_USERNAME", USERNAME)
    monkeypatch.setenv("DEMO_PASSWORD", PASSWORD)
    monkeypatch.setenv("INVENTORY_DATA_PATH", str(SOURCE_DATA))


@pytest.fixture
def client(configured_environment: None) -> Iterator[TestClient]:
    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture
def auth() -> tuple[str, str]:
    return USERNAME, PASSWORD
