# Bruno endpoint checks

This collection exercises deterministic inventory, supplier, and two-step order endpoints plus
the shared authentication gate. The order requests run last, store the opaque confirmation token
as a Bruno runtime variable, confirm once, and replay the same confirmation to verify idempotency.
It contains no real credentials. The human runs and validates these requests manually; agents only
keep the request definitions current.

1. Start the application with the ignored local `bruno/.env` file:

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
storing them in a committed Bruno environment file. The ignored `bruno/.env` contains only local
demo values; do not reuse them for Render or any other deployed environment.
