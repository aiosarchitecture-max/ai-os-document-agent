import asyncio

from fastapi.testclient import TestClient

from app.main import app
from app import services


HEADERS = {"Authorization": "Bearer test-token"}


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


def test_apps_script_call_uses_post_secret_and_unique_request_id(monkeypatch):
    captured = {}

    class Settings:
        apps_script_webapp_url = "https://script.google.test/exec"
        apps_script_secret = "private-test-secret"
        request_timeout_seconds = 10
        version = "test-version"

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"status": "success", "data": {"pong": True}}

    class Client:
        def __init__(self, timeout, follow_redirects):
            captured["timeout"] = timeout
            captured["follow_redirects"] = follow_redirects

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def post(self, url, json):
            captured["url"] = url
            captured["body"] = json
            return Response()

    monkeypatch.setattr(services, "get_settings", lambda: Settings())
    monkeypatch.setattr(services.httpx, "AsyncClient", Client)
    result = asyncio.run(services.call_apps_script("PING", {}))

    assert result["status"] == "success"
    assert captured["url"] == Settings.apps_script_webapp_url
    assert captured["body"]["secret"] == Settings.apps_script_secret
    assert captured["body"]["requestId"]
    assert "secret" not in captured["url"]
    assert captured["follow_redirects"] is True
