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


APP_NAME = "AI_OS_DOCUMENT_AGENT_V0_4_CREATE_PROJECT"

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/spreadsheets",
]

app = FastAPI(title=APP_NAME, version="0.4.0")


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
    raise HTTPException(status_code=500, detail="Missing GOOGLE_SERVICE_ACCOUNT_JSON_B64 or GOOGLE_SERVICE_ACCOUNT_JSON")


def _credentials():
    return service_account.Credentials.from_service_account_info(_service_account_info(), scopes=SCOPES)


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
    q = (f"'{_safe_query_string(root_id)}' in parents and "
         f"name='{_safe_query_string(name)}' and "
         f"mimeType='{mime_type}' and trashed=false")
    result = drive_service.files().list(q=q, fields="files(id,name,mimeType,webViewLink,parents)", pageSize=10, supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
    files = result.get("files", [])
    if not files:
        raise HTTPException(status_code=404, detail=f"Required file not found in AI_OS root folder: {name}. Create it manually first.")
    return files[0]


def _find_child_folder(drive_service, parent_id: str, name: str) -> dict:
    q = (f"'{_safe_query_string(parent_id)}' in parents and "
         f"name='{_safe_query_string(name)}' and "
         "mimeType='application/vnd.google-apps.folder' and trashed=false")
    result = drive_service.files().list(q=q, fields="files(id,name,mimeType,webViewLink,parents)", pageSize=10, supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
    files = result.get("files", [])
    if not files:
        raise HTTPException(status_code=404, detail=f"Required folder not found: {name}.")
    return files[0]


def _projects_folder(drive_service) -> dict:
    return _find_child_folder(drive_service, _root_folder_id(), "05_PROJECTS")


def _project_status_folder(drive_service, status: str) -> dict:
    projects = _projects_folder(drive_service)
    normalized = (status or "ACTIVE").upper()
    if normalized not in {"ACTIVE", "ON_HOLD", "COMPLETED", "ARCHIVED"}:
        normalized = "ACTIVE"
    return _find_child_folder(drive_service, projects["id"], normalized)


def _find_project_template(drive_service) -> dict:
    projects = _projects_folder(drive_service)
    q = (f"'{_safe_query_string(projects['id'])}' in parents and "
         "name='AI_OS_PROJECT_TEMPLATE' and "
         "mimeType='application/vnd.google-apps.document' and trashed=false")
    result = drive_service.files().list(q=q, fields="files(id,name,mimeType,webViewLink,parents)", pageSize=10, supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
    files = result.get("files", [])
    if not files:
        raise HTTPException(status_code=404, detail="AI_OS_PROJECT_TEMPLATE not found inside 05_PROJECTS.")
    return files[0]


def _append_to_existing_doc(document_id: str, text: str) -> None:
    docs_service = _docs()
    document = docs_service.documents().get(documentId=document_id).execute()
    end_index = document["body"]["content"][-1]["endIndex"] - 1
    docs_service.documents().batchUpdate(documentId=document_id, body={"requests": [{"insertText": {"location": {"index": end_index}, "text": "\n\n" + text}}]}).execute()


def _replace_whole_doc(document_id: str, text: str) -> None:
    docs_service = _docs()
    document = docs_service.documents().get(documentId=document_id).execute()
    end_index = document["body"]["content"][-1]["endIndex"]
    requests = []
    if end_index > 2:
        requests.append({"deleteContentRange": {"range": {"startIndex": 1, "endIndex": end_index - 1}}})
    requests.append({"insertText": {"location": {"index": 1}, "text": text}})
    docs_service.documents().batchUpdate(documentId=document_id, body={"requests": requests}).execute()


def _append_change_log_row(spreadsheet_id: str, action: str, target_document: str, status: str, note: str, link: str) -> None:
    sheets_service = _sheets()
    values = [[_now_iso(), APP_NAME, action, target_document, status, note, link]]
    sheets_service.spreadsheets().values().append(spreadsheetId=spreadsheet_id, range="A:G", valueInputOption="RAW", insertDataOption="INSERT_ROWS", body={"values": values}).execute()


def _change_log(drive_service) -> dict:
    return _find_file_by_name(drive_service, "AI_OS_CHANGE_LOG", "application/vnd.google-apps.spreadsheet")


def _copy_file(drive_service, source_file_id: str, new_name: str, parent_folder_id: str) -> dict:
    return drive_service.files().copy(fileId=source_file_id, body={"name": new_name, "parents": [parent_folder_id]}, fields="id,name,mimeType,webViewLink,parents", supportsAllDrives=True).execute()


def _project_document_text(title, owner, status, priority, description, objectives, deliverables, risks, next_actions) -> str:
    timestamp = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    return (
        "AI_OS_PROJECT\n\n"
        f"Project Name:\n{title}\n\n"
        f"Owner:\n{owner}\n\n"
        f"Status:\n{status}\n\n"
        f"Priority:\n{priority}\n\n"
        f"Created:\n{timestamp}\n\n"
        f"Created by:\n{APP_NAME}\n\n"
        f"Description:\n{description}\n\n"
        f"Objectives:\n{objectives}\n\n"
        f"Deliverables:\n{deliverables}\n\n"
        f"Risks:\n{risks}\n\n"
        f"Next Actions:\n{next_actions}\n"
    )


@app.get("/")
def root():
    return {"service": APP_NAME, "status": "running", "message": "AI OS Document Agent v0.4 is online. Supports notes, decisions and projects."}


@app.get("/health")
def health():
    return {"status": "ok", "service": APP_NAME, "time_utc": _now_iso()}


@app.get("/root-check")
def root_check(request: Request):
    _check_token(request)
    try:
        drive_service = _drive()
        result = drive_service.files().list(q=f"'{_safe_query_string(_root_folder_id())}' in parents and trashed=false", fields="files(id,name,mimeType,webViewLink)", pageSize=100, supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
        return {"status": "success", "root_folder_id": _root_folder_id(), "items": result.get("files", [])}
    except HttpError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/test-write")
def test_write_get(request: Request):
    _check_token(request)
    try:
        drive_service = _drive()
        doc = _find_file_by_name(drive_service, "AI_OS_SYSTEM_TEST", "application/vnd.google-apps.document")
        sheet = _change_log(drive_service)
        content = "AI_OS_SYSTEM_TEST\n" + f"Updated by: {APP_NAME}\nUpdated at: {dt.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}\nResult: Google Drive + Google Docs + Google Sheets integration works."
        _append_to_existing_doc(doc["id"], content)
        _append_change_log_row(sheet["id"], "TEST_WRITE", doc["name"], "SUCCESS", "Document Agent v0.4 test write.", doc.get("webViewLink", ""))
        return {"status": "success", "document_name": doc["name"], "document_url": doc.get("webViewLink"), "change_log_name": sheet["name"], "change_log_url": sheet.get("webViewLink")}
    except HttpError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/append-note")
def append_note_get(request: Request, title: str = "AI_OS_NOTE", content: str = "Empty note"):
    _check_token(request)
    return _append_note(title=title, content=content)


@app.post("/append-note")
async def append_note_post(request: Request, payload: WriteRequest):
    _check_token(request)
    return _append_note(title=payload.title or "AI_OS_NOTE", content=payload.content or "Empty note")


def _append_note(title: str, content: str):
    try:
        drive_service = _drive()
        inbox = _find_file_by_name(drive_service, "AI_OS_INBOX", "application/vnd.google-apps.document")
        sheet = _change_log(drive_service)
        timestamp = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        note_block = f"AI_OS_NOTE\nTitle: {title}\nCreated by: {APP_NAME}\nCreated at: {timestamp}\n\n{content}\n---"
        _append_to_existing_doc(inbox["id"], note_block)
        _append_change_log_row(sheet["id"], "APPEND_NOTE", inbox["name"], "SUCCESS", title, inbox.get("webViewLink", ""))
        return {"status": "success", "target_document": inbox["name"], "document_url": inbox.get("webViewLink"), "change_log_name": sheet["name"], "change_log_url": sheet.get("webViewLink"), "note_title": title}
    except HttpError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/create-decision")
def create_decision_get(request: Request, title: str = "Untitled decision", decision: str = "No decision text provided.", owner: str = "Unassigned", status: str = "APPROVED", context: str = ""):
    _check_token(request)
    return _create_decision(title, decision, owner, status, context)


@app.post("/create-decision")
async def create_decision_post(request: Request, payload: DecisionRequest):
    _check_token(request)
    return _create_decision(payload.title or "Untitled decision", payload.decision or "No decision text provided.", payload.owner or "Unassigned", payload.status or "APPROVED", payload.context or "")


def _create_decision(title: str, decision: str, owner: str, status: str, context: str):
    try:
        drive_service = _drive()
        decision_log = _find_file_by_name(drive_service, "AI_OS_DECISION_LOG", "application/vnd.google-apps.document")
        sheet = _change_log(drive_service)
        timestamp = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        decision_block = ("AI_OS_DECISION\n" f"Title: {title}\nOwner: {owner}\nStatus: {status}\nCreated by: {APP_NAME}\nCreated at: {timestamp}\n\n" "Context:\n" f"{context if context else 'No context provided.'}\n\n" "Decision:\n" f"{decision}\n" "------------------------------------------------")
        _append_to_existing_doc(decision_log["id"], decision_block)
        _append_change_log_row(sheet["id"], "CREATE_DECISION", decision_log["name"], "SUCCESS", title, decision_log.get("webViewLink", ""))
        return {"status": "success", "target_document": decision_log["name"], "document_url": decision_log.get("webViewLink"), "change_log_name": sheet["name"], "change_log_url": sheet.get("webViewLink"), "decision_title": title, "decision_status": status}
    except HttpError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/create-project")
def create_project_get(request: Request, title: str = "Untitled_Project", owner: str = "Unassigned", status: str = "ACTIVE", priority: str = "MEDIUM", description: str = "No description provided.", objectives: str = "No objectives provided.", deliverables: str = "No deliverables provided.", risks: str = "No risks provided.", next_actions: str = "No next actions provided."):
    _check_token(request)
    return _create_project(title, owner, status, priority, description, objectives, deliverables, risks, next_actions)


@app.post("/create-project")
async def create_project_post(request: Request, payload: ProjectRequest):
    _check_token(request)
    return _create_project(payload.title or "Untitled_Project", payload.owner or "Unassigned", payload.status or "ACTIVE", payload.priority or "MEDIUM", payload.description or "No description provided.", payload.objectives or "No objectives provided.", payload.deliverables or "No deliverables provided.", payload.risks or "No risks provided.", payload.next_actions or "No next actions provided.")


def _create_project(title, owner, status, priority, description, objectives, deliverables, risks, next_actions):
    try:
        drive_service = _drive()
        template = _find_project_template(drive_service)
        target_folder = _project_status_folder(drive_service, status)
        sheet = _change_log(drive_service)
        project_doc = _copy_file(drive_service, template["id"], title, target_folder["id"])
        project_text = _project_document_text(title, owner, (status or "ACTIVE").upper(), (priority or "MEDIUM").upper(), description, objectives, deliverables, risks, next_actions)
        _replace_whole_doc(project_doc["id"], project_text)
        _append_change_log_row(sheet["id"], "CREATE_PROJECT", project_doc["name"], "SUCCESS", f"{title} | {(status or 'ACTIVE').upper()} | {(priority or 'MEDIUM').upper()}", project_doc.get("webViewLink", ""))
        return {"status": "success", "project_name": project_doc["name"], "project_status_folder": target_folder["name"], "document_url": project_doc.get("webViewLink"), "change_log_name": sheet["name"], "change_log_url": sheet.get("webViewLink")}
    except HttpError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
