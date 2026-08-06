# General design and programming rules

- When experiencing insufficient tooling or tooling failure, do not simply try to work around the limitation. Stop what you are doing instead and instruct the human to either manually add, fix, or reconfigure the tooling, or to provide permission for you to do it.
- Do not take instructions at face value. Always verify claims and reasoning provided by the human, and challenge or push back when things seem wrong, incomplete, or unclear.
- Always provide references to authoritative sources for claims. For example, provide official documentation when explaining how a tool works and code locations when explaining application logic.
- When trying to work with a new tool or framework, look for related MCP servers first. If one exists, either add it when permitted or ask the human to add it. Prefer authoritative MCP documentation over general web search.
- Before editing these general rules, present the exact proposed changes to the human and obtain explicit approval.
- When the human gives a reusable instruction, propose a generalized version for this file, but do not add it without approval.
- For material design decisions, present viable alternatives, their advantages and disadvantages, and a recommendation, then obtain the human's decision instead of assuming one.
- Structure implementation as vertical steelthreads. Every completed step must leave the application runnable and verified, with later optional functionality degrading gracefully when unavailable. Keep the plan below current as work progresses.
- Treat `AGENTS.md` as a living project reference, not an immutable source of truth. Update its plans, recorded decisions, status, and future work when the project changes; use Git history rather than stale text to preserve superseded guidance.
- When `AGENTS.md` differs from content previously written or remembered by the agent, assume the discrepancy is an intentional human edit and preserve it. If the discrepancy appears to be an accidental typo, contradiction, or malformed content, raise the concern with the human before changing it.
- Keep in mind that this is a small demonstration exercise, so choose free tools and hosting when practical.
- Prioritize designs and tools that enable fast development at small scale, and document what would be changed or added with more time and resources in the "Future TODOs" section.
- Never create commits or push commits, tags, branches, or other Git refs to a remote repository on the human’s behalf. Leave code change ready on local and let human manage source control.
- Always remember to add Bruno requests for testing after implementing code where applicable. Leave request validation to human.
- On Windows with Python 3.13 or later, run the project-local pytest executable outside the Codex filesystem sandbox because Python's `0o700` temporary-directory ACLs cannot be reopened by the sandbox token. Keep the permission exception scoped to the project-local pytest command, and never run pytest as Windows Administrator.


# Design and implementation plans

## Goal and constraints

Build the construction material inventory assistant specified in `Requirements/README.md`. The delivered program must ingest the supplied synthetic JSON, expose deterministic inventory and ordering behavior, provide a conversational web interface, and be deployable at a public URL. Every number shown to a user must originate from application code operating on the source data/database, never from model-generated knowledge.

Current status: steelthreads 1 through 4 are complete and deployed at `https://sidian-inventory-assistant-demo.onrender.com`. Steelthread 5 is implemented locally and passes 162 tests, Ruff lint/format checks, JavaScript syntax validation, dependency validation with `google-genai` 2.17.0, wheel/asset packaging, and Render Blueprint validation. The human must configure a Gemini API key, perform live-Gemini/Bruno/browser validation, review, commit, push, and verify CI and the resulting deployment before steelthread 5 is complete. Steelthread 4 commit `4d0b0d3` passed GitHub Actions CI run `31090725994` and the human's protected local/remote verification. Python 3.13, Git, GitHub CLI, Render CLI, the curated GitHub and Render Codex plugins, and Render MCP are installed and verified. Use authenticated GitHub CLI for programmatic GitHub operations: the human explicitly waived the GitHub App connector check after Codex CLI's connector-directory request was blocked by a Cloudflare challenge even though Codex Doctor and GitHub CLI authentication passed.

## Agreed demo design

- Use Python 3.13, FastAPI, a project-local virtual environment, and `pip`. FastAPI is the server framework and generates the OpenAPI contract. See [FastAPI features](https://fastapi.tiangolo.com/features/) and the [OpenAPI specification](https://spec.openapis.org/oas/v3.0.4.html).
- Build a modular monolith and deploy it as one web service. Serve a small HTML/CSS/JavaScript interface from FastAPI rather than introducing a separate frontend framework and deployment. FastAPI supports [templates](https://fastapi.tiangolo.com/advanced/templates/) and [static files](https://fastapi.tiangolo.com/tutorial/static-files/).
- Start with the supplied JSON as a read-only repository, then add repeatable SQLite ingestion behind the same repository interface. Python provides standard-library [SQLite support](https://docs.python.org/3/library/sqlite3.html).
- When SQLite is introduced, build a fresh database from the supplied JSON at every application process start, validate it completely before readiness, and replace any previous session database rather than upserting or preserving runtime reservations. Reuse this implementation from `scripts/ingest.py`, expose no runtime re-ingestion HTTP endpoint, and add no migration framework for the ephemeral demo. Local restarts intentionally reset session orders just like Render restarts. Persistent snapshot reconciliation and schema migrations belong to the future PostgreSQL design.
- Use SQLite `STRICT` tables with normalized snapshot, supplier, and material records; case-insensitive supplier/SKU keys; enforced foreign keys and integrity checks; and indexes for category, supplier, and warehouse. Store CAD prices as integer cents after rejecting source prices with more than two fractional digits. Keep availability and per-material currency derived rather than duplicated.
- Default the database to project-relative `var/inventory.sqlite3`, allow `INVENTORY_DB_PATH` to override it, and open a separate connection per repository operation. Use the rollback journal for the replaceable demo snapshot. Record only the source filename (not its local path), exact-byte SHA-256, byte length, UTC ingestion time, schema version, and record counts.
- Keep `scripts/ingest.py` offline-only and independent of demo credentials. Its explicit `--source` and `--database` flags override environment/default paths. Build a sibling temporary database, validate integrity, foreign keys, provenance, and complete JSON/repository parity, close all connections, and atomically replace the destination only after success.
- Preserve the mandated raw `qty_available = qty_on_hand - qty_reserved` value even when it is negative. Separately derive `qty_shippable = max(qty_available, 0)`, `overallocated_by = max(-qty_available, 0)`, and an inventory status. Use `qty_shippable` for order validation while returning the raw value and discrepancy fields in structured responses. User-facing messages must say that zero units can ship and state the over-allocation, on-hand quantity, and reserved quantity rather than describing a negative number as shippable stock.
- Keep unresolved over-allocations persistently visible through a non-modal inventory-warning banner on protected browser pages, backed by a deterministic `GET /api/inventory/alerts` endpoint and linked to the affected materials. Calculate the warning on initial page load and refresh it after successful order mutations; do not poll when no external inventory updates can occur, repeatedly inject it into chat responses, or use recurring toasts or dialogs. Render an initial warning as ordinary semantic content and expose a dynamically changed warning as an accessible, non-focus-stealing status message. The demo has no correction workflow, so state that in the status message. See the W3C [Alert Pattern](https://www.w3.org/WAI/ARIA/apg/patterns/alert/) and [status-message guidance](https://www.w3.org/WAI/WCAG22/Understanding/status-messages.html).
- Keep domain rules and application services independent of HTTP, persistence, and the LLM provider. HTTP routes and agent tools must call the same application services so their behavior cannot diverge.
- Use in-process application-service calls for agent tools in the demo. Do not make the agent call the application's own HTTP API.
- Keep the protected `GET /api/catalog/summary` endpoint for the browser UI and operational source metadata. It returns only the dataset name, as-of date, currency, notes, and record counts, not raw supplier or material records. Do not expose this endpoint or arbitrary HTTP access to Gemini; the later provider adapter receives only the explicitly declared inventory and ordering tool schemas.
- Use Gemini's free tier through the Interactions API as the initial LLM provider behind a narrow provider interface. Use the stable `gemini-3.6-flash` model by default and make the model ID configurable through an environment variable. Only one provider implementation is in demo scope. The free tier's data-use terms must be documented. See the [Gemini API reference](https://ai.google.dev/api), [latest-model guidance](https://ai.google.dev/gemini-api/docs/latest-model), and [pricing](https://ai.google.dev/gemini-api/docs/pricing).
- Make the LLM optional to the core application. Catalogue browsing, deterministic APIs, and order operations must remain usable without an API key or during provider failure; only conversational interpretation may become unavailable.
- Limit the LLM to selecting typed tools and supplying arguments. It must not receive direct database access, calculate inventory figures, enforce business rules, or write the authoritative factual response. Declare Gemini function schemas explicitly, disable automatic function execution, validate proposed arguments in application code, execute application services manually, and display complete deterministic messages in clearly titled verified-result boxes. See [Gemini function calling](https://ai.google.dev/gemini-api/docs/function-calling) and the [Google Gen AI Python SDK](https://googleapis.github.io/python-genai/index.html).
- Use a bounded stateless Gemini Interactions loop with `store=false` and function-calling mode `any`. Preserve and resend the original input, every model-generated step and thought signature, and every application `function_result` so Gemini can wait for prerequisites before selecting dependent calls. Permit independent calls together, stop after five routing interactions or ten proposed application calls, require the no-argument `finish_turn` tool to be the sole completion call, and make no automatic provider retry. Treat these limits and best-effort dependency handling as POC safeguards that require stronger production orchestration later.
- Use the tool surface `show_help`, `query_inventory`, `get_supplier_terms`, `evaluate_order`, `place_confirmed_order`, `cancel_pending_order`, and `finish_turn`. Expose placement/cancellation only when application code detects the corresponding explicit intent and eligible pending orders existed at turn start. Freeze mutation eligibility for the complete turn so an order evaluated during a message cannot be confirmed until a later explicit-confirmation message. Allow Gemini to map natural-language bulk confirmation/cancellation requests to multiple session-local pending-order references; accept this powerful POC behavior while documenting that production authorization must not rely on model interpretation alone.
- Keep conversational state in the application rather than relying on provider-hosted history. Isolate recipients with a cryptographically random HttpOnly cookie and retain at most 20 transcript turns, recent requests, and multiple pending-order summaries in concurrency-safe process memory for 30 minutes of inactivity. Gemini may receive bounded recent requests, minimal pending-order summaries, and current deterministic function results, but never raw database records, cookies, credentials, or confirmation tokens.
- After `finish_turn`, request one tools-disabled, `store=false` Gemini commentary covering all verified results. Display it separately and label it non-authoritative. Prompt it not to add facts and omit it completely unless every numeric, currency, date/time, and SKU-like token already appears in the verified application messages. Provider or validation failure must never hide verified results or break deterministic features.
- Require an explicit confirmation step before the mutating order tool runs. All validation must be repeated inside the final database transaction; the confirmation step is not authorization to use stale availability.
- For the essential demo, do not persist first-class order records. Keep pending confirmation details and terminal confirmation results in a small, concurrency-safe, process-memory registry keyed by an opaque, securely generated token. Bind each token to the evaluated material, quantity, price, and inventory state; consume it at most once, return the cached terminal result on replay, and revalidate all rules inside the reservation transaction. Losing this registry on restart is acceptable because the ephemeral database and its reservations reset at the same time.
- Expire unconfirmed order tokens after 15 minutes using a monotonic deadline and return an absolute UTC expiry to clients. Keep successful and stale terminal results replayable for the remaining process session. Treat unknown, expired, and restart-lost tokens identically. Serialize confirmations with an in-process lock for the demo's single Uvicorn process and use a SQLite `BEGIN IMMEDIATE` transaction plus an exact-state conditional update; database-backed cross-process idempotency remains future work.
- Expose protected `POST /api/orders/evaluate` and `POST /api/orders/confirm` actions. Valid business rejections are deterministic `200` outcomes, stale confirmation is `409`, unknown/expired confirmation is `404`, transient reservation persistence failure is `503`, and structurally invalid input is `422`. Show clearly labelled hypothetical line totals for rejected requests. In the catalogue, give every row an Order action that opens one shared accessible evaluation/confirmation panel, refreshes the affected row and inventory alerts after confirmation, and shows a static expiry time without a live countdown.
- Host the demo as one free Render web service using Render's native Python runtime and an ephemeral SQLite database rebuilt from the supplied JSON at each process start. Accept and prominently document that order state is session-lifetime only and is lost on spin-down, restart, or redeployment. Render free services spin down after 15 idle minutes and cannot attach persistent disks: [Render free services](https://render.com/docs/free).
- Use a public GitHub repository and standard GitHub Actions runners for CI. On pull requests and pushes to `main`, install pinned dependencies, lint, and run tests. Configure Render to deploy `main` only after CI checks pass, using a committed `render.yaml` Blueprint and a readiness endpoint. Store `GEMINI_API_KEY` only as a Render secret. See [GitHub Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions), [Render deploy controls](https://render.com/docs/deploys), and [Render Blueprints](https://render.com/docs/infrastructure-as-code).
- Prefer the native Render Python build for this demo rather than adding Docker. Record a portable container build as future work.
- Use `pyproject.toml` as the canonical project, dependency, pytest, and Ruff configuration with setuptools as the build backend. Use `pip-tools` to compile and commit exact runtime and development dependency sets as `requirements.txt` and `requirements-dev.txt`; Render installs the runtime file and GitHub Actions installs the development file. See the Python Packaging Guide for [`pyproject.toml`](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/) and the [`src` layout](https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/).
- Use pytest for unit, integration, and acceptance tests and Ruff for both linting and formatting. CI runs `ruff check .`, `ruff format --check .`, and `pytest` on Python 3.13 only. Ruff documents both [linting](https://docs.astral.sh/ruff/linter/) and non-mutating [format checks](https://docs.astral.sh/ruff/formatter/).
- Protect the demo with one shared HTTP Basic credential. Require authentication for the web UI, application APIs, chat endpoint, OpenAPI schema, and interactive API documentation; leave only minimal `/health/live` and `/health/ready` endpoints public for Render. Read `DEMO_USERNAME` and `DEMO_PASSWORD` from Render secrets declared with `sync: false`, fail startup when either is missing, compare both with `secrets.compare_digest()`, return a generic `401` on failure, and never log authorization headers or credentials. This is a demonstration access gate, not production identity management. See [FastAPI HTTP Basic](https://fastapi.tiangolo.com/advanced/security/http-basic-auth/) and [Render secrets](https://render.com/docs/configure-environment-variables).

## Proposed folder structure

```text
/
|-- AGENTS.md
|-- README.md
|-- Requirements/                 # supplied brief and source dataset
|-- docs/
|   `-- system-flow.md             # flowchart and design rationale
|-- src/
|   `-- inventory_assistant/
|       |-- domain/                # entities and business rules
|       |-- data/                  # JSON/SQLite repositories and ingestion
|       |-- application/           # inventory, supplier, and order use cases
|       |-- api/                   # HTTP routes and request/response models
|       |-- agent/                 # tool schemas, orchestration, provider adapter
|       |-- web/                   # templates and static browser assets
|       |-- config.py              # environment-backed configuration
|       `-- main.py                # application composition root
|-- scripts/
|   `-- ingest.py                  # repeatable explicit ingestion command
|-- tests/
|   |-- unit/
|   |-- integration/
|   `-- acceptance/
|-- pyproject.toml                 # canonical project and tool configuration
|-- requirements.txt              # compiled, pinned runtime dependencies
`-- requirements-dev.txt          # compiled, pinned development dependencies
```

Do not split the demo into separately deployed frontend, agent, and inventory services. Preserve internal boundaries so those components can be extracted later without rewriting domain behavior.

## Steelthread implementation sequence

Each numbered step is independently runnable and is completed only when its stated verification passes. Do not begin a later step by breaking or replacing the working path from an earlier one.

1. **Deployed JSON-reading web MVP — complete**
   - Status: complete. Commit `82e494f`, CI, the Render Blueprint deployment, public health checks, and the unauthenticated access boundary are verified.
   - Scaffold the FastAPI service, `pyproject.toml`, compiled requirement files, Ruff/pytest configuration, tests, and minimal browser page.
   - Load and validate `Requirements/inventory_data.json` through a JSON repository without mutating it.
   - Expose a health endpoint, dataset metadata, and a browsable material list with basic text filtering.
   - Add the shared HTTP Basic gate to every non-health route and require credentials at startup.
   - Add the GitHub Actions CI workflow and Render Blueprint, then deploy the working MVP publicly before adding later behavior.
   - Verify startup failure for missing/invalid data and missing credentials, protected-route `401` behavior, authorized access, public health checks, the displayed counts of 9 suppliers and 77 materials, and the public URL.

2. **Deterministic read-only inventory behavior — complete**
   - Status: commit `e1de56d` passed CI and is live on Render. Local automated verification, public smoke checks, and the human's protected Bruno/browser checks pass.
   - Add domain models, raw availability, non-negative shippable quantity, explicit over-allocation status, catalogue matching, supplier lookup, and deterministic message rendering.
   - Add read-only application services and HTTP endpoints for stock, search, supplier terms, and inventory alerts.
   - Add the persistent, non-modal over-allocation banner to the protected browser UI, with affected-material links and accessible semantics.
   - Distinguish exact matches, no matches, and ambiguous matches; never silently substitute a near match.
   - Verify the read-only portions of all required prompts plus over-allocated, fully reserved, discontinued, zero-stock, and unknown-SKU cases; verify that the warning appears while a discrepancy exists and is absent when none exists.

3. **Repeatable SQLite ingestion — complete**
   - Status: commit `3fff68a` passed 96 local tests, Ruff checks, GitHub Actions CI run `31088132893`, public deployed smoke checks, and the human's local database-reset and protected remote verification.
   - Add normalized supplier and material tables, constraints, indexes, and an ingestion record containing source metadata.
   - Build and validate a fresh SQLite file at every process start, atomically replace the previous session file only after success, and reuse the same operation from `scripts/ingest.py`.
   - Switch the application to the SQLite repository without changing observable read behavior; do not add an upsert path, runtime ingestion endpoint, or demo migration framework.
   - Keep the JSON repository available for the first-slice fallback and focused tests.
   - Verify repeated clean replacement, foreign-key integrity, preservation of the prior valid file after failed ingestion, readiness failure on invalid input, session reset behavior, and JSON/SQLite response parity.

4. **Deterministic order workflow — complete**
   - Status: commit `4d0b0d3` passed 140 local tests, Ruff checks, wheel/asset packaging, JavaScript syntax validation, dependency validation, ingestion smoke testing, GitHub Actions CI run `31090725994`, public deployed smoke checks, and the human's protected local/remote browser verification.
   - Add order evaluation, process-memory confirmation/idempotency state, explicit confirmation, and transactional reservation updates without a first-class orders table.
   - Reject quantities above derived availability, discontinued materials, invalid quantities, unknown/ambiguous products, and stale confirmations. Never partially fulfill silently.
   - Increase `qty_reserved` without decreasing `qty_on_hand`; calculate totals in application code using decimal-safe currency arithmetic.
   - Verify successful reservation, concurrent and sequential confirmation replay without double reservation, unknown or stale confirmation handling, registry reset with the process, all rejection paths, and the required 500-length rebar and discontinued-plate prompts.

5. **Conversational tool-calling interface**
   - Status: implemented locally and verified with 162 tests, Ruff lint/format, JavaScript syntax, dependency, wheel/asset packaging, and Render Blueprint checks. Human Gemini-key configuration, live-Gemini/Bruno/browser validation, review, commit/push, CI, and deployed verification remain.
   - Add the Gemini Interactions API adapter, explicit function schemas, manual call execution, application-owned 30-minute browser sessions, bounded iterative orchestration, protected chat endpoint, and embedded catalogue chat UI.
   - Reuse the persistent inventory-warning banner in the chat UI without inserting the warning into every conversational response.
   - Use function-calling mode `any`, return deterministic results between rounds so Gemini can select dependent calls, and restrict placement/cancellation tools to eligible pending orders and explicit action turns.
   - Render handler messages verbatim in verified-result boxes, then optionally add separately labelled, token-validated Gemini commentary. Log routing rounds, tool name, validated arguments, result status, latency, termination, and provider errors without logging secrets.
   - When Gemini is unconfigured or unavailable, keep the catalogue and deterministic endpoints working and show a clear chat-specific error.
   - Run acceptance tests for all five supplied prompts and paraphrased, compound, ambiguous, and adversarial variants.

6. **Submission hardening and documentation**
   - Confirm the GitHub Actions-to-Render pipeline still gates production deployment on successful CI and verify recovery after an ephemeral database reset.
   - Add the system flowchart, local setup, schema rationale, implemented/skipped rules, assumptions, limitations, and another-week improvements to `README.md`/`docs/system-flow.md`.
   - Verify a clean local setup, production startup, public smoke test, expected session-lifetime reset behavior, and secret-free repository history.

# Future TODOs

- Extract an agent gateway from the modular monolith only when independent scaling, ownership, security, or failure isolation justifies the operational cost. The gateway would call a versioned inventory HTTP API generated/documented through OpenAPI.
- Add an MCP adapter over the inventory application API when multiple compatible AI hosts need tool discovery and invocation. Keep REST/OpenAPI as the general service contract; MCP is an agent-facing protocol with its own stateful client/server lifecycle. See the [MCP architecture](https://modelcontextprotocol.io/docs/learn/architecture).
- Add a Dockerfile and container build when deployment portability or runtime reproducibility justifies the additional demo complexity.
- Replace ephemeral SQLite first with free Neon Postgres when order persistence across Render spin-downs and deployments becomes necessary. For a larger production system, use managed PostgreSQL with atomic conditional reservation, row locking, connection pooling, migrations, backups, and disaster recovery. SQLite serializes writers even though transactions are isolated: [SQLite isolation](https://www.sqlite.org/isolation.html). Neon currently offers a no-expiry free tier suitable for the first upgrade: [Neon pricing](https://neon.com/pricing).
- Add mypy, coverage thresholds, pre-commit hooks, automated dependency updates, and dependency/security scanning when the project needs broader enforcement than the demo's Ruff and pytest checks.
- Integrate a real ERP feed with incremental synchronization, reconciliation, data-quality quarantine, freshness indicators, source-version tracking, and an over-allocation remediation workflow with acknowledgement, assignment, correction, and appropriately rate-limited external notifications.
- Optionally add a deterministic shipment-receiving function after the essential steelthreads. It must validate a positive received quantity and transactionally increase `qty_on_hand`; it must never write `qty_available` directly because availability remains derived as `qty_on_hand - qty_reserved`. Refresh inventory status after receipt so a sufficiently large shipment clears the affected over-allocation warning. Decide whether to expose this operation through a protected API, browser control, and/or agent tool before implementing it, along with its confirmation, authorization, idempotency, and audit requirements.
- Add authentication, role-based authorization, tenant boundaries, audit trails, order history, cancellation/shipment workflows, taxes, discounts, and approval policies.
- Replace the shared HTTP Basic credential with per-user authentication, credential hashing, login throttling, revocation, and MFA or an external identity provider before treating the application as production-ready. See the [OWASP Authentication Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html).
- After all essential steelthreads work, optionally replace the process-memory confirmation registry with a first-class SQLite `orders` table if time and resources permit. Represent pending and terminal status, material, quantity, quoted unit price and total, expected inventory version, timestamps, and a confirmation-token hash in one record. This would provide stable order IDs, a coherent evaluation-to-confirmation audit record, and a direct migration path to durable PostgreSQL order history without introducing a separate confirmation-token table.
- Optionally add a live browser countdown synchronized to an order evaluation's `expires_at`, with an accessible expiry announcement and automatic disabling of the Confirm action when the 15-minute window ends.
- Add durable idempotency keys, request correlation, rate limiting, structured logs, metrics, distributed traces, alerting, and provider cost/latency budgets.
- Add provider failover only after measuring whether its reliability benefit outweighs behavioral differences and additional acceptance testing.
- Expand catalogue matching with an evaluated search index or embeddings only when real query logs demonstrate the deterministic matcher is inadequate. Never allow ranking to turn a non-match into an asserted exact match.
- Add broader LLM evaluations, prompt/version tracking, regression datasets from anonymized conversations, and continuous checks that displayed numbers exactly match deterministic tool outputs.
- Replace the chat POC's process-memory 30-minute sessions and best-effort natural-language bulk authorization with durable encrypted session storage, explicit retention controls, per-tool authorization, formal dependency-plan validation, rate/concurrency and provider-quota limits, structured orchestration telemetry, and regression evaluations before production use.
- Re-evaluate the Gemini integration through Google's official Gemini Docs MCP when that service is available reliably. During initial design it repeatedly returned HTTP 429 during MCP initialization, so the human explicitly approved official Google web documentation as the provider-specific fallback.
