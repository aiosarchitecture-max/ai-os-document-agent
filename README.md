# AI_OS Core v3 foundation

This branch introduces a backward-compatible foundation for evolving AI_OS from a document-driven prototype into a durable digital-organization operating system.

## Architecture

- PostgreSQL is the operational source of truth for tasks, Work Orders, runs, approvals, audit events, and the document registry.
- Google Drive remains the knowledge and document source of truth.
- GitHub remains the code source of truth.
- Apps Script remains a restricted Google write adapter during migration.
- Render runs the API and one-shot Cron worker.

## Safety

- Production `main` is unchanged until this draft PR is reviewed and merged.
- API authentication uses an Authorization bearer header, not query parameters.
- Dangerous Drive operations require a payload-bound, expiring, single-use approval.
- The legacy bridge can run in parallel during migration.

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
- `APPROVAL_SIGNING_KEY`
- `APPS_SCRIPT_WEBAPP_URL`
- `APPS_SCRIPT_SECRET`
- `AI_OS_ROOT_FOLDER_ID`
- `TASK_REGISTER_SPREADSHEET_ID` (optional; enables task dual-write)
- `TASK_REGISTER_SHEET_NAME` (defaults to `AI_OS_TASKS`)
- provider API keys required by individual agents

## Migration sequence

1. Deploy PostgreSQL and run schema migration.
2. Import current `AI_OS_TASKS` records with stable external IDs.
3. Enable dual-write to PostgreSQL and the human-readable Drive register. The implementation is available and remains disabled until `TASK_REGISTER_SPREADSHEET_ID` is configured.
4. Compare both stores and resolve discrepancies.
5. Switch reads to PostgreSQL.
6. Keep Drive as a synchronized operational view and knowledge store.
7. Add Creator, Opponent, Reviewer, and approval gates as isolated workflow stages.

