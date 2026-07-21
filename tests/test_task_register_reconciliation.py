import asyncio
from types import SimpleNamespace

from app import services
from app.db import SessionLocal
from app.schemas import TaskCreate


def test_task_register_comparison_is_read_only_and_reports_missing(monkeypatch):
    settings = SimpleNamespace(
        task_register_spreadsheet_id="register-id",
        task_register_sheet_name="AI_OS_TASKS",
    )
    monkeypatch.setattr(services, "get_settings", lambda: settings)

    with SessionLocal() as db:
        task = services.create_task(
            db,
            TaskCreate(
                title="Reconciliation task",
                project_key="AI_OS",
                owner="test",
                idempotency_key="test-register-reconciliation",
            ),
        )
        before = db.query(services.Task).count()

        async def fake_call(action, payload, request_id=None):
            assert action == "READ_SHEET_ROWS"
            assert payload["spreadsheetId"] == "register-id"
            return {"status": "success", "data": {"rows": [["task_id", "", "", "", "", "", "", "", "", "", "version"]]}}

        monkeypatch.setattr(services, "call_apps_script", fake_call)
        result = asyncio.run(services.compare_task_register(db))
        after = db.query(services.Task).count()

    assert result["status"] == "success"
    assert task.id in result["missing_task_ids"]
    assert result["missing"] >= 1
    assert after == before


def test_task_register_comparison_is_disabled_without_sheet(monkeypatch):
    settings = SimpleNamespace(
        task_register_spreadsheet_id="",
        task_register_sheet_name="AI_OS_TASKS",
    )
    monkeypatch.setattr(services, "get_settings", lambda: settings)
    with SessionLocal() as db:
        result = asyncio.run(services.compare_task_register(db))
    assert result == {
        "status": "disabled",
        "postgres_tasks": 0,
        "register_tasks": 0,
        "missing": 0,
        "stale": 0,
    }
