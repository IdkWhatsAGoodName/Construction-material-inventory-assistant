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
    monkeypatch.setenv("INVENTORY_DB_PATH", "var/test.sqlite3")

    settings = Settings.from_environment()

    assert settings.inventory_data_path == (PROJECT_ROOT / "fixtures/data.json").resolve()
    assert settings.inventory_db_path == (PROJECT_ROOT / "var/test.sqlite3").resolve()
    assert isinstance(settings.inventory_data_path, Path)
    assert isinstance(settings.inventory_db_path, Path)


def test_optional_gemini_settings_and_cookie_security(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMO_USERNAME", "user")
    monkeypatch.setenv("DEMO_PASSWORD", "password")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_MODEL", "test-model")
    monkeypatch.setenv("CHAT_COOKIE_SECURE", "yes")

    settings = Settings.from_environment()

    assert settings.gemini_api_key == "test-key"
    assert settings.gemini_model == "test-model"
    assert settings.chat_cookie_secure is True


def test_default_gemini_model_is_flash_lite(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMO_USERNAME", "user")
    monkeypatch.setenv("DEMO_PASSWORD", "password")

    settings = Settings.from_environment()

    assert settings.gemini_model == "gemini-3.5-flash-lite"


def test_invalid_cookie_security_setting_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMO_USERNAME", "user")
    monkeypatch.setenv("DEMO_PASSWORD", "password")
    monkeypatch.setenv("CHAT_COOKIE_SECURE", "sometimes")

    with pytest.raises(ConfigurationError, match="CHAT_COOKIE_SECURE"):
        Settings.from_environment()
