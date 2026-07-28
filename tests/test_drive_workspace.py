import pytest
from fastapi import HTTPException

from app.drive_workspace import parse_drive_intake_rows
from app.services import TASK_REGISTER_HEADERS


def test_parses_only_human_intake_rows():
    rows = [
        TASK_REGISTER_HEADERS,
        ["", "GD-001", "NEW", "80", "AI_OS", "Daniel", "Prvé zadanie", "Popis", "", "", ""],
        ["task-1", "GD-002", "NEW", "50", "AI_OS", "Daniel", "Projektovaný stav", "", "", "", "1"],
        ["", "GD-001", "NEW", "80", "AI_OS", "Daniel", "Duplikát", "", "", "", ""],
    ]

    tasks = parse_drive_intake_rows(rows)

    assert len(tasks) == 1
    assert tasks[0].title == "Prvé zadanie"
    assert tasks[0].priority == 80
    assert tasks[0].idempotency_key == "drive-intake:GD-001"


def test_rejects_unexpected_schema():
    with pytest.raises(HTTPException) as exc:
        parse_drive_intake_rows([["wrong"]])
    assert exc.value.status_code == 409
    assert exc.value.detail == {"code": "drive_workspace_invalid_schema"}
