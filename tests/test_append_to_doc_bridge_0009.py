from fastapi.testclient import TestClient

from app.main import app


HEADERS = {"Authorization": "Bearer test-token"}


def test_append_document_requires_authentication():
    with TestClient(app) as client:
        response = client.post(
            "/docs/append",
            json={
                "request_id": "bridge-0009-test",
                "document_id": "document-id-123",
                "text": "Bridge append test",
            },
        )
    assert response.status_code == 401


def test_append_document_calls_canonical_apps_script_action(monkeypatch):
    captured = {}

    async def fake_call(action, payload, request_id=None):
        captured.update(action=action, payload=payload, request_id=request_id)
        return {"status": "success", "requestId": request_id, "duplicate": False}

    monkeypatch.setattr("app.main.call_apps_script", fake_call)
    payload = {
        "request_id": "bridge-0009-test",
        "document_id": "document-id-123",
        "text": "Bridge append test",
    }

    with TestClient(app) as client:
        response = client.post("/docs/append", json=payload, headers=HEADERS)

    assert response.status_code == 200
    assert captured == {
        "action": "APPEND_DOC",
        "payload": {"documentId": "document-id-123", "text": "Bridge append test"},
        "request_id": "bridge-0009-test",
    }


def test_append_document_compatibility_route_and_boot_capability(monkeypatch):
    async def fake_call(action, payload, request_id=None):
        return {"status": "success", "requestId": request_id, "duplicate": False}

    monkeypatch.setattr("app.main.call_apps_script", fake_call)
    payload = {
        "request_id": "bridge-0009-alias",
        "document_id": "document-id-123",
        "text": "Alias test",
    }

    with TestClient(app) as client:
        alias_response = client.post(
            "/integrations/apps-script/documents/append",
            json=payload,
            headers=HEADERS,
        )
        boot_response = client.get("/boot", headers=HEADERS)

    assert alias_response.status_code == 200
    assert "APPEND_TO_DOC" in boot_response.json()["capabilities"]
