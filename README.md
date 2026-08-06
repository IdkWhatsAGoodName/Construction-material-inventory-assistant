# Construction Material Inventory Assistant

This repository implements the construction material inventory assistant described in
[`Requirements/README.md`](Requirements/README.md) as a sequence of runnable vertical
steelthreads.

## Current implementation

Steelthreads 1 through 5 provide a FastAPI web application that:

- validates the supplied synthetic JSON and atomically rebuilds a SQLite snapshot at process
  startup;
- displays all 77 materials with raw availability, non-negative shippable quantity, status, and
  ordered inventory conditions;
- conservatively matches normalized catalogue tokens while reporting exact, unique, ambiguous,
  and no-match outcomes without fuzzy substitution;
- exposes protected catalogue, inventory, supplier, discrepancy, and two-step order APIs plus API
  documentation;
- keeps the known over-allocation visible in a linked, non-modal warning banner;
- evaluates customer orders, calculates decimal-safe totals, and requires explicit confirmation
  before reserving inventory;
- renders all inventory, supplier, and order facts through deterministic application services
  shared by the HTTP and browser layers;
- embeds an optional Gemini chat interface that iteratively chooses typed tools while displaying
  every authoritative outcome in a separate verified application result box;
- keeps conversational sessions, transcripts, and multiple pending chat orders isolated through
  an opaque HttpOnly cookie for 30 minutes of inactivity;
- protects every non-health route with one shared HTTP Basic credential; and
- provides public liveness and readiness endpoints for Render.

The application preserves raw `qty_available = qty_on_hand - qty_reserved`, including negative
values. It separately reports `qty_shippable = max(qty_available, 0)` and never describes negative
stock as shippable. Placing an order increases `qty_reserved` without changing `qty_on_hand`.

The SQLite schema normalizes snapshot metadata, suppliers, and materials; enables foreign-key
checks; uses [`STRICT` tables](https://www.sqlite.org/stricttables.html); and stores CAD prices as
integer cents. Availability remains derived rather than stored. Ingestion records the source
filename, byte length, SHA-256 digest, timestamp, schema version, and record counts. A fully built
and parity-checked sibling file replaces the session database only after validation, so a failed
ingestion leaves the prior valid file intact. Each successful process start intentionally replaces
any previous session changes with the committed JSON values.

Matching uses Unicode NFKC normalization, case folding, punctuation/separator normalization, and
a small alias set for common units and catalogue plurals. Exact normalized SKUs and full
descriptions win; otherwise every meaningful query token must occur in the SKU, description,
category, grade, or unit. The matcher does not rank, fuzz, or silently choose a near match.

Orders use an evaluate-then-confirm workflow. Evaluation is read-only, rejects discontinued or
insufficient stock without partial fulfilment, and may show a clearly labelled hypothetical total
for a rejected request. A valid evaluation creates an opaque, 15-minute process-memory
confirmation token bound to the exact SKU, quantity, price, on-hand quantity, reserved quantity,
and discontinued state. Confirmation revalidates that state in a SQLite `BEGIN IMMEDIATE`
transaction before increasing `qty_reserved`. Sequential or concurrent replay of a consumed token
returns its cached terminal result without reserving twice. There is no first-class order record,
tax, discount, shipment, or durable idempotency key in this demo. See the official documentation
for Python [`secrets`](https://docs.python.org/3/library/secrets.html) and
[SQLite transactions](https://sqlite.org/lang_transaction.html).

Chat uses Google's Gemini Interactions API through an application-owned, stateless orchestration
loop. Gemini receives only explicit function declarations, bounded recent context, session-local
pending-order summaries, and deterministic function results. The application manually validates
and executes every call; Gemini has no database, repository, arbitrary HTTP, or raw confirmation
token access. Independent calls may be returned together, while dependent calls wait for prior
results. A turn is bounded to five routing interactions and ten proposed application calls.
Orders evaluated during a turn cannot be confirmed until a later explicit-confirmation turn.

After successful orchestration, Gemini may add a separately labelled, non-authoritative comment.
The verified result boxes remain controlling, and commentary is omitted unless all number,
currency, date/time, and SKU-like tokens already occur in the verified results. Gemini requests
use `store=false`, so no provider-hosted conversation history is used. The free Gemini API tier
currently permits Google to use submitted content to improve its products; use only this synthetic
demo data and review Google's current [Gemini pricing and data-use terms](https://ai.google.dev/gemini-api/docs/pricing)
before supplying a key.

## Run locally

Python 3.13 is required. From PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
$env:DEMO_USERNAME = "demo"
$env:DEMO_PASSWORD = "choose-a-long-random-password"
$env:GEMINI_API_KEY = "your-gemini-api-key" # Optional; omit to run deterministic features only
.\.venv\Scripts\uvicorn.exe inventory_assistant.main:app --app-dir src --reload
```

The committed [`.env.example`](.env.example) lists all settings without real secrets. Copy values
into your shell or an ignored `.env`; never place a real Gemini key or demo password in a tracked
file.

Then open `http://127.0.0.1:8000/` and enter the configured credential. Do not commit local
credentials. `INVENTORY_DATA_PATH` can override the default
`Requirements/inventory_data.json` source and `INVENTORY_DB_PATH` can override the default
`var/inventory.sqlite3` destination. Relative paths resolve from the project root.
`GEMINI_MODEL` defaults to `gemini-3.6-flash`. `CHAT_COOKIE_SECURE` defaults to false for local
HTTP and is set to true by the Render Blueprint.

To build the same snapshot without starting the web application or requiring demo credentials:

```powershell
.\.venv\Scripts\python.exe scripts\ingest.py
```

The command accepts `--source` and `--database`; command-line values take precedence over the
corresponding environment variables. It is an offline operation—there is deliberately no runtime
re-ingestion HTTP endpoint.

Run the verification suite with:

```powershell
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\ruff.exe format --check .
.\.venv\Scripts\pytest.exe
```

The [`bruno`](bruno) collection provides human-run HTTP checks for the protected endpoints,
authentication gate, deterministic ordering, and iterative chat behavior. Its environment reads
`DEMO_USERNAME` and `DEMO_PASSWORD` from the Bruno process, so no real credential is stored in the
collection. Run these against local with the Bruno app or CLI.

## Routes

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
- `POST /api/orders/evaluate` — read-only deterministic quote or rejection
- `POST /api/orders/confirm` — explicit, idempotent session-lifetime reservation confirmation
- `POST /api/chat` — bounded iterative tool orchestration with structured verified results
- `GET /openapi.json`, `GET /docs`, and `GET /redoc` — API contract and interactive docs

These application APIs serve the protected browser and operators. Gemini does not receive
arbitrary API or dataset access; its explicit function declarations invoke the same deterministic
application services in-process.

## Deployment

The root `render.yaml` defines one free native-Python Render web service at
`https://sidian-inventory-assistant-demo.onrender.com`. Render waits for the GitHub Actions checks
to pass before automatically deploying updates from `main`. `DEMO_USERNAME` and `DEMO_PASSWORD`
and `GEMINI_API_KEY` are Render secrets declared with `sync: false`; no secret values belong in the
repository. The application remains ready and deterministic features remain usable if the Gemini
key is absent or the provider is unavailable.

Render's free service filesystem and process lifetime are ephemeral. Every application process
start rebuilds `var/inventory.sqlite3` from the committed source JSON before readiness. SQLite
reservations, pending confirmation tokens, chat sessions, transcripts, and cached terminal results
therefore intentionally reset on spin-down, restart, or redeploy. Chat sessions also expire after
30 minutes of inactivity. The in-memory confirmation registry assumes the
single Uvicorn process configured in `render.yaml`; multiple workers would not share tokens. This
session-lifetime behavior is suitable for the demo, not durable order storage.
