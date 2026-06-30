import base64
import datetime as dt
import hashlib
import json
import os
import re
import unicodedata
import httpx
from typing import Optional, List, Dict, Any
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


APP_NAME = "AI_OS_ORCHESTRATOR_V1_3_5_4_COMPACT_DEBUG_OUTPUT"
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
    version="1.3.5.4",
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



class OrchestratorRequest(BaseModel):
    message: str
    write_result: Optional[bool] = False
    result_title: Optional[str] = None
    project_id: Optional[str] = "AI_OS"
    limit: Optional[int] = 5
    debug: Optional[bool] = False



SEARCH_DOCUMENT_NAMES = [
    "AI_OS_DOCUMENT_REGISTRY",
    "AI_OS_PROJECT_HUBS",
    "AI_OS_INBOX",
    "AI_OS_DECISION_LOG",
    "AI_OS_PROJECTS",
    "AI_OS_ROADMAP",
    "AI_OS_MASTER",
    "AI_OS_MASTER_STATE",
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
    """Find a Google Docs document by exact name inside the AI_OS tree.

    v1.3.5 compatibility note:
    Earlier versions searched only the AI_OS root folder. Governance documents
    are now often stored inside AI_OS_Governing_Documents, therefore this helper
    first checks the root for backward compatibility and then falls back to the
    recursive AI_OS document index.
    """
    root_id = _root_folder_id()
    safe_name = _safe_query_string(name)

    # 1) Backward-compatible root lookup.
    q = (
        f"'{_safe_query_string(root_id)}' in parents and "
        f"name='{safe_name}' and "
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
    if files:
        return files[0]

    # 2) Recursive lookup inside the AI_OS tree.
    target = (name or "").strip()
    if not target:
        return None
    try:
        for item in _list_ai_os_google_docs_recursive(drive_service, max_documents=800):
            if (item.get("name") or "").strip() == target:
                return item
    except Exception:
        # Final fallback below still allows Drive search to work if recursive scan fails.
        pass

    # 3) Broad Drive lookup, then constrain to AI_OS tree by ID when possible.
    try:
        q = (
            f"name='{safe_name}' and "
            "mimeType='application/vnd.google-apps.document' and "
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
            return None
        indexed_ids = {d.get("id") for d in _list_ai_os_google_docs_recursive(drive_service, max_documents=800)}
        for item in files:
            if item.get("id") in indexed_ids:
                return item
        return files[0]
    except Exception:
        return None


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




# Early ultra-safe index constants.
# These must be defined before any function or FastAPI route uses them as default values.
# They are intentionally repeated later in the configuration section for readability;
# the value remains identical because both read the same environment variable.
MAX_INDEX_DOCUMENTS = int(os.getenv("MAX_INDEX_DOCUMENTS", "20"))

def _find_google_doc_by_exact_name_anywhere(drive_service, name: str) -> Optional[dict]:
    """Memory-safe exact-name lookup across Google Drive.

    This intentionally avoids recursive AI_OS tree scans. It is used by the
    v1.3.5.2 ultra-safe index to find only the small set of core Governance
    documents needed for Knowledge Retrieval on Render Free.
    """
    safe_name = _safe_query_string((name or "").strip())
    if not safe_name:
        return None
    q = (
        f"name='{safe_name}' and "
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


def _build_governance_only_index(drive_service, max_documents: int = 20) -> Dict[str, Any]:
    """Build a tiny memory-safe index from known AI_OS Governance documents."""
    safe_limit = max(1, min(int(max_documents or MAX_INDEX_DOCUMENTS), 50))
    indexed_documents: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    seen_ids = set()

    for name in GOVERNANCE_DOCUMENT_CANDIDATES:
        if len(indexed_documents) >= safe_limit:
            break
        try:
            item = _find_google_doc_by_exact_name_anywhere(drive_service, name)
            if not item:
                errors.append({"name": name, "error": "not_found"})
                continue
            doc_id = item.get("id")
            if not doc_id or doc_id in seen_ids:
                continue
            seen_ids.add(doc_id)
            indexed_documents.append({
                "name": item.get("name", ""),
                "id": doc_id,
                "url": item.get("webViewLink", ""),
                "parents": item.get("parents", []),
                "content_status": "metadata_only_governance_core",
                "text_length": 0,
                "indexed_text": "",
            })
        except Exception as exc:
            errors.append({"name": name, "error": _safe_error_text(exc)})

    index = {
        "status": "ready",
        "created_utc": _now_iso(),
        "created_local": _now_local_iso(),
        "document_count": len(indexed_documents),
        "max_documents": safe_limit,
        "max_chars_per_document": 0,
        "index_mode": "governance_only_ultra_safe",
        "documents": indexed_documents,
        "errors": errors,
    }
    AI_OS_INDEX.clear()
    AI_OS_INDEX.update(index)
    return index

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
    if INDEX_GOVERNANCE_ONLY:
        return _build_governance_only_index(
            drive_service,
            max_documents=max_documents or MAX_INDEX_DOCUMENTS,
        )

    safe_limit = max(1, min(int(max_documents or MAX_INDEX_DOCUMENTS), 200))

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


def _ensure_ai_os_index_ready(max_documents: int = MAX_INDEX_DOCUMENTS) -> Dict[str, Any]:
    """Ensure the in-memory index exists before /search or /orchestrator/ask.

    Render free services can restart or route requests after inactivity. The old version
    required manual /refresh-index after every restart. This version rebuilds the fast
    metadata index automatically on first search/orchestrator request if it is empty.
    """
    if AI_OS_INDEX.get("status") == "ready" and AI_OS_INDEX.get("documents"):
        return AI_OS_INDEX

    drive_service = _drive()
    return _build_ai_os_knowledge_index(
        drive_service,
        max_documents=max_documents,
        max_chars_per_document=0,
    )


def _search_in_knowledge_index(query: str, limit: int = 10) -> Dict[str, Any]:
    safe_limit = max(1, min(int(limit or 10), 50))
    q = _normalize_search_text(query)
    if not q:
        raise HTTPException(status_code=400, detail="Query is required.")

    if AI_OS_INDEX.get("status") != "ready" or not AI_OS_INDEX.get("documents"):
        try:
            _ensure_ai_os_index_ready(max_documents=MAX_INDEX_DOCUMENTS)
        except Exception as exc:
            return {
                "status": "success",
                "query": query,
                "found": False,
                "match_count": 0,
                "matches": [],
                "index_status": AI_OS_INDEX.get("status", "empty"),
                "requires_refresh_index": True,
                "auto_refresh_error": str(exc)[:800],
                "note": "Knowledge index is empty and automatic refresh failed. Run /refresh-index and check Render logs if this repeats.",
                "time_utc": _now_iso(),
                "time_local": _now_local_iso(),
                "timezone": AI_OS_TIMEZONE_NAME,
            }

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
                pageSize=max(1, min(DRIVE_SEARCH_PAGE_SIZE, safe_limit * 2)),
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
        "message": "AI_OS Orchestrator v1.3.5 is online. Knowledge Retrieval is enabled for /orchestrator/ask.",
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
def refresh_index_get(request: Request, limit: int = MAX_INDEX_DOCUMENTS, max_chars: int = 0):
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
            "index_mode": index.get("index_mode", "metadata_recursive"),
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


@app.get("/orchestrator/extract-snippets")
def orchestrator_extract_snippets_get(
    request: Request,
    name: str,
    query: str,
    max_snippets: int = 5,
    max_chars_per_snippet: int = 800,
    include_scores: bool = False,
):
    _check_token(request)
    working_context = _build_working_context(
        query=query,
        document_name=name,
        max_snippets=max_snippets,
        max_chars_per_snippet=max_chars_per_snippet,
        include_scores=include_scores,
    )
    return {
        "status": "success",
        "service": APP_NAME,
        "action": "EXTRACT_SNIPPETS",
        "working_context": working_context,
        "time_utc": _now_iso(),
        "time_local": _now_local_iso(),
        "timezone": AI_OS_TIMEZONE_NAME,
    }


@app.get("/orchestrator/knowledge-retrieval")
def orchestrator_knowledge_retrieval_get(
    request: Request,
    message: str,
    limit: int = 5,
):
    """Diagnostic endpoint for AI_OS v1.3.5 Knowledge Retrieval.

    This endpoint does not call Gemini/OpenAI. It only shows which documents and
    snippets would be used to build the unified WorkingContext.
    """
    _check_token(request)
    if not message or not message.strip():
        raise HTTPException(status_code=400, detail="message is required.")
    try:
        retrieval = _build_knowledge_retrieval_context(message=message.strip(), limit=limit)
        return {
            "status": "success",
            "service": APP_NAME,
            "action": "KNOWLEDGE_RETRIEVAL",
            "knowledge_retrieval": _compact_knowledge_retrieval_for_debug(retrieval),
            "debug_compacted": True,
            "time_utc": _now_iso(),
            "time_local": _now_local_iso(),
            "timezone": AI_OS_TIMEZONE_NAME,
        }
    except Exception as exc:
        return {
            "status": "error",
            "service": APP_NAME,
            "action": "KNOWLEDGE_RETRIEVAL",
            "error": _safe_error_text(exc),
            "fallback_available": True,
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


# -----------------------------------------------------------------------------
# AI_OS ORCHESTRATOR v1.2
# -----------------------------------------------------------------------------
# Purpose:
# Daniel talks to one entry point: /orchestrator/ask.
# Orchestrator uses existing AI_OS Knowledge Index + Document Agent functions.
# AI Provider Router tries configured AI providers in a safe order.
# Default policy is FREE-FIRST:
#   1) Gemini Flash (free quota where available)
#   2) OpenAI (paid fallback)
#   3) deterministic fallback
# You can override it in Render with:
#   PRIMARY_AI_PROVIDER=gemini   # default, free-first
#   PRIMARY_AI_PROVIDER=openai   # paid-first, only if deliberately needed
#   AI_PROVIDER_ORDER=gemini,openai  # optional explicit order
# This keeps one practical agent now, while preparing AI_OS for provider neutrality.

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
PRIMARY_AI_PROVIDER = os.getenv("PRIMARY_AI_PROVIDER", os.getenv("AI_PROVIDER", "gemini")).strip().lower()
AI_PROVIDER_ORDER = os.getenv("AI_PROVIDER_ORDER")
ORCHESTRATOR_RESULT_CATEGORY = "ORCHESTRATOR_RESULT"
MASTER_STATE_DOCUMENT_NAME = "AI_OS_MASTER_STATE"
MASTER_STATE_MAX_CHARS = int(os.getenv("MASTER_STATE_MAX_CHARS", "6000"))

# AI_OS v1.3.5 – Knowledge Retrieval configuration.
ENABLE_KNOWLEDGE_RETRIEVAL = os.getenv("ENABLE_KNOWLEDGE_RETRIEVAL", "true").strip().lower() not in {"0", "false", "no", "off"}
KNOWLEDGE_RETRIEVAL_LIMIT = int(os.getenv("KNOWLEDGE_RETRIEVAL_LIMIT", "5"))
SNIPPETS_PER_DOCUMENT = int(os.getenv("SNIPPETS_PER_DOCUMENT", "2"))
MAX_CONTEXT_CHARS = int(os.getenv("MAX_CONTEXT_CHARS", "6000"))
MAX_CHARS_PER_RETRIEVAL_SNIPPET = int(os.getenv("MAX_CHARS_PER_RETRIEVAL_SNIPPET", "700"))
MIN_RELEVANCE_SCORE = float(os.getenv("MIN_RELEVANCE_SCORE", "0.25"))
KNOWLEDGE_RETRIEVAL_PIPELINE_VERSION = "1.3.5.4-compact-debug-output"
AI_PROMPT_MAX_CHARS = int(os.getenv("AI_PROMPT_MAX_CHARS", "9000"))
MAX_DEBUG_CHARS = int(os.getenv("MAX_DEBUG_CHARS", "3000"))
DEBUG_TEXT_PREVIEW_CHARS = int(os.getenv("DEBUG_TEXT_PREVIEW_CHARS", "220"))
DEBUG_MAX_BLOCKS = int(os.getenv("DEBUG_MAX_BLOCKS", "8"))

# Ultra memory safe index configuration for Render Free (512 MB RAM).
# Default behavior indexes only core governance documents, not the whole Drive tree.
MAX_INDEX_DOCUMENTS = int(os.getenv("MAX_INDEX_DOCUMENTS", "20"))
INDEX_GOVERNANCE_ONLY = os.getenv("INDEX_GOVERNANCE_ONLY", "true").strip().lower() not in {"0", "false", "no", "off"}
DRIVE_SEARCH_PAGE_SIZE = int(os.getenv("DRIVE_SEARCH_PAGE_SIZE", "10"))


GOVERNANCE_DOCUMENT_CANDIDATES = [
    "AI_OS_MASTER_STATE_v1.0",
    "AI_OS_MASTER_STATE",
    "AI_OS_ARCHITECTURE_v1.0",
    "AI_OS_ROADMAP_v1.0",
    "AI_OS_DECISIONS_v1.0",
    "AI_OS_KNOWLEDGE_POLICY_v1.0",
    "AI_OS_DOCUMENTATION_STANDARD_v1.0",
    "AI_OS_DOCUMENTATION_STANDARD",
    "AI_OS_GLOSSARY",
    "AI_OS_GLOSSARY_v1.0",
    "AI_OS_NOTES",
]

ORCHESTRATOR_SYSTEM_PROMPT = """
Si AI_OS Orchestrátor, riaditeľ digitálneho podniku Daniela Valušiaka.
Komunikuj po slovensky. Buď stručný, praktický a vykonávací.
Tvoj prvý zdroj pravdy je AI_OS_MASTER_STATE. Tvoj širší zdroj pravdy je Google Drive cez AI_OS Document Agent.
Nikdy nevymýšľaj neoverené fakty. Ak nevieš, povedz čo chýba.
Najprv použi dostupné dokumenty, potom navrhni ďalší konkrétny krok.
Ak používateľ žiada výkon, vráť vykonateľný výsledok, nie teóriu.
""".strip()


def _configured_provider_order() -> List[str]:
    """Return provider order without duplicates.

    Policy:
    - If AI_PROVIDER_ORDER is set, respect it.
    - Otherwise use PRIMARY_AI_PROVIDER first.
    - Default PRIMARY_AI_PROVIDER is gemini, so the free/quota-friendly provider is tried first.
    - OpenAI is used only as fallback unless PRIMARY_AI_PROVIDER=openai or explicit order says so.
    """
    allowed = {"openai", "gemini"}

    if AI_PROVIDER_ORDER:
        raw_order = AI_PROVIDER_ORDER
    else:
        primary = PRIMARY_AI_PROVIDER if PRIMARY_AI_PROVIDER in allowed else "gemini"
        fallback = "openai" if primary == "gemini" else "gemini"
        raw_order = f"{primary},{fallback}"

    providers: List[str] = []
    for raw in raw_order.split(","):
        provider = raw.strip().lower()
        if provider in allowed and provider not in providers:
            providers.append(provider)

    return providers or ["gemini", "openai"]


def _provider_status() -> Dict[str, Any]:
    provider_order = _configured_provider_order()
    return {
        "router": "enabled",
        "routing_policy": "free_first_unless_overridden",
        "primary_ai_provider": provider_order[0] if provider_order else "deterministic",
        "provider_order": provider_order,
        "openai_configured": bool(os.getenv("OPENAI_API_KEY")),
        "openai_model": OPENAI_MODEL if os.getenv("OPENAI_API_KEY") else None,
        "gemini_configured": bool(os.getenv("GEMINI_API_KEY")),
        "gemini_model": GEMINI_MODEL if os.getenv("GEMINI_API_KEY") else None,
        "deterministic_fallback": True,
    }


def _load_master_state(max_chars: Optional[int] = None) -> Dict[str, Any]:
    """Load AI_OS_MASTER_STATE as the first context source.

    This is intentionally small and defensive:
    - it never crashes /orchestrator/ask if the document is missing or temporarily unreadable,
    - it reads the actual Google Doc text, not only the metadata index,
    - it returns metadata for health checks and debugging.
    """
    safe_max_chars = max(1000, min(int(max_chars or MASTER_STATE_MAX_CHARS), 50000))
    result: Dict[str, Any] = {
        "name": MASTER_STATE_DOCUMENT_NAME,
        "loaded": False,
        "found": False,
        "document_id": None,
        "document_url": None,
        "text": "",
        "text_length": 0,
        "truncated": False,
        "error": None,
    }

    try:
        drive_service = _drive()
        doc = None
        for master_name in ["AI_OS_MASTER_STATE_v1.0", MASTER_STATE_DOCUMENT_NAME]:
            doc = _find_google_doc_by_exact_name_anywhere(drive_service, master_name)
            if doc:
                result["name"] = doc.get("name") or master_name
                break
        if not doc:
            result["error"] = "AI_OS_MASTER_STATE not found."
            return result

        result["found"] = True
        result["document_id"] = doc.get("id")
        result["document_url"] = doc.get("webViewLink", "")

        raw_text = _extract_text_from_doc(doc["id"]) if doc.get("id") else ""
        raw_text = (raw_text or "").strip()
        result["text_length"] = len(raw_text)

        if len(raw_text) > safe_max_chars:
            result["text"] = raw_text[:safe_max_chars].rstrip()
            result["truncated"] = True
        else:
            result["text"] = raw_text

        result["loaded"] = bool(result["text"])
        return result
    except Exception as exc:
        result["error"] = _safe_error_text(exc)
        return result


WORKING_CONTEXT_PIPELINE_VERSION = "1.3.2.1-deterministic-v1"
SLOVAK_STOPWORDS = {
    "a", "aj", "ale", "alebo", "ako", "ak", "aby", "bez", "bol", "bola", "bolo", "boli",
    "cez", "co", "čo", "do", "ho", "ich", "je", "ju", "k", "ku", "ma", "má", "me", "mi",
    "mna", "mňa", "na", "nad", "nam", "nám", "nas", "nás", "ne", "nie", "no", "o", "od",
    "po", "pod", "pre", "pri", "sa", "si", "sme", "som", "su", "sú", "ta", "tá", "tak",
    "tam", "te", "ten", "to", "tu", "toto", "ty", "v", "vo", "za", "ze", "že", "z",
    "projekt", "dokument", "dokumenty", "najdi", "nájdi", "ukaz", "ukáž", "povedz",
}


def _clean_text(text: str) -> str:
    """Basic whitespace cleanup for Google Docs text."""
    value = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.strip() for line in value.split("\n")]
    cleaned_lines = []
    empty_seen = False
    for line in lines:
        if not line:
            if not empty_seen:
                cleaned_lines.append("")
            empty_seen = True
        else:
            cleaned_lines.append(line)
            empty_seen = False
    return "\n".join(cleaned_lines).strip()


def _normalize_text(value: str) -> str:
    """Lowercase, remove diacritics and punctuation-like characters."""
    value = (value or "").lower()
    value = "".join(
        ch for ch in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(ch)
    )
    value = re.sub(r"[^a-z0-9_\s-]", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def _extract_keywords(query: str, max_keywords: int = 12) -> List[str]:
    """Extract simple deterministic keywords from user query."""
    normalized = _normalize_text(query)
    raw_words = re.findall(r"[a-z0-9_]{3,}", normalized)
    keywords: List[str] = []
    for word in raw_words:
        if word in SLOVAK_STOPWORDS:
            continue
        if word not in keywords:
            keywords.append(word)
        if len(keywords) >= max_keywords:
            break
    return keywords


def _split_into_blocks(text: str, max_chars_per_block: int = 900) -> List[Dict[str, Any]]:
    """Split document text into paragraph-like blocks with positions."""
    cleaned = _clean_text(text)
    if not cleaned:
        return []

    raw_parts = re.split(r"\n\s*\n|(?<=\n)(?=[A-ZÁÄČĎÉÍĹĽŇÓÔŔŠŤÚÝŽ0-9][^\n]{0,120}\n)", cleaned)
    blocks: List[Dict[str, Any]] = []
    cursor = 0

    for raw in raw_parts:
        part = raw.strip()
        if not part:
            continue

        chunks = []
        if len(part) <= max_chars_per_block:
            chunks = [part]
        else:
            sentences = re.split(r"(?<=[.!?])\s+", part)
            current = ""
            for sentence in sentences:
                if len(current) + len(sentence) + 1 <= max_chars_per_block:
                    current = (current + " " + sentence).strip()
                else:
                    if current:
                        chunks.append(current)
                    current = sentence.strip()
            if current:
                chunks.append(current)

        for chunk in chunks:
            start = cleaned.find(chunk, cursor)
            if start < 0:
                start = cursor
            end = start + len(chunk)
            normalized = _normalize_text(chunk)
            blocks.append({
                "id": len(blocks) + 1,
                "start": start,
                "end": end,
                "text": chunk,
                "normalized_text": normalized,
                "matched_keywords": [],
                "score": 0.0,
            })
            cursor = end

    return blocks


def _keyword_variants(keyword: str) -> List[str]:
    """Very small Slovak-friendly deterministic variants without heavy NLP."""
    keyword = _normalize_text(keyword)
    variants = {keyword}
    suffixes = ["u", "a", "om", "och", "mi", "y", "e", "ov", "ove", "ovy", "neho", "nom"]
    for suffix in suffixes:
        if keyword.endswith(suffix) and len(keyword) > len(suffix) + 3:
            variants.add(keyword[: -len(suffix)])
    if len(keyword) >= 5:
        variants.add(keyword[:5])
    return [v for v in variants if len(v) >= 3]


def _score_block(block: Dict[str, Any], keywords: List[str]) -> Dict[str, Any]:
    """Score one block by deterministic keyword overlap."""
    normalized = block.get("normalized_text", "")
    matched: List[str] = []
    score = 0.0
    original_text = block.get("text", "")
    is_heading_like = len(original_text) <= 160 and (
        original_text.isupper()
        or original_text.endswith(":")
        or original_text.strip().startswith("#")
    )

    for keyword in keywords:
        variants = _keyword_variants(keyword)
        matched_this = False
        for variant in variants:
            if re.search(rf"\b{re.escape(variant)}[a-z0-9_]*\b", normalized):
                matched_this = True
                break
        if matched_this:
            matched.append(keyword)
            score += 1.0

    if matched:
        score += min(len(set(matched)) * 0.25, 1.5)
    if is_heading_like and matched:
        score += 1.0
    if matched and len(normalized) < 700:
        score += 0.25

    updated = dict(block)
    updated["matched_keywords"] = sorted(set(matched))
    updated["score"] = round(score, 4)
    return updated


def _select_best_blocks(
    blocks: List[Dict[str, Any]],
    keywords: List[str],
    max_snippets: int = 5,
    max_chars_per_snippet: int = 800,
) -> List[Dict[str, Any]]:
    """Score and select best text blocks."""
    safe_max_snippets = max(1, min(int(max_snippets or 5), 20))
    safe_max_chars = max(100, min(int(max_chars_per_snippet or 800), 3000))

    scored = [_score_block(block, keywords) for block in blocks]
    selected = [block for block in scored if block.get("score", 0) > 0]
    if not selected:
        selected = scored[:safe_max_snippets]

    selected = sorted(selected, key=lambda b: (-float(b.get("score", 0)), int(b.get("id", 0))))
    selected = selected[:safe_max_snippets]

    compact: List[Dict[str, Any]] = []
    for _rank, block in enumerate(selected, start=1):
        text_value = (block.get("text") or "").strip()
        if len(text_value) > safe_max_chars:
            text_value = text_value[:safe_max_chars].rstrip() + "..."
        compact.append({
            "id": block.get("id"),
            "start": block.get("start"),
            "end": block.get("end"),
            "text": text_value,
            "normalized_text": block.get("normalized_text", ""),
            "matched_keywords": block.get("matched_keywords", []),
            "score": block.get("score", 0.0),
        })
    return compact


def _build_working_context(
    query: str,
    document_name: str,
    max_snippets: int = 5,
    max_chars_per_snippet: int = 800,
    include_scores: bool = False,
) -> Dict[str, Any]:
    """Build the first deterministic WorkingContext from one Google Docs document."""
    requested_name = (document_name or "").strip()
    if not requested_name:
        raise HTTPException(status_code=400, detail="Parameter name is required.")
    if not query or not query.strip():
        raise HTTPException(status_code=400, detail="Parameter query is required.")

    drive_service = _drive()
    doc = _find_google_doc_by_exact_name_anywhere(drive_service, requested_name)
    if not doc:
        raise HTTPException(
            status_code=404,
            detail=f"Google document not found in AI_OS root folder: {requested_name}",
        )

    raw_text = _extract_text_from_doc(doc["id"]) if doc.get("id") else ""
    cleaned_text = _clean_text(raw_text)
    keywords = _extract_keywords(query)
    blocks = _split_into_blocks(cleaned_text)
    selected_blocks = _select_best_blocks(
        blocks=blocks,
        keywords=keywords,
        max_snippets=max_snippets,
        max_chars_per_snippet=max_chars_per_snippet,
    )

    if not include_scores:
        for block in selected_blocks:
            block.pop("normalized_text", None)
            block.pop("score", None)
            block.pop("matched_keywords", None)

    return {
        "query": query,
        "document_name": doc.get("name") or requested_name,
        "document_id": doc.get("id"),
        "document_url": doc.get("webViewLink", ""),
        "text_length": len(cleaned_text),
        "keywords": keywords,
        "blocks_count": len(blocks),
        "selected_blocks": selected_blocks,
        "created_utc": _now_iso(),
        "pipeline_version": WORKING_CONTEXT_PIPELINE_VERSION,
        "provider": None,
        "ai_response": None,
    }


def _master_state_status() -> Dict[str, Any]:
    """Compact health information for AI_OS_MASTER_STATE."""
    master_state = _load_master_state(max_chars=4000)
    return {
        "master_state_reader": "enabled",
        "master_state_document_name": MASTER_STATE_DOCUMENT_NAME,
        "master_state_found": master_state.get("found", False),
        "master_state_loaded": master_state.get("loaded", False),
        "master_state_document_id": master_state.get("document_id"),
        "master_state_document_url": master_state.get("document_url"),
        "master_state_text_length": master_state.get("text_length", 0),
        "master_state_truncated": master_state.get("truncated", False),
        "master_state_error": master_state.get("error"),
    }


def _orchestrator_compact_matches(search_result: Dict[str, Any], max_items: int = 5) -> List[Dict[str, Any]]:
    items = []
    for match in (search_result or {}).get("matches", [])[:max_items]:
        items.append({
            "title": match.get("document_name") or match.get("title") or "",
            "url": match.get("document_url") or match.get("url") or "",
            "score": match.get("score"),
            "match_type": match.get("match_type"),
            "snippet": (match.get("snippet") or "")[:1200],
        })
    return items


def _choose_working_context_document(message: str, matches: List[Dict[str, Any]]) -> str:
    """Choose the best document for WorkingContext without adding new architecture.

    Prefer AI_OS_MASTER_STATE for project-state questions. Otherwise use the first
    matched document. This keeps /orchestrator/ask simple and testable in v1.3.3.
    """
    normalized_message = _normalize_text(message)
    state_terms = [
        "aktualny", "stav", "dalej", "dalsi", "krok", "hotove", "nefunguje",
        "priorita", "riziko", "rozhodnutie", "roadmapa", "plan",
    ]
    if any(term in normalized_message for term in state_terms):
        return MASTER_STATE_DOCUMENT_NAME

    for item in matches or []:
        title = item.get("title") or item.get("document_name") or ""
        if title:
            return title

    return MASTER_STATE_DOCUMENT_NAME


def _working_context_text(working_context: Optional[Dict[str, Any]]) -> str:
    """Render WorkingContext selected blocks into compact text for Gemini/OpenAI."""
    if not working_context:
        return "Pracovný kontext (WorkingContext) nie je dostupný."

    lines = []
    lines.append("=== PRACOVNÝ KONTEXT (WorkingContext) ===")
    lines.append(f"Dokument: {working_context.get('document_name')}")
    if working_context.get("document_url"):
        lines.append(f"URL: {working_context.get('document_url')}")
    lines.append(f"Kľúčové slová: {', '.join(working_context.get('keywords') or [])}")
    lines.append(f"Počet blokov dokumentu: {working_context.get('blocks_count')}")
    lines.append(f"Pipeline verzia: {working_context.get('pipeline_version')}")
    lines.append("\nVybrané relevantné úryvky:")
    selected_blocks = working_context.get("selected_blocks") or []
    if not selected_blocks:
        lines.append("Žiadne úryvky neboli vybrané.")
    for i, block in enumerate(selected_blocks, start=1):
        lines.append(f"\n[{i}] Blok ID: {block.get('id')}")
        if block.get("matched_keywords"):
            lines.append(f"Zhoda slov: {', '.join(block.get('matched_keywords') or [])}")
        if block.get("score") is not None:
            lines.append(f"Skóre: {block.get('score')}")
        lines.append(block.get("text") or "")
    return "\n".join(lines)


def _safe_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = default
    return max(minimum, min(parsed, maximum))


def _safe_float(value: Any, default: float, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except Exception:
        parsed = default
    return max(minimum, min(parsed, maximum))


def _retrieval_config() -> Dict[str, Any]:
    """Runtime configuration for AI_OS v1.3.5 Knowledge Retrieval."""
    return {
        "enabled": ENABLE_KNOWLEDGE_RETRIEVAL,
        "knowledge_retrieval_limit": _safe_int(KNOWLEDGE_RETRIEVAL_LIMIT, 5, 1, 12),
        "snippets_per_document": _safe_int(SNIPPETS_PER_DOCUMENT, 3, 1, 8),
        "max_context_chars": _safe_int(MAX_CONTEXT_CHARS, 12000, 3000, 50000),
        "max_chars_per_snippet": _safe_int(MAX_CHARS_PER_RETRIEVAL_SNIPPET, 900, 200, 3000),
        "min_relevance_score": _safe_float(MIN_RELEVANCE_SCORE, 0.25, 0.0, 100.0),
        "max_index_docs": _safe_int(MAX_INDEX_DOCUMENTS, 20, 1, 50),
        "index_governance_only": INDEX_GOVERNANCE_ONLY,
        "drive_search_page_size": _safe_int(DRIVE_SEARCH_PAGE_SIZE, 10, 1, 50),
        "pipeline_version": KNOWLEDGE_RETRIEVAL_PIPELINE_VERSION,
    }


def _document_title_from_match(item: Dict[str, Any]) -> str:
    return (item.get("title") or item.get("document_name") or item.get("name") or "").strip()


def _document_identity_from_doc(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "title": doc.get("name") or doc.get("document_name") or doc.get("title") or "",
        "document_id": doc.get("id") or doc.get("document_id"),
        "document_url": doc.get("webViewLink") or doc.get("document_url") or doc.get("url") or "",
    }


def _unique_document_candidates(message: str, search_matches: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    """Build a deterministic candidate list for v1.3.5 retrieval.

    The list combines:
    - AI_OS_MASTER_STATE first,
    - search matches from the index/fullText search,
    - known Governance documents.
    """
    safe_limit = max(1, min(int(limit or 5), 12))
    drive_service = _drive()
    candidates: List[Dict[str, Any]] = []
    seen: set = set()

    def add_candidate(raw: Dict[str, Any], source: str) -> None:
        title = _document_title_from_match(raw)
        doc_id = raw.get("document_id") or raw.get("id")
        key = doc_id or title
        if not key or key in seen:
            return
        seen.add(key)
        candidates.append({
            "title": title,
            "document_id": doc_id,
            "document_url": raw.get("document_url") or raw.get("url") or raw.get("webViewLink") or "",
            "source": source,
            "match_score": raw.get("score"),
            "match_type": raw.get("match_type"),
            "snippet": raw.get("snippet", ""),
        })

    # Master state is always first source of truth. Prefer v1.0 if it exists, otherwise legacy name.
    for master_name in ["AI_OS_MASTER_STATE_v1.0", MASTER_STATE_DOCUMENT_NAME]:
        try:
            doc = _find_google_doc_by_exact_name_anywhere(drive_service, master_name)
            if doc:
                identity = _document_identity_from_doc(doc)
                add_candidate({**identity, "score": 9999, "match_type": "master_state"}, "master_state")
                break
        except Exception:
            continue

    for match in search_matches or []:
        add_candidate(match, "search")

    # Governance documents are highly relevant for AI_OS operation. Add them as fallback candidates.
    for name in GOVERNANCE_DOCUMENT_CANDIDATES:
        try:
            doc = _find_google_doc_by_exact_name_anywhere(drive_service, name)
            if doc:
                identity = _document_identity_from_doc(doc)
                add_candidate({**identity, "score": 50, "match_type": "governance_candidate"}, "governance")
        except Exception:
            continue
        if len(candidates) >= max(safe_limit * 3, safe_limit + 6):
            break

    return candidates


def _score_working_context_document(candidate: Dict[str, Any], working_context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Score a document using selected snippet scores and metadata.

    This is deterministic and transparent for debug=true. It does not use AI.
    """
    selected_blocks = (working_context or {}).get("selected_blocks") or []
    snippet_score = 0.0
    matched_keywords = set()
    for block in selected_blocks:
        try:
            snippet_score += float(block.get("score") or 0)
        except Exception:
            pass
        for kw in block.get("matched_keywords") or []:
            matched_keywords.add(kw)

    source_bonus = 0.0
    if candidate.get("source") == "master_state":
        source_bonus = 10.0
    elif candidate.get("source") == "search":
        source_bonus = 3.0
    elif candidate.get("source") == "governance":
        source_bonus = 1.0

    match_score = candidate.get("match_score") or 0
    try:
        match_score = float(match_score)
    except Exception:
        match_score = 0.0

    total = snippet_score + source_bonus + min(match_score, 20.0) * 0.1 + len(matched_keywords) * 0.5
    updated = dict(candidate)
    updated["relevance_score"] = round(total, 4)
    updated["snippet_score"] = round(snippet_score, 4)
    updated["matched_keywords"] = sorted(matched_keywords)
    return updated


def _build_knowledge_retrieval_context(message: str, limit: int = 5) -> Dict[str, Any]:
    """AI_OS v1.3.5 Knowledge Retrieval.

    Creates one unified WorkingContext from multiple relevant documents.
    Fallback behavior: if multi-document retrieval fails, caller can use legacy v1.3.4.2 context.
    """
    cfg = _retrieval_config()
    safe_limit = max(1, min(int(limit or cfg["knowledge_retrieval_limit"]), cfg["knowledge_retrieval_limit"], 12))
    snippets_per_document = cfg["snippets_per_document"]
    max_chars_per_snippet = cfg["max_chars_per_snippet"]
    max_context_chars = cfg["max_context_chars"]
    min_relevance_score = cfg["min_relevance_score"]

    search_result = _search_ai_os(query=message, limit=max(safe_limit * 3, safe_limit + 4))
    matches = _orchestrator_compact_matches(search_result, max(safe_limit * 3, safe_limit + 4))
    candidates = _unique_document_candidates(message, matches, safe_limit)

    document_contexts: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []

    for candidate in candidates:
        title = candidate.get("title")
        if not title:
            continue
        try:
            wc = _build_working_context(
                query=message,
                document_name=title,
                max_snippets=snippets_per_document,
                max_chars_per_snippet=max_chars_per_snippet,
                include_scores=True,
            )
            scored_candidate = _score_working_context_document(candidate, wc)
            # Keep master state even with low score; apply threshold to other docs.
            if scored_candidate.get("source") != "master_state" and scored_candidate.get("relevance_score", 0) < min_relevance_score:
                continue
            document_contexts.append({
                **scored_candidate,
                "working_context": wc,
                "selected_blocks": wc.get("selected_blocks") or [],
                "text_length": wc.get("text_length", 0),
                "blocks_count": wc.get("blocks_count", 0),
                "keywords": wc.get("keywords") or [],
            })
        except Exception as exc:
            errors.append({"document": title, "error": _safe_error_text(exc)})

    document_contexts = sorted(
        document_contexts,
        key=lambda item: (
            0 if item.get("source") == "master_state" else 1,
            -float(item.get("relevance_score") or 0),
            item.get("title") or "",
        ),
    )[:safe_limit]

    # Build unified selected snippets with a global char budget.
    unified_blocks: List[Dict[str, Any]] = []
    used_chars = 0
    for doc_ctx in document_contexts:
        for block in doc_ctx.get("selected_blocks") or []:
            text = (block.get("text") or "").strip()
            if not text:
                continue
            if used_chars >= max_context_chars:
                break
            remaining = max_context_chars - used_chars
            clipped = text if len(text) <= remaining else text[:remaining].rstrip() + "..."
            used_chars += len(clipped)
            unified_blocks.append({
                "document_name": doc_ctx.get("title"),
                "document_id": doc_ctx.get("document_id"),
                "document_url": doc_ctx.get("document_url"),
                "block_id": block.get("id"),
                "text": clipped,
                "matched_keywords": block.get("matched_keywords") or [],
                "score": block.get("score"),
                "document_relevance_score": doc_ctx.get("relevance_score"),
            })
        if used_chars >= max_context_chars:
            break

    return {
        "query": message,
        "pipeline_version": cfg["pipeline_version"],
        "retrieval_enabled": True,
        "config": cfg,
        "search_found": search_result.get("found"),
        "index_status": search_result.get("index_status"),
        "requires_refresh_index": search_result.get("requires_refresh_index", False),
        "candidate_count": len(candidates),
        "used_document_count": len(document_contexts),
        "used_documents": [
            {
                "document_name": item.get("title"),
                "document_id": item.get("document_id"),
                "document_url": item.get("document_url"),
                "source": item.get("source"),
                "relevance_score": item.get("relevance_score"),
                "matched_keywords": item.get("matched_keywords") or [],
                "selected_snippet_count": len(item.get("selected_blocks") or []),
                "text_length": item.get("text_length", 0),
            }
            for item in document_contexts
        ],
        "document_contexts": document_contexts,
        "selected_blocks": unified_blocks,
        "context_chars": used_chars,
        "errors": errors,
        "created_utc": _now_iso(),
        "provider": None,
        "ai_response": None,
    }


def _build_legacy_single_document_context(message: str, limit: int = 5) -> Dict[str, Any]:
    """v1.3.4.2-compatible context builder used for rollback/fallback."""
    safe_limit = max(1, min(int(limit or 5), 10))

    master_state = _load_master_state()
    search_result = _search_ai_os(query=message, limit=safe_limit)
    matches = _orchestrator_compact_matches(search_result, safe_limit)

    working_context = None
    working_context_error = None
    try:
        selected_document_name = _choose_working_context_document(message, matches)
        working_context = _build_working_context(
            query=message,
            document_name=selected_document_name,
            max_snippets=5,
            max_chars_per_snippet=1200,
            include_scores=True,
        )
    except Exception as exc:
        working_context_error = _safe_error_text(exc)

    return {
        "query": message,
        "mode": "legacy_single_document",
        "master_state": master_state,
        "search_found": search_result.get("found"),
        "match_count": search_result.get("match_count", 0),
        "matches": matches,
        "working_context_used": working_context is not None,
        "working_context": working_context,
        "knowledge_retrieval_used": False,
        "knowledge_retrieval": None,
        "knowledge_retrieval_error": None,
        "working_context_error": working_context_error,
        "index_status": search_result.get("index_status"),
        "requires_refresh_index": search_result.get("requires_refresh_index", False),
    }


def _orchestrator_build_context(message: str, limit: int = 5) -> Dict[str, Any]:
    """Build context for /orchestrator/ask.

    v1.3.5 adds Knowledge Retrieval. If disabled or failing, it automatically
    falls back to the stable v1.3.4.2 single-document WorkingContext.
    """
    if not ENABLE_KNOWLEDGE_RETRIEVAL:
        context = _build_legacy_single_document_context(message=message, limit=limit)
        context["knowledge_retrieval_error"] = "ENABLE_KNOWLEDGE_RETRIEVAL=false"
        return context

    try:
        kr = _build_knowledge_retrieval_context(message=message, limit=limit)
        master_state = _load_master_state()
        return {
            "query": message,
            "mode": "knowledge_retrieval",
            "master_state": master_state,
            "search_found": kr.get("search_found"),
            "match_count": kr.get("used_document_count", 0),
            "matches": kr.get("used_documents", []),
            "working_context_used": bool(kr.get("selected_blocks")),
            "working_context": {
                "query": message,
                "document_name": "MULTI_DOCUMENT_WORKING_CONTEXT",
                "document_id": None,
                "document_url": None,
                "text_length": kr.get("context_chars", 0),
                "keywords": sorted({kw for doc in kr.get("used_documents", []) for kw in (doc.get("matched_keywords") or [])}),
                "blocks_count": len(kr.get("selected_blocks") or []),
                "selected_blocks": kr.get("selected_blocks") or [],
                "created_utc": kr.get("created_utc"),
                "pipeline_version": kr.get("pipeline_version"),
                "provider": None,
                "ai_response": None,
            },
            "knowledge_retrieval_used": True,
            "knowledge_retrieval": kr,
            "knowledge_retrieval_error": None,
            "working_context_error": None,
            "index_status": kr.get("index_status"),
            "requires_refresh_index": kr.get("requires_refresh_index", False),
        }
    except Exception as exc:
        context = _build_legacy_single_document_context(message=message, limit=limit)
        context["knowledge_retrieval_error"] = _safe_error_text(exc)
        return context

def _orchestrator_context_text(context: Dict[str, Any]) -> str:
    lines = []
    lines.append(f"Dotaz: {context.get('query')}")
    lines.append(f"Režim kontextu: {context.get('mode') or 'unknown'}")

    master_state = context.get("master_state") or {}
    lines.append("\n=== AI_OS_MASTER_STATE — prvý zdroj pravdy ===")
    if master_state.get("loaded"):
        lines.append(f"Dokument: {master_state.get('name')}")
        if master_state.get("document_url"):
            lines.append(f"URL: {master_state.get('document_url')}")
        if master_state.get("truncated"):
            lines.append("Poznámka: AI_OS_MASTER_STATE bol skrátený pre bezpečný kontext.")
        lines.append(master_state.get("text", ""))
    else:
        lines.append(
            "AI_OS_MASTER_STATE sa nepodarilo načítať. "
            f"Chyba: {master_state.get('error') or 'neznáma chyba'}"
        )

    kr = context.get("knowledge_retrieval") or {}
    if context.get("knowledge_retrieval_used") and kr:
        lines.append("\n=== KNOWLEDGE RETRIEVAL (Vyhľadanie znalostí) ===")
        lines.append(f"Pipeline: {kr.get('pipeline_version')}")
        lines.append(f"Použité dokumenty: {kr.get('used_document_count', 0)}")
        lines.append(f"Veľkosť zjednoteného kontextu: {kr.get('context_chars', 0)} znakov")
        if kr.get("errors"):
            lines.append(f"Chyby pri čítaní niektorých dokumentov: {len(kr.get('errors') or [])}")

        lines.append("\nPoužité dokumenty:")
        for i, doc in enumerate(kr.get("used_documents") or [], start=1):
            lines.append(
                f"{i}. {doc.get('document_name')} "
                f"(score={doc.get('relevance_score')}, source={doc.get('source')})"
            )
            if doc.get("document_url"):
                lines.append(f"   URL: {doc.get('document_url')}")
            if doc.get("matched_keywords"):
                lines.append(f"   Kľúčové slová: {', '.join(doc.get('matched_keywords') or [])}")

        lines.append("\nVybrané úryvky:")
        for i, block in enumerate(kr.get("selected_blocks") or [], start=1):
            lines.append(f"\n[{i}] Dokument: {block.get('document_name')}")
            if block.get("score") is not None:
                lines.append(f"Skóre úryvku: {block.get('score')}; skóre dokumentu: {block.get('document_relevance_score')}")
            if block.get("matched_keywords"):
                lines.append(f"Zhoda slov: {', '.join(block.get('matched_keywords') or [])}")
            lines.append(block.get("text") or "")
    else:
        lines.append("\n")
        lines.append(_working_context_text(context.get("working_context")))

        lines.append("\n=== Ďalšie nájdené dokumenty ===")
        lines.append(f"Nájdené dokumenty: {context.get('match_count', 0)}")
        for i, item in enumerate(context.get("matches", []), start=1):
            lines.append(f"\n[{i}] {item.get('title') or item.get('document_name')}")
            if item.get("url") or item.get("document_url"):
                lines.append(f"URL: {item.get('url') or item.get('document_url')}")
            if item.get("score") is not None:
                lines.append(f"Skóre: {item.get('score')}")
            if item.get("snippet"):
                lines.append(f"Úryvok: {item.get('snippet')}")

    if context.get("knowledge_retrieval_error"):
        lines.append("\n=== Knowledge Retrieval fallback ===")
        lines.append(f"Chyba: {context.get('knowledge_retrieval_error')}")
        lines.append("Použitá stabilná fallback logika v1.3.4.2.")

    return "\n".join(lines)

def _truncate_text(value: Any, max_chars: int) -> str:
    text = "" if value is None else str(value)
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "\n\n[TRUNCATED_FOR_MEMORY_SAFETY]"


def _orchestrator_user_prompt(message: str, context: Dict[str, Any]) -> str:
    # v1.3.5.1: keep the AI prompt compact so Render Free 512 MB does not crash
    # while calling Gemini/OpenAI. Knowledge Retrieval still runs; only the prompt
    # sent to the AI model is bounded.
    context_text = _truncate_text(_orchestrator_context_text(context), AI_PROMPT_MAX_CHARS)
    return (
        "Úloha od Daniela:\n"
        f"{message}\n\n"
        "Dostupný kontext z AI_OS dokumentov:\n"
        f"{context_text}\n\n"
        "Odpovedz po slovensky ako čistý text pre používateľa. "
        "Nevracaj JSON. Nevypisuj interné polia ako working_context, provider_attempts, "
        "reasoning_engine, context, used_documents ani project_id. "
        "Ak treba, uveď iba stručnú odpoveď a ďalší konkrétny krok."
    )


def _compact_block_for_debug(block: Dict[str, Any], preview_chars: Optional[int] = None) -> Dict[str, Any]:
    """Return a small debug-safe block without full text.

    v1.3.5.4 rule: debug=true must explain what happened, not return the
    full WorkingContext. This prevents browser hangs and Render Free memory spikes.
    """
    preview_limit = _safe_int(preview_chars or DEBUG_TEXT_PREVIEW_CHARS, 220, 80, 1000)
    return {
        "document_name": block.get("document_name"),
        "document_id": block.get("document_id"),
        "document_url": block.get("document_url"),
        "block_id": block.get("block_id") or block.get("id"),
        "score": block.get("score"),
        "document_relevance_score": block.get("document_relevance_score"),
        "matched_keywords": (block.get("matched_keywords") or [])[:10],
        "text_preview": _truncate_text(block.get("text"), preview_limit),
        "text_length": len(block.get("text") or ""),
    }


def _compact_working_context_for_debug(wc: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not wc:
        return None
    blocks = wc.get("selected_blocks") or []
    max_blocks = _safe_int(DEBUG_MAX_BLOCKS, 8, 1, 30)
    return {
        "query": wc.get("query"),
        "document_name": wc.get("document_name"),
        "document_id": wc.get("document_id"),
        "document_url": wc.get("document_url"),
        "text_length": wc.get("text_length"),
        "keywords": (wc.get("keywords") or [])[:20],
        "blocks_count": wc.get("blocks_count"),
        "selected_block_count": len(blocks),
        "selected_blocks_preview": [_compact_block_for_debug(block) for block in blocks[:max_blocks]],
        "truncated_blocks": max(0, len(blocks) - max_blocks),
        "created_utc": wc.get("created_utc"),
        "pipeline_version": wc.get("pipeline_version"),
        "provider": wc.get("provider"),
        "ai_response": None,
    }


def _compact_knowledge_retrieval_for_debug(kr: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not kr:
        return None
    max_blocks = _safe_int(DEBUG_MAX_BLOCKS, 8, 1, 30)
    selected_blocks = kr.get("selected_blocks") or []
    compact_documents = []
    for doc in (kr.get("used_documents") or [])[:12]:
        compact_documents.append({
            "document_name": doc.get("document_name"),
            "document_id": doc.get("document_id"),
            "document_url": doc.get("document_url"),
            "source": doc.get("source"),
            "relevance_score": doc.get("relevance_score"),
            "matched_keywords": (doc.get("matched_keywords") or [])[:10],
            "selected_snippet_count": doc.get("selected_snippet_count"),
            "text_length": doc.get("text_length"),
        })
    return {
        "query": kr.get("query"),
        "pipeline_version": kr.get("pipeline_version"),
        "retrieval_enabled": kr.get("retrieval_enabled"),
        "config": kr.get("config"),
        "search_found": kr.get("search_found"),
        "index_status": kr.get("index_status"),
        "requires_refresh_index": kr.get("requires_refresh_index", False),
        "candidate_count": kr.get("candidate_count"),
        "used_document_count": kr.get("used_document_count"),
        "used_documents": compact_documents,
        "selected_block_count": len(selected_blocks),
        "selected_blocks_preview": [_compact_block_for_debug(block) for block in selected_blocks[:max_blocks]],
        "truncated_blocks": max(0, len(selected_blocks) - max_blocks),
        "context_chars": kr.get("context_chars"),
        "error_count": len(kr.get("errors") or []),
        "errors_preview": (kr.get("errors") or [])[:5],
        "created_utc": kr.get("created_utc"),
    }


def _debug_payload_compact(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Hard cap debug response size as a last safety line.

    Normal compacting above should already keep responses small. This function
    prevents any unexpected field from making the JSON huge.
    """
    max_chars = _safe_int(MAX_DEBUG_CHARS, 3000, 1000, 20000)
    text = json.dumps(payload, ensure_ascii=False)
    if len(text) <= max_chars:
        payload["debug_size_chars"] = len(text)
        payload["debug_truncated"] = False
        return payload
    safe = {
        "version": payload.get("version"),
        "service": payload.get("service"),
        "action": payload.get("action"),
        "message": payload.get("message"),
        "reasoning_engine": payload.get("reasoning_engine"),
        "reasoning_model": payload.get("reasoning_model"),
        "provider_attempts": payload.get("provider_attempts"),
        "context_mode": payload.get("context_mode"),
        "knowledge_retrieval_used": payload.get("knowledge_retrieval_used"),
        "knowledge_retrieval": payload.get("knowledge_retrieval"),
        "knowledge_retrieval_error": payload.get("knowledge_retrieval_error"),
        "working_context_used": payload.get("working_context_used"),
        "working_context": payload.get("working_context"),
        "working_context_error": payload.get("working_context_error"),
        "saved_document": payload.get("saved_document"),
        "time_utc": payload.get("time_utc"),
        "time_local": payload.get("time_local"),
        "timezone": payload.get("timezone"),
        "debug_truncated": True,
        "debug_size_chars_before_truncate": len(text),
    }
    # If still large, keep only the minimum operational diagnostic fields.
    text2 = json.dumps(safe, ensure_ascii=False)
    if len(text2) > max_chars:
        kr = safe.get("knowledge_retrieval") or {}
        safe["knowledge_retrieval"] = {
            "pipeline_version": kr.get("pipeline_version"),
            "used_document_count": kr.get("used_document_count"),
            "used_documents": (kr.get("used_documents") or [])[:6],
            "selected_block_count": kr.get("selected_block_count"),
            "context_chars": kr.get("context_chars"),
            "error_count": kr.get("error_count"),
        }
        wc = safe.get("working_context") or {}
        safe["working_context"] = {
            "document_name": wc.get("document_name"),
            "text_length": wc.get("text_length"),
            "selected_block_count": wc.get("selected_block_count"),
            "pipeline_version": wc.get("pipeline_version"),
        }
    safe["debug_size_chars"] = len(json.dumps(safe, ensure_ascii=False))
    return safe

def _safe_error_text(exc: Exception, limit: int = 800) -> str:
    """Return short safe error text without secrets."""
    text = str(exc)
    openai_key = os.getenv("OPENAI_API_KEY") or ""
    gemini_key = os.getenv("GEMINI_API_KEY") or ""
    for secret in (openai_key, gemini_key):
        if secret:
            text = text.replace(secret, "***")
    return text[:limit]


def _response_error_summary(provider: str, response: httpx.Response) -> str:
    try:
        data = response.json()
        if isinstance(data, dict):
            error = data.get("error")
            if isinstance(error, dict):
                message = error.get("message") or error.get("status") or str(error)
                code = error.get("code") or error.get("type") or response.status_code
                return f"{provider} API error {response.status_code} ({code}): {message}"
            return f"{provider} API error {response.status_code}: {json.dumps(data, ensure_ascii=False)[:800]}"
    except Exception:
        pass
    return f"{provider} API error {response.status_code}: {response.text[:800]}"


async def _call_openai_reasoning(message: str, context: Dict[str, Any]) -> Optional[str]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None

    payload = {
        "model": OPENAI_MODEL,
        "input": [
            {"role": "system", "content": [{"type": "input_text", "text": ORCHESTRATOR_SYSTEM_PROMPT}]},
            {"role": "user", "content": [{"type": "input_text", "text": _orchestrator_user_prompt(message, context)}]},
        ],
    }

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            "https://api.openai.com/v1/responses",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )

    if response.status_code >= 400:
        raise RuntimeError(_response_error_summary("OpenAI", response))

    data = response.json()
    if data.get("output_text"):
        return data["output_text"]

    # Fallback parser for structured Responses API output.
    texts = []
    for item in data.get("output", []) or []:
        for content in item.get("content", []) or []:
            if content.get("type") in ("output_text", "text") and content.get("text"):
                texts.append(content["text"])
    return "\n".join(texts).strip() if texts else json.dumps(data, ensure_ascii=False)[:4000]


async def _call_gemini_reasoning(message: str, context: Dict[str, Any]) -> Optional[str]:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return None

    endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
    payload = {
        "systemInstruction": {
            "parts": [{"text": ORCHESTRATOR_SYSTEM_PROMPT}]
        },
        "contents": [
            {
                "role": "user",
                "parts": [{"text": _orchestrator_user_prompt(message, context)}],
            }
        ],
        "generationConfig": {
            "temperature": 0.2,
        },
    }

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            endpoint,
            params={"key": api_key},
            headers={"Content-Type": "application/json"},
            json=payload,
        )

    if response.status_code >= 400:
        raise RuntimeError(_response_error_summary("Gemini", response))

    data = response.json()
    texts = []
    for candidate in data.get("candidates", []) or []:
        content = candidate.get("content") or {}
        for part in content.get("parts", []) or []:
            if part.get("text"):
                texts.append(part["text"])
    return "\n".join(texts).strip() if texts else json.dumps(data, ensure_ascii=False)[:4000]


async def _call_ai_reasoning(message: str, context: Dict[str, Any]) -> Dict[str, Any]:
    """Try configured AI providers in order. Never crash the orchestrator if a provider fails."""
    attempts: List[Dict[str, Any]] = []

    for provider in _configured_provider_order():
        try:
            if provider == "openai":
                if not os.getenv("OPENAI_API_KEY"):
                    attempts.append({"provider": "openai", "status": "skipped", "reason": "OPENAI_API_KEY not configured"})
                    continue
                answer = await _call_openai_reasoning(message, context)
                if answer:
                    attempts.append({"provider": "openai", "status": "success", "model": OPENAI_MODEL})
                    return {"answer": answer, "reasoning_engine": "openai", "model": OPENAI_MODEL, "attempts": attempts}
                attempts.append({"provider": "openai", "status": "empty_response", "model": OPENAI_MODEL})

            elif provider == "gemini":
                if not os.getenv("GEMINI_API_KEY"):
                    attempts.append({"provider": "gemini", "status": "skipped", "reason": "GEMINI_API_KEY not configured"})
                    continue
                answer = await _call_gemini_reasoning(message, context)
                if answer:
                    attempts.append({"provider": "gemini", "status": "success", "model": GEMINI_MODEL})
                    return {"answer": answer, "reasoning_engine": "gemini", "model": GEMINI_MODEL, "attempts": attempts}
                attempts.append({"provider": "gemini", "status": "empty_response", "model": GEMINI_MODEL})

        except Exception as exc:
            attempts.append({
                "provider": provider,
                "status": "failed",
                "model": OPENAI_MODEL if provider == "openai" else GEMINI_MODEL,
                "error": _safe_error_text(exc),
            })
            continue

    return {"answer": None, "reasoning_engine": "deterministic", "model": None, "attempts": attempts}


def _orchestrator_deterministic_answer(message: str, context: Dict[str, Any]) -> str:
    matches = context.get("matches", [])
    if context.get("requires_refresh_index"):
        return (
            "Index dokumentov je prázdny. Najprv otvor: "
            "https://ai-os-document-agent.onrender.com/refresh-index "
            "a potom zopakuj požiadavku."
        )
    if not matches:
        return (
            "Nenašiel som relevantný dokument v AI_OS indexe. "
            "Skús presnejší názov dokumentu alebo najprv obnov index cez /refresh-index."
        )

    lines = [
        "Našiel som tieto najbližšie dokumenty v AI_OS:",
    ]
    for i, item in enumerate(matches, start=1):
        lines.append(f"{i}. {item.get('title')}")
        if item.get("url"):
            lines.append(f"   {item.get('url')}")
        if item.get("snippet"):
            lines.append(f"   Úryvok: {item.get('snippet')[:300]}")
    lines.append("\nĎalší krok: povedz mi, ktorý dokument mám otvoriť alebo čo mám z výsledkov spracovať.")
    return "\n".join(lines)


def _clean_answer_for_user(answer: Any) -> str:
    """Return a strict clean user-facing answer.

    Production output must never expose diagnostic JSON. If the model returns
    a JSON object as text, extract only its answer/odpoveď field. If no answer
    field exists, return a short safe text instead of leaking internals.
    """
    if answer is None:
        return ""
    if not isinstance(answer, str):
        return str(answer)

    value = answer.strip()
    if not value:
        return ""

    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", value, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        value = fenced.group(1).strip()

    def _extract_from_json_text(candidate: str) -> Optional[str]:
        try:
            parsed = json.loads(candidate)
        except Exception:
            return None
        if isinstance(parsed, dict):
            nested = parsed.get("answer") or parsed.get("odpoveď") or parsed.get("odpoved")
            if nested:
                nested_text = str(nested).strip()
                # Recursively clean if answer itself is a JSON string.
                if nested_text.startswith("{") or nested_text.startswith("```"):
                    return _clean_answer_for_user(nested_text)
                return nested_text
        return None

    direct = _extract_from_json_text(value)
    if direct:
        return direct

    # If JSON is embedded inside surrounding text, try to extract it safely.
    first = value.find("{")
    last = value.rfind("}")
    if first >= 0 and last > first:
        embedded = _extract_from_json_text(value[first:last + 1])
        if embedded:
            return embedded

    # Remove common diagnostic sections if model returned a semi-structured answer.
    diagnostic_markers = [
        "\nused_documents", "\nused documents", "\npoužité dokumenty", "\nproject_id",
        "\nprovider_attempts", "\nworking_context", "\nreasoning_engine", "\ncontext:",
    ]
    lowered = value.lower()
    cut_positions = [lowered.find(marker) for marker in diagnostic_markers if lowered.find(marker) >= 0]
    if cut_positions:
        value = value[:min(cut_positions)].strip()

    return value




async def _orchestrate(payload: OrchestratorRequest) -> Dict[str, Any]:
    if not payload.message or not payload.message.strip():
        raise HTTPException(status_code=400, detail="message is required.")

    message = payload.message.strip()
    context = _orchestrator_build_context(message=message, limit=payload.limit or 5)

    ai_result = await _call_ai_reasoning(message, context)
    answer = ai_result.get("answer")
    reasoning_engine = ai_result.get("reasoning_engine") or "deterministic"
    reasoning_model = ai_result.get("model")
    provider_attempts = ai_result.get("attempts", [])

    if not answer:
        answer = _orchestrator_deterministic_answer(message, context)
        reasoning_engine = "deterministic"
        reasoning_model = None

    saved_document = None
    if payload.write_result:
        title = payload.result_title or f"AI_OS_ORCHESTRATOR_RESULT_{_today_id_date()}"
        doc_payload = DocumentRequest(
            title=title,
            object_type="DOCUMENT",
            document_category=ORCHESTRATOR_RESULT_CATEGORY,
            project_id=(payload.project_id or "AI_OS"),
            status="APPROVED",
            owner=DEFAULT_OWNER,
            version="1.0",
            content=(
                "AI_OS_ORCHESTRATOR_RESULT\n"
                + _timestamp_block("Created")
                + f"USER_MESSAGE:\n{message}\n\n"
                + f"REASONING_ENGINE: {reasoning_engine}\n"
                + f"REASONING_MODEL: {reasoning_model}\n"
                + "PROVIDER_ATTEMPTS:\n"
                + json.dumps(provider_attempts, ensure_ascii=False, indent=2)
                + "\n\nANSWER:\n"
                + f"{answer}\n\n"
                + "CONTEXT:\n"
                + json.dumps(context, ensure_ascii=False, indent=2)
            ),
            source_object_id="AI_OS_ORCHESTRATOR",
            related_objects=[],
        )
        saved_document = _create_document(doc_payload)

    user_answer = _clean_answer_for_user(answer)

    if not payload.debug:
        return {
            "status": "success",
            "answer": user_answer,
        }

    debug_payload = {
        "version": "1.3.5.4",
        "service": APP_NAME,
        "action": "ORCHESTRATE",
        "message": message,
        "reasoning_engine": reasoning_engine,
        "reasoning_model": reasoning_model,
        "provider_attempts": provider_attempts,
        "raw_answer_preview": _truncate_text(answer, 600),
        "context_mode": context.get("mode"),
        "knowledge_retrieval_used": context.get("knowledge_retrieval_used", False),
        "knowledge_retrieval": _compact_knowledge_retrieval_for_debug(context.get("knowledge_retrieval")),
        "knowledge_retrieval_error": context.get("knowledge_retrieval_error"),
        "working_context_used": context.get("working_context_used", False),
        "working_context": _compact_working_context_for_debug(context.get("working_context")),
        "working_context_error": context.get("working_context_error"),
        "saved_document": saved_document,
        "time_utc": _now_iso(),
        "time_local": _now_local_iso(),
        "timezone": AI_OS_TIMEZONE_NAME,
    }

    return {
        "status": "success",
        "answer": user_answer,
        "debug": _debug_payload_compact(debug_payload),
    }


@app.get("/orchestrator/health")
def orchestrator_health_get(request: Request):
    _check_token(request)
    status = _provider_status()
    master_state_status = _master_state_status()
    return {
        "status": "ok",
        "service": APP_NAME,
        "orchestrator": "enabled",
        **status,
        **master_state_status,
        # Backward compatibility with earlier health checks:
        "openai_configured": status["openai_configured"],
        "model": status["openai_model"],
        "document_agent_internal": True,
        "knowledge_retrieval": _retrieval_config(),
        "time_utc": _now_iso(),
        "time_local": _now_local_iso(),
    }


@app.get("/orchestrator/ask")
async def orchestrator_ask_get(
    request: Request,
    message: str,
    write_result: bool = False,
    result_title: Optional[str] = None,
    project_id: str = "AI_OS",
    limit: int = 5,
    debug: bool = False,
):
    _check_token(request)
    return await _orchestrate(OrchestratorRequest(
        message=message,
        write_result=write_result,
        result_title=result_title,
        project_id=project_id,
        limit=limit,
        debug=debug,
    ))


@app.post("/orchestrator/ask")
async def orchestrator_ask_post(request: Request, payload: OrchestratorRequest):
    _check_token(request)
    return await _orchestrate(payload)


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
