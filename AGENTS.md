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

Current status: steelthread 1 is complete and deployed at `https://sidian-inventory-assistant-demo.onrender.com`; its public health checks return `200`, its authentication boundary returns `401` without credentials, and Render deployed commit `82e494f` after CI passed. Steelthread 2 is implemented and locally verified with 80 passing tests and clean Ruff checks. It adds persistence-independent read services, conservative matching, deterministic inventory and supplier responses, derived availability/status fields, read-only APIs, and the accessible over-allocation banner. The human must review, commit, push, run the Bruno requests manually, and verify the resulting CI-gated Render deployment before steelthread 2 is complete. Python 3.13, Git, GitHub CLI, Render CLI, the curated GitHub and Render Codex plugins, and Render MCP are installed and verified. Use authenticated GitHub CLI for programmatic GitHub operations: the human explicitly waived the GitHub App connector check after Codex CLI's connector-directory request was blocked by a Cloudflare challenge even though Codex Doctor and GitHub CLI authentication passed.

## Agreed demo design

- Use Python 3.13, FastAPI, a project-local virtual environment, and `pip`. FastAPI is the server framework and generates the OpenAPI contract. See [FastAPI features](https://fastapi.tiangolo.com/features/) and the [OpenAPI specification](https://spec.openapis.org/oas/v3.0.4.html).
- Build a modular monolith and deploy it as one web service. Serve a small HTML/CSS/JavaScript interface from FastAPI rather than introducing a separate frontend framework and deployment. FastAPI supports [templates](https://fastapi.tiangolo.com/advanced/templates/) and [static files](https://fastapi.tiangolo.com/tutorial/static-files/).
- Start with the supplied JSON as a read-only repository, then add repeatable SQLite ingestion behind the same repository interface. Python provides standard-library [SQLite support](https://docs.python.org/3/library/sqlite3.html).
- When SQLite is introduced, build a fresh database from the supplied JSON at every application process start, validate it completely before readiness, and replace any previous session database rather than upserting or preserving runtime reservations. Reuse this implementation from `scripts/ingest.py`, expose no runtime re-ingestion HTTP endpoint, and add no migration framework for the ephemeral demo. Local restarts intentionally reset session orders just like Render restarts. Persistent snapshot reconciliation and schema migrations belong to the future PostgreSQL design.
- Preserve the mandated raw `qty_available = qty_on_hand - qty_reserved` value even when it is negative. Separately derive `qty_shippable = max(qty_available, 0)`, `overallocated_by = max(-qty_available, 0)`, and an inventory status. Use `qty_shippable` for order validation while returning the raw value and discrepancy fields in structured responses. User-facing messages must say that zero units can ship and state the over-allocation, on-hand quantity, and reserved quantity rather than describing a negative number as shippable stock.
- Keep unresolved over-allocations persistently visible through a non-modal inventory-warning banner on protected browser pages, backed by a deterministic `GET /api/inventory/alerts` endpoint and linked to the affected materials. Calculate the warning on initial page load and refresh it after successful order mutations; do not poll when no external inventory updates can occur, repeatedly inject it into chat responses, or use recurring toasts or dialogs. Render an initial warning as ordinary semantic content and expose a dynamically changed warning as an accessible, non-focus-stealing status message. The demo has no correction workflow, so state that in the status message. See the W3C [Alert Pattern](https://www.w3.org/WAI/ARIA/apg/patterns/alert/) and [status-message guidance](https://www.w3.org/WAI/WCAG22/Understanding/status-messages.html).
- Keep domain rules and application services independent of HTTP, persistence, and the LLM provider. HTTP routes and agent tools must call the same application services so their behavior cannot diverge.
- Use in-process application-service calls for agent tools in the demo. Do not make the agent call the application's own HTTP API.
- Keep the protected `GET /api/catalog/summary` endpoint for the browser UI and operational source metadata. It returns only the dataset name, as-of date, currency, notes, and record counts, not raw supplier or material records. Do not expose this endpoint or arbitrary HTTP access to Gemini; the later provider adapter receives only the explicitly declared inventory and ordering tool schemas.
- Use Gemini's free tier through the Interactions API as the initial LLM provider behind a narrow provider interface. Use the stable `gemini-3.6-flash` model by default and make the model ID configurable through an environment variable. Only one provider implementation is in demo scope. The free tier's data-use terms must be documented. See the [Gemini API reference](https://ai.google.dev/api), [latest-model guidance](https://ai.google.dev/gemini-api/docs/latest-model), and [pricing](https://ai.google.dev/gemini-api/docs/pricing).
- Make the LLM optional to the core application. Catalogue browsing, deterministic APIs, and order operations must remain usable without an API key or during provider failure; only conversational interpretation may become unavailable.
- Limit the LLM to selecting typed tools and supplying arguments. It must not receive direct database access, calculate inventory figures, enforce business rules, or write the factual response. Declare Gemini function schemas explicitly, disable automatic function execution, validate proposed arguments in application code, execute application services manually, and present their complete deterministic messages verbatim without a second model narration step. See [Gemini function calling](https://ai.google.dev/gemini-api/docs/function-calling) and the [Google Gen AI Python SDK](https://googleapis.github.io/python-genai/index.html).
- Use Gemini function-calling mode `any` so every model response is a schema-adherent function call. Begin with the small tool surface `show_help`, `query_inventory`, `get_supplier_terms`, `evaluate_order`, and `place_confirmed_order`; `show_help` handles greetings and unsupported requests without permitting uncontrolled model prose. On normal turns expose only the first four tools. Expose `place_confirmed_order` only after application code recognizes an explicit confirmation for a pending order.
- Keep conversational state in the application rather than relying on provider-hosted history. Store only small session-lifetime context needed for follow-ups, such as the last resolved material/query, recent user requests, and a pending confirmation identifier. Do not put authoritative inventory quantities or raw database records in model context.
- Require an explicit confirmation step before the mutating order tool runs. All validation must be repeated inside the final database transaction; the confirmation step is not authorization to use stale availability.
- For the essential demo, do not persist first-class order records. Keep pending confirmation details and terminal confirmation results in a small, concurrency-safe, process-memory registry keyed by an opaque, securely generated token. Bind each token to the evaluated material, quantity, price, and inventory state; consume it at most once, return the cached terminal result on replay, and revalidate all rules inside the reservation transaction. Losing this registry on restart is acceptable because the ephemeral database and its reservations reset at the same time.
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
   - Status: implementation and local verification are complete; human commit/push, CI verification, initial Render Blueprint creation, and public smoke testing remain.
   - Scaffold the FastAPI service, `pyproject.toml`, compiled requirement files, Ruff/pytest configuration, tests, and minimal browser page.
   - Load and validate `Requirements/inventory_data.json` through a JSON repository without mutating it.
   - Expose a health endpoint, dataset metadata, and a browsable material list with basic text filtering.
   - Add the shared HTTP Basic gate to every non-health route and require credentials at startup.
   - Add the GitHub Actions CI workflow and Render Blueprint, then deploy the working MVP publicly before adding later behavior.
   - Verify startup failure for missing/invalid data and missing credentials, protected-route `401` behavior, authorized access, public health checks, the displayed counts of 9 suppliers and 77 materials, and the public URL.

2. **Deterministic read-only inventory behavior — implemented locally; deployment pending**
   - Add domain models, raw availability, non-negative shippable quantity, explicit over-allocation status, catalogue matching, supplier lookup, and deterministic message rendering.
   - Add read-only application services and HTTP endpoints for stock, search, supplier terms, and inventory alerts.
   - Add the persistent, non-modal over-allocation banner to the protected browser UI, with affected-material links and accessible semantics.
   - Distinguish exact matches, no matches, and ambiguous matches; never silently substitute a near match.
   - Verify the read-only portions of all required prompts plus over-allocated, fully reserved, discontinued, zero-stock, and unknown-SKU cases; verify that the warning appears while a discrepancy exists and is absent when none exists.

3. **Repeatable SQLite ingestion**
   - Add normalized supplier and material tables, constraints, indexes, and an ingestion record containing source metadata.
   - Build and validate a fresh SQLite file at every process start, atomically replace the previous session file only after success, and reuse the same operation from `scripts/ingest.py`.
   - Switch the application to the SQLite repository without changing observable read behavior; do not add an upsert path, runtime ingestion endpoint, or demo migration framework.
   - Keep the JSON repository available for the first-slice fallback and focused tests.
   - Verify repeated clean replacement, foreign-key integrity, preservation of the prior valid file after failed ingestion, readiness failure on invalid input, session reset behavior, and JSON/SQLite response parity.

4. **Deterministic order workflow**
   - Add order evaluation, process-memory confirmation/idempotency state, explicit confirmation, and transactional reservation updates without a first-class orders table.
   - Reject quantities above derived availability, discontinued materials, invalid quantities, unknown/ambiguous products, and stale confirmations. Never partially fulfill silently.
   - Increase `qty_reserved` without decreasing `qty_on_hand`; calculate totals in application code using decimal-safe currency arithmetic.
   - Verify successful reservation, concurrent and sequential confirmation replay without double reservation, unknown or stale confirmation handling, registry reset with the process, all rejection paths, and the required 500-length rebar and discontinued-plate prompts.

5. **Conversational tool-calling interface**
   - Add the Gemini Interactions API adapter, explicit function schemas, manual call execution, application-owned conversation context, bounded orchestration, chat endpoint, and chat UI.
   - Reuse the persistent inventory-warning banner in the chat UI without inserting the warning into every conversational response.
   - Use function-calling mode `any`; expose `show_help` for non-data conversation and restrict the mutating tool to confirmed pending orders.
   - Render handler messages verbatim. Log tool name, validated arguments, result status, latency, and provider errors without logging secrets.
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
- Add durable idempotency keys, request correlation, rate limiting, structured logs, metrics, distributed traces, alerting, and provider cost/latency budgets.
- Add provider failover only after measuring whether its reliability benefit outweighs behavioral differences and additional acceptance testing.
- Expand catalogue matching with an evaluated search index or embeddings only when real query logs demonstrate the deterministic matcher is inadequate. Never allow ranking to turn a non-match into an asserted exact match.
- Add broader LLM evaluations, prompt/version tracking, regression datasets from anonymized conversations, and continuous checks that displayed numbers exactly match deterministic tool outputs.
- Re-evaluate the Gemini integration through Google's official Gemini Docs MCP when that service is available reliably. During initial design it repeatedly returned HTTP 429 during MCP initialization, so the human explicitly approved official Google web documentation as the provider-specific fallback.
