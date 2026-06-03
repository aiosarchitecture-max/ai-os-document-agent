import base64
import datetime as dt
from zoneinfo import ZoneInfo
import json
import os
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


APP_NAME = "AI_OS_DOCUMENT_AGENT_V0_5_4_DUAL_TIME_READY"
PUBLIC_BASE_URL = "https://ai-os-document-agent.onrender.com"
AI_OS_TIMEZONE_NAME = "Europe/Bratislava"
AI_OS_TIMEZONE = ZoneInfo(AI_OS_TIMEZONE_NAME)

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/spreadsheets",
]

app = FastAPI(
    title=APP_NAME,
    version="0.5.4",
    servers=[{"url": PUBLIC_BASE_URL}],
)


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


class SearchRequest(BaseModel):
    query: str
    limit: Optional[int] = 10


SEARCH_DOCUMENT_NAMES = [
    "AI_OS_INBOX",
    "AI_OS_DECISION_LOG",
    "AI_OS_PROJECTS",
    "AI_OS_ROADMAP",
    "AI_OS_MASTER",
    "AI_OS_SYSTEM_TEST",
    "AI_OS_RELATIONS",
    "AI_OS_OBJECT_TYPES",
    "AI_OS_RELATION_TYPES",
    "AI_OS_ENTITY_REGISTRY",
    "AI_OS_CAPABILITY_MAP",
    "AI_OS_DATA_MODEL",
    "AI_OS_INFORMATION_ARCHITECTURE",
    "AI_OS_CORE_WORKFLOWS",
    "AI_OS_PERMISSION_MODEL",
    "AI_OS_ARCHITECTURE_PRINCIPLES",
    "AI_OS_ARCHITECT_INITIALIZATION_PROTOCOL",
    "AI_OS_DOCUMENT_AGENT_SPECIFICATION",
    "AI_OS_DOCUMENT_AGENT_MVP_ARCHITECTURE",
    "AI_OS_SUCCESS_METRICS",
    "AI_OS_V0.1_SPECIFICATION",
    "AI_OS_V0.1_DATABASE_SCHEMA",
    "AI_OS_V0.1_ARCHITECTURE_REVIEW",
]


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise HTTPException(status_code=500, detail=f"Missing environment variable: {name}")
    return value


def _check_token(request: Request) -> None:
    """
    TEMPORARY TEST MODE:
    Authorization is disabled so GPT Actions can write during integration testing.

    Later we will restore secure auth:
    x-ai-os-token: <API_TOKEN>
    """
    return


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


def _now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def _now_local() -> dt.datetime:
    return dt.datetime.now(AI_OS_TIMEZONE).replace(microsecond=0)


def _now_iso() -> str:
    return _now_utc().isoformat().replace("+00:00", "Z")


def _now_local_iso() -> str:
    return _now_local().isoformat()


def _now_local_string() -> str:
    return _now_local().strftime("%Y-%m-%d %H:%M:%S")


def _timestamp_block(label: str = "Created") -> str:
    return (
        f"{label} at: {_now_local_string()}\n"
        f"Timezone: {AI_OS_TIMEZONE_NAME}\n"
        f"UTC: {_now_iso()}\n"
    )


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


def _find_optional_doc_by_name(drive_service, name: str) -> Optional[dict]:
    root_id = _root_folder_id()
    q = (
        f"'{_safe_query_string(root_id)}' in parents and "
        f"name='{_safe_query_string(name)}' and "
        "mimeType='application/vnd.google-apps.document' and "
        "trashed=false"
    )
    result = drive_service.files().list(
        q=q,
        fields="files(id,name,mimeType,webViewLink,parents)",
        pageSize=5,
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
    ).execute()
    files = result.get("files", [])
    return files[0] if files else None


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


def _extract_text_from_doc(document_id: str) -> str:
    docs_service = _docs()
    document = docs_service.documents().get(documentId=document_id).execute()
    parts = []

    def read_elements(elements):
        for element in elements:
            if "paragraph" in element:
                for pe in element["paragraph"].get("elements", []):
                    text_run = pe.get("textRun")
                    if text_run and "content" in text_run:
                        parts.append(text_run["content"])
            elif "table" in element:
                for row in element["table"].get("tableRows", []):
                    for cell in row.get("tableCells", []):
                        read_elements(cell.get("content", []))
            elif "tableOfContents" in element:
                read_elements(element["tableOfContents"].get("content", []))

    read_elements(document.get("body", {}).get("content", []))
    return "".join(parts)


def _snippet(text: str, query: str, radius: int = 180) -> str:
    if not text:
        return ""
    low_text = text.lower()
    low_query = query.lower()
    idx = low_text.find(low_query)
    if idx == -1:
        return text[: radius * 2].replace("\n", " ").strip()
    start = max(0, idx - radius)
    end = min(len(text), idx + len(query) + radius)
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(text) else ""
    return (prefix + text[start:end] + suffix).replace("\n", " ").strip()


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
        "message": "AI OS Document Agent v0.5.4 is online. Temporary no-auth test mode is active. Dual UTC + Europe/Bratislava timestamps are enabled.",
    }


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": APP_NAME,
        "time_utc": _now_iso(),
        "time_local": _now_local_iso(),
        "timezone": AI_OS_TIMEZONE_NAME,
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
        return {"status": "success", "root_folder_id": root_id, "items": result.get("files", [])}
    except HttpError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/test-write")
def test_write_get(request: Request):
    _check_token(request)
    timestamp = _now_local_string()
    content = (
        "AI_OS_SYSTEM_TEST\n"
        f"Updated by: {APP_NAME}\n"
        _timestamp_block("Updated") +
        "Result: Google Drive + Google Docs + Google Sheets integration works."
    )

    try:
        drive_service = _drive()
        doc = _find_file_by_name(drive_service, "AI_OS_SYSTEM_TEST", "application/vnd.google-apps.document")
        sheet = _change_log(drive_service)
        _append_to_existing_doc(doc["id"], content)
        _append_change_log_row(sheet["id"], "TEST_WRITE", doc["name"], "SUCCESS", "Document Agent v0.5.4 test write.", doc.get("webViewLink", ""))
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
    return _append_note(payload.title or "AI_OS_NOTE", payload.content or "Empty note")


def _append_note(title: str, content: str):
    try:
        drive_service = _drive()
        inbox = _find_file_by_name(drive_service, "AI_OS_INBOX", "application/vnd.google-apps.document")
        sheet = _change_log(drive_service)
        timestamp = _now_local_string()
        note_block = (
            f"AI_OS_NOTE\nTitle: {title}\nCreated by: {APP_NAME}\n"
            + _timestamp_block("Created")
            + f"\n{content}\n---"
        )
        _append_to_existing_doc(inbox["id"], note_block)
        _append_change_log_row(sheet["id"], "APPEND_NOTE", inbox["name"], "SUCCESS", title, inbox.get("webViewLink", ""))
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
        payload.title or "Untitled decision",
        payload.decision or "No decision text provided.",
        payload.owner or "Unassigned",
        payload.status or "APPROVED",
        payload.context or "",
    )


def _create_decision(title: str, decision: str, owner: str, status: str, context: str):
    try:
        drive_service = _drive()
        decision_log = _find_file_by_name(drive_service, "AI_OS_DECISION_LOG", "application/vnd.google-apps.document")
        sheet = _change_log(drive_service)
        timestamp = _now_local_string()
        decision_block = (
            "AI_OS_DECISION\n"
            f"Title: {title}\nOwner: {owner}\nStatus: {status}\nCreated by: {APP_NAME}\n"
            + _timestamp_block("Created")
            + f"\nContext:\n{context if context else 'No context provided.'}\n\n"
            f"Decision:\n{decision}\n"
            "------------------------------------------------"
        )
        _append_to_existing_doc(decision_log["id"], decision_block)
        _append_change_log_row(sheet["id"], "CREATE_DECISION", decision_log["name"], "SUCCESS", title, decision_log.get("webViewLink", ""))
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
    return _create_project(title, owner, status, priority, description, objectives, deliverables, risks, next_actions)


@app.post("/create-project")
async def create_project_post(request: Request, payload: ProjectRequest):
    _check_token(request)
    return _create_project(
        payload.title or "Untitled_Project",
        payload.owner or "Unassigned",
        payload.status or "ACTIVE",
        payload.priority or "MEDIUM",
        payload.description or "No description provided.",
        payload.objectives or "No objectives provided.",
        payload.deliverables or "No deliverables provided.",
        payload.risks or "No risks provided.",
        payload.next_actions or "No next actions provided.",
    )


def _create_project(title: str, owner: str, status: str, priority: str, description: str, objectives: str, deliverables: str, risks: str, next_actions: str):
    try:
        drive_service = _drive()
        project_register = _project_register(drive_service)
        sheet = _change_log(drive_service)

        normalized_status = (status or "ACTIVE").upper()
        normalized_priority = (priority or "MEDIUM").upper()
        timestamp = _now_local_string()

        project_block = (
            "AI_OS_PROJECT\n"
            f"Project Name: {title}\nOwner: {owner}\nStatus: {normalized_status}\nPriority: {normalized_priority}\n"
            f"Created by: {APP_NAME}\n"
            + _timestamp_block("Created")
            + f"\nDescription:\n{description}\n\nObjectives:\n{objectives}\n\nDeliverables:\n{deliverables}\n\nRisks:\n{risks}\n\nNext Actions:\n{next_actions}\n"
            "------------------------------------------------"
        )

        _append_to_existing_doc(project_register["id"], project_block)
        _append_change_log_row(sheet["id"], "CREATE_PROJECT", project_register["name"], "SUCCESS", f"{title} | {normalized_status} | {normalized_priority}", project_register.get("webViewLink", ""))
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


@app.get("/search")
def search_get(request: Request, query: str, limit: int = 10):
    _check_token(request)
    return _search_ai_os(query=query, limit=limit)


@app.post("/search")
async def search_post(request: Request, payload: SearchRequest):
    _check_token(request)
    return _search_ai_os(query=payload.query, limit=payload.limit or 10)


def _search_ai_os(query: str, limit: int = 10):
    if not query or not query.strip():
        raise HTTPException(status_code=400, detail="Query is required.")

    try:
        drive_service = _drive()
        matches: List[Dict[str, Any]] = []
        searched_documents = []
        missing_documents = []

        for doc_name in SEARCH_DOCUMENT_NAMES:
            if len(matches) >= limit:
                break

            file_info = _find_optional_doc_by_name(drive_service, doc_name)
            if not file_info:
                missing_documents.append(doc_name)
                continue

            searched_documents.append(doc_name)
            text = _extract_text_from_doc(file_info["id"])
            if query.lower() in text.lower():
                matches.append({
                    "document_name": file_info["name"],
                    "document_url": file_info.get("webViewLink", ""),
                    "snippet": _snippet(text, query),
                })

        return {
            "status": "success",
            "query": query,
            "found": len(matches) > 0,
            "match_count": len(matches),
            "matches": matches,
            "searched_documents": searched_documents,
            "missing_documents": missing_documents,
            "note": "v0.5.4 uses simple full-text search across selected Google Docs, not semantic/vector search yet.",
        }
    except HttpError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
