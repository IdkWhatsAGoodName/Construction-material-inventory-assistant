"""Offline command for rebuilding the ephemeral SQLite inventory snapshot."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from inventory_assistant.config import (  # noqa: E402
    inventory_data_path_from_environment,
    inventory_database_path_from_environment,
    resolve_project_path,
)
from inventory_assistant.data.ingestion import ingest_inventory  # noqa: E402
from inventory_assistant.data.json_repository import InventoryDataError  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Rebuild the offline SQLite inventory snapshot from validated JSON."
    )
    parser.add_argument("--source", type=Path, help="Source JSON path")
    parser.add_argument("--database", type=Path, help="Destination SQLite path")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    source_path = (
        resolve_project_path(args.source)
        if args.source is not None
        else inventory_data_path_from_environment()
    )
    database_path = (
        resolve_project_path(args.database)
        if args.database is not None
        else inventory_database_path_from_environment()
    )

    try:
        result = ingest_inventory(source_path, database_path)
    except InventoryDataError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    print(
        f"Ingested {result.supplier_count} suppliers and {result.material_count} materials "
        f"from {result.source_filename} into {result.database_path} "
        f"(sha256 {result.source_sha256})."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
