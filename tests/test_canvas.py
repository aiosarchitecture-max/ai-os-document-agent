from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.main import app
from app.models import AuditEvent
from app.canvas import get_settings


HEADERS = {"Authorization": "Bearer test-token"}


def payload(version: int, text: str = "Uzol") -> dict:
    return {
        "expected_version": version,
        "nodes": [{"id": "n1", "text": text, "x": 1, "y": 2, "w": 3, "h": 4}],
        "edges": [],
        "snapshot": {"elements": [{"id": "element-1", "type": "rectangle"}]},
    }


def test_canvas_page_is_in_render_runtime_without_secret_in_url():
    with TestClient(app) as client:
        page = client.get("/canvas?token=must-not-be-reflected")
        script = client.get("/canvas/app.js")

    assert page.status_code == 200
    assert "must-not-be-reflected" not in page.text
    assert page.headers["cache-control"] == "no-store"
    assert page.headers["referrer-policy"] == "no-referrer"
    assert script.status_code == 200
    assert "?token=" not in script.text
    assert "Authorization" in script.text
    assert "sessionStorage" in script.text
    assert "localStorage" not in script.text
    assert "GitHub" not in page.text


def test_canvas_api_requires_bearer_authentication():
    with TestClient(app) as client:
        assert client.get("/canvas/document").status_code == 401
        assert client.put("/canvas/document", json=payload(0)).status_code == 401
        assert client.get("/canvas/document", headers=HEADERS).status_code == 200


def test_canvas_is_atomically_persisted_versioned_and_audited():
    with TestClient(app) as client:
        initial = client.get("/canvas/document", headers=HEADERS)
        assert initial.status_code == 200
        current_version = initial.json()["version"]

        saved = client.put(
            "/canvas/document",
            headers=HEADERS,
            json=payload(current_version, "Prvá verzia"),
        )
        assert saved.status_code == 200
        saved_data = saved.json()
        assert saved_data["version"] == current_version + 1
        assert saved_data["nodes"][0]["text"] == "Prvá verzia"
        assert saved_data["snapshot"]["elements"][0]["id"] == "element-1"

        persisted = client.get("/canvas/document", headers=HEADERS)
        assert persisted.json() == saved_data

    with SessionLocal() as db:
        event = db.scalar(
            select(AuditEvent)
            .where(AuditEvent.event_type == "CANVAS_SAVED")
            .order_by(AuditEvent.created_at.desc())
        )
        assert event is not None
        assert event.actor == "authenticated-api-user"
        assert event.payload["to_version"] == saved_data["version"]


def test_stale_canvas_write_is_rejected_without_overwriting_data():
    with TestClient(app) as client:
        current = client.get("/canvas/document", headers=HEADERS).json()
        saved = client.put(
            "/canvas/document",
            headers=HEADERS,
            json=payload(current["version"], "Aktuálna verzia"),
        ).json()

        conflict = client.put(
            "/canvas/document",
            headers=HEADERS,
            json=payload(current["version"], "Prepísaná verzia"),
        )
        persisted = client.get("/canvas/document", headers=HEADERS).json()

    assert conflict.status_code == 409
    assert conflict.json()["detail"] == {
        "code": "canvas_version_conflict",
        "current_version": saved["version"],
    }
    assert persisted["nodes"][0]["text"] == "Aktuálna verzia"


def test_canvas_validation_returns_truthful_http_errors(monkeypatch):
    with TestClient(app) as client:
        current = client.get("/canvas/document", headers=HEADERS).json()
        malformed = client.put(
            "/canvas/document",
            headers=HEADERS,
            json={"expected_version": current["version"], "nodes": "not-a-list"},
        )
        monkeypatch.setattr(get_settings(), "canvas_max_payload_bytes", 100_000)
        oversized = client.put(
            "/canvas/document",
            headers=HEADERS,
            json={
                **payload(current["version"]),
                "snapshot": {"document": "x" * 100_001},
            },
        )

    assert malformed.status_code == 422
    assert oversized.status_code == 413


def test_openapi_declares_canvas_bearer_security():
    schema = app.openapi()
    assert schema["paths"]["/canvas/document"]["get"]["security"] == [{"BearerAuth": []}]
    assert schema["paths"]["/canvas/document"]["put"]["security"] == [{"BearerAuth": []}]
