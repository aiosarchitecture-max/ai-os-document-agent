import asyncio
from pathlib import Path

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app
from app import services


HEADERS = {"Authorization": "Bearer test-token"}


def test_runtime_imports_canonical_services_module():
    assert Path(services.__file__).resolve() == (Path.cwd() / "app" / "services.py").resolve()
    assert not (Path.cwd() / "rebuild").exists()


def test_health():
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["database"] == "ok"


def test_secured_endpoint_requires_bearer_token():
    with TestClient(app) as client:
        assert client.get("/tasks").status_code == 401
        assert client.get("/tasks", headers={"Authorization": "Bearer wrong-token"}).status_code == 401
        assert client.get("/tasks", headers=HEADERS).status_code == 200


def test_openapi_declares_bearer_security_scheme():
    schema = app.openapi()
    assert schema["components"]["securitySchemes"]["BearerAuth"]["scheme"] == "bearer"
    assert schema["paths"]["/tasks"]["post"]["security"] == [{"BearerAuth": []}]
    assert schema["paths"]["/integrations/apps-script/documents"]["post"]["security"] == [{"BearerAuth": []}]
    assert schema["paths"]["/integrations/apps-script/documents/{document_id}"]["get"]["security"] == [{"BearerAuth": []}]


def test_create_document_is_root_scoped_and_idempotent(monkeypatch):
    captured = []
    monkeypatch.setattr("app.main.settings.ai_os_root_folder_id", "root-folder")

    async def fake_call(action, payload, request_id=None):
        captured.append((action, payload, request_id))
        return {"status": "success", "requestId": request_id, "duplicate": len(captured) > 1}

    monkeypatch.setattr("app.main.call_apps_script", fake_call)
    payload = {"request_id": "staging-doc-001", "title": "AI_OS staging test", "content": "ok"}
    with TestClient(app) as client:
        first = client.post("/integrations/apps-script/documents", json=payload, headers=HEADERS)
        second = client.post("/integrations/apps-script/documents", json=payload, headers=HEADERS)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["duplicate"] is False
    assert second.json()["duplicate"] is True
    assert captured == [
        ("CREATE_DOC", {"title": "AI_OS staging test", "content": "ok", "folderId": "root-folder"}, "staging-doc-001"),
        ("CREATE_DOC", {"title": "AI_OS staging test", "content": "ok", "folderId": "root-folder"}, "staging-doc-001"),
    ]


def test_create_document_rejects_invalid_request_id():
    with TestClient(app) as client:
        response = client.post(
            "/integrations/apps-script/documents",
            json={"request_id": "bad id", "title": "AI_OS staging test"},
            headers=HEADERS,
        )
    assert response.status_code == 422


def test_read_document_is_read_only_and_root_validation_is_delegated_to_bridge(monkeypatch):
    captured = []

    async def fake_call(action, payload, request_id=None):
        captured.append((action, payload, request_id))
        return {
            "status": "success",
            "data": {"documentId": payload["documentId"], "name": "Test", "text": "ok"},
        }

    monkeypatch.setattr("app.main.call_apps_script", fake_call)
    with TestClient(app) as client:
        response = client.get(
            "/integrations/apps-script/documents/doc_1234567890",
            headers=HEADERS,
        )

    assert response.status_code == 200
    assert response.json()["data"]["text"] == "ok"
    assert captured == [("READ_DOC", {"documentId": "doc_1234567890"}, None)]


def test_read_document_rejects_invalid_document_id_without_calling_bridge(monkeypatch):
    async def must_not_call(*_args, **_kwargs):
        raise AssertionError("bridge must not be called")

    monkeypatch.setattr("app.main.call_apps_script", must_not_call)
    with TestClient(app) as client:
        response = client.get(
            "/integrations/apps-script/documents/bad%20id",
            headers=HEADERS,
        )

    assert response.status_code == 422


def test_task_idempotency_and_transition():
    payload = {
        "title": "Implementovať pracovný kontext",
        "idempotency_key": "test-context-1",
        "work_order": {
            "objective": "Vytvoriť deterministický pracovný kontext",
            "acceptance_criteria": ["Relevantné dokumenty sú citované"],
            "definition_of_done": ["Testy prešli"],
        },
    }
    with TestClient(app) as client:
        first = client.post("/tasks", json=payload, headers=HEADERS)
        second = client.post("/tasks", json=payload, headers=HEADERS)
        assert first.status_code == 200
        assert second.json()["id"] == first.json()["id"]
        moved = client.post(f"/tasks/{first.json()['id']}/transition?new_status=RESEARCH", headers=HEADERS)
        assert moved.status_code == 200
        assert moved.json()["status"] == "RESEARCH"


def test_complete_task_workflow_is_persisted_and_auditable(monkeypatch):
    monkeypatch.setattr("app.main.settings.task_register_dual_write_enabled", False)
    payload = {
        "title": "Overiť celý PostgreSQL workflow",
        "idempotency_key": "test-complete-workflow-1",
    }
    workflow = ["RESEARCH", "CREATION", "OPPOSITION", "REVIEW", "APPROVAL", "DONE"]

    with TestClient(app) as client:
        created = client.post("/tasks", json=payload, headers=HEADERS)
        assert created.status_code == 200
        task_id = created.json()["id"]

        for status in workflow:
            moved = client.post(
                f"/tasks/{task_id}/transition?new_status={status}",
                headers=HEADERS,
            )
            assert moved.status_code == 200
            assert moved.json()["status"] == status

        persisted = next(
            task for task in client.get("/tasks", headers=HEADERS).json()
            if task["id"] == task_id
        )
        assert persisted["status"] == "DONE"
        audit = client.get(f"/tasks/{task_id}/audit", headers=HEADERS)

    assert audit.status_code == 200
    events = audit.json()
    assert [event["event_type"] for event in events] == [
        "TASK_CREATED",
        *(["TASK_TRANSITION"] * len(workflow)),
    ]
    assert [event["payload"]["to"] for event in events[1:]] == workflow


def test_invalid_transition_does_not_change_task_or_audit(monkeypatch):
    monkeypatch.setattr("app.main.settings.task_register_dual_write_enabled", False)
    payload = {
        "title": "Odmietnuť neplatný prechod",
        "idempotency_key": "test-invalid-transition-1",
    }
    with TestClient(app) as client:
        created = client.post("/tasks", json=payload, headers=HEADERS)
        task_id = created.json()["id"]
        rejected = client.post(
            f"/tasks/{task_id}/transition?new_status=DONE",
            headers=HEADERS,
        )
        audit = client.get(f"/tasks/{task_id}/audit", headers=HEADERS)

    assert rejected.status_code == 409
    assert [event["event_type"] for event in audit.json()] == ["TASK_CREATED"]


def test_task_audit_requires_authentication_and_existing_task():
    with TestClient(app) as client:
        assert client.get("/tasks/missing/audit").status_code == 401
        assert client.get("/tasks/missing/audit", headers=HEADERS).status_code == 404


@pytest.mark.parametrize(
    ("detail", "expected_code"),
    [
        (
            {"status": "error", "code": "EXCEPTION", "message": "Error: Spreadsheet is outside AI_OS root"},
            "register_outside_root",
        ),
        (
            {"status": "error", "code": "UNAUTHORIZED"},
            "bridge_auth_failed",
        ),
        ("Apps Script request failed: timed out", "bridge_timeout"),
    ],
)
def test_public_task_register_status_classifies_safe_bridge_errors(monkeypatch, detail, expected_code):
    async def fake_inspect():
        raise HTTPException(status_code=502, detail=detail)

    monkeypatch.setattr("app.main.inspect_task_register", fake_inspect)
    monkeypatch.setattr("app.main.settings.task_register_dual_write_enabled", False)
    with TestClient(app) as client:
        response = client.get("/integrations/task-register/status")

    assert response.status_code == 200
    assert response.json()["error_code"] == expected_code
    assert response.json()["dual_write_enabled"] is False
    assert response.json()["ready"] is False


def test_task_register_dual_write_is_persistently_idempotent(monkeypatch):
    captured = []

    class Settings:
        task_register_spreadsheet_id = "tasks-sheet"
        task_register_sheet_name = "AI_OS_TASKS"
        task_register_dual_write_enabled = True

    async def fake_call(action, payload, request_id=None):
        captured.append((action, payload, request_id))
        return {"status": "success", "requestId": request_id, "duplicate": False}

    monkeypatch.setattr(services, "get_settings", lambda: Settings())
    monkeypatch.setattr(services, "call_apps_script", fake_call)
    payload = {
        "title": "Dual-write task",
        "description": "Stored in PostgreSQL and the readable register",
        "idempotency_key": "test-dual-write-1",
    }
    with TestClient(app) as client:
        first = client.post("/tasks", json=payload, headers=HEADERS)
        second = client.post("/tasks", json=payload, headers=HEADERS)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert len(captured) == 1
    action, register_payload, request_id = captured[0]
    assert action == "APPEND_SHEET_ROW"
    assert register_payload["spreadsheetId"] == "tasks-sheet"
    assert register_payload["sheetName"] == "AI_OS_TASKS"
    assert register_payload["values"][0] == first.json()["id"]
    assert register_payload["values"][6] == "Dual-write task"
    assert request_id == f"task-register:{first.json()['id']}:v1"


def test_legacy_task_import_dry_run_then_apply_is_idempotent():
    payload = {
        "source_document_id": "legacy-doc-1",
        "tasks": [
            {
                "external_id": "LEGACY-001",
                "status": "DONE",
                "priority": "HIGH",
                "project_key": "AI_OS",
                "owner": "Daniel",
                "title": "Legacy done task",
                "description": "Imported description",
            },
            {
                "external_id": "LEGACY-002",
                "status": "STAV",
                "priority": "NÍZKA",
                "project_key": "AI_OS",
                "owner": "Daniel",
                "title": "Legacy pending task",
            },
        ],
    }
    with TestClient(app) as client:
        dry_run = client.post(
            "/migration/legacy-tasks",
            json={**payload, "dry_run": True},
            headers=HEADERS,
        )
        assert dry_run.status_code == 200
        assert dry_run.json()["imported"] == 2
        assert not any(
            task["external_id"] in {"LEGACY-001", "LEGACY-002"}
            for task in client.get("/tasks", headers=HEADERS).json()
        )

        applied = client.post(
            "/migration/legacy-tasks",
            json={**payload, "dry_run": False},
            headers=HEADERS,
        )
        repeated = client.post(
            "/migration/legacy-tasks",
            json={**payload, "dry_run": False},
            headers=HEADERS,
        )
        tasks = client.get("/tasks", headers=HEADERS).json()

    assert applied.json()["imported"] == 2
    assert repeated.json()["imported"] == 0
    assert repeated.json()["skipped_existing"] == 2
    assert {
        task["external_id"]: task["status"]
        for task in tasks
        if task["external_id"] in {"LEGACY-001", "LEGACY-002"}
    } == {
        "LEGACY-001": "DONE",
        "LEGACY-002": "NEW",
    }


def test_legacy_task_import_rejects_duplicate_external_ids():
    item = {
        "external_id": "DUP-001",
        "title": "Duplicate",
    }
    with TestClient(app) as client:
        response = client.post(
            "/migration/legacy-tasks",
            json={"source_document_id": "legacy-doc-2", "tasks": [item, item]},
            headers=HEADERS,
        )
    assert response.status_code == 422


def test_approval_is_single_use():
    request = {"operation": "TRASH_FILE", "target": "file-1", "payload": {"fileId": "file-1"}}
    with TestClient(app) as client:
        issued = client.post("/approvals", json=request, headers=HEADERS)
        assert issued.status_code == 200
        operation = {**request, "approval_token": issued.json()["approval_token"]}
        # First request reaches integration boundary; second must fail before it.
        client.post("/drive/execute", json=operation, headers=HEADERS)
        repeated = client.post("/drive/execute", json=operation, headers=HEADERS)
        assert repeated.status_code == 403


def test_dangerous_operation_target_must_match_payload():
    request = {"operation": "TRASH_FILE", "target": "file-1", "payload": {"fileId": "file-2"}}
    with TestClient(app) as client:
        issued = client.post("/approvals", json=request, headers=HEADERS)
        operation = {**request, "approval_token": issued.json()["approval_token"]}
        response = client.post("/drive/execute", json=operation, headers=HEADERS)
        assert response.status_code == 400


def test_apps_script_call_follows_realistic_google_redirect(monkeypatch):
    captured = {}

    class Settings:
        apps_script_webapp_url = "https://script.google.test/exec"
        apps_script_secret = "private-test-secret"
        request_timeout_seconds = 10
        version = "test-version"

    def handler(request: httpx.Request) -> httpx.Response:
        captured.setdefault("requests", []).append(request)
        if request.url.host == "script.google.test":
            captured["body"] = __import__("json").loads(request.content)
            return httpx.Response(302, headers={"Location": "https://script.googleusercontent.com/result"})
        assert request.url.host == "script.googleusercontent.com"
        return httpx.Response(200, json={"status": "success", "data": {"pong": True}})

    real_client = httpx.AsyncClient

    def client_factory(*, timeout):
        captured["timeout"] = timeout
        return real_client(timeout=timeout, transport=httpx.MockTransport(handler))

    monkeypatch.setattr(services, "get_settings", lambda: Settings())
    monkeypatch.setattr(services.httpx, "AsyncClient", client_factory)
    result = asyncio.run(services.call_apps_script("PING", {}))

    assert result["status"] == "success"
    assert captured["body"]["secret"] == Settings.apps_script_secret
    assert captured["body"]["requestId"]
    assert len(captured["requests"]) == 2
    assert captured["requests"][0].method == "POST"
    assert captured["requests"][1].method == "GET"
    assert "secret" not in str(captured["requests"][0].url)
    assert captured["requests"][1].content == b""


@pytest.mark.parametrize(
    ("status", "location"),
    [
        (302, ""),
        (302, "http://script.googleusercontent.com/result"),
        (302, "https://evil.example/result"),
        (307, "https://script.googleusercontent.com/result"),
        (308, "https://script.googleusercontent.com/result"),
    ],
)
def test_apps_script_rejects_unsafe_or_body_replaying_redirects(monkeypatch, status, location):
    class Settings:
        apps_script_webapp_url = "https://script.google.test/exec"
        apps_script_secret = "private-test-secret"
        request_timeout_seconds = 10
        version = "test-version"

    headers = {"Location": location} if location else {}
    real_client = httpx.AsyncClient

    def client_factory(*, timeout):
        return real_client(
            transport=httpx.MockTransport(lambda _request: httpx.Response(status, headers=headers)),
            timeout=timeout,
        )

    monkeypatch.setattr(services, "get_settings", lambda: Settings())
    monkeypatch.setattr(services.httpx, "AsyncClient", client_factory)
    with pytest.raises(HTTPException) as raised:
        asyncio.run(services.call_apps_script("PING", {}))
    assert raised.value.status_code == 502


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (httpx.Response(500, text="upstream failed"), "bridge_http_error"),
        (httpx.Response(200, text="not-json"), "bridge_invalid_response"),
        (httpx.Response(200, json={"status": "error", "error": "Unauthorized"}), "bridge_auth_failed"),
    ],
)
def test_apps_script_failures_are_closed_and_mapped_to_502(monkeypatch, response, expected):
    class Settings:
        apps_script_webapp_url = "https://script.google.test/exec"
        apps_script_secret = "private-test-secret"
        request_timeout_seconds = 10
        version = "test-version"

    real_client = httpx.AsyncClient

    def client_factory(*, timeout):
        return real_client(transport=httpx.MockTransport(lambda _request: response), timeout=timeout)

    monkeypatch.setattr(services, "get_settings", lambda: Settings())
    monkeypatch.setattr(services.httpx, "AsyncClient", client_factory)
    with pytest.raises(HTTPException) as raised:
        asyncio.run(services.call_apps_script("PING", {}))
    assert raised.value.status_code == 502
    assert expected in str(raised.value.detail)



def test_deterministic_legacy_snapshot_preview_is_read_only():
    from app.db import SessionLocal
    from app.legacy_migration import LEGACY_TASK_SNAPSHOT, run_legacy_task_migration

    with SessionLocal() as db:
        before = db.query(services.Task).count()
        result = run_legacy_task_migration(db, apply=False)
        after = db.query(services.Task).count()

    assert len(LEGACY_TASK_SNAPSHOT) == 5
    assert result["received"] == 5
    assert result["applied"] == 0
    assert after == before
    assert result["importable"] + result["skipped_existing"] == 5
