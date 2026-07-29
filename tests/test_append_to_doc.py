from fastapi.testclient import TestClient

from app.main import app


HEADERS = {"Authorization": "Bearer test-token"}


def test_append_to_doc_is_secured_and_forwards_idempotent_request(monkeypatch):
    captured = []

    async def fake_call(action, payload, request_id=None):
        captured.append((action, payload, request_id))
        return {"status": "success", "requestId": request_id, "duplicate": False}

    monkeypatch.setattr("app.main.call_apps_script", fake_call)
    payload = {
        "request_id": "bridge-0009-append-001",
        "file_id": "document-123",
        "text": "[GPT_CONTRIBUTION] Test append.",
    }

    with TestClient(app) as client:
        assert client.post("/docs/append", json=payload).status_code == 401
        response = client.post("/docs/append", json=payload, headers=HEADERS)

    assert response.status_code == 200
    assert captured == [
        (
            "APPEND_DOC",
            {"documentId": "document-123", "text": "[GPT_CONTRIBUTION] Test append."},
            "bridge-0009-append-001",
        )
    ]


def test_append_to_doc_rejects_invalid_payload():
    with TestClient(app) as client:
        response = client.post(
            "/docs/append",
            json={"request_id": "bad id", "file_id": "", "text": ""},
            headers=HEADERS,
        )

    assert response.status_code == 422


def test_openapi_exposes_append_to_doc_capability():
    schema = app.openapi()
    assert schema["paths"]["/docs/append"]["post"]["security"] == [{"BearerAuth": []}]
    assert schema["paths"]["/integrations/apps-script/documents/append"]["post"]["security"] == [{"BearerAuth": []}]
