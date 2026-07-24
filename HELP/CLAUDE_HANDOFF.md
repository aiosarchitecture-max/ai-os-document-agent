# AI_OS bridge_error — technical handoff for Claude

Status date: 2026-07-22  
Repository: `aiosarchitecture-max/ai-os-document-agent`  
Coordination branch: `agent/help-claude-bridge-error`

## Purpose

Please independently diagnose the remaining `bridge_error` in the one-way task-register integration:

`PostgreSQL -> FastAPI/Render -> Apps Script bridge -> Google Sheets`

Do not implement another speculative root-folder fix first. Establish the real failing operation and return an evidence-backed solution in `HELP/CLAUDE_RESPONSE.md`.

## Safety boundaries

- PostgreSQL remains the single source of truth.
- `dual_write_enabled` must remain `false`.
- Do not write, clear, reorder, or reformat the task-register sheet during diagnosis.
- Do not change Render environment variables or Apps Script properties unless the exact cause proves that a configuration change is required.
- Do not add tokens, secrets, Google Drive IDs, spreadsheet IDs, deployment URLs containing secrets, or Script Property values to commits, PR text, comments, test fixtures, or logs.
- Preserve fail-closed behavior for objects outside the configured AI_OS root.
- Any diagnostics exposed through the public API must use stable allow-listed error codes only; never return raw exception messages, stack traces, object IDs, or secret-bearing upstream responses.

## Confirmed live state

The public staging diagnostic endpoint currently returns:

```json
{
  "status": "error",
  "ready": false,
  "dual_write_enabled": false,
  "checks": {
    "configured": true,
    "readable": false,
    "header_valid": false
  },
  "postgres_tasks": 0,
  "register_tasks": 0,
  "missing": 0,
  "stale": 0,
  "error_code": "bridge_error"
}
```

Additional confirmed facts:

- The configured task register exists and its intended worksheet exists.
- The worksheet contains the expected 11-column header and no task rows.
- PostgreSQL currently reports zero tasks.
- The register file was moved directly under the configured AI_OS root.
- The prior `register_outside_root` response disappeared after deployment of bridge `3.2.1`.
- Apps Script Executions records the relevant `doPost` calls as completed because the bridge catches the exception and serializes an error response.
- Cloud logs were not available in the visible Apps Script execution menu.
- The live API deliberately collapses the underlying bridge failure to `bridge_error`, so the exact failing operation is not yet proven.

## Changes already attempted

### PR #20 / bridge 3.2.1

- Merge commit reference previously reported: `660f392`.
- Added a bounded downward fallback for root-containment checks when parent traversal is incomplete.
- Contract tests passed.
- After deployment, `register_outside_root` changed to generic `bridge_error`.

### PR #21 / bridge 3.2.2

- PR: #21.
- Resulting commit: `c5e9c548d52eb01500271d60df6681841a6cdfe9`.
- Extended the fallback to recognize a target file directly inside the configured root when its parent iterator is unexpectedly empty.
- Ten simulated contract tests passed, including internal root file, nested internal file/folder, and external object rejection.
- GitHub CI passed.
- After deployment, the live endpoint still returns the same generic `bridge_error`.

These tests prove the modeled containment cases, but not the actual live failure. Do not assume the remaining error is still root-containment related.

## Investigation requested

Please inspect the current `main` implementation, especially:

- `apps-script/Code.gs`
- Apps Script contract tests
- the FastAPI task-register integration client and status endpoint
- request/response envelope, action names, authentication comparison, HTTP handling, JSON parsing, worksheet lookup, header reading, Drive lookup, and exception mapping

Build a failure matrix covering at least:

1. wrong or missing action
2. authentication mismatch without exposing either secret
3. malformed JSON request or response
4. Apps Script HTML/error page returned with HTTP 200/redirect behavior
5. missing or inaccessible spreadsheet
6. missing worksheet
7. Drive containment lookup failure
8. header range/read failure
9. unexpected header values
10. timeout/network/redirect failure
11. deployment mismatch or stale deployment
12. Apps Script runtime/API incompatibility

## Required diagnostic approach

1. Reproduce the Render-to-bridge contract locally with deterministic fixtures or mocks.
2. Identify where raw upstream failures are currently collapsed.
3. Add the smallest safe diagnostic taxonomy that distinguishes failure stages while preserving secrets and IDs.
4. Add regression tests for every new public diagnostic code and verify no raw upstream text leaks.
5. If feasible, add a bridge version/capability field to an authenticated or safely public diagnostic response so deployment mismatch can be proven.
6. Only after the concrete failing stage is observable, propose or implement the actual fix.
7. Run all relevant JavaScript and Python tests and report exact commands/results.

Prefer one cohesive PR if the cause can be reproduced. If live-only evidence is required, first submit a narrowly scoped diagnostic change, state exactly what one live observation is needed, and do not bundle an unproven functional fix.

## Acceptance criteria

Claude's response must include:

- the proven or currently unproven root cause
- evidence and reproduction
- files and lines/functions involved
- threat/safety analysis
- proposed patch or commit(s), if created
- tests run and their results
- one minimal next live verification step
- rollback plan
- explicit confirmation that no token, secret, Google Drive ID, spreadsheet ID, or Script Property value was committed

Write the response to `HELP/CLAUDE_RESPONSE.md` on this same branch. Do not merge the coordination PR.
