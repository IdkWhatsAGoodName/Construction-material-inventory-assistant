from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from inventory_assistant.data.sqlite_repository import SQLiteInventoryRepository

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_DATA = PROJECT_ROOT / "Requirements" / "inventory_data.json"
SCRIPT = PROJECT_ROOT / "scripts" / "ingest.py"


def run_cli(
    *arguments: str, environment: dict[str, str] | None = None
) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *arguments],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli_flags_build_database_without_demo_credentials(tmp_path: Path) -> None:
    database_path = tmp_path / "inventory.sqlite3"
    environment = os.environ.copy()
    environment.pop("DEMO_USERNAME", None)
    environment.pop("DEMO_PASSWORD", None)

    result = run_cli(
        "--source",
        str(SOURCE_DATA),
        "--database",
        str(database_path),
        environment=environment,
    )

    assert result.returncode == 0
    assert "Ingested 9 suppliers and 77 materials" in result.stdout
    assert "sha256" in result.stdout
    assert result.stderr == ""
    assert len(SQLiteInventoryRepository(database_path).list_materials()) == 77


def test_cli_uses_environment_defaults_and_reports_known_failure(tmp_path: Path) -> None:
    database_path = tmp_path / "inventory.sqlite3"
    environment = os.environ.copy()
    environment["INVENTORY_DATA_PATH"] = str(SOURCE_DATA)
    environment["INVENTORY_DB_PATH"] = str(database_path)
    assert run_cli(environment=environment).returncode == 0
    original_bytes = database_path.read_bytes()

    environment["INVENTORY_DATA_PATH"] = str(tmp_path / "missing.json")
    failed = run_cli(environment=environment)

    assert failed.returncode == 1
    assert failed.stdout == ""
    assert failed.stderr.startswith("error: Unable to read inventory data")
    assert database_path.read_bytes() == original_bytes
