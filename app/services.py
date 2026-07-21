from datetime import datetime, timezone
from uuid import uuid4
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import get_settings
from .models import AuditEvent, Task, TaskStatus, WorkOrder
from .schemas import LegacyTaskImportRequest, LegacyTaskImportResult, TaskCreate


def create_task(db: Session, data: TaskCreate) -> Task:
    if data.idempotency_key:
        existing = db.scalar(select(Task).where(Task.idempotency_key == data.idempotency_key))
        if existing:
            return existing
    task = Task(
        title=data.title,
        description=data.description,
        priority=data.priority,
        project_key=data.project_key,
        owner=data.owner,
        idempotency_key=data.idempotency_key,
    )
    if data.work_order:
        task.work_order = WorkOrder(**data.work_order.model_dump())
    db.add(task)
    db.flush()
    db.add(AuditEvent(event_type="TASK_CREATED", actor=data.owner, entity_type="task", entity_id=task.id, payload={"title": data.title}))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        if data.idempotency_key:
            existing = db.scalar(select(Task).where(Task.idempotency_key == data.idempotency_key))
            if existing:
                return existing
        raise
    db.refresh(task)
    return task


def _legacy_priority(value: str | int) -> int:
    if isinstance(value, int):
        return min(max(value, 0), 100)
    normalized = value.strip().upper()
    return {
        "LOW": 25,
        "NÍZKA": 25,
        "NIZKA": 25,
        "MEDIUM": 50,
        "STREDNÁ": 50,
        "STREDNA": 50,
        "HIGH": 80,
        "VYSOKÁ": 80,
        "VYSOKA": 80,
        "CRITICAL": 100,
        "KRITICKÁ": 100,
        "KRITICKA": 100,
    }.get(normalized, 50)


def _legacy_status(value: str) -> TaskStatus:
    normalized = value.strip().upper()
    aliases = {"PENDING": TaskStatus.NEW, "STAV": TaskStatus.NEW}
    if normalized in aliases:
        return aliases[normalized]
    try:
        return TaskStatus(normalized)
    except ValueError:
        return TaskStatus.NEW


def import_legacy_tasks(db: Session, data: LegacyTaskImportRequest) -> LegacyTaskImportResult:
    external_ids = [item.external_id.strip() for item in data.tasks]
    if len(set(external_ids)) != len(external_ids):
        raise HTTPException(status_code=422, detail="Duplicate external_id in import payload")
    existing = set(
        db.scalars(select(Task.external_id).where(Task.external_id.in_(external_ids)))
    )
    pending = [
        (item, external_id)
        for item, external_id in zip(data.tasks, external_ids)
        if external_id not in existing
    ]
    if not data.dry_run:
        for item, external_id in pending:
            db.add(
                Task(
                    external_id=external_id,
                    title=item.title,
                    description=item.description,
                    status=_legacy_status(item.status),
                    priority=_legacy_priority(item.priority),
                    project_key=item.project_key,
                    owner=item.owner,
                    idempotency_key=f"legacy:{data.source_document_id}:{external_id}",
                    source_document_id=data.source_document_id,
                )
            )
        db.add(
            AuditEvent(
                event_type="LEGACY_TASKS_IMPORTED",
                actor="system",
                entity_type="document",
                entity_id=data.source_document_id,
                payload={"received": len(data.tasks), "imported": len(pending), "skipped": len(existing)},
            )
        )
        db.commit()
    return LegacyTaskImportResult(
        dry_run=data.dry_run,
        source_document_id=data.source_document_id,
        received=len(data.tasks),
        imported=len(pending),
        skipped_existing=len(existing),
        external_ids=[external_id for _, external_id in pending],
    )


def transition_task(db: Session, task: Task, new_status: TaskStatus, actor: str = "system") -> Task:
    allowed = {
        TaskStatus.NEW: {TaskStatus.RESEARCH, TaskStatus.BLOCKED, TaskStatus.CANCELLED},
        TaskStatus.RESEARCH: {TaskStatus.CREATION, TaskStatus.BLOCKED, TaskStatus.FAILED},
        TaskStatus.CREATION: {TaskStatus.OPPOSITION, TaskStatus.BLOCKED, TaskStatus.FAILED},
        TaskStatus.OPPOSITION: {TaskStatus.REWORK, TaskStatus.REVIEW, TaskStatus.BLOCKED},
        TaskStatus.REWORK: {TaskStatus.OPPOSITION, TaskStatus.BLOCKED, TaskStatus.FAILED},
        TaskStatus.REVIEW: {TaskStatus.APPROVAL, TaskStatus.REWORK, TaskStatus.FAILED},
        TaskStatus.APPROVAL: {TaskStatus.DONE, TaskStatus.REWORK, TaskStatus.CANCELLED},
    }
    if new_status not in allowed.get(task.status, set()):
        raise HTTPException(status_code=409, detail=f"Invalid transition {task.status} -> {new_status}")
    previous = task.status
    task.status = new_status
    task.version += 1
    task.updated_at = datetime.now(timezone.utc)
    db.add(AuditEvent(event_type="TASK_TRANSITION", actor=actor, entity_type="task", entity_id=task.id, payload={"from": previous.value, "to": new_status.value}))
    db.commit()
    db.refresh(task)
    return task


async def sync_task_to_register(db: Session, task: Task) -> dict:
    """Append one task version to the optional human-readable Sheets register."""
    settings = get_settings()
    if not settings.task_register_spreadsheet_id:
        return {"status": "disabled"}

    synced_events = db.scalars(
        select(AuditEvent).where(
            AuditEvent.event_type == "TASK_REGISTER_SYNCED",
            AuditEvent.entity_type == "task",
            AuditEvent.entity_id == task.id,
        )
    )
    if any(event.payload.get("version") == task.version for event in synced_events):
        return {"status": "already_synced", "version": task.version}

    request_id = f"task-register:{task.id}:v{task.version}"
    values = [
        task.id,
        task.external_id or "",
        task.status.value,
        task.priority,
        task.project_key,
        task.owner,
        task.title,
        task.description,
        task.created_at.isoformat(),
        task.updated_at.isoformat(),
        task.version,
    ]
    try:
        result = await call_apps_script(
            "APPEND_SHEET_ROW",
            {
                "spreadsheetId": settings.task_register_spreadsheet_id,
                "sheetName": settings.task_register_sheet_name,
                "values": values,
            },
            request_id=request_id,
        )
    except HTTPException as exc:
        db.add(
            AuditEvent(
                event_type="TASK_REGISTER_SYNC_FAILED",
                actor="system",
                entity_type="task",
                entity_id=task.id,
                payload={"version": task.version, "error_type": type(exc).__name__},
            )
        )
        db.commit()
        raise

    db.add(
        AuditEvent(
            event_type="TASK_REGISTER_SYNCED",
            actor="system",
            entity_type="task",
            entity_id=task.id,
            payload={
                "version": task.version,
                "request_id": request_id,
                "duplicate": bool(result.get("duplicate")),
            },
        )
    )
    db.commit()
    return {"status": "synced", "version": task.version, "request_id": request_id}


async def compare_task_register(db: Session) -> dict:
    """Compare PostgreSQL task versions with the optional Sheets register without writing."""
    settings = get_settings()
    if not settings.task_register_spreadsheet_id:
        return {"status": "disabled", "postgres_tasks": 0, "register_tasks": 0, "missing": 0, "stale": 0}

    tasks = list(db.scalars(select(Task)))
    result = await call_apps_script(
        "READ_SHEET_ROWS",
        {
            "spreadsheetId": settings.task_register_spreadsheet_id,
            "sheetName": settings.task_register_sheet_name,
            "rowCount": 5000,
            "columnCount": 11,
        },
    )
    rows = result.get("data", {}).get("rows", [])
    register_versions: dict[str, int] = {}
    for row in rows:
        if not isinstance(row, list) or len(row) < 11:
            continue
        task_id = str(row[0]).strip()
        try:
            version = int(row[10])
        except (TypeError, ValueError):
            continue
        if task_id:
            register_versions[task_id] = max(register_versions.get(task_id, 0), version)

    missing_ids = sorted(task.id for task in tasks if task.id not in register_versions)
    stale_ids = sorted(
        task.id
        for task in tasks
        if task.id in register_versions and register_versions[task.id] < task.version
    )
    return {
        "status": "success",
        "postgres_tasks": len(tasks),
        "register_tasks": len(register_versions),
        "missing": len(missing_ids),
        "stale": len(stale_ids),
        "missing_task_ids": missing_ids,
        "stale_task_ids": stale_ids,
    }


async def call_apps_script(action: str, payload: dict, request_id: str | None = None) -> dict:
    settings = get_settings()
    if not settings.apps_script_webapp_url or not settings.apps_script_secret:
        raise HTTPException(status_code=503, detail="Apps Script bridge is not configured")
    body = {
        "secret": settings.apps_script_secret,
        "action": action,
        "payload": payload,
        "version": settings.version,
        "requestId": request_id or str(uuid4()),
    }
    try:
        # Follow exactly the redirect protocol used by Apps Script. Automatic
        # redirect handling is deliberately disabled: a 307/308 response could
        # otherwise replay the POST body (including the bridge secret) to an
        # arbitrary host.
        async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
            response = await client.post(settings.apps_script_webapp_url, json=body)
            if response.status_code in {301, 302, 303}:
                location = response.headers.get("location", "")
                target = urlparse(location)
                if target.scheme != "https" or not (
                    target.hostname == "script.googleusercontent.com"
                    or (target.hostname or "").endswith(".script.googleusercontent.com")
                ):
                    raise HTTPException(status_code=502, detail="Apps Script returned an unsafe redirect")
                response = await client.get(location)
            response.raise_for_status()
            result = response.json()
    except HTTPException:
        raise
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=f"Apps Script request failed: {exc}") from exc
    if result.get("status") != "success":
        raise HTTPException(status_code=502, detail=result)
    return result

