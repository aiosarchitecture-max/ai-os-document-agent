import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .config import get_settings
from .db import create_schema, database_status, get_db
from .models import Task, TaskStatus
from .schemas import (
    AppendDocumentRequest,
    ApprovalRequest,
    CreateDocumentRequest,
    DangerousOperation,
    TaskCreate,
    TaskRead,
)
from .security import consume_approval, issue_approval, require_api_token
from .services import call_apps_script, create_task, transition_task


settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Alembic owns staging and production schema changes. Local SQLite remains
    # convenient for development and tests without making the public process
    # depend on a remote database before it can report its own health.
    if settings.environment.lower() in {"development", "test"} and settings.database_url.startswith("sqlite"):
        create_schema()
    yield


app = FastAPI(title=settings.app_name, version=settings.version, lifespan=lifespan)


def system_readiness() -> dict:
    database = database_status()
    migration_status = os.getenv("AI_OS_MIGRATION_STATUS", "not-required")
    requires_migration = settings.environment.lower() in {"staging", "production"}
    migration_ready = not requires_migration or migration_status == "ok"
    ready = database["status"] == "ok" and migration_ready
    return {
        "ready": ready,
        "database": database,
        "migrations": migration_status,
    }


def require_system_ready() -> None:
    if not system_readiness()["ready"]:
        raise HTTPException(
            status_code=503,
            detail="AI_OS data service is temporarily unavailable; no data operation was performed.",
        )


@app.exception_handler(SQLAlchemyError)
async def database_exception_handler(_: Request, __: SQLAlchemyError) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={
            "status": "unavailable",
            "component": "database",
            "message": "AI_OS data service is temporarily unavailable; no data operation was performed.",
        },
    )


@app.get("/")
def root() -> dict:
    return {"system": "AI_OS", "status": "online", "version": settings.version}


@app.get("/health/live")
def health_live() -> dict:
    """Process-level check that never depends on PostgreSQL."""
    return {
        "status": "ok",
        "application": "online",
        "version": settings.version,
        "migrations": os.getenv("AI_OS_MIGRATION_STATUS", "not-required"),
    }


@app.get("/health")
def health() -> dict:
    """Compatibility health response with an explicit degraded state."""
    readiness = system_readiness()
    return {
        "status": "ok" if readiness["ready"] else "degraded",
        "application": "online",
        "version": settings.version,
        "database": readiness["database"]["status"],
        "database_latency_ms": readiness["database"]["latency_ms"],
        "migrations": readiness["migrations"],
    }


@app.get("/health/ready")
def health_ready() -> JSONResponse:
    """Traffic-readiness check: 503 when data operations must stay blocked."""
    readiness = system_readiness()
    payload = {
        "status": "ok" if readiness["ready"] else "unavailable",
        "application": "online",
        "version": settings.version,
        "database": readiness["database"]["status"],
        "database_latency_ms": readiness["database"]["latency_ms"],
        "migrations": readiness["migrations"],
    }
    return JSONResponse(status_code=200 if readiness["ready"] else 503, content=payload)


@app.get(
    "/tasks",
    response_model=list[TaskRead],
    dependencies=[Depends(require_api_token), Depends(require_system_ready)],
)
def list_tasks(status: TaskStatus | None = None, limit: int = 100, db: Session = Depends(get_db)):
    query = select(Task).order_by(Task.priority.desc(), Task.created_at.asc()).limit(min(max(limit, 1), 500))
    if status:
        query = query.where(Task.status == status)
    return list(db.scalars(query))


@app.post(
    "/tasks",
    response_model=TaskRead,
    dependencies=[Depends(require_api_token), Depends(require_system_ready)],
)
def task_create(data: TaskCreate, db: Session = Depends(get_db)):
    return create_task(db, data)


@app.post(
    "/tasks/{task_id}/transition",
    response_model=TaskRead,
    dependencies=[Depends(require_api_token), Depends(require_system_ready)],
)
def task_transition(task_id: str, new_status: TaskStatus, db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return transition_task(db, task, new_status)


@app.post(
    "/approvals",
    dependencies=[Depends(require_api_token), Depends(require_system_ready)],
)
def approval_create(data: ApprovalRequest, db: Session = Depends(get_db)):
    token = issue_approval(db, data.operation, data.target, data.payload, data.ttl_seconds)
    return {"status": "success", "approval_token": token, "expires_in_seconds": data.ttl_seconds}


@app.post(
    "/drive/execute",
    dependencies=[Depends(require_api_token), Depends(require_system_ready)],
)
async def drive_execute(data: DangerousOperation, db: Session = Depends(get_db)):
    allowed = {"MOVE_FILE", "TRASH_FILE", "RENAME_FILE"}
    if data.operation not in allowed:
        raise HTTPException(status_code=400, detail="Unsupported operation")
    if data.payload.get("fileId") != data.target:
        raise HTTPException(status_code=400, detail="Operation target must match payload fileId")
    consume_approval(db, data.operation, data.target, data.payload, data.approval_token)
    payload = {**data.payload, "target": data.target}
    return await call_apps_script(data.operation, payload)


@app.get("/integrations/apps-script/health", dependencies=[Depends(require_api_token)])
async def apps_script_health() -> dict:
    return await call_apps_script("PING", {})


@app.post("/integrations/apps-script/documents", dependencies=[Depends(require_api_token)])
async def apps_script_create_document(data: CreateDocumentRequest) -> dict:
    if not settings.ai_os_root_folder_id:
        raise HTTPException(status_code=503, detail="AI_OS root folder is not configured")
    return await call_apps_script(
        "CREATE_DOC",
        {"title": data.title, "content": data.content, "folderId": settings.ai_os_root_folder_id},
        request_id=data.request_id,
    )


@app.post("/docs/append", dependencies=[Depends(require_api_token)])
@app.post("/integrations/apps-script/documents/append", dependencies=[Depends(require_api_token)])
async def append_to_document(data: AppendDocumentRequest) -> dict:
    """Append text to an existing AI_OS Google Doc.

    APPEND_TO_DOC is the public Orchestrator capability name. The deployed
    Apps Script bridge already exposes the equivalent, root-scoped APPEND_DOC
    action, so the Orchestrator translates the canonical name at this boundary.
    """
    return await call_apps_script(
        "APPEND_DOC",
        {"documentId": data.file_id, "text": data.text},
        request_id=data.request_id,
    )


@app.get("/boot", dependencies=[Depends(require_api_token)])
def boot() -> dict:
    return {
        "status": "success",
        "version": settings.version,
        "architecture": "modular-postgres",
        "workflow": ["NEW", "RESEARCH", "CREATION", "OPPOSITION", "REVIEW", "APPROVAL", "DONE"],
        "compatibility": "Legacy bridge remains available during migration",
        "capabilities": ["CREATE_DOC", "APPEND_TO_DOC"],
    }
