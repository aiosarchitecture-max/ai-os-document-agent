# AI_OS Drive-first workspace

## Human workflow

The human operator works in the shared Google Drive task register. PostgreSQL remains an internal execution engine and does not require direct human access.

### Creating an assignment

Add one row to `AI_OS_TASKS` with:

- `task_id`: leave blank
- `external_id`: required stable human identifier, for example `GD-2026-001`
- `status`: optional; the database creates new tasks in `NEW`
- `priority`: `0-100` or LOW/MEDIUM/HIGH/CRITICAL
- `project_key`: defaults to `AI_OS`
- `owner`: defaults to `Daniel`
- `title`: required
- `description`: optional
- system timestamp/version columns: leave blank

The scheduled worker reads the register every ten minutes. A stable `external_id` prevents duplicate PostgreSQL tasks.

## System projection

AI_OS appends a canonical projection row for each task version. Projection rows contain a populated `task_id` and are read-only for humans. They show:

- PostgreSQL task identifier
- Drive external identifier
- current workflow status
- priority, project and owner
- title and description
- creation/update timestamps
- version

Human intake rows and system projection rows are deliberately distinguishable: blank `task_id` means intake; populated `task_id` means system output.

## Source-of-truth boundaries

- Google Drive is the human workspace and task intake surface.
- PostgreSQL is the execution, workflow, audit and relationship source of truth.
- Google Drive contains a human-readable projection of PostgreSQL state.
- Direct PostgreSQL access is not part of the normal operating workflow.
- The sync is idempotent and append-only; it does not destructively overwrite human rows.

## Automation

Render runs `python -m app.drive_workspace_worker` every ten minutes. The authenticated endpoint `POST /integrations/drive-workspace/sync` provides an explicit on-demand sync for administrators and automation.

## Safety

- No API token is passed in a URL.
- Apps Script remains authenticated with the existing bridge secret.
- Duplicate intake is prevented by `drive-intake:<external_id>` idempotency keys.
- Unexpected register headers fail closed.
- Existing PostgreSQL workflow and audit records remain authoritative.
