import base64
import datetime as dt
import hashlib
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


APP_NAME = "AI_OS_DOCUMENT_AGENT_V1_0_1_FAST_INDEX"
PUBLIC_BASE_URL = "https://ai-os-document-agent.onrender.com"
AI_OS_TIMEZONE_NAME = "Europe/Bratislava"
AI_OS_TIMEZONE = ZoneInfo(AI_OS_TIMEZONE_NAME)
DEFAULT_OWNER = "Daniel Valušiak"

# Fast in-memory knowledge index.
# Source of truth remains Google Drive; this cache only prevents /search from reading
# hundreds of Google Docs on every request, which caused Render 503 timeouts.
AI_OS_INDEX: Dict[str, Any] = {
    "status": "empty",
    "created_utc": None,
    "document_count": 0,
    "documents": [],
    "errors": [],
}

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/spreadsheets",
]

app = FastAPI(
    title=APP_NAME,
    version="1.0.1",
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


class DocumentRequest(BaseModel):
    title: str
    object_type: str
    document_category: str
    project_id: str
    status: Optional[str] = "APPROVED"
    owner: Optional[str] = DEFAULT_OWNER
    version: Optional[str] = "1.0"
    content: Optional[str] = None
    source_object_id: Optional[str] = None
    related_objects: Optional[List[str]] = None


class UpdateDocumentRequest(BaseModel):
    title: Optional[str] = None
    object_type: Optional[str] = None
    document_category: Optional[str] = None
    project_id: Optional[str] = None
    status: Optional[str] = None
    owner: Optional[str] = None
    version: Optional[str] = None
    content: Optional[str] = None
    source_object_id: Optional[str] = None
    related_objects: Optional[List[str]] = None


class ProjectHubRequest(BaseModel):
    project_id: str
    title: Optional[str] = None
    owner: Optional[str] = DEFAULT_OWNER
    status: Optional[str] = "ACTIVE"
    overview: Optional[str] = None



SEARCH_DOCUMENT_NAMES = [
    "AI_OS_DOCUMENT_REGISTRY",
    "AI_OS_PROJECT_HUBS",
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
    "DOCUMENT": "AI_OS_DOCUMENT_REGISTRY",
    "HUB": "AI_OS_PROJECT_HUBS",
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


def _list_children(drive_service, folder_id: str, mime_type: Optional[str] = None) -> List[dict]:
    """Return direct children of one Google Drive folder. Supports shared-drive flags."""
    q_parts = [
        f"'{_safe_query_string(folder_id)}' in parents",
        "trashed=false",
    ]
    if mime_type:
        q_parts.append(f"mimeType='{mime_type}'")

    items: List[dict] = []
    page_token = None
    while True:
        result = drive_service.files().list(
            q=" and ".join(q_parts),
            fields="nextPageToken, files(id,name,mimeType,webViewLink,parents)",
            pageSize=100,
            pageToken=page_token,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute()
        items.extend(result.get("files", []))
        page_token = result.get("nextPageToken")
        if not page_token:
            break
    return items


def _list_ai_os_google_docs_recursive(drive_service, max_documents: int = 500) -> List[dict]:
    """Return all Google Docs under AI_OS root folder, including subfolders.

    This replaces the old fixed SEARCH_DOCUMENT_NAMES search path for /search.
    It keeps Google Drive as the source of truth: every Google document inside
    the AI_OS folder tree becomes searchable without manually editing a list.
    """
    root_id = _root_folder_id()
    folders_to_scan = [root_id]
    scanned_folders = set()
    documents: List[dict] = []

    while folders_to_scan and len(documents) < max_documents:
        folder_id = folders_to_scan.pop(0)
        if folder_id in scanned_folders:
            continue
        scanned_folders.add(folder_id)

        children = _list_children(drive_service, folder_id)
        for item in children:
            mime_type = item.get("mimeType")
            if mime_type == "application/vnd.google-apps.folder":
                folders_to_scan.append(item["id"])
            elif mime_type == "application/vnd.google-apps.document":
                documents.append(item)
                if len(documents) >= max_documents:
                    break

    return documents


def _normalize_search_text(value: str) -> str:
    return (value or "").lower().strip()


def _build_ai_os_knowledge_index(
    drive_service,
    max_documents: int = 500,
    max_chars_per_document: int = 0,
) -> Dict[str, Any]:
    """Build a fast metadata index from Google Docs under AI_OS.

    v1.0.1 change:
    - /refresh-index no longer opens and reads every Google Doc.
    - It indexes metadata only: name, id, url, parents.
    - This prevents Render 502/503 timeouts on large AI_OS folders.
    - /search uses this metadata index for fast name search and Google Drive
      server-side fullText search for content search.
    """
    safe_limit = max(1, min(int(max_documents or 500), 2000))

    docs = _list_ai_os_google_docs_recursive(drive_service, max_documents=safe_limit)
    indexed_documents: List[Dict[str, Any]] = []

    for item in docs:
        indexed_documents.append({
            "name": item.get("name", ""),
            "id": item.get("id"),
            "url": item.get("webViewLink", ""),
            "parents": item.get("parents", []),
            "content_status": "metadata_only",
            "text_length": 0,
            "indexed_text": "",
        })

    index = {
        "status": "ready",
        "created_utc": _now_iso(),
        "created_local": _now_local_iso(),
        "document_count": len(indexed_documents),
        "max_documents": safe_limit,
        "max_chars_per_document": 0,
        "documents": indexed_documents,
        "errors": [],
    }
    AI_OS_INDEX.clear()
    AI_OS_INDEX.update(index)
    return index

def _compact_index_document(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "name": item.get("name"),
        "id": item.get("id"),
        "url": item.get("url"),
        "parents": item.get("parents", []),
        "content_status": item.get("content_status"),
        "text_length": item.get("text_length", 0),
    }


def _search_in_knowledge_index(query: str, limit: int = 10) -> Dict[str, Any]:
    safe_limit = max(1, min(int(limit or 10), 50))
    q = _normalize_search_text(query)
    if not q:
        raise HTTPException(status_code=400, detail="Query is required.")

    if AI_OS_INDEX.get("status") != "ready":
        return {
            "status": "success",
            "query": query,
            "found": False,
            "match_count": 0,
            "matches": [],
            "index_status": AI_OS_INDEX.get("status", "empty"),
            "requires_refresh_index": True,
            "note": "Knowledge index is empty. Run /refresh-index first, then repeat /search.",
            "time_utc": _now_iso(),
            "time_local": _now_local_iso(),
            "timezone": AI_OS_TIMEZONE_NAME,
        }

    matches: List[Dict[str, Any]] = []
    seen_ids = set()
    indexed_docs = AI_OS_INDEX.get("documents", [])
    indexed_ids = {item.get("id") for item in indexed_docs if item.get("id")}

    # 1) Fast local search by document name from the AI_OS metadata index.
    for item in indexed_docs:
        name = item.get("name", "")
        if q in _normalize_search_text(name):
            doc_id = item.get("id")
            seen_ids.add(doc_id)
            matches.append({
                "document_name": name,
                "document_id": doc_id,
                "document_url": item.get("url", ""),
                "match_type": "name",
                "snippet": name,
                "text_length": 0,
            })
            if len(matches) >= safe_limit:
                break

    # 2) If needed, use Google Drive server-side fullText search.
    # This avoids opening hundreds of documents from Python/Render.
    if len(matches) < safe_limit:
        try:
            drive_service = _drive()
            escaped_query = _safe_query_string(query.strip())
            drive_q = (
                "mimeType='application/vnd.google-apps.document' and "
                "trashed=false and "
                f"(name contains '{escaped_query}' or fullText contains '{escaped_query}')"
            )
            result = drive_service.files().list(
                q=drive_q,
                fields="files(id,name,mimeType,webViewLink,parents)",
                pageSize=min(100, safe_limit * 5),
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            ).execute()

            for file_info in result.get("files", []):
                doc_id = file_info.get("id")
                if doc_id in seen_ids:
                    continue
                # Keep results inside the AI_OS tree only. The metadata index is the boundary.
                if indexed_ids and doc_id not in indexed_ids:
                    continue
                seen_ids.add(doc_id)
                matches.append({
                    "document_name": file_info.get("name"),
                    "document_id": doc_id,
                    "document_url": file_info.get("webViewLink", ""),
                    "match_type": "drive_fulltext_or_name",
                    "snippet": "Nájdené cez Google Drive serverové vyhľadávanie. Detailný text otvor cez document_id alebo Google URL.",
                    "text_length": 0,
                })
                if len(matches) >= safe_limit:
                    break
        except Exception as exc:
            # Search should not crash the agent if Drive fullText has a temporary problem.
            drive_search_error = str(exc)[:500]
        else:
            drive_search_error = None
    else:
        drive_search_error = None

    return {
        "status": "success",
        "query": query,
        "found": len(matches) > 0,
        "match_count": len(matches),
        "matches": matches,
        "index_status": AI_OS_INDEX.get("status"),
        "index_created_utc": AI_OS_INDEX.get("created_utc"),
        "indexed_document_count": AI_OS_INDEX.get("document_count", 0),
        "searched_document_count": len(indexed_docs),
        "index_error_count": len(AI_OS_INDEX.get("errors", [])),
        "drive_search_error": drive_search_error,
        "note": "v1.0.1 searches the fast AI_OS metadata index by name and uses Google Drive fullText search for content without reading every document live.",
        "time_utc": _now_iso(),
        "time_local": _now_local_iso(),
        "timezone": AI_OS_TIMEZONE_NAME,
    }

def _get_or_create_doc_by_name(drive_service, name: str, initial_text: Optional[str] = None) -> dict:
    existing = _find_optional_doc_by_name(drive_service, name)
    if existing:
        return existing

    metadata = {
        "name": name,
        "mimeType": "application/vnd.google-apps.document",
        "parents": [_root_folder_id()],
    }
    created = drive_service.files().create(
        body=metadata,
        fields="id,name,mimeType,webViewLink,parents",
        supportsAllDrives=True,
    ).execute()

    intro = initial_text or (
        f"{name}\n"
        f"Created by: {APP_NAME}\n"
        + _timestamp_block("Created")
        + "------------------------------------------------"
    )
    _append_to_existing_doc(created["id"], intro)
    return created



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



def _document_registry(drive_service) -> dict:
    return _get_or_create_doc_by_name(drive_service, "AI_OS_DOCUMENT_REGISTRY")


def _project_hubs_registry(drive_service) -> dict:
    return _get_or_create_doc_by_name(drive_service, "AI_OS_PROJECT_HUBS")


def _content_hash(content: str) -> str:
    normalized = (content or "").strip().encode("utf-8")
    return hashlib.sha256(normalized).hexdigest()


def _object_url(kind: str, object_id: str) -> str:
    kind = (kind or "object").strip("/").lower()

    # Compatibility fix:
    # The API endpoint is /documents/{document_id}, not /document/{document_id}.
    # Older records may still contain /document/... links, therefore we also keep
    # a /document/{document_id} alias endpoint below.
    if kind == "document":
        kind = "documents"

    if kind == "hub":
        kind = "project-hubs"

    return f"{PUBLIC_BASE_URL}/{kind}/{object_id}"



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
        "message": "AI OS Document Agent v1.0.1 is online. Fast AI_OS metadata index and Drive search are enabled.",
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
            "Document Agent v0.8.2 test write.",
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


@app.get("/list-ai-os-documents")
def list_ai_os_documents_get(request: Request, limit: int = 500):
    _check_token(request)
    try:
        drive_service = _drive()
        safe_limit = max(1, min(int(limit or 500), 1000))
        docs = _list_ai_os_google_docs_recursive(drive_service, max_documents=safe_limit)
        return {
            "status": "success",
            "action": "LIST_AI_OS_DOCUMENTS",
            "count": len(docs),
            "documents": [
                {
                    "name": item.get("name"),
                    "id": item.get("id"),
                    "url": item.get("webViewLink", ""),
                    "parents": item.get("parents", []),
                }
                for item in docs
            ],
            "note": "Lists Google Docs under AI_OS root folder, including subfolders. This endpoint does not read document content.",
            "time_utc": _now_iso(),
            "time_local": _now_local_iso(),
            "timezone": AI_OS_TIMEZONE_NAME,
        }
    except HttpError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/refresh-index")
def refresh_index_get(request: Request, limit: int = 500, max_chars: int = 0):
    _check_token(request)
    try:
        drive_service = _drive()
        index = _build_ai_os_knowledge_index(
            drive_service,
            max_documents=limit,
            max_chars_per_document=max_chars,
        )
        return {
            "status": "success",
            "action": "REFRESH_INDEX",
            "index_status": index.get("status"),
            "document_count": index.get("document_count", 0),
            "error_count": len(index.get("errors", [])),
            "created_utc": index.get("created_utc"),
            "created_local": index.get("created_local"),
            "max_documents": index.get("max_documents"),
            "max_chars_per_document": index.get("max_chars_per_document"),
            "sample_documents": [_compact_index_document(item) for item in index.get("documents", [])[:20]],
            "errors": index.get("errors", [])[:20],
            "note": "Fast metadata index is ready. /search will use document names from the index and Google Drive server-side fullText search for content.",
            "time_utc": _now_iso(),
            "time_local": _now_local_iso(),
            "timezone": AI_OS_TIMEZONE_NAME,
        }
    except HttpError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/index-status")
def index_status_get(request: Request):
    _check_token(request)
    return {
        "status": "success",
        "index_status": AI_OS_INDEX.get("status", "empty"),
        "created_utc": AI_OS_INDEX.get("created_utc"),
        "document_count": AI_OS_INDEX.get("document_count", 0),
        "error_count": len(AI_OS_INDEX.get("errors", [])),
        "sample_documents": [_compact_index_document(item) for item in AI_OS_INDEX.get("documents", [])[:10]],
        "time_utc": _now_iso(),
        "time_local": _now_local_iso(),
        "timezone": AI_OS_TIMEZONE_NAME,
    }


@app.get("/search")
def search_get(request: Request, query: str, limit: int = 10):
    _check_token(request)
    return _search_ai_os(query=query, limit=limit)


@app.post("/search")
async def search_post(request: Request, payload: SearchRequest):
    _check_token(request)
    return _search_ai_os(query=payload.query, limit=payload.limit or 10)


def _search_ai_os(query: str, limit: int = 10):
    return _search_in_knowledge_index(query=query, limit=limit)


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
    limit: int = 5,
):
    if not object_id or not object_id.strip():
        raise HTTPException(status_code=400, detail="object_id is required.")

    object_id = object_id.strip().upper()
    relation_filter = relation_type.strip().upper() if relation_type else None
    direction = (direction or "both").strip().lower()
    limit = max(1, min(int(limit or 5), 5))

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

        compact_relations = []
        total_matches = 0

        for rel in all_relations:
            if relation_filter and rel["relation_type"] != relation_filter:
                continue

            is_outgoing = rel["source_id"] == object_id
            is_incoming = rel["target_id"] == object_id

            if not is_outgoing and not is_incoming:
                continue

            if direction in ("outgoing", "out") and not is_outgoing:
                continue
            if direction in ("incoming", "in") and not is_incoming:
                continue

            total_matches += 1

            if len(compact_relations) >= limit:
                continue

            compact_relations.append({
                "relation_id": rel.get("relation_id"),
                "direction": "outgoing" if is_outgoing else "incoming",
                "type": rel["relation_type"],
                "source": rel["source_id"],
                "target": rel["target_id"],
            })

        return {
            "status": "success",
            "action": "FIND_RELATED_COMPACT",
            "object_id": object_id,
            "total_matches": total_matches,
            "returned": len(compact_relations),
            "relations": compact_relations,
        }
    except HttpError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/find-related-compact")
def find_related_compact_get(
    request: Request,
    object_id: str,
    relation_type: Optional[str] = None,
    direction: str = "both",
    limit: int = 5,
):
    _check_token(request)
    return _find_related(object_id, relation_type, direction, limit)


@app.post("/find-related-compact")
async def find_related_compact_post(request: Request, payload: FindRelatedRequest):
    _check_token(request)
    return _find_related(
        payload.object_id,
        payload.relation_type,
        payload.direction or "both",
        payload.limit or 5,
    )


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



# -----------------------------------------------------------------------------
# AI_OS Knowledge Persistence Layer v0.9.1
# -----------------------------------------------------------------------------

DOCUMENT_CATEGORY_VALUES = {
    "ANALYSIS",
    "AUDIT",
    "FORMULA",
    "DECISION_SUPPORT",
    "RFQ",
    "MANUFACTURING",
    "LEGAL",
    "RESEARCH",
    "PROJECT",
    "OTHER",
}


def _normalize_document_category(value: str) -> str:
    category = (value or "OTHER").strip().upper()
    return category if category in DOCUMENT_CATEGORY_VALUES else "OTHER"


def _parse_blocks_by_marker(text: str, marker: str) -> List[str]:
    blocks = text.split("------------------------------------------------")
    return [block.strip() for block in blocks if marker in block]


def _extract_field(block: str, field: str) -> Optional[str]:
    match = re.search(rf"^\s*{re.escape(field)}:\s*(.*)$", block, re.IGNORECASE | re.MULTILINE)
    return match.group(1).strip() if match else None


def _block_to_document_record(block: str) -> Dict[str, Any]:
    return {
        "document_id": _extract_field(block, "DOCUMENT_ID") or _extract_field(block, "ID"),
        "title": _extract_field(block, "TITLE"),
        "object_type": _extract_field(block, "OBJECT_TYPE"),
        "document_category": _extract_field(block, "DOCUMENT_CATEGORY"),
        "project_id": _extract_field(block, "PROJECT_ID"),
        "status": _extract_field(block, "STATUS"),
        "owner": _extract_field(block, "OWNER"),
        "version": _extract_field(block, "VERSION"),
        "url": _extract_field(block, "URL"),
        "content_hash": _extract_field(block, "CONTENT_HASH"),
        "source_object_id": _extract_field(block, "SOURCE_OBJECT_ID"),
        "related_objects": _extract_field(block, "RELATED_OBJECTS"),
        "created_at": _extract_field(block, "CREATED_AT"),
        "updated_at": _extract_field(block, "UPDATED_AT"),
        "snippet": block[:1200],
    }


def _document_exists_by_hash(drive_service, content_hash: str) -> Optional[Dict[str, Any]]:
    registry = _document_registry(drive_service)
    text = _extract_text_from_doc(registry["id"])
    for block in _parse_blocks_by_marker(text, "AI_OS_DOCUMENT"):
        if f"CONTENT_HASH: {content_hash}" in block:
            return _block_to_document_record(block)
    return None


def _append_document_registry(
    drive_service,
    document_id: str,
    title: str,
    object_type: str,
    document_category: str,
    project_id: str,
    status: str,
    owner: str,
    version: str,
    url: str,
    content_hash: str,
    source_object_id: str,
    related_objects: List[str],
    content: str,
) -> None:
    registry = _document_registry(drive_service)
    now = _now_iso()
    related_json = json.dumps(related_objects or [], ensure_ascii=False)
    block = (
        "AI_OS_DOCUMENT\n"
        f"DOCUMENT_ID: {document_id}\n"
        f"TITLE: {title}\n"
        f"OBJECT_TYPE: {object_type}\n"
        f"DOCUMENT_CATEGORY: {document_category}\n"
        f"PROJECT_ID: {project_id}\n"
        f"STATUS: {status}\n"
        f"OWNER: {owner}\n"
        f"VERSION: {version}\n"
        f"URL: {url}\n"
        f"CONTENT_HASH: {content_hash}\n"
        f"SOURCE_OBJECT_ID: {source_object_id or ''}\n"
        f"RELATED_OBJECTS: {related_json}\n"
        f"CREATED_AT: {now}\n"
        f"UPDATED_AT: {now}\n"
        "CONTENT:\n"
        f"{content or ''}\n"
        "------------------------------------------------"
    )
    _append_to_existing_doc(registry["id"], block)


def _create_document(payload: DocumentRequest) -> Dict[str, Any]:
    if not payload.title or not payload.object_type or not payload.project_id:
        raise HTTPException(status_code=400, detail="title, object_type and project_id are required.")

    drive_service = _drive()
    sheet = _change_log(drive_service)

    title = payload.title.strip()
    object_type = payload.object_type.strip().upper()
    category = _normalize_document_category(payload.document_category)
    project_id = payload.project_id.strip().upper()
    status = (payload.status or "APPROVED").strip().upper()
    owner = payload.owner or DEFAULT_OWNER
    version = payload.version or "1.0"
    content = payload.content or ""
    source_object_id = (payload.source_object_id or project_id).strip().upper()
    related_objects = [x.strip().upper() for x in (payload.related_objects or []) if x and x.strip()]

    hash_input = json.dumps({
        "title": title,
        "object_type": object_type,
        "document_category": category,
        "project_id": project_id,
        "version": version,
        "content": content,
    }, ensure_ascii=False, sort_keys=True)
    content_hash = _content_hash(hash_input)

    existing = _document_exists_by_hash(drive_service, content_hash)
    if existing:
        return {
            "status": "success",
            "action": "CREATE_DOCUMENT",
            "deduplicated": True,
            "document": existing,
            "note": "Document with identical CONTENT_HASH already exists. No duplicate created.",
            "time_utc": _now_iso(),
            "time_local": _now_local_iso(),
        }

    document_id = _generate_object_id(drive_service, "DOC", ["AI_OS_DOCUMENT_REGISTRY"])
    url = _object_url("document", document_id)

    _append_document_registry(
        drive_service=drive_service,
        document_id=document_id,
        title=title,
        object_type=object_type,
        document_category=category,
        project_id=project_id,
        status=status,
        owner=owner,
        version=version,
        url=url,
        content_hash=content_hash,
        source_object_id=source_object_id,
        related_objects=related_objects,
        content=content,
    )

    _append_relation(drive_service, document_id, "BELONGS_TO", project_id, title)
    for related in related_objects:
        _append_relation(drive_service, document_id, "REFERENCES", related, title)

    registry = _document_registry(drive_service)
    _append_change_log_row(
        sheet["id"],
        "CREATE_DOCUMENT",
        registry["name"],
        "SUCCESS",
        f"{document_id} | {title} | {project_id}",
        registry.get("webViewLink", ""),
    )

    return {
        "status": "success",
        "action": "CREATE_DOCUMENT",
        "document_id": document_id,
        "title": title,
        "object_type": object_type,
        "document_category": category,
        "project_id": project_id,
        "url": url,
        "registry_url": registry.get("webViewLink", ""),
        "content_hash": content_hash,
        "time_utc": _now_iso(),
        "time_local": _now_local_iso(),
    }


@app.post("/documents")
async def create_document_post(request: Request, payload: DocumentRequest):
    _check_token(request)
    try:
        return _create_document(payload)
    except HttpError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/documents/{document_id}")
def get_document_get(request: Request, document_id: str):
    _check_token(request)
    return _get_document(document_id)


# Backward-compatible alias for URLs already stored as /document/DOC-...
@app.get("/document/{document_id}")
def get_document_alias_get(request: Request, document_id: str):
    _check_token(request)
    return _get_document(document_id)


def _get_document(document_id: str) -> Dict[str, Any]:
    if not document_id:
        raise HTTPException(status_code=400, detail="document_id is required.")
    document_id = document_id.strip().upper()
    try:
        drive_service = _drive()
        registry = _document_registry(drive_service)
        text = _extract_text_from_doc(registry["id"])
        matches = []
        for block in _parse_blocks_by_marker(text, "AI_OS_DOCUMENT"):
            if re.search(rf"^\s*DOCUMENT_ID:\s*{re.escape(document_id)}\s*$", block, re.IGNORECASE | re.MULTILINE):
                matches.append(_block_to_document_record(block))
        return {
            "status": "success",
            "document_id": document_id,
            "found": len(matches) > 0,
            "version_count": len(matches),
            "versions": matches,
            "registry_url": registry.get("webViewLink", ""),
            "time_utc": _now_iso(),
            "time_local": _now_local_iso(),
        }
    except HttpError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.put("/documents/{document_id}")
async def update_document_put(request: Request, document_id: str, payload: UpdateDocumentRequest):
    _check_token(request)
    return _update_document(document_id, payload)


def _update_document(document_id: str, payload: UpdateDocumentRequest) -> Dict[str, Any]:
    current = _get_document(document_id)
    if not current.get("found"):
        raise HTTPException(status_code=404, detail=f"Document not found: {document_id}")
    latest = current["versions"][-1]

    def choose(name: str, fallback: str = ""):
        value = getattr(payload, name, None)
        return value if value is not None else latest.get(name, fallback)

    old_version = str(latest.get("version") or "1.0")
    try:
        major_minor = old_version.split(".")
        new_version = f"{major_minor[0]}.{int(major_minor[1]) + 1}" if len(major_minor) == 2 else f"{old_version}.1"
    except Exception:
        new_version = f"{old_version}.1"

    create_payload = DocumentRequest(
        title=choose("title"),
        object_type=choose("object_type"),
        document_category=choose("document_category", "OTHER"),
        project_id=choose("project_id"),
        status=choose("status", "UPDATED"),
        owner=choose("owner", DEFAULT_OWNER),
        version=payload.version or new_version,
        content=payload.content or latest.get("snippet", ""),
        source_object_id=choose("source_object_id"),
        related_objects=payload.related_objects or [],
    )
    result = _create_document(create_payload)
    result["action"] = "UPDATE_DOCUMENT"
    result["updated_document_id"] = document_id
    return result


@app.delete("/documents/{document_id}")
def delete_document_delete(request: Request, document_id: str):
    _check_token(request)
    return _delete_document(document_id)


def _delete_document(document_id: str) -> Dict[str, Any]:
    current = _get_document(document_id)
    if not current.get("found"):
        raise HTTPException(status_code=404, detail=f"Document not found: {document_id}")
    latest = current["versions"][-1]
    payload = UpdateDocumentRequest(
        title=latest.get("title"),
        object_type=latest.get("object_type"),
        document_category=latest.get("document_category"),
        project_id=latest.get("project_id"),
        status="DELETED",
        owner=latest.get("owner") or DEFAULT_OWNER,
        content=f"TOMBSTONE: Document {document_id} marked as DELETED at {_now_iso()}.",
        source_object_id=latest.get("source_object_id"),
    )
    result = _update_document(document_id, payload)
    result["action"] = "DELETE_DOCUMENT"
    return result


@app.get("/projects/{project_id}/documents")
def list_project_documents_get(request: Request, project_id: str, category: Optional[str] = None, limit: int = 100):
    _check_token(request)
    return _list_project_documents(project_id, category, limit)


def _list_project_documents(project_id: str, category: Optional[str] = None, limit: int = 100) -> Dict[str, Any]:
    if not project_id:
        raise HTTPException(status_code=400, detail="project_id is required.")
    project_id = project_id.strip().upper()
    category_filter = _normalize_document_category(category) if category else None
    try:
        drive_service = _drive()
        registry = _document_registry(drive_service)
        text = _extract_text_from_doc(registry["id"])
        items = []
        seen_doc_versions = set()
        for block in reversed(_parse_blocks_by_marker(text, "AI_OS_DOCUMENT")):
            rec = _block_to_document_record(block)
            if (rec.get("project_id") or "").upper() != project_id:
                continue
            if category_filter and (rec.get("document_category") or "").upper() != category_filter:
                continue
            key = (rec.get("document_id"), rec.get("version"))
            if key in seen_doc_versions:
                continue
            seen_doc_versions.add(key)
            items.append(rec)
            if len(items) >= limit:
                break
        return {
            "status": "success",
            "project_id": project_id,
            "category": category_filter,
            "count": len(items),
            "documents": items,
            "registry_url": registry.get("webViewLink", ""),
            "time_utc": _now_iso(),
            "time_local": _now_local_iso(),
        }
    except HttpError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


def _append_project_hub(drive_service, hub_id: str, project_id: str, title: str, status: str, owner: str, overview: str, url: str) -> None:
    hubs = _project_hubs_registry(drive_service)
    now = _now_iso()
    block = (
        "AI_OS_PROJECT_HUB\n"
        f"HUB_ID: {hub_id}\n"
        f"PROJECT_ID: {project_id}\n"
        f"TITLE: {title}\n"
        f"STATUS: {status}\n"
        f"OWNER: {owner}\n"
        f"URL: {url}\n"
        f"CREATED_AT: {now}\n"
        f"UPDATED_AT: {now}\n"
        "SECTIONS:\n"
        "- Overview\n"
        "- Current Status\n"
        "- Decisions\n"
        "- Documents\n"
        "- Audits\n"
        "- Formulas\n"
        "- RFQ\n"
        "- Related Objects\n"
        "OVERVIEW:\n"
        f"{overview or ''}\n"
        "------------------------------------------------"
    )
    _append_to_existing_doc(hubs["id"], block)


@app.post("/project-hubs")
async def create_project_hub_post(request: Request, payload: ProjectHubRequest):
    _check_token(request)
    return _create_project_hub(payload)


def _create_project_hub(payload: ProjectHubRequest) -> Dict[str, Any]:
    if not payload.project_id:
        raise HTTPException(status_code=400, detail="project_id is required.")
    try:
        drive_service = _drive()
        sheet = _change_log(drive_service)
        hubs = _project_hubs_registry(drive_service)
        project_id = payload.project_id.strip().upper()
        existing = _get_project_hub(project_id)
        if existing.get("found"):
            return existing
        hub_id = _generate_object_id(drive_service, "HUB", ["AI_OS_PROJECT_HUBS"])
        title = payload.title or f"Project Hub {project_id}"
        status = (payload.status or "ACTIVE").upper()
        owner = payload.owner or DEFAULT_OWNER
        url = _object_url("hub", hub_id)
        _append_project_hub(drive_service, hub_id, project_id, title, status, owner, payload.overview or "", url)
        _append_relation(drive_service, project_id, "HAS_HUB", hub_id, title)
        _append_change_log_row(sheet["id"], "CREATE_PROJECT_HUB", hubs["name"], "SUCCESS", f"{hub_id} | {project_id} | {title}", hubs.get("webViewLink", ""))
        return {
            "status": "success",
            "action": "CREATE_PROJECT_HUB",
            "hub_id": hub_id,
            "project_id": project_id,
            "title": title,
            "url": url,
            "registry_url": hubs.get("webViewLink", ""),
            "time_utc": _now_iso(),
            "time_local": _now_local_iso(),
        }
    except HttpError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/project-hubs/{project_id}")
def get_project_hub_get(request: Request, project_id: str):
    _check_token(request)
    return _get_project_hub(project_id)


def _get_project_hub(project_id: str) -> Dict[str, Any]:
    project_id = project_id.strip().upper()
    try:
        drive_service = _drive()
        hubs = _project_hubs_registry(drive_service)
        text = _extract_text_from_doc(hubs["id"])
        matches = []
        for block in reversed(_parse_blocks_by_marker(text, "AI_OS_PROJECT_HUB")):
            if re.search(rf"^\s*PROJECT_ID:\s*{re.escape(project_id)}\s*$", block, re.IGNORECASE | re.MULTILINE):
                matches.append({
                    "hub_id": _extract_field(block, "HUB_ID"),
                    "project_id": _extract_field(block, "PROJECT_ID"),
                    "title": _extract_field(block, "TITLE"),
                    "status": _extract_field(block, "STATUS"),
                    "owner": _extract_field(block, "OWNER"),
                    "url": _extract_field(block, "URL"),
                    "created_at": _extract_field(block, "CREATED_AT"),
                    "updated_at": _extract_field(block, "UPDATED_AT"),
                    "snippet": block[:1200],
                })
                break
        docs = _list_project_documents(project_id, None, 100).get("documents", []) if matches else []
        return {
            "status": "success",
            "project_id": project_id,
            "found": len(matches) > 0,
            "hub": matches[0] if matches else None,
            "document_count": len(docs),
            "documents": docs[:100],
            "registry_url": hubs.get("webViewLink", ""),
            "time_utc": _now_iso(),
            "time_local": _now_local_iso(),
        }
    except HttpError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/resolve-url")
def resolve_url_get(request: Request, object_id: str, object_kind: str = "object"):
    _check_token(request)
    return {
        "status": "success",
        "object_id": object_id,
        "object_kind": object_kind,
        "url": _object_url(object_kind, object_id),
        "time_utc": _now_iso(),
        "time_local": _now_local_iso(),
    }

@app.get("/openapi-gpt.json")
def openapi_gpt_json():
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "AI_OS_DOCUMENT_AGENT_GPT_ACTIONS_COMPACT",
            "version": "0.9.0",
            "description": "Compact schema for AI_OS Commander GPT Actions with Knowledge Persistence Layer."
        },
        "servers": [{"url": PUBLIC_BASE_URL}],
        "paths": {
            "/health": {
                "get": {
                    "operationId": "health",
                    "summary": "Check health.",
                    "responses": {"200": {"description": "OK"}}
                }
            },
            "/append-note": {
                "post": {
                    "operationId": "appendNote",
                    "summary": "Append note.",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "title": {"type": "string"},
                                        "content": {"type": "string"},
                                        "owner": {"type": "string"},
                                        "related_to": {"type": "string"}
                                    },
                                    "required": ["title", "content"]
                                }
                            }
                        }
                    },
                    "responses": {"200": {"description": "Success"}}
                }
            },
            "/create-project": {
                "post": {
                    "operationId": "createProject",
                    "summary": "Create project.",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "title": {"type": "string"},
                                        "owner": {"type": "string"},
                                        "status": {"type": "string"},
                                        "priority": {"type": "string"},
                                        "description": {"type": "string"},
                                        "objectives": {"type": "string"},
                                        "deliverables": {"type": "string"},
                                        "risks": {"type": "string"},
                                        "next_actions": {"type": "string"},
                                        "related_to": {"type": "string"}
                                    },
                                    "required": ["title"]
                                }
                            }
                        }
                    },
                    "responses": {"200": {"description": "Success"}}
                }
            },
            "/create-decision": {
                "post": {
                    "operationId": "createDecision",
                    "summary": "Create decision.",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "title": {"type": "string"},
                                        "decision": {"type": "string"},
                                        "owner": {"type": "string"},
                                        "status": {"type": "string"},
                                        "priority": {"type": "string"},
                                        "context": {"type": "string"},
                                        "related_to": {"type": "string"}
                                    },
                                    "required": ["title", "decision"]
                                }
                            }
                        }
                    },
                    "responses": {"200": {"description": "Success"}}
                }
            },
            "/create-entity": {
                "post": {
                    "operationId": "createEntity",
                    "summary": "Create entity.",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "entity_type": {"type": "string"},
                                        "title": {"type": "string"},
                                        "description": {"type": "string"},
                                        "owner": {"type": "string"},
                                        "status": {"type": "string"},
                                        "priority": {"type": "string"},
                                        "related_to": {"type": "string"}
                                    },
                                    "required": ["entity_type", "title"]
                                }
                            }
                        }
                    },
                    "responses": {"200": {"description": "Success"}}
                }
            },
            "/create-relation": {
                "post": {
                    "operationId": "createRelation",
                    "summary": "Create relation.",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "source_id": {"type": "string"},
                                        "relation_type": {"type": "string"},
                                        "target_id": {"type": "string"},
                                        "note": {"type": "string"}
                                    },
                                    "required": ["source_id", "relation_type", "target_id"]
                                }
                            }
                        }
                    },
                    "responses": {"200": {"description": "Success"}}
                }
            },
            "/find-entity": {
                "get": {
                    "operationId": "findEntity",
                    "summary": "Find entity.",
                    "parameters": [
                        {"name": "query", "in": "query", "required": True, "schema": {"type": "string"}},
                        {"name": "limit", "in": "query", "required": False, "schema": {"type": "integer", "default": 5}}
                    ],
                    "responses": {"200": {"description": "Success"}}
                }
            },
            "/find-related-compact": {
                "get": {
                    "operationId": "findRelatedCompact",
                    "summary": "Find related compact.",
                    "parameters": [
                        {"name": "object_id", "in": "query", "required": True, "schema": {"type": "string"}},
                        {"name": "relation_type", "in": "query", "required": False, "schema": {"type": "string"}},
                        {"name": "direction", "in": "query", "required": False, "schema": {"type": "string", "default": "both"}},
                        {"name": "limit", "in": "query", "required": False, "schema": {"type": "integer", "default": 5}}
                    ],
                    "responses": {"200": {"description": "Success"}}
                }
            },
            "/find-by-id": {
                "get": {
                    "operationId": "findById",
                    "summary": "Find by ID.",
                    "parameters": [
                        {"name": "object_id", "in": "query", "required": True, "schema": {"type": "string"}}
                    ],
                    "responses": {"200": {"description": "Success"}}
                }
            },
            "/search": {
                "get": {
                    "operationId": "searchAiOs",
                    "summary": "Search AI_OS.",
                    "parameters": [
                        {"name": "query", "in": "query", "required": True, "schema": {"type": "string"}},
                        {"name": "limit", "in": "query", "required": False, "schema": {"type": "integer", "default": 5}}
                    ],
                    "responses": {"200": {"description": "Success"}}
                }
            },
            "/documents": {
                "post": {
                    "operationId": "createDocument",
                    "summary": "Create document registry record.",
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "object_type": {"type": "string"},
                                "document_category": {"type": "string"},
                                "project_id": {"type": "string"},
                                "status": {"type": "string"},
                                "owner": {"type": "string"},
                                "version": {"type": "string"},
                                "content": {"type": "string"},
                                "source_object_id": {"type": "string"},
                                "related_objects": {"type": "array", "items": {"type": "string"}}
                            },
                            "required": ["title", "object_type", "document_category", "project_id"]
                        }}}
                    },
                    "responses": {"200": {"description": "Success"}}
                }
            },
            "/documents/{document_id}": {
                "get": {
                    "operationId": "getDocument",
                    "summary": "Get document by ID.",
                    "parameters": [{"name": "document_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                    "responses": {"200": {"description": "Success"}}
                },
                "put": {
                    "operationId": "updateDocument",
                    "summary": "Append updated document version.",
                    "parameters": [{"name": "document_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                    "requestBody": {"required": True, "content": {"application/json": {"schema": {"type": "object"}}}},
                    "responses": {"200": {"description": "Success"}}
                },
                "delete": {
                    "operationId": "deleteDocument",
                    "summary": "Mark document as deleted.",
                    "parameters": [{"name": "document_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                    "responses": {"200": {"description": "Success"}}
                }
            },
            "/projects/{project_id}/documents": {
                "get": {
                    "operationId": "listProjectDocuments",
                    "summary": "List project documents.",
                    "parameters": [
                        {"name": "project_id", "in": "path", "required": True, "schema": {"type": "string"}},
                        {"name": "category", "in": "query", "required": False, "schema": {"type": "string"}},
                        {"name": "limit", "in": "query", "required": False, "schema": {"type": "integer", "default": 100}}
                    ],
                    "responses": {"200": {"description": "Success"}}
                }
            },
            "/project-hubs": {
                "post": {
                    "operationId": "createProjectHub",
                    "summary": "Create project hub.",
                    "requestBody": {"required": True, "content": {"application/json": {"schema": {
                        "type": "object",
                        "properties": {
                            "project_id": {"type": "string"},
                            "title": {"type": "string"},
                            "owner": {"type": "string"},
                            "status": {"type": "string"},
                            "overview": {"type": "string"}
                        },
                        "required": ["project_id"]
                    }}}},
                    "responses": {"200": {"description": "Success"}}
                }
            },
            "/project-hubs/{project_id}": {
                "get": {
                    "operationId": "getProjectHub",
                    "summary": "Get project hub.",
                    "parameters": [{"name": "project_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                    "responses": {"200": {"description": "Success"}}
                }
            },
            "/resolve-url": {
                "get": {
                    "operationId": "resolveUrl",
                    "summary": "Resolve object URL.",
                    "parameters": [
                        {"name": "object_id", "in": "query", "required": True, "schema": {"type": "string"}},
                        {"name": "object_kind", "in": "query", "required": False, "schema": {"type": "string", "default": "object"}}
                    ],
                    "responses": {"200": {"description": "Success"}}
                }
            },
            "/graph-summary": {
                "get": {
                    "operationId": "graphSummary",
                    "summary": "Graph summary.",
                    "responses": {"200": {"description": "Success"}}
                }
            }
        }
    }
