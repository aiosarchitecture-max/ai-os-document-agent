import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .models import Approval


def require_api_token(authorization: str | None = Header(default=None)) -> None:
    expected = get_settings().api_token
    if not expected:
        raise HTTPException(status_code=503, detail="API token is not configured")
    supplied = ""
    if authorization and authorization.lower().startswith("bearer "):
        supplied = authorization[7:].strip()
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")


def payload_digest(operation: str, target: str, payload: dict) -> str:
    raw = json.dumps({"operation": operation, "target": target, "payload": payload}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def issue_approval(db: Session, operation: str, target: str, payload: dict, ttl_seconds: int) -> str:
    token = secrets.token_urlsafe(32)
    record = Approval(
        operation=operation,
        target=target,
        payload_hash=payload_digest(operation, target, payload),
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds),
    )
    db.add(record)
    db.commit()
    return token


def consume_approval(db: Session, operation: str, target: str, payload: dict, token: str) -> Approval:
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    record = db.scalar(select(Approval).where(Approval.token_hash == token_hash).with_for_update())
    now = datetime.now(timezone.utc)
    expires_at = record.expires_at if record else None
    if expires_at is not None and expires_at.tzinfo is None:
        # SQLite drops timezone metadata; PostgreSQL keeps it. Normalize both.
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if not record or record.used or expires_at is None or expires_at < now:
        raise HTTPException(status_code=403, detail="Approval is invalid, expired, or already used")
    if record.operation != operation or record.target != target:
        raise HTTPException(status_code=403, detail="Approval does not match operation target")
    if not hmac.compare_digest(record.payload_hash, payload_digest(operation, target, payload)):
        raise HTTPException(status_code=403, detail="Approval does not match payload")
    record.used = True
    record.used_at = now
    db.commit()
    return record
