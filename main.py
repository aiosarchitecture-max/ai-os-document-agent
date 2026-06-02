import base64
import datetime as dt
import json
import os
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


APP_NAME = "AI_OS_DOCUMENT_AGENT_V0_4_1_PROJECT_LOG"

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/spreadsheets",
]

app = FastAPI(title=APP_NAME, version="0.4.1")


class WriteRequest(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None


class DecisionRequest(BaseModel):
    title: Optional[str] = None
    decision: Optional[str] = None
    owner: Optional[str] = None
    status: Optional[str] = "APPROVED"
    context: Optional[str] = None


class ProjectRequest(BaseModel):
    title: Optional[str] = None
    owner: Optional[str] = None
    status: Optional[str] = "ACTIVE"
    priority: Optional[str] = "MEDIUM"
    description: Optional[str] = None
    objectives: Optional[str] = None
    deliverables: Optional[str] = None
    risks: Optional[str] = None
    next_actions: Optional[str] = None


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise HTTPException(status_code=500, detail=f"Missing environment variable: {name}")
    return value


def _check_token(request: Request) -> None:
    expected = os.getenv("API_TOKEN")
    if not expected:
        raise HTTPException(status_code=500, detail="Missing environment variable: API_TOKEN")
    supplied = request.headers.get("x-ai-os-token") or request.query_params.get("token")
    if supplied != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")


def _service_account_info() -> dict:
    raw_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    b64_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON_B64")

    if b64_json:
        return json.loads(base64.b64decode(b64_json).decode("utf-8"))
    if raw_json:
        return json.loads(raw_json)

    raise HTTPException(
        status_code=500,
        detail="Missing GOOGLE_SERVICE_ACCOUNT_JSON_B64 or GOOGLE_SERVICE_ACCOUNT_JSON",
    )


def _credentials():
    return service_account.Credentials.from_service_account_info(
        _service_account_info(),
        scopes=SCOPES,
    )


def _drive():
    return build("drive", "v3", credentials=_credentials(), cache_discovery=False)


def _docs():
    return build("docs", "v1", credentials=_credentials(), cache_discovery=False)


def _sheets():
    return build("sheets", "v4", credentials=_credentials(), cache_discovery=False)


def _root_folder_id() -> str:
    return _require_env("AI_OS_ROOT_FOLDER_ID")


def _now_iso() -> str:
    return dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _safe_query_string(value: str) -> str:
    return value.replace("'", "\\'")


def _find_file_by_name(drive_service, name: str, mime_type: str) -> dict:
    root_id = _root_folder_id()
    q = (
        f"'{_safe_query_string(root_id)}' in parents and "
        f"name='{_safe_query_string(name)}' and "
        f"mimeType='{mime_type}' and "
        "trashed=false"
    )
    result = drive_service.files().list(
        q=q,
        fields="files(id,name,mimeType,webViewLink,parents)",
        pageSize=10,
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
    ).execute()

    files = result.get("files", [])
    if not files:
        raise HTTPException(
            status_code=404,
            detail=f"Required file not found in AI_OS root folder: {name}. Create it manually first.",
        )
    return files[0]


def _append_to_existing_doc(document_id: str, text: str) -> None:
    docs_service = _docs()
    document = docs_service.documents().get(documentId=document_id).execute()
    end_index = document["body"]["content"][-1]["endIndex"] - 1

    docs_service.documents().batchUpdate(
        documentId=document_id,
        body={
            "requests": [
                {
                    "insertText": {
                        "location": {"index": end_index},
                        "text": "\n\n" + text,
                    }
                }
            ]
        },
    ).execute()


def _append_change_log_row(
    spreadsheet_id: str,
    action: str,
    target_document: str,
    status: str,
    note: str,
    link: str,
) -> None:
    sheets_service = _sheets()
    values = [[
        _now_iso(),
        APP_NAME,
        action,
        target_document,
        status,
        note,
        link,
    ]]

    sheets_service.spreadsheets().values().append(
        spreadsheetId=spreadsheet_id,
        range="A:G",
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body={"values": values},
    ).execute()


def _change_log(drive_service) -> dict:
    return _find_file_by_name(
        drive_service,
        "AI_OS_CHANGE_LOG",
        "application/vnd.google-apps.spreadsheet",
    )


def _project_register(drive_service) -> dict:
    return _find_file_by_name(
        drive_service,
        "AI_OS_PROJECTS",
        "application/vnd.google-apps.document",
    )


@app.get("/")
def root():
    return {
        "service": APP_NAME,
        "status": "running",
        "message": "AI OS Document Agent v0.4.1 is online. Project creation now uses AI_OS_PROJECTS register, not file copy.",
    }


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": APP_NAME,
        "time_utc": _now_iso(),
    }


@app.get("/root-check")
def root_check(request: Request):
    _check_token(request)
    try:
        drive_service = _drive()
        root_id = _root_folder_id()
        result = drive_service.files().list(
            q=f"'{_safe_query_string(root_id)}' in parents and trashed=false",
            fields="files(id,name,mimeType,webViewLink)",
            pageSize=100,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute()
        return {
            "status": "success",
            "root_folder_id": root_id,
            "items": result.get("files", []),
        }
    except HttpError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/test-write")
def test_write_get(request: Request):
    _check_token(request)
    timestamp = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    content = (
        "AI_OS_SYSTEM_TEST\n"
        f"Updated by: {APP_NAME}\n"
        f"Updated at: {timestamp}\n"
        "Result: Google Drive + Google Docs + Google Sheets integration works."
    )

    try:
        drive_service = _drive()
        doc = _find_file_by_name(
            drive_service,
            "AI_OS_SYSTEM_TEST",
            "application/vnd.google-apps.document",
        )
        sheet = _change_log(drive_service)
        _append_to_existing_doc(doc["id"], content)
        _append_change_log_row(
            spreadsheet_id=sheet["id"],
            action="TEST_WRITE",
            target_document=doc["name"],
            status="SUCCESS",
            note="Document Agent v0.4.1 test write.",
            link=doc.get("webViewLink", ""),
        )
        return {
            "status": "success",
            "document_name": doc["name"],
            "document_url": doc.get("webViewLink"),
            "change_log_name": sheet["name"],
            "change_log_url": sheet.get("webViewLink"),
        }
    except HttpError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/append-note")
def append_note_get(request: Request, title: str = "AI_OS_NOTE", content: str = "Empty note"):
    _check_token(request)
    return _append_note(title=title, content=content)


@app.post("/append-note")
async def append_note_post(request: Request, payload: WriteRequest):
    _check_token(request)
    return _append_note(
        title=payload.title or "AI_OS_NOTE",
        content=payload.content or "Empty note",
    )


def _append_note(title: str, content: str):
    try:
        drive_service = _drive()
        inbox = _find_file_by_name(
            drive_service,
            "AI_OS_INBOX",
            "application/vnd.google-apps.document",
        )
        sheet = _change_log(drive_service)
        timestamp = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        note_block = (
            f"AI_OS_NOTE\n"
            f"Title: {title}\n"
            f"Created by: {APP_NAME}\n"
            f"Created at: {timestamp}\n\n"
            f"{content}\n"
            f"---"
        )
        _append_to_existing_doc(inbox["id"], note_block)
        _append_change_log_row(
            spreadsheet_id=sheet["id"],
            action="APPEND_NOTE",
            target_document=inbox["name"],
            status="SUCCESS",
            note=title,
            link=inbox.get("webViewLink", ""),
        )
        return {
            "status": "success",
            "target_document": inbox["name"],
            "document_url": inbox.get("webViewLink"),
            "change_log_name": sheet["name"],
            "change_log_url": sheet.get("webViewLink"),
            "note_title": title,
        }
    except HttpError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/create-decision")
def create_decision_get(
    request: Request,
    title: str = "Untitled decision",
    decision: str = "No decision text provided.",
    owner: str = "Unassigned",
    status: str = "APPROVED",
    context: str = "",
):
    _check_token(request)
    return _create_decision(title, decision, owner, status, context)


@app.post("/create-decision")
async def create_decision_post(request: Request, payload: DecisionRequest):
    _check_token(request)
    return _create_decision(
        title=payload.title or "Untitled decision",
        decision=payload.decision or "No decision text provided.",
        owner=payload.owner or "Unassigned",
        status=payload.status or "APPROVED",
        context=payload.context or "",
    )


def _create_decision(title: str, decision: str, owner: str, status: str, context: str):
    try:
        drive_service = _drive()
        decision_log = _find_file_by_name(
            drive_service,
            "AI_OS_DECISION_LOG",
            "application/vnd.google-apps.document",
        )
        sheet = _change_log(drive_service)
        timestamp = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        decision_block = (
            "AI_OS_DECISION\n"
            f"Title: {title}\n"
            f"Owner: {owner}\n"
            f"Status: {status}\n"
            f"Created by: {APP_NAME}\n"
            f"Created at: {timestamp}\n\n"
            "Context:\n"
            f"{context if context else 'No context provided.'}\n\n"
            "Decision:\n"
            f"{decision}\n"
            "------------------------------------------------"
        )
        _append_to_existing_doc(decision_log["id"], decision_block)
        _append_change_log_row(
            spreadsheet_id=sheet["id"],
            action="CREATE_DECISION",
            target_document=decision_log["name"],
            status="SUCCESS",
            note=title,
            link=decision_log.get("webViewLink", ""),
        )
        return {
            "status": "success",
            "target_document": decision_log["name"],
            "document_url": decision_log.get("webViewLink"),
            "change_log_name": sheet["name"],
            "change_log_url": sheet.get("webViewLink"),
            "decision_title": title,
            "decision_status": status,
        }
    except HttpError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/create-project")
def create_project_get(
    request: Request,
    title: str = "Untitled_Project",
    owner: str = "Unassigned",
    status: str = "ACTIVE",
    priority: str = "MEDIUM",
    description: str = "No description provided.",
    objectives: str = "No objectives provided.",
    deliverables: str = "No deliverables provided.",
    risks: str = "No risks provided.",
    next_actions: str = "No next actions provided.",
):
    _check_token(request)
    return _create_project(
        title=title,
        owner=owner,
        status=status,
        priority=priority,
        description=description,
        objectives=objectives,
        deliverables=deliverables,
        risks=risks,
        next_actions=next_actions,
    )


@app.post("/create-project")
async def create_project_post(request: Request, payload: ProjectRequest):
    _check_token(request)
    return _create_project(
        title=payload.title or "Untitled_Project",
        owner=payload.owner or "Unassigned",
        status=payload.status or "ACTIVE",
        priority=payload.priority or "MEDIUM",
        description=payload.description or "No description provided.",
        objectives=payload.objectives or "No objectives provided.",
        deliverables=payload.deliverables or "No deliverables provided.",
        risks=payload.risks or "No risks provided.",
        next_actions=payload.next_actions or "No next actions provided.",
    )


def _create_project(
    title: str,
    owner: str,
    status: str,
    priority: str,
    description: str,
    objectives: str,
    deliverables: str,
    risks: str,
    next_actions: str,
):
    try:
        drive_service = _drive()
        project_register = _project_register(drive_service)
        sheet = _change_log(drive_service)

        normalized_status = (status or "ACTIVE").upper()
        normalized_priority = (priority or "MEDIUM").upper()
        timestamp = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

        project_block = (
            "AI_OS_PROJECT\n"
            f"Project Name: {title}\n"
            f"Owner: {owner}\n"
            f"Status: {normalized_status}\n"
            f"Priority: {normalized_priority}\n"
            f"Created by: {APP_NAME}\n"
            f"Created at: {timestamp}\n\n"
            "Description:\n"
            f"{description}\n\n"
            "Objectives:\n"
            f"{objectives}\n\n"
            "Deliverables:\n"
            f"{deliverables}\n\n"
            "Risks:\n"
            f"{risks}\n\n"
            "Next Actions:\n"
            f"{next_actions}\n"
            "------------------------------------------------"
        )

        _append_to_existing_doc(project_register["id"], project_block)
        _append_change_log_row(
            spreadsheet_id=sheet["id"],
            action="CREATE_PROJECT",
            target_document=project_register["name"],
            status="SUCCESS",
            note=f"{title} | {normalized_status} | {normalized_priority}",
            link=project_register.get("webViewLink", ""),
        )

        return {
            "status": "success",
            "target_document": project_register["name"],
            "document_url": project_register.get("webViewLink"),
            "change_log_name": sheet["name"],
            "change_log_url": sheet.get("webViewLink"),
            "project_title": title,
            "project_status": normalized_status,
            "project_priority": normalized_priority,
        }
    except HttpError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
