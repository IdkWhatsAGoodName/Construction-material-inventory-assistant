"""Environment-backed application configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class ConfigurationError(RuntimeError):
    """Raised when required application configuration is absent or invalid."""


@dataclass(frozen=True, slots=True)
class Settings:
    """Validated runtime settings."""

    demo_username: str
    demo_password: str
    inventory_data_path: Path
    inventory_db_path: Path
    gemini_api_key: str | None
    gemini_model: str
    chat_cookie_secure: bool

    @classmethod
    def from_environment(cls) -> Settings:
        """Load settings, failing closed when required credentials are absent."""
        username = os.environ.get("DEMO_USERNAME")
        password = os.environ.get("DEMO_PASSWORD")

        missing = [
            name
            for name, value in (
                ("DEMO_USERNAME", username),
                ("DEMO_PASSWORD", password),
            )
            if not value
        ]
        if missing:
            joined = ", ".join(missing)
            raise ConfigurationError(f"Missing required environment variable(s): {joined}")

        return cls(
            demo_username=username,
            demo_password=password,
            inventory_data_path=inventory_data_path_from_environment(),
            inventory_db_path=inventory_database_path_from_environment(),
            gemini_api_key=os.environ.get("GEMINI_API_KEY") or None,
            gemini_model=os.environ.get("GEMINI_MODEL", "gemini-3.6-flash"),
            chat_cookie_secure=_boolean_from_environment("CHAT_COOKIE_SECURE", default=False),
        )


def resolve_project_path(value: str | Path) -> Path:
    configured_path = Path(value)
    if not configured_path.is_absolute():
        configured_path = PROJECT_ROOT / configured_path
    return configured_path.resolve()


def inventory_data_path_from_environment() -> Path:
    return resolve_project_path(
        os.environ.get("INVENTORY_DATA_PATH", "Requirements/inventory_data.json")
    )


def inventory_database_path_from_environment() -> Path:
    return resolve_project_path(os.environ.get("INVENTORY_DB_PATH", "var/inventory.sqlite3"))


def _boolean_from_environment(name: str, *, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigurationError(f"{name} must be a boolean value")
