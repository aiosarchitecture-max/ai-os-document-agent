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

