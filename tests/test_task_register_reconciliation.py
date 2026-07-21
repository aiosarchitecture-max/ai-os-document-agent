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


def test_task_register_preflight_validates_exact_header(monkeypatch):
    settings = SimpleNamespace(
        task_register_spreadsheet_id="register-id",
        task_register_sheet_name="AI_OS_TASKS",
    )
    monkeypatch.setattr(services, "get_settings", lambda: settings)

    async def fake_call(action, payload, request_id=None):
        assert action == "READ_SHEET_ROWS"
        assert payload["rowCount"] == 1
        return {"status": "success", "data": {"rows": [services.TASK_REGISTER_HEADERS]}}

    monkeypatch.setattr(services, "call_apps_script", fake_call)
    result = asyncio.run(services.inspect_task_register())
    assert result["status"] == "ready"
    assert result["ready"] is True
    assert result["checks"] == {"configured": True, "readable": True, "header_valid": True}


def test_task_register_preflight_rejects_wrong_header(monkeypatch):
    settings = SimpleNamespace(
        task_register_spreadsheet_id="register-id",
        task_register_sheet_name="AI_OS_TASKS",
    )
    monkeypatch.setattr(services, "get_settings", lambda: settings)

    async def fake_call(action, payload, request_id=None):
        return {"status": "success", "data": {"rows": [["wrong", "header"]]}}

    monkeypatch.setattr(services, "call_apps_script", fake_call)
    result = asyncio.run(services.inspect_task_register())
    assert result["status"] == "invalid_schema"
    assert result["ready"] is False
    assert result["checks"]["header_valid"] is False


def test_task_register_preflight_is_disabled_without_configuration(monkeypatch):
    settings = SimpleNamespace(
        task_register_spreadsheet_id="",
        task_register_sheet_name="AI_OS_TASKS",
    )
    monkeypatch.setattr(services, "get_settings", lambda: settings)
    result = asyncio.run(services.inspect_task_register())
    assert result["status"] == "disabled"
    assert result["ready"] is False
