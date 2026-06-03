import base64
import datetime as dt
import json
import os
import re
from typing import Optional, List, Dict, Any
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


APP_NAME = "AI_OS_DOCUMENT_AGENT_V0_8_0_QUERY_ENGINE"
PUBLIC_BASE_URL = "https://ai-os-document-agent.onrender.com"
AI_OS_TIMEZONE_NAME = "Europe/Bratislava"
AI_OS_TIMEZONE = ZoneInfo(AI_OS_TIMEZONE_NAME)
DEFAULT_OWNER = "Daniel Valušiak"

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/spreadsheets",
]

app = FastAPI(
    title=APP_NAME,
    version="0.8.0",
    servers=[{"url": PUBLIC_BASE_URL}],
)


class WriteRequest(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    owner: Optional[str] = None
    related_to: Optional[str] = None


class DecisionRequest(BaseModel):
    title: Optional[str] = None
    decision: Optional[str] = None
    owner: Optional[str] = None
    status: Optional[str] = "APPROVED"
    priority: Optional[str] = "MEDIUM"
    context: Optional[str] = None
    related_to: Optional[str] = None


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
    related_to: Optional[str] = None


class SearchRequest(BaseModel):
    query: str
    limit: Optional[int] = 10


class FindByIdRequest(BaseModel):
    object_id: str


class RelationRequest(BaseModel):
    source_id: str
    relation_type: str
    target_id: str
    note: Optional[str] = None


class GetRelationsRequest(BaseModel):
    object_id: str


class FindEntityRequest(BaseModel):
    query: str
    limit: Optional[int] = 10


class FindRelatedRequest(BaseModel):
    object_id: str
    relation_type: Optional[str] = None
    direction: Optional[str] = "both"
    limit: Optional[int] = 20


class EntityRequest(BaseModel):
    entity_type: str
    title: str
    description: Optional[str] = None
    owner: Optional[str] = None
    status: Optional[str] = "ACTIVE"
    priority: Optional[str] = "NORMAL"
    related_to: Optional[str] = None


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


OBJECT_DOCUMENT_MAP = {
    "NOTE": "AI_OS_INBOX",
    "PROJECT": "AI_OS_PROJECTS",
    "DECISION": "AI_OS_DECISION_LOG",
}


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise HTTPException(status_code=500, detail=f"Missing environment variable: {name}")
    return value


def _check_token(request: Request) -> None:
    """
    TEMPORARY TEST MODE:
    Authorization is disabled so GPT Actions can write during integration testing.

    Later restore secure auth:
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


def _today_id_date() -> str:
    return _now_local().strftime("%Y%m%d")


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


def _snippet(text: str, query: str, radius: int = 220) -> str:
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


def _relations_register(drive_service) -> Optional[dict]:
    return _find_optional_doc_by_name(drive_service, "AI_OS_RELATIONS")


def _entity_registry(drive_service) -> Optional[dict]:
    return _find_optional_doc_by_name(drive_service, "AI_OS_ENTITY_REGISTRY")


def _build_object_id(prefix: str, existing_texts: List[str]) -> str:
    date_part = _today_id_date()
    pattern = re.compile(rf"\b{re.escape(prefix)}-{date_part}-(\d{{4}})\b")
    max_num = 0

    for text in existing_texts:
        for match in pattern.finditer(text or ""):
            try:
                max_num = max(max_num, int(match.group(1)))
            except ValueError:
                continue

    return f"{prefix}-{date_part}-{max_num + 1:04d}"


def _generate_object_id(drive_service, prefix: str, doc_names: List[str]) -> str:
    texts = []
    for doc_name in doc_names:
        doc = _find_optional_doc_by_name(drive_service, doc_name)
        if doc:
            texts.append(_extract_text_from_doc(doc["id"]))
    return _build_object_id(prefix, texts)


def _metadata_block(
    object_id: str,
    object_type: str,
    owner: str,
    status: Optional[str] = None,
    priority: Optional[str] = None,
) -> str:
    lines = [
        "AI_OS_METADATA",
        f"ID: {object_id}",
        f"TYPE: {object_type}",
        f"OWNER: {owner}",
    ]
    if status:
        lines.append(f"STATUS: {status}")
    if priority:
        lines.append(f"PRIORITY: {priority}")
    lines.extend([
        _timestamp_block("Created").rstrip(),
        "END_METADATA",
    ])
    return "\n".join(lines) + "\n"


def _append_entity_registry(
    drive_service,
    object_id: str,
    object_type: str,
    title: str,
    owner: str,
    status: str,
    priority: str,
    target_document: str,
    link: str,
) -> None:
    registry = _entity_registry(drive_service)
    if not registry:
        return

    block = (
        "AI_OS_ENTITY\n"
        f"ID: {object_id}\n"
        f"TYPE: {object_type}\n"
        f"TITLE: {title}\n"
        f"OWNER: {owner}\n"
        f"STATUS: {status}\n"
        f"PRIORITY: {priority}\n"
        f"TARGET_DOCUMENT: {target_document}\n"
        f"LINK: {link}\n"
        + _timestamp_block("Registered")
        + "------------------------------------------------"
    )
    _append_to_existing_doc(registry["id"], block)


def _append_relation(
    drive_service,
    source_id: str,
    relation_type: str,
    target_id: str,
    note: str = "",
) -> bool:
    relations = _relations_register(drive_service)
    if not relations:
        return False

    block = (
        "AI_OS_RELATION\n"
        f"SOURCE_ID: {source_id}\n"
        f"RELATION_TYPE: {relation_type}\n"
        f"TARGET_ID: {target_id}\n"
        f"NOTE: {note}\n"
        + _timestamp_block("Created")
        + "------------------------------------------------"
    )
    _append_to_existing_doc(relations["id"], block)
    return True


def _create_owner_relation(drive_service, object_id: str, owner: str) -> None:
    if owner:
        owner_slug = re.sub(r"[^A-Za-z0-9]+", "_", owner.strip()).strip("_").upper()
        if owner_slug:
            _append_relation(drive_service, object_id, "HAS_OWNER", f"OWNER-{owner_slug}", owner)


def _parse_object_type_from_id(object_id: str) -> Optional[str]:
    if not object_id or "-" not in object_id:
        return None
    prefix = object_id.split("-", 1)[0].upper()
    return prefix if prefix in OBJECT_DOCUMENT_MAP else None


def _compact_success(
    object_id: Optional[str] = None,
    object_type: Optional[str] = None,
    title: Optional[str] = None,
    target_document: Optional[str] = None,
    action: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    response: Dict[str, Any] = {
        "status": "success",
        "service": APP_NAME,
        "time_utc": _now_iso(),
        "time_local": _now_local_iso(),
        "timezone": AI_OS_TIMEZONE_NAME,
    }
    if action:
        response["action"] = action
    if object_id:
        response["object_id"] = object_id
    if object_type:
        response["object_type"] = object_type
    if title:
        response["title"] = title
    if target_document:
        response["target_document"] = target_document
    if extra:
        response.update(extra)
    return response


@app.get("/")
def root():
    return {
        "service": APP_NAME,
        "status": "running",
        "message": "AI OS Document Agent v0.8.0 is online. Query Engine is enabled.",
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
    content = (
        "AI_OS_SYSTEM_TEST\n"
        f"Updated by: {APP_NAME}\n"
        + _timestamp_block("Updated")
        + "Result: Google Drive + Google Docs + Google Sheets integration works."
    )

    try:
        drive_service = _drive()
        doc = _find_file_by_name(drive_service, "AI_OS_SYSTEM_TEST", "application/vnd.google-apps.document")
        sheet = _change_log(drive_service)
        _append_to_existing_doc(doc["id"], content)
        _append_change_log_row(
            sheet["id"],
            "TEST_WRITE",
            doc["name"],
            "SUCCESS",
            "Document Agent v0.8.0 test write.",
            doc.get("webViewLink", ""),
        )
        return {
            "status": "success",
            "document_name": doc["name"],
            "document_url": doc.get("webViewLink"),
            "change_log_name": sheet["name"],
            "change_log_url": sheet.get("webViewLink"),
            "time_utc": _now_iso(),
            "time_local": _now_local_iso(),
            "timezone": AI_OS_TIMEZONE_NAME,
        }
    except HttpError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/append-note")
def append_note_get(
    request: Request,
    title: str = "AI_OS_NOTE",
    content: str = "Empty note",
    owner: str = DEFAULT_OWNER,
    related_to: Optional[str] = None,
):
    _check_token(request)
    return _append_note(title=title, content=content, owner=owner, related_to=related_to)


@app.post("/append-note")
async def append_note_post(request: Request, payload: WriteRequest):
    _check_token(request)
    return _append_note(
        payload.title or "AI_OS_NOTE",
        payload.content or "Empty note",
        payload.owner or DEFAULT_OWNER,
        payload.related_to,
    )


def _append_note(title: str, content: str, owner: str, related_to: Optional[str] = None):
    try:
        drive_service = _drive()
        inbox = _find_file_by_name(drive_service, "AI_OS_INBOX", "application/vnd.google-apps.document")
        sheet = _change_log(drive_service)

        object_id = _generate_object_id(drive_service, "NOTE", ["AI_OS_INBOX", "AI_OS_ENTITY_REGISTRY"])

        note_block = (
            "AI_OS_NOTE\n"
            + _metadata_block(object_id, "NOTE", owner, status="CAPTURED", priority="NORMAL")
            + f"Title: {title}\n\n"
            f"Content:\n{content}\n"
            "------------------------------------------------"
        )
        _append_to_existing_doc(inbox["id"], note_block)

        _append_entity_registry(
            drive_service, object_id, "NOTE", title, owner, "CAPTURED", "NORMAL",
            inbox["name"], inbox.get("webViewLink", "")
        )
        _create_owner_relation(drive_service, object_id, owner)
        if related_to:
            _append_relation(drive_service, related_to, "HAS_NOTE", object_id, title)

        _append_change_log_row(sheet["id"], "APPEND_NOTE", inbox["name"], "SUCCESS", f"{object_id} | {title}", inbox.get("webViewLink", ""))

        return _compact_success(
            object_id=object_id,
            object_type="NOTE",
            title=title,
            target_document=inbox["name"],
            action="APPEND_NOTE",
            extra={"owner": owner, "related_to": related_to},
        )
    except HttpError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/create-decision")
def create_decision_get(
    request: Request,
    title: str = "Untitled decision",
    decision: str = "No decision text provided.",
    owner: str = DEFAULT_OWNER,
    status: str = "APPROVED",
    priority: str = "MEDIUM",
    context: str = "",
    related_to: Optional[str] = None,
):
    _check_token(request)
    return _create_decision(title, decision, owner, status, priority, context, related_to)


@app.post("/create-decision")
async def create_decision_post(request: Request, payload: DecisionRequest):
    _check_token(request)
    return _create_decision(
        payload.title or "Untitled decision",
        payload.decision or "No decision text provided.",
        payload.owner or DEFAULT_OWNER,
        payload.status or "APPROVED",
        payload.priority or "MEDIUM",
        payload.context or "",
        payload.related_to,
    )


def _create_decision(title: str, decision: str, owner: str, status: str, priority: str, context: str, related_to: Optional[str] = None):
    try:
        drive_service = _drive()
        decision_log = _find_file_by_name(drive_service, "AI_OS_DECISION_LOG", "application/vnd.google-apps.document")
        sheet = _change_log(drive_service)

        normalized_status = (status or "APPROVED").upper()
        normalized_priority = (priority or "MEDIUM").upper()
        object_id = _generate_object_id(drive_service, "DECISION", ["AI_OS_DECISION_LOG", "AI_OS_ENTITY_REGISTRY"])

        decision_block = (
            "AI_OS_DECISION\n"
            + _metadata_block(object_id, "DECISION", owner, normalized_status, normalized_priority)
            + f"Title: {title}\n\n"
            f"Context:\n{context if context else 'No context provided.'}\n\n"
            f"Decision:\n{decision}\n"
            "------------------------------------------------"
        )
        _append_to_existing_doc(decision_log["id"], decision_block)

        _append_entity_registry(
            drive_service, object_id, "DECISION", title, owner, normalized_status, normalized_priority,
            decision_log["name"], decision_log.get("webViewLink", "")
        )
        _create_owner_relation(drive_service, object_id, owner)
        if related_to:
            _append_relation(drive_service, related_to, "HAS_DECISION", object_id, title)

        _append_change_log_row(sheet["id"], "CREATE_DECISION", decision_log["name"], "SUCCESS", f"{object_id} | {title}", decision_log.get("webViewLink", ""))

        return _compact_success(
            object_id=object_id,
            object_type="DECISION",
            title=title,
            target_document=decision_log["name"],
            action="CREATE_DECISION",
            extra={
                "status_value": normalized_status,
                "priority": normalized_priority,
                "owner": owner,
                "related_to": related_to,
            },
        )
    except HttpError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/create-project")
def create_project_get(
    request: Request,
    title: str = "Untitled_Project",
    owner: str = DEFAULT_OWNER,
    status: str = "ACTIVE",
    priority: str = "MEDIUM",
    description: str = "No description provided.",
    objectives: str = "No objectives provided.",
    deliverables: str = "No deliverables provided.",
    risks: str = "No risks provided.",
    next_actions: str = "No next actions provided.",
    related_to: Optional[str] = None,
):
    _check_token(request)
    return _create_project(title, owner, status, priority, description, objectives, deliverables, risks, next_actions, related_to)


@app.post("/create-project")
async def create_project_post(request: Request, payload: ProjectRequest):
    _check_token(request)
    return _create_project(
        payload.title or "Untitled_Project",
        payload.owner or DEFAULT_OWNER,
        payload.status or "ACTIVE",
        payload.priority or "MEDIUM",
        payload.description or "No description provided.",
        payload.objectives or "No objectives provided.",
        payload.deliverables or "No deliverables provided.",
        payload.risks or "No risks provided.",
        payload.next_actions or "No next actions provided.",
        payload.related_to,
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
    related_to: Optional[str] = None,
):
    try:
        drive_service = _drive()
        project_register = _project_register(drive_service)
        sheet = _change_log(drive_service)

        normalized_status = (status or "ACTIVE").upper()
        normalized_priority = (priority or "MEDIUM").upper()
        object_id = _generate_object_id(drive_service, "PROJECT", ["AI_OS_PROJECTS", "AI_OS_ENTITY_REGISTRY"])

        project_block = (
            "AI_OS_PROJECT\n"
            + _metadata_block(object_id, "PROJECT", owner, normalized_status, normalized_priority)
            + f"Project Name: {title}\n\n"
            f"Description:\n{description}\n\n"
            f"Objectives:\n{objectives}\n\n"
            f"Deliverables:\n{deliverables}\n\n"
            f"Risks:\n{risks}\n\n"
            f"Next Actions:\n{next_actions}\n"
            "------------------------------------------------"
        )

        _append_to_existing_doc(project_register["id"], project_block)

        _append_entity_registry(
            drive_service, object_id, "PROJECT", title, owner, normalized_status, normalized_priority,
            project_register["name"], project_register.get("webViewLink", "")
        )
        _create_owner_relation(drive_service, object_id, owner)
        if related_to:
            _append_relation(drive_service, related_to, "RELATES_TO", object_id, title)

        _append_change_log_row(sheet["id"], "CREATE_PROJECT", project_register["name"], "SUCCESS", f"{object_id} | {title} | {normalized_status} | {normalized_priority}", project_register.get("webViewLink", ""))

        return _compact_success(
            object_id=object_id,
            object_type="PROJECT",
            title=title,
            target_document=project_register["name"],
            action="CREATE_PROJECT",
            extra={
                "status_value": normalized_status,
                "priority": normalized_priority,
                "owner": owner,
                "related_to": related_to,
            },
        )
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
            "note": "v0.8.0 uses simple full-text search across selected Google Docs, not semantic/vector search yet.",
            "time_utc": _now_iso(),
            "time_local": _now_local_iso(),
            "timezone": AI_OS_TIMEZONE_NAME,
        }
    except HttpError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/find-by-id")
def find_by_id_get(request: Request, object_id: str):
    _check_token(request)
    return _find_by_id(object_id)


@app.post("/find-by-id")
async def find_by_id_post(request: Request, payload: FindByIdRequest):
    _check_token(request)
    return _find_by_id(payload.object_id)


def _find_by_id(object_id: str):
    if not object_id or not object_id.strip():
        raise HTTPException(status_code=400, detail="object_id is required.")

    object_id = object_id.strip().upper()
    object_type = _parse_object_type_from_id(object_id)

    candidate_docs = []
    if object_type:
        candidate_docs.append(OBJECT_DOCUMENT_MAP[object_type])
    candidate_docs.extend(["AI_OS_ENTITY_REGISTRY", "AI_OS_RELATIONS"])
    candidate_docs.extend([d for d in SEARCH_DOCUMENT_NAMES if d not in candidate_docs])

    try:
        drive_service = _drive()
        matches = []
        seen = set()

        for doc_name in candidate_docs:
            if doc_name in seen:
                continue
            seen.add(doc_name)

            file_info = _find_optional_doc_by_name(drive_service, doc_name)
            if not file_info:
                continue

            text = _extract_text_from_doc(file_info["id"])
            if object_id.lower() in text.lower():
                matches.append({
                    "document_name": file_info["name"],
                    "document_url": file_info.get("webViewLink", ""),
                    "snippet": _snippet(text, object_id, radius=320),
                })

        return {
            "status": "success",
            "object_id": object_id,
            "object_type": object_type or "UNKNOWN",
            "found": len(matches) > 0,
            "match_count": len(matches),
            "matches": matches,
            "time_utc": _now_iso(),
            "time_local": _now_local_iso(),
            "timezone": AI_OS_TIMEZONE_NAME,
        }
    except HttpError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/list-projects")
def list_projects_get(request: Request, limit: int = 20):
    _check_token(request)
    return _list_by_type("PROJECT", "AI_OS_PROJECTS", limit)


@app.get("/list-decisions")
def list_decisions_get(request: Request, limit: int = 20):
    _check_token(request)
    return _list_by_type("DECISION", "AI_OS_DECISION_LOG", limit)


@app.get("/list-notes")
def list_notes_get(request: Request, limit: int = 20):
    _check_token(request)
    return _list_by_type("NOTE", "AI_OS_INBOX", limit)


def _list_by_type(object_type: str, doc_name: str, limit: int = 20):
    try:
        drive_service = _drive()
        file_info = _find_optional_doc_by_name(drive_service, doc_name)
        if not file_info:
            raise HTTPException(status_code=404, detail=f"Document not found: {doc_name}")

        text = _extract_text_from_doc(file_info["id"])
        marker = f"TYPE: {object_type}"
        blocks = text.split("------------------------------------------------")
        results = []

        for block in reversed(blocks):
            if marker in block:
                object_id_match = re.search(r"\bID:\s*([A-Z]+-\d{8}-\d{4})", block)
                title_match = re.search(r"(?:Title|Project Name):\s*(.+)", block)
                results.append({
                    "object_id": object_id_match.group(1) if object_id_match else None,
                    "title": title_match.group(1).strip() if title_match else None,
                    "snippet": block.strip()[:900],
                })
                if len(results) >= limit:
                    break

        return {
            "status": "success",
            "object_type": object_type,
            "document_name": doc_name,
            "document_url": file_info.get("webViewLink", ""),
            "count": len(results),
            "items": results,
            "time_utc": _now_iso(),
            "time_local": _now_local_iso(),
            "timezone": AI_OS_TIMEZONE_NAME,
        }
    except HttpError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/create-entity")
def create_entity_get(
    request: Request,
    entity_type: str,
    title: str,
    description: str = "",
    owner: str = DEFAULT_OWNER,
    status: str = "ACTIVE",
    priority: str = "NORMAL",
    related_to: Optional[str] = None,
):
    _check_token(request)
    return _create_entity(entity_type, title, description, owner, status, priority, related_to)


@app.post("/create-entity")
async def create_entity_post(request: Request, payload: EntityRequest):
    _check_token(request)
    return _create_entity(
        payload.entity_type,
        payload.title,
        payload.description or "",
        payload.owner or DEFAULT_OWNER,
        payload.status or "ACTIVE",
        payload.priority or "NORMAL",
        payload.related_to,
    )


def _create_entity(
    entity_type: str,
    title: str,
    description: str = "",
    owner: str = DEFAULT_OWNER,
    status: str = "ACTIVE",
    priority: str = "NORMAL",
    related_to: Optional[str] = None,
):
    if not entity_type or not title:
        raise HTTPException(status_code=400, detail="entity_type and title are required.")

    normalized_type = entity_type.strip().upper()
    normalized_status = (status or "ACTIVE").upper()
    normalized_priority = (priority or "NORMAL").upper()

    try:
        drive_service = _drive()
        entity_registry = _entity_registry(drive_service)
        sheet = _change_log(drive_service)

        if not entity_registry:
            raise HTTPException(
                status_code=404,
                detail="AI_OS_ENTITY_REGISTRY document was not found in AI_OS root folder.",
            )

        object_id = _generate_object_id(drive_service, "ENTITY", ["AI_OS_ENTITY_REGISTRY"])

        entity_block = (
            "AI_OS_ENTITY\n"
            + _metadata_block(object_id, "ENTITY", owner, normalized_status, normalized_priority)
            + f"ENTITY_TYPE: {normalized_type}\n"
            f"TITLE: {title}\n"
            f"DESCRIPTION: {description}\n"
            "------------------------------------------------"
        )

        _append_to_existing_doc(entity_registry["id"], entity_block)
        _create_owner_relation(drive_service, object_id, owner)

        if related_to:
            _append_relation(drive_service, related_to.strip().upper(), "RELATED_TO_ENTITY", object_id, title)

        _append_change_log_row(
            sheet["id"],
            "CREATE_ENTITY",
            entity_registry["name"],
            "SUCCESS",
            f"{object_id} | {normalized_type} | {title}",
            entity_registry.get("webViewLink", ""),
        )

        return _compact_success(
            object_id=object_id,
            object_type="ENTITY",
            title=title,
            target_document=entity_registry["name"],
            action="CREATE_ENTITY",
            extra={
                "entity_type": normalized_type,
                "owner": owner,
                "status_value": normalized_status,
                "priority": normalized_priority,
                "related_to": related_to,
            },
        )
    except HttpError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/create-relation")
def create_relation_get(
    request: Request,
    source_id: str,
    relation_type: str,
    target_id: str,
    note: str = "",
):
    _check_token(request)
    return _create_relation(source_id, relation_type, target_id, note)


@app.post("/create-relation")
async def create_relation_post(request: Request, payload: RelationRequest):
    _check_token(request)
    return _create_relation(
        payload.source_id,
        payload.relation_type,
        payload.target_id,
        payload.note or "",
    )


def _create_relation(source_id: str, relation_type: str, target_id: str, note: str = ""):
    if not source_id or not relation_type or not target_id:
        raise HTTPException(status_code=400, detail="source_id, relation_type and target_id are required.")

    source_id = source_id.strip().upper()
    relation_type = relation_type.strip().upper()
    target_id = target_id.strip().upper()

    try:
        drive_service = _drive()
        relations = _relations_register(drive_service)
        sheet = _change_log(drive_service)

        if not relations:
            raise HTTPException(
                status_code=404,
                detail="AI_OS_RELATIONS document was not found in AI_OS root folder.",
            )

        relation_id = _generate_object_id(drive_service, "REL", ["AI_OS_RELATIONS"])

        block = (
            "AI_OS_RELATION\n"
            f"ID: {relation_id}\n"
            "TYPE: RELATION\n"
            f"SOURCE_ID: {source_id}\n"
            f"RELATION_TYPE: {relation_type}\n"
            f"TARGET_ID: {target_id}\n"
            f"NOTE: {note}\n"
            f"Created at: {_now_local_string()}\n"
            f"Timezone: {AI_OS_TIMEZONE_NAME}\n"
            f"UTC: {_now_iso()}\n"
            "------------------------------------------------"
        )

        _append_to_existing_doc(relations["id"], block)

        _append_change_log_row(
            sheet["id"],
            "CREATE_RELATION",
            "AI_OS_RELATIONS",
            "SUCCESS",
            f"{relation_id} | {source_id} | {relation_type} | {target_id}",
            "",
        )

        return {
            "status": "success",
            "action": "CREATE_RELATION",
            "relation_id": relation_id,
            "source_id": source_id,
            "relation_type": relation_type,
            "target_id": target_id,
            "time_utc": _now_iso(),
            "time_local": _now_local_iso(),
        }
    except HttpError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/get-relations")
def get_relations_get(request: Request, object_id: str):
    _check_token(request)
    return _get_relations(object_id)


@app.post("/get-relations")
async def get_relations_post(request: Request, payload: GetRelationsRequest):
    _check_token(request)
    return _get_relations(payload.object_id)


def _get_relations(object_id: str):
    if not object_id or not object_id.strip():
        raise HTTPException(status_code=400, detail="object_id is required.")

    object_id = object_id.strip().upper()

    try:
        drive_service = _drive()
        relations_doc = _relations_register(drive_service)
        if not relations_doc:
            raise HTTPException(
                status_code=404,
                detail="AI_OS_RELATIONS document was not found in AI_OS root folder.",
            )

        text = _extract_text_from_doc(relations_doc["id"])
        blocks = text.split("------------------------------------------------")

        outgoing = []
        incoming = []

        for block in blocks:
            source_match = re.search(r"(?:SOURCE_ID|Source ID):\s*([A-Z]+-\d{8}-\d{4}|OWNER-[A-Z0-9_]+)", block, re.IGNORECASE)
            relation_match = re.search(r"(?:RELATION_TYPE|Relation Type):\s*([A-Z0-9_]+)", block, re.IGNORECASE)
            target_match = re.search(r"(?:TARGET_ID|Target ID):\s*([A-Z]+-\d{8}-\d{4}|OWNER-[A-Z0-9_]+)", block, re.IGNORECASE)
            relation_id_match = re.search(r"\bID:\s*(REL-\d{8}-\d{4})", block)
            note_match = re.search(r"Note:\s*(.*)", block)

            if not source_match or not relation_match or not target_match:
                continue

            item = {
                "relation_id": relation_id_match.group(1) if relation_id_match else None,
                "source_id": source_match.group(1).upper(),
                "relation_type": relation_match.group(1).upper(),
                "target_id": target_match.group(1).upper(),
                "note": note_match.group(1).strip()[:160] if note_match else "",
            }

            if item["source_id"] == object_id:
                outgoing.append(item)
            if item["target_id"] == object_id:
                incoming.append(item)

        return {
            "status": "success",
            "object_id": object_id,
            "outgoing_count": len(outgoing),
            "incoming_count": len(incoming),
            "outgoing": outgoing[:20],
            "incoming": incoming[:20],
            "relations_document": relations_doc["name"],
            "relations_document_url": relations_doc.get("webViewLink", ""),
            "time_utc": _now_iso(),
            "time_local": _now_local_iso(),
            "timezone": AI_OS_TIMEZONE_NAME,
        }
    except HttpError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/get-object")
def get_object_get(request: Request, object_id: str):
    _check_token(request)
    return _get_object(object_id)


@app.post("/get-object")
async def get_object_post(request: Request, payload: FindByIdRequest):
    _check_token(request)
    return _get_object(payload.object_id)


def _get_object(object_id: str):
    found = _find_by_id(object_id)
    if not found.get("found"):
        return found

    relations = _get_relations(object_id)
    return {
        "status": "success",
        "object_id": found.get("object_id"),
        "object_type": found.get("object_type"),
        "found": True,
        "matches": found.get("matches", [])[:3],
        "relations": {
            "outgoing": relations.get("outgoing", [])[:20],
            "incoming": relations.get("incoming", [])[:20],
            "outgoing_count": relations.get("outgoing_count", 0),
            "incoming_count": relations.get("incoming_count", 0),
        },
        "time_utc": _now_iso(),
        "time_local": _now_local_iso(),
        "timezone": AI_OS_TIMEZONE_NAME,
    }


def _parse_relation_blocks(text: str) -> List[Dict[str, Any]]:
    relations: List[Dict[str, Any]] = []
    blocks = text.split("------------------------------------------------")

    for block in blocks:
        source_match = re.search(r"(?:SOURCE_ID|Source ID):\s*([A-Z]+-\d{8}-\d{4}|OWNER-[A-Z0-9_]+)", block, re.IGNORECASE)
        relation_match = re.search(r"(?:RELATION_TYPE|Relation Type):\s*([A-Z0-9_]+)", block, re.IGNORECASE)
        target_match = re.search(r"(?:TARGET_ID|Target ID):\s*([A-Z]+-\d{8}-\d{4}|OWNER-[A-Z0-9_]+)", block, re.IGNORECASE)
        relation_id_match = re.search(r"\b(?:ID|relation_id):\s*(REL-\d{8}-\d{4}|NOTE-\d{8}-\d{4})", block, re.IGNORECASE)
        note_match = re.search(r"(?:NOTE|Note|Poznámka):\s*(.*)", block)

        if not source_match or not relation_match or not target_match:
            continue

        relations.append({
            "relation_id": relation_id_match.group(1).upper() if relation_id_match else None,
            "source_id": source_match.group(1).upper(),
            "relation_type": relation_match.group(1).upper(),
            "target_id": target_match.group(1).upper(),
            "note": note_match.group(1).strip()[:180] if note_match else "",
        })

    return relations


def _entity_title_from_block(block: str) -> Optional[str]:
    patterns = [
        r"\bTITLE:\s*(.+)",
        r"\bTitle:\s*(.+)",
        r"\bNázov:\s*(.+)",
        r"\bNazov:\s*(.+)",
        r"\bName:\s*(.+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, block)
        if match:
            return match.group(1).strip()
    return None


def _entity_type_from_block(block: str) -> Optional[str]:
    patterns = [
        r"\bENTITY_TYPE:\s*(.+)",
        r"\bTyp:\s*(.+)",
        r"\bTYPE:\s*(ENTITY|PERSON|COMPANY|BRAND|SYSTEM|PRODUCT|PROJECT|NOTE|DECISION)",
    ]
    for pattern in patterns:
        match = re.search(pattern, block, re.IGNORECASE)
        if match:
            return match.group(1).strip().upper()
    return None


def _object_id_from_block(block: str) -> Optional[str]:
    match = re.search(r"\b(?:ID|object_id):\s*([A-Z]+-\d{8}-\d{4})", block, re.IGNORECASE)
    if match:
        return match.group(1).upper()
    return None


def _compact_entity_matches_from_text(text: str, query: str, limit: int = 10) -> List[Dict[str, Any]]:
    q = query.lower().strip()
    blocks = text.split("------------------------------------------------")
    matches = []

    for block in reversed(blocks):
        if not block.strip():
            continue
        if q not in block.lower():
            continue

        object_id = _object_id_from_block(block)
        title = _entity_title_from_block(block)
        entity_type = _entity_type_from_block(block)

        matches.append({
            "object_id": object_id,
            "title": title,
            "entity_type": entity_type,
            "snippet": block.strip().replace("\n", " ")[:500],
        })

        if len(matches) >= limit:
            break

    return matches


@app.get("/find-entity")
def find_entity_get(request: Request, query: str, limit: int = 10):
    _check_token(request)
    return _find_entity(query, limit)


@app.post("/find-entity")
async def find_entity_post(request: Request, payload: FindEntityRequest):
    _check_token(request)
    return _find_entity(payload.query, payload.limit or 10)


def _find_entity(query: str, limit: int = 10):
    if not query or not query.strip():
        raise HTTPException(status_code=400, detail="query is required.")

    try:
        drive_service = _drive()
        entity_registry = _entity_registry(drive_service)
        if not entity_registry:
            raise HTTPException(
                status_code=404,
                detail="AI_OS_ENTITY_REGISTRY document was not found in AI_OS root folder.",
            )

        text = _extract_text_from_doc(entity_registry["id"])
        matches = _compact_entity_matches_from_text(text, query, limit)

        return {
            "status": "success",
            "action": "FIND_ENTITY",
            "query": query,
            "found": len(matches) > 0,
            "count": len(matches),
            "matches": matches,
            "time_utc": _now_iso(),
            "time_local": _now_local_iso(),
        }
    except HttpError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/find-related")
def find_related_get(
    request: Request,
    object_id: str,
    relation_type: Optional[str] = None,
    direction: str = "both",
    limit: int = 20,
):
    _check_token(request)
    return _find_related(object_id, relation_type, direction, limit)


@app.post("/find-related")
async def find_related_post(request: Request, payload: FindRelatedRequest):
    _check_token(request)
    return _find_related(
        payload.object_id,
        payload.relation_type,
        payload.direction or "both",
        payload.limit or 20,
    )


def _find_related(
    object_id: str,
    relation_type: Optional[str] = None,
    direction: str = "both",
    limit: int = 20,
):
    if not object_id or not object_id.strip():
        raise HTTPException(status_code=400, detail="object_id is required.")

    object_id = object_id.strip().upper()
    relation_filter = relation_type.strip().upper() if relation_type else None
    direction = (direction or "both").strip().lower()

    try:
        drive_service = _drive()
        relations_doc = _relations_register(drive_service)
        if not relations_doc:
            raise HTTPException(
                status_code=404,
                detail="AI_OS_RELATIONS document was not found in AI_OS root folder.",
            )

        text = _extract_text_from_doc(relations_doc["id"])
        all_relations = _parse_relation_blocks(text)

        outgoing = []
        incoming = []

        for rel in all_relations:
            if relation_filter and rel["relation_type"] != relation_filter:
                continue

            if rel["source_id"] == object_id and direction in ("both", "outgoing", "out"):
                outgoing.append(rel)
            if rel["target_id"] == object_id and direction in ("both", "incoming", "in"):
                incoming.append(rel)

        outgoing = outgoing[:limit]
        incoming = incoming[:limit]

        return {
            "status": "success",
            "action": "FIND_RELATED",
            "object_id": object_id,
            "relation_type_filter": relation_filter,
            "direction": direction,
            "outgoing_count": len(outgoing),
            "incoming_count": len(incoming),
            "outgoing": outgoing,
            "incoming": incoming,
            "time_utc": _now_iso(),
            "time_local": _now_local_iso(),
        }
    except HttpError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/graph-summary")
def graph_summary_get(request: Request):
    _check_token(request)
    return _graph_summary()


def _graph_summary():
    try:
        drive_service = _drive()
        entity_registry = _entity_registry(drive_service)
        relations_doc = _relations_register(drive_service)

        entity_count = 0
        relation_count = 0

        if entity_registry:
            entity_text = _extract_text_from_doc(entity_registry["id"])
            entity_count = len(re.findall(r"\bID:\s*ENTITY-\d{8}-\d{4}", entity_text))

        if relations_doc:
            relation_text = _extract_text_from_doc(relations_doc["id"])
            relation_count = len(_parse_relation_blocks(relation_text))

        return {
            "status": "success",
            "action": "GRAPH_SUMMARY",
            "entity_count": entity_count,
            "relation_count": relation_count,
            "entity_registry": "AI_OS_ENTITY_REGISTRY" if entity_registry else "missing",
            "relations_registry": "AI_OS_RELATIONS" if relations_doc else "missing",
            "time_utc": _now_iso(),
            "time_local": _now_local_iso(),
        }
    except HttpError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
