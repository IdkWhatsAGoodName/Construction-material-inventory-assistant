# Construction Material Inventory Assistant

This repository implements the construction material inventory assistant described in
[`Requirements/README.md`](Requirements/README.md) as a sequence of runnable vertical
steelthreads.

## Current implementation

Steelthreads 1 and 2 provide a read-only FastAPI web application that:

- validates and loads the supplied synthetic JSON at process startup;
- displays all 77 materials with raw availability, non-negative shippable quantity, status, and
  ordered inventory conditions;
- conservatively matches normalized catalogue tokens while reporting exact, unique, ambiguous,
  and no-match outcomes without fuzzy substitution;
- exposes protected catalogue, inventory, supplier, and discrepancy APIs plus API documentation;
- keeps the known over-allocation visible in a linked, non-modal warning banner;
- renders all inventory and supplier facts through deterministic application services shared by
  the HTTP and browser layers;
- protects every non-health route with one shared HTTP Basic credential; and
- provides public liveness and readiness endpoints for Render.

The application preserves raw `qty_available = qty_on_hand - qty_reserved`, including negative
values. It separately reports `qty_shippable = max(qty_available, 0)` and never describes negative
stock as shippable. SQLite, orders, and conversational interpretation remain later steelthreads.

Matching uses Unicode NFKC normalization, case folding, punctuation/separator normalization, and
a small alias set for common units and catalogue plurals. Exact normalized SKUs and full
descriptions win; otherwise every meaningful query token must occur in the SKU, description,
category, grade, or unit. The matcher does not rank, fuzz, or silently choose a near match.

## Run locally

Python 3.13 is required. From PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
$env:DEMO_USERNAME = "demo"
$env:DEMO_PASSWORD = "choose-a-long-random-password"
.\.venv\Scripts\uvicorn.exe inventory_assistant.main:app --app-dir src --reload
```

Then open `http://127.0.0.1:8000/` and enter the configured credential. Do not commit local
credentials. `INVENTORY_DATA_PATH` can override the default
`Requirements/inventory_data.json` path for explicit local testing.

Run the verification suite with:

```powershell
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\ruff.exe format --check .
.\.venv\Scripts\pytest.exe
```

The [`bruno`](bruno) collection provides human-run HTTP checks for the protected endpoints and authentication gate. Its environment reads `DEMO_USERNAME` and `DEMO_PASSWORD` from the Bruno process, so no real credential is stored in the collection. Run these against local with the Bruno app or CLI.

## Read-only routes

The following health routes are intentionally public:

- `GET /health/live`
- `GET /health/ready`

All other routes require HTTP Basic authentication:

- `GET /` — server-rendered catalogue, deterministic filter, and discrepancy warning
- `GET /api/catalog/summary` — source metadata and record counts
- `GET /api/catalog/materials?q=` — material list with optional all-token filtering
- `GET /api/inventory/search?q=` — explicit exact, unique, ambiguous, or no-match outcome
- `GET /api/inventory/{sku}` — exact case-insensitive SKU lookup
- `GET /api/inventory/alerts` — current over-allocation discrepancies
- `GET /api/suppliers?category=` — supplier resolution for a material category
- `GET /api/suppliers/{supplier_id}` — exact case-insensitive supplier lookup
- `GET /openapi.json`, `GET /docs`, and `GET /redoc` — API contract and interactive docs

These application APIs serve the protected browser and operators. A future LLM will not receive
arbitrary HTTP or dataset access; it will be restricted to explicit function declarations backed
by the same deterministic application services.

## Deployment

The root `render.yaml` defines one free native-Python Render web service at
`https://sidian-inventory-assistant-demo.onrender.com`. Render waits for the GitHub Actions checks
to pass before automatically deploying updates from `main`. `DEMO_USERNAME` and `DEMO_PASSWORD`
are Render secrets declared with `sync: false`; no secret values belong in the repository.

Render's free service filesystem and process lifetime are ephemeral. The current read-only slice
reloads the committed source JSON after a restart. Later SQLite order state will intentionally
reset on restart and will be documented when that behavior exists.
