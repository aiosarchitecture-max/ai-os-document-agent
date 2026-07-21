from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from .models import TaskStatus


class WorkOrderInput(BaseModel):
    objective: str = Field(min_length=3)
    deliverable_type: str = "document"
    constraints: dict[str, Any] = Field(default_factory=dict)
    inputs: list[dict[str, Any]] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    definition_of_done: list[str] = Field(default_factory=list)
    required_checks: list[str] = Field(default_factory=list)


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    description: str = ""
    priority: int = Field(default=50, ge=0, le=100)
    project_key: str = "AI_OS"
    owner: str = "Daniel"
    idempotency_key: str | None = Field(default=None, max_length=200)
    work_order: WorkOrderInput | None = None


class TaskRead(BaseModel):
    id: str
    external_id: str | None
    title: str
    description: str
    status: TaskStatus
    priority: int
    project_key: str
    owner: str

    model_config = {"from_attributes": True}


class AuditEventRead(BaseModel):
    id: str
    event_type: str
    actor: str
    entity_type: str
    entity_id: str
    payload: dict[str, Any]
    created_at: datetime

    model_config = {"from_attributes": True}


class ApprovalRequest(BaseModel):
    operation: str = Field(min_length=3, max_length=100)
    target: str = Field(min_length=1, max_length=500)
    payload: dict[str, Any] = Field(default_factory=dict)
    ttl_seconds: int = Field(default=900, ge=60, le=3600)


class DangerousOperation(BaseModel):
    operation: str
    target: str
    payload: dict[str, Any] = Field(default_factory=dict)
    approval_token: str


class CreateDocumentRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=200, pattern=r"^[A-Za-z0-9._:-]+$")
    title: str = Field(min_length=1, max_length=500)
    content: str = Field(default="", max_length=100000)


class LegacyTaskInput(BaseModel):
    external_id: str = Field(min_length=1, max_length=120)
    status: str = Field(default="NEW", max_length=40)
    priority: str | int = "MEDIUM"
    project_key: str = Field(default="AI_OS", max_length=120)
    owner: str = Field(default="Daniel", max_length=200)
    title: str = Field(min_length=1, max_length=500)
    description: str = ""


class LegacyTaskImportRequest(BaseModel):
    source_document_id: str = Field(min_length=1, max_length=200)
    dry_run: bool = True
    tasks: list[LegacyTaskInput] = Field(min_length=1, max_length=500)


class LegacyTaskImportResult(BaseModel):
    dry_run: bool
    source_document_id: str
    received: int
    imported: int
    skipped_existing: int
    external_ids: list[str]


