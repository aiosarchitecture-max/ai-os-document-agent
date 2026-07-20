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

