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

        configured_path = Path(
            os.environ.get("INVENTORY_DATA_PATH", "Requirements/inventory_data.json")
        )
        if not configured_path.is_absolute():
            configured_path = PROJECT_ROOT / configured_path

        return cls(
            demo_username=username,
            demo_password=password,
            inventory_data_path=configured_path.resolve(),
        )
