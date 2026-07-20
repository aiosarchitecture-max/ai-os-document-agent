"""One-shot durable worker entrypoint for Render Cron."""
from sqlalchemy import select

from .db import SessionLocal
from .models import AuditEvent, Task, TaskStatus


def run_once() -> int:
    with SessionLocal() as db:
        task = db.scalar(
            select(Task)
            .where(Task.status == TaskStatus.NEW)
            .order_by(Task.priority.desc(), Task.created_at.asc())
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if not task:
            return 0
        task.status = TaskStatus.RESEARCH
        task.version += 1
        db.add(AuditEvent(event_type="TASK_CLAIMED", entity_type="task", entity_id=task.id, payload={"next": "RESEARCH"}))
        db.commit()
        return 1


if __name__ == "__main__":
    raise SystemExit(0 if run_once() >= 0 else 1)

