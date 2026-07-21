from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .config import get_settings
from .db import SessionLocal, create_schema, get_db
from .legacy_migration import run_legacy_task_migration
from .models import AuditEvent, Task, TaskStatus
from .schemas import (
    AuditEventRead,
    ApprovalRequest,
    CreateDocumentRequest,
    DangerousOperation,
    LegacyTaskImportRequest,
    LegacyTaskImportResult,
    TaskCreate,
    TaskRead,
)
from .security import consume_approval, issue_approval, require_api_token
from .services import (
    call_apps_script,
    compare_task_register,
    create_task,
    import_legacy_tasks,
    inspect_task_register,
    sync_task_to_register,
    transition_task,
)


legacy_migration_preview: dict = {"status": "not_run"}


@asynccontextmanager
async def lifespan(_: FastAPI):
    global legacy_migration_preview
    create_schema()
    if settings.legacy_tasks_preview_on_startup:
        try:
            with SessionLocal() as db:
                result = run_legacy_task_migration(
                    db, apply=settings.legacy_tasks_apply_on_startup
                )
            legacy_migration_preview = {
                "status": "success",
                "received": result["received"],
                "importable": result["importable"],
                "skipped_existing": result["skipped_existing"],
                "applied": result["applied"],
            }
        except Exception as exc:
            legacy_migration_preview = {
                "status": "failed",
                "error_type": type(exc).__name__,
            }
    yield


settings = get_settings()
app = FastAPI(title=settings.app_name, version=settings.version, lifespan=lifespan)


@app.get("/")
def root() -> dict:
    return {"system": "AI_OS", "status": "online", "version": settings.version}


@app.get("/health")
def health(db: Session = Depends(get_db)) -> dict:
    db.execute(text("SELECT 1"))
    return {
        "status": "ok",
        "version": settings.version,
        "database": "ok",
        "legacy_task_migration_preview": legacy_migration_preview,
    }


@app.get("/tasks", response_model=list[TaskRead], dependencies=[Depends(require_api_token)])
def list_tasks(status: TaskStatus | None = None, limit: int = 100, db: Session = Depends(get_db)):
    query = select(Task).order_by(Task.priority.desc(), Task.created_at.asc()).limit(min(max(limit, 1), 500))
    if status:
        query = query.where(Task.status == status)
    return list(db.scalars(query))


@app.post("/tasks", response_model=TaskRead, dependencies=[Depends(require_api_token)])
async def task_create(data: TaskCreate, db: Session = Depends(get_db)):
    task = create_task(db, data)
    await sync_task_to_register(db, task)
    return task


@app.post(
    "/migration/legacy-tasks",
    response_model=LegacyTaskImportResult,
    dependencies=[Depends(require_api_token)],
)
def legacy_tasks_import(data: LegacyTaskImportRequest, db: Session = Depends(get_db)):
    return import_legacy_tasks(db, data)


@app.post("/tasks/{task_id}/transition", response_model=TaskRead, dependencies=[Depends(require_api_token)])
def task_transition(task_id: str, new_status: TaskStatus, db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return transition_task(db, task, new_status)


@app.get(
    "/tasks/{task_id}/audit",
    response_model=list[AuditEventRead],
    dependencies=[Depends(require_api_token)],
)
def task_audit(task_id: str, db: Session = Depends(get_db)):
    if not db.get(Task, task_id):
        raise HTTPException(status_code=404, detail="Task not found")
    query = (
        select(AuditEvent)
        .where(AuditEvent.entity_type == "task", AuditEvent.entity_id == task_id)
        .order_by(AuditEvent.created_at.asc(), AuditEvent.id.asc())
    )
    return list(db.scalars(query))


@app.post("/approvals", dependencies=[Depends(require_api_token)])
def approval_create(data: ApprovalRequest, db: Session = Depends(get_db)):
    token = issue_approval(db, data.operation, data.target, data.payload, data.ttl_seconds)
    return {"status": "success", "approval_token": token, "expires_in_seconds": data.ttl_seconds}


@app.post("/drive/execute", dependencies=[Depends(require_api_token)])
async def drive_execute(data: DangerousOperation, db: Session = Depends(get_db)):
    allowed = {"MOVE_FILE", "TRASH_FILE", "RENAME_FILE"}
    if data.operation not in allowed:
        raise HTTPException(status_code=400, detail="Unsupported operation")
    if data.payload.get("fileId") != data.target:
        raise HTTPException(status_code=400, detail="Operation target must match payload fileId")
    consume_approval(db, data.operation, data.target, data.payload, data.approval_token)
    payload = {**data.payload, "target": data.target}
    return await call_apps_script(data.operation, payload)


@app.get("/integrations/task-register/status")
async def task_register_status(db: Session = Depends(get_db)) -> dict:
    """Return only aggregate, non-sensitive register diagnostics for deployment checks."""
    try:
        readiness = await inspect_task_register()
    except HTTPException as exc:
        detail = exc.detail
        if isinstance(detail, dict):
            error = " ".join(
                str(detail.get(key, "")) for key in ("error", "message", "code")
            )
        else:
            error = str(detail)
        error_code = "bridge_error"
        for needle, code in (
            ("Unsupported action", "bridge_version_outdated"),
            ("outside AI_OS root", "register_outside_root"),
            ("Sheet not found", "sheet_not_found"),
            ("native Google Sheet", "register_not_native"),
            ("Unauthorized", "bridge_auth_failed"),
            ("UNAUTHORIZED", "bridge_auth_failed"),
            ("timed out", "bridge_timeout"),
            ("unsafe redirect", "bridge_unsafe_redirect"),
            ("Apps Script request failed", "bridge_transport_error"),
        ):
            if needle in error:
                error_code = code
                break
        return {
            "status": "error",
            "ready": False,
            "dual_write_enabled": bool(settings.task_register_dual_write_enabled),
            "checks": {"configured": True, "readable": False, "header_valid": False},
            "postgres_tasks": 0,
            "register_tasks": 0,
            "missing": 0,
            "stale": 0,
            "error_code": error_code,
        }
    response = {
        "status": readiness.get("status"),
        "ready": bool(readiness.get("ready")),
        "dual_write_enabled": bool(settings.task_register_dual_write_enabled),
        "checks": readiness.get("checks", {}),
        "postgres_tasks": 0,
        "register_tasks": 0,
        "missing": 0,
        "stale": 0,
    }
    if response["ready"]:
        reconciliation = await compare_task_register(db)
        for key in ("postgres_tasks", "register_tasks", "missing", "stale"):
            response[key] = int(reconciliation.get(key, 0))
    return response


@app.get("/integrations/task-register/readiness", dependencies=[Depends(require_api_token)])
async def task_register_readiness() -> dict:
    return await inspect_task_register()


@app.get("/integrations/task-register/reconciliation", dependencies=[Depends(require_api_token)])
async def task_register_reconciliation(db: Session = Depends(get_db)) -> dict:
    return await compare_task_register(db)


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


@app.get("/boot", dependencies=[Depends(require_api_token)])
def boot() -> dict:
    return {
        "status": "success",
        "version": settings.version,
        "architecture": "modular-postgres",
        "workflow": ["NEW", "RESEARCH", "CREATION", "OPPOSITION", "REVIEW", "APPROVAL", "DONE"],
        "compatibility": "Legacy bridge remains available during migration",
    }

