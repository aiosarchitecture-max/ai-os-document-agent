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
        (httpx.Response(500, text="upstream failed"), "Server error"),
        (httpx.Response(200, text="not-json"), "Apps Script request failed"),
        (httpx.Response(200, json={"status": "error", "error": "Unauthorized"}), "Unauthorized"),
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
