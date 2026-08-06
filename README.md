# Construction Material Inventory Assistant

This repository implements the construction material inventory assistant described in
[`Requirements/README.md`](Requirements/README.md) as a sequence of runnable vertical
steelthreads.

## Current implementation

Steelthread 1 is a read-only FastAPI web application that:

- validates and loads the supplied synthetic JSON at process startup;
- displays all 77 materials and supports literal text filtering;
- exposes protected catalogue APIs and API documentation;
- protects every non-health route with one shared HTTP Basic credential; and
- provides public liveness and readiness endpoints for Render.

It deliberately displays `qty_on_hand` and `qty_reserved` under their source names. It does not
yet calculate or label availability. Deterministic availability rules, inventory alerts, SQLite,
orders, and conversational interpretation are later steelthreads.

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

The [`bruno`](bruno) collection provides executable HTTP checks for every MVP endpoint and the
authentication gate. Its environment reads `DEMO_USERNAME` and `DEMO_PASSWORD` from the Bruno
process, so no real credential is stored in the collection. With the application running, execute
`bru run bruno --env Local` from the repository root.

## MVP routes

The following health routes are intentionally public:

- `GET /health/live`
- `GET /health/ready`

All other routes require HTTP Basic authentication:

- `GET /` — server-rendered catalogue and search form
- `GET /api/catalog/summary` — source metadata and record counts
- `GET /api/catalog/materials?q=` — material list with optional literal filtering
- `GET /openapi.json`, `GET /docs`, and `GET /redoc` — API contract and interactive docs

`/api/catalog/summary` is an application API for the protected browser and operators. A future
LLM will not receive arbitrary HTTP access and this route will not be included in its explicit
function declarations.

## Deployment

The root `render.yaml` defines one free native-Python Render web service. Render waits for the
GitHub Actions checks to pass before automatically deploying updates from `main`. During the
initial Blueprint creation flow, set `DEMO_USERNAME` and `DEMO_PASSWORD`; both are declared with
`sync: false` and no secret values belong in the repository.

Render's free service filesystem and process lifetime are ephemeral. This read-only slice simply
reloads the committed source JSON after a restart. Later SQLite order state will intentionally
reset on restart and will be documented when that behavior exists.
