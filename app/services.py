from datetime import datetime, timezone
from uuid import uuid4

import httpx
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import get_settings
from .models import AuditEvent, Task, TaskStatus, WorkOrder
from .schemas import TaskCreate


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


async def call_apps_script(action: str, payload: dict) -> dict:
    settings = get_settings()
    if not settings.apps_script_webapp_url or not settings.apps_script_secret:
        raise HTTPException(status_code=503, detail="Apps Script bridge is not configured")
    body = {
        "secret": settings.apps_script_secret,
        "action": action,
        "payload": payload,
        "version": settings.version,
        "requestId": str(uuid4()),
    }
    try:
        async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
            response = await client.post(settings.apps_script_webapp_url, json=body)
            response.raise_for_status()
            result = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=f"Apps Script request failed: {exc}") from exc
    if result.get("status") != "success":
        raise HTTPException(status_code=502, detail=result)
    return result
