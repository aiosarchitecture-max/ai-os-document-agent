import json
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from .config import get_settings
from .models import AuditEvent, CanvasDocument, utcnow
from .schemas import CanvasDocumentRead, CanvasDocumentUpdate


CANVAS_ID = "primary"
CANVAS_WRITE_LOCK_ID = 1095786323
ASSET_DIR = Path(__file__).with_name("static")


def default_canvas() -> CanvasDocumentRead:
    return CanvasDocumentRead(
        version=0,
        nodes=[
            {"id": "D1", "x": 40, "y": 60, "w": 150, "h": 60, "text": "D1 Komunikácia", "color": "green"},
            {"id": "D4", "x": 220, "y": 60, "w": 150, "h": 60, "text": "D4 Produkcia", "color": "green"},
            {"id": "D5", "x": 400, "y": 60, "w": 150, "h": 60, "text": "D5 Kvalita", "color": "green"},
            {"id": "D7", "x": 580, "y": 60, "w": 150, "h": 60, "text": "D7 Riadenie", "color": "green"},
            {"id": "D2", "x": 130, "y": 180, "w": 150, "h": 60, "text": "D2 Šírenie", "color": "amber"},
            {"id": "D3", "x": 310, "y": 180, "w": 150, "h": 60, "text": "D3 Financie", "color": "amber"},
            {"id": "D6", "x": 490, "y": 180, "w": 150, "h": 60, "text": "D6 Verejnosť", "color": "amber"},
        ],
        edges=[
            {"from": "D1", "to": "D2"},
            {"from": "D4", "to": "D3"},
            {"from": "D5", "to": "D6"},
        ],
        snapshot={},
        updated_by="system",
        updated_at=None,
    )


def read_canvas(db: Session) -> CanvasDocumentRead:
    record = db.get(CanvasDocument, CANVAS_ID)
    if record is None:
        return default_canvas()
    return CanvasDocumentRead.model_validate(record, from_attributes=True)


def _lock_canvas_write(db: Session) -> None:
    """Serialize singleton canvas writes, including the first insert.

    ``SELECT ... FOR UPDATE`` cannot lock a row that does not exist yet. A
    transaction-scoped PostgreSQL advisory lock closes that initial-write race
    without changing the schema. SQLite remains unchanged for local tests.
    """
    if db.get_bind().dialect.name == "postgresql":
        db.execute(
            text("SELECT pg_advisory_xact_lock(:lock_id)"),
            {"lock_id": CANVAS_WRITE_LOCK_ID},
        )


def save_canvas(db: Session, data: CanvasDocumentUpdate) -> CanvasDocumentRead:
    serialized_size = len(
        json.dumps(data.model_dump(), ensure_ascii=False, separators=(",", ":")).encode()
    )
    if serialized_size > get_settings().canvas_max_payload_bytes:
        raise HTTPException(status_code=413, detail="Canvas payload is too large")

    _lock_canvas_write(db)
    record = (
        db.query(CanvasDocument)
        .filter(CanvasDocument.id == CANVAS_ID)
        .with_for_update()
        .one_or_none()
    )
    current_version = record.version if record else 0
    if data.expected_version != current_version:
        raise HTTPException(
            status_code=409,
            detail={"code": "canvas_version_conflict", "current_version": current_version},
        )

    now = utcnow()
    actor = "authenticated-api-user"
    if record is None:
        record = CanvasDocument(id=CANVAS_ID)
        db.add(record)
    record.version = current_version + 1
    record.nodes = data.nodes
    record.edges = data.edges
    record.snapshot = data.snapshot
    record.updated_by = actor
    record.updated_at = now
    db.add(
        AuditEvent(
            event_type="CANVAS_SAVED",
            actor=actor,
            entity_type="canvas",
            entity_id=CANVAS_ID,
            payload={
                "from_version": current_version,
                "to_version": record.version,
                "nodes": len(data.nodes),
                "edges": len(data.edges),
            },
        )
    )
    db.commit()
    db.refresh(record)
    return CanvasDocumentRead.model_validate(record, from_attributes=True)


def asset(name: str) -> str:
    return (ASSET_DIR / name).read_text(encoding="utf-8")
