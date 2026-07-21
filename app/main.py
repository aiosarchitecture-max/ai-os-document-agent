from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .config import get_settings
from .db import create_schema, get_db
from .models import Task, TaskStatus
from .schemas import (
    ApprovalRequest,
    CreateDocumentRequest,
    DangerousOperation,
    LegacyTaskImportRequest,
    LegacyTaskImportResult,
    TaskCreate,
    TaskRead,
)
from .security import consume_approval, issue_approval, require_api_token
from .services import call_apps_script, create_task, import_legacy_tasks, transition_task


@asynccontextmanager
async def lifespan(_: FastAPI):
    create_schema()
    yield


settings = get_settings()
app = FastAPI(title=settings.app_name, version=settings.version, lifespan=lifespan)


@app.get("/")
def root() -> dict:
    return {"system": "AI_OS", "status": "online", "version": settings.version}


@app.get("/health")
def health(db: Session = Depends(get_db)) -> dict:
    db.execute(text("SELECT 1"))
    return {"status": "ok", "version": settings.version, "database": "ok"}


@app.get("/tasks", response_model=list[TaskRead], dependencies=[Depends(require_api_token)])
def list_tasks(status: TaskStatus | None = None, limit: int = 100, db: Session = Depends(get_db)):
    query = select(Task).order_by(Task.priority.desc(), Task.created_at.asc()).limit(min(max(limit, 1), 500))
    if status:
        query = query.where(Task.status == status)
    return list(db.scalars(query))


@app.post("/tasks", response_model=TaskRead, dependencies=[Depends(require_api_token)])
def task_create(data: TaskCreate, db: Session = Depends(get_db)):
    return create_task(db, data)


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

