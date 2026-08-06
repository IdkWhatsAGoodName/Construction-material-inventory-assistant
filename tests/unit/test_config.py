from __future__ import annotations

from pathlib import Path

import pytest

from inventory_assistant.config import PROJECT_ROOT, ConfigurationError, Settings


@pytest.mark.parametrize("missing_name", ["DEMO_USERNAME", "DEMO_PASSWORD"])
def test_required_credentials_must_exist(
    monkeypatch: pytest.MonkeyPatch, missing_name: str
) -> None:
    monkeypatch.setenv("DEMO_USERNAME", "user")
    monkeypatch.setenv("DEMO_PASSWORD", "password")
    monkeypatch.delenv(missing_name)

    with pytest.raises(ConfigurationError, match=missing_name):
        Settings.from_environment()


@pytest.mark.parametrize("empty_name", ["DEMO_USERNAME", "DEMO_PASSWORD"])
def test_required_credentials_cannot_be_empty(
    monkeypatch: pytest.MonkeyPatch, empty_name: str
) -> None:
    monkeypatch.setenv("DEMO_USERNAME", "user")
    monkeypatch.setenv("DEMO_PASSWORD", "password")
    monkeypatch.setenv(empty_name, "")

    with pytest.raises(ConfigurationError, match=empty_name):
        Settings.from_environment()


def test_relative_inventory_path_is_resolved_from_project_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEMO_USERNAME", "user")
    monkeypatch.setenv("DEMO_PASSWORD", "password")
    monkeypatch.setenv("INVENTORY_DATA_PATH", "fixtures/data.json")

    settings = Settings.from_environment()

    assert settings.inventory_data_path == (PROJECT_ROOT / "fixtures/data.json").resolve()
    assert isinstance(settings.inventory_data_path, Path)
