# AI_OS Core v3 foundation

AI_OS v3 provides a backward-compatible foundation for evolving the document-driven prototype into a durable digital-organization operating system.

## Architecture

- PostgreSQL is the operational source of truth for tasks, Work Orders, runs, approvals, audit events, and the document registry.
- Google Drive remains the knowledge and document source of truth.
- GitHub remains the code source of truth.
- Apps Script remains a restricted Google adapter during migration.
- Render runs the API and one-shot Cron worker.

## Safety

- API authentication uses an Authorization bearer header, not query parameters.
- Dangerous Drive operations require a payload-bound, expiring, single-use approval.
- The legacy bridge can run in parallel during migration.
- The approved legacy import is disabled by default; the startup preview remains read-only.
- Google Sheets is an optional read-only human projection. Task writes stay in PostgreSQL.
- Register reconciliation is read-only and requires the API bearer token.

## Local validation

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
pytest -q
uvicorn app.main:app --reload
```

## Required production secrets

- `API_TOKEN`
- `APPS_SCRIPT_WEBAPP_URL`
- `APPS_SCRIPT_SECRET`
- `AI_OS_ROOT_FOLDER_ID`
- `TASK_REGISTER_SPREADSHEET_ID` (configures register access; does not enable writes)
- `TASK_REGISTER_SHEET_NAME` (defaults to `AI_OS_TASKS`)
- `TASK_REGISTER_DUAL_WRITE_ENABLED` (must remain `false`)
- provider API keys required by individual agents

## Migration status

1. **Complete:** deploy PostgreSQL and run schema migration.
2. **Complete:** import the five approved `AI_OS_TASKS` records with stable external IDs.
3. **Implemented, permanently disabled:** legacy dual-write to the human-readable Google Sheets register.
4. **Implemented, read-only:** compare PostgreSQL with the register through `GET /integrations/task-register/reconciliation`.
5. **Current:** keep operational reads and writes in PostgreSQL and verify the authenticated staging workflow.
6. **Complete:** operational task reads use PostgreSQL.
7. **Pending:** expose Google Sheets only as a one-way, replaceable projection from PostgreSQL.
8. **Pending:** add Creator, Opponent, Reviewer, and approval gates as isolated workflow stages.

## Safe projection order

1. Deploy the Apps Script bridge version that supports `READ_SHEET_ROWS`.
2. Keep `TASK_REGISTER_DUAL_WRITE_ENABLED=false`.
3. Design a one-way projection that can be rebuilt entirely from PostgreSQL.
4. Validate the projection without making Google Sheets an operational dependency.
