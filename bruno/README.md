# Bruno endpoint checks

This collection exercises deterministic inventory, supplier, two-step order, and Gemini chat
endpoints plus the shared authentication gate. Deterministic order requests store the opaque
confirmation token and verify idempotency. Chat requests rely on Bruno's cookie jar, exercise
compound iterative tools, and store only session-local pending references for confirmation and
cancellation.
It contains no real credentials. The human runs and validates these requests manually; agents only
keep the request definitions current.

1. Put `GEMINI_API_KEY` in the ignored local `bruno/.env`, then start the application:

   ```powershell
   .\.venv\Scripts\uvicorn.exe inventory_assistant.main:app --app-dir src --env-file bruno/.env
   ```

2. Open this `bruno` directory as a collection in Bruno.
3. Select the `Local` environment. It reads the same credentials from the Bruno process
   environment and targets `http://127.0.0.1:8000`.
4. Run the collection.

From PowerShell, the CLI equivalent is:

```powershell
bru run bruno --env Local
```

Override `baseUrl` when checking a deployed environment. Pass secrets at runtime rather than
storing them in a committed Bruno environment file. Keep the local Gemini key and demo credentials
only in the ignored `bruno/.env`; do not reuse the demo credential for Render or commit any secret.
