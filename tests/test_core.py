from fastapi.testclient import TestClient

from app.main import app


HEADERS = {"Authorization": "Bearer test-token"}


def test_health():
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["database"] == "ok"


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

