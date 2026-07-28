from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .models import AuditEvent, Task, TaskStatus
from .schemas import TaskCreate
from .services import TASK_REGISTER_HEADERS, call_apps_script, create_task


@dataclass(frozen=True)
class DriveWorkspaceSyncResult:
    received: int
    imported: int
    skipped: int
    projected: int

    def as_dict(self) -> dict[str, int | str]:
        return {
            "status": "success",
            "received": self.received,
            "imported": self.imported,
            "skipped": self.skipped,
            "projected": self.projected,
        }


def _cell(row: list, index: int, default: str = "") -> str:
    if index >= len(row) or row[index] is None:
        return default
    return str(row[index]).strip()


def _priority(value: str) -> int:
    if not value:
        return 50
    try:
        return min(max(int(float(value)), 0), 100)
    except ValueError:
        aliases = {
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
        }
        return aliases.get(value.upper(), 50)


def parse_drive_intake_rows(rows: list[list]) -> list[TaskCreate]:
    """Parse user-authored rows from the shared Drive task register.

    Rows with a populated task_id are system projection rows and are ignored.
    Human intake rows must keep task_id blank and provide a stable external_id.
    """
    if not rows:
        return []
    header = [str(value).strip() for value in rows[0]]
    if header != TASK_REGISTER_HEADERS:
        raise HTTPException(status_code=409, detail={"code": "drive_workspace_invalid_schema"})

    tasks: list[TaskCreate] = []
    seen: set[str] = set()
    for row in rows[1:]:
        task_id = _cell(row, 0)
        external_id = _cell(row, 1)
        title = _cell(row, 6)
        if task_id or not external_id or not title:
            continue
        if external_id in seen:
            continue
        seen.add(external_id)
        tasks.append(
            TaskCreate(
                title=title,
                description=_cell(row, 7),
                priority=_priority(_cell(row, 3)),
                project_key=_cell(row, 4, "AI_OS") or "AI_OS",
                owner=_cell(row, 5, "Daniel") or "Daniel",
                idempotency_key=f"drive-intake:{external_id}",
            )
        )
    return tasks


async def import_drive_workspace(db: Session) -> tuple[int, int, int]:
    settings = get_settings()
    if not settings.task_register_spreadsheet_id:
        raise HTTPException(status_code=503, detail={"code": "drive_workspace_not_configured"})

    result = await call_apps_script(
        "READ_SHEET_ROWS",
        {
            "spreadsheetId": settings.task_register_spreadsheet_id,
            "sheetName": settings.task_register_sheet_name,
            "rowCount": 5000,
            "columnCount": len(TASK_REGISTER_HEADERS),
        },
    )
    rows = result.get("data", {}).get("rows", [])
    candidates = parse_drive_intake_rows(rows)
    imported = 0
    skipped = 0
    for candidate in candidates:
        existing = db.scalar(select(Task).where(Task.idempotency_key == candidate.idempotency_key))
        if existing:
            skipped += 1
            continue
        task = create_task(db, candidate)
        external_id = candidate.idempotency_key.removeprefix("drive-intake:")
        task.external_id = external_id
        task.source_document_id = settings.task_register_spreadsheet_id
        db.add(
            AuditEvent(
                event_type="TASK_IMPORTED_FROM_DRIVE",
                actor=candidate.owner,
                entity_type="task",
                entity_id=task.id,
                payload={"external_id": external_id, "source": "google_drive"},
            )
        )
        db.commit()
        imported += 1
    return len(candidates), imported, skipped


async def project_tasks_to_drive(db: Session) -> int:
    """Append only task versions not yet projected to the human-readable Drive register."""
    settings = get_settings()
    if not settings.task_register_spreadsheet_id:
        raise HTTPException(status_code=503, detail={"code": "drive_workspace_not_configured"})

    projected = 0
    for task in db.scalars(select(Task).order_by(Task.created_at.asc())):
        already = db.scalar(
            select(AuditEvent).where(
                AuditEvent.event_type == "TASK_DRIVE_PROJECTED",
                AuditEvent.entity_type == "task",
                AuditEvent.entity_id == task.id,
                AuditEvent.payload["version"].as_integer() == task.version,
            )
        )
        if already:
            continue
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
        request_id = f"drive-projection:{task.id}:v{task.version}"
        await call_apps_script(
            "APPEND_SHEET_ROW",
            {
                "spreadsheetId": settings.task_register_spreadsheet_id,
                "sheetName": settings.task_register_sheet_name,
                "values": values,
            },
            request_id=request_id,
        )
        db.add(
            AuditEvent(
                event_type="TASK_DRIVE_PROJECTED",
                actor="system",
                entity_type="task",
                entity_id=task.id,
                payload={
                    "version": task.version,
                    "request_id": request_id,
                    "projected_at": datetime.now(timezone.utc).isoformat(),
                },
            )
        )
        db.commit()
        projected += 1
    return projected


async def sync_drive_workspace(db: Session) -> DriveWorkspaceSyncResult:
    received, imported, skipped = await import_drive_workspace(db)
    projected = await project_tasks_to_drive(db)
    return DriveWorkspaceSyncResult(received, imported, skipped, projected)
