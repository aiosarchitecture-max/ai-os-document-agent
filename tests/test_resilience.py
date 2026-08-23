from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from app import db
from app import main as main_module


HEADERS = {"Authorization": "Bearer test-token"}


def unavailable_readiness() -> dict:
    return {
        "ready": False,
        "database": {"status": "unavailable", "latency_ms": 5},
        "migrations": "timeout",
    }


def test_liveness_never_depends_on_database(monkeypatch):
    monkeypatch.setattr(
        main_module,
        "system_readiness",
        lambda: (_ for _ in ()).throw(AssertionError("liveness touched readiness")),
    )
    with TestClient(main_module.app) as client:
        response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json()["application"] == "online"


def test_compatibility_health_reports_degraded_without_hiding_application(monkeypatch):
    monkeypatch.setattr(main_module, "system_readiness", unavailable_readiness)
    with TestClient(main_module.app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "degraded",
        "application": "online",
        "version": main_module.settings.version,
        "database": "unavailable",
        "database_latency_ms": 5,
        "migrations": "timeout",
    }


def test_readiness_returns_503_when_database_is_unavailable(monkeypatch):
    monkeypatch.setattr(main_module, "system_readiness", unavailable_readiness)
    with TestClient(main_module.app) as client:
        response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["database"] == "unavailable"


def test_data_operations_fail_closed_when_system_is_not_ready(monkeypatch):
    monkeypatch.setattr(main_module, "system_readiness", unavailable_readiness)
    with TestClient(main_module.app) as client:
        response = client.get("/tasks", headers=HEADERS)
    assert response.status_code == 503
    assert "no data operation was performed" in response.json()["detail"]


def test_database_status_hides_driver_details(monkeypatch):
    def fail_connect():
        raise SQLAlchemyError("secret connection detail")

    monkeypatch.setattr(db.engine, "connect", fail_connect)
    result = db.database_status()
    assert result["status"] == "unavailable"
    assert "secret" not in str(result)


def test_render_uses_bounded_start_and_process_liveness():
    render = Path("render.yaml").read_text(encoding="utf-8")
    starter = Path("scripts/start_service.py").read_text(encoding="utf-8")
    assert "startCommand: python scripts/start_service.py" in render
    assert "healthCheckPath: /health/live" in render
    assert "DATABASE_CONNECT_TIMEOUT_SECONDS" in render
    assert "MIGRATION_TIMEOUT_SECONDS" in render
    assert "timeout=timeout_seconds" in starter
    assert "os.execvp" in starter
