
import os
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, List

from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.responses import JSONResponse

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


APP_NAME = "AI_OS_ORCHESTRATOR_V1_4_4_1_CAP0041_GOOGLE_DOCS_PHYSICAL_WRITE"
VERSION = "1.4.4.1-cap0041-google-docs-physical-write"

API_TOKEN = os.getenv("API_TOKEN", "").strip()

ENABLE_EXECUTIVE_ASSISTANT = os.getenv("ENABLE_EXECUTIVE_ASSISTANT", "true").lower() == "true"
ENABLE_CAPABILITY_RUNTIME = os.getenv("ENABLE_CAPABILITY_RUNTIME", "true").lower() == "true"
ENABLE_KNOWLEDGE_EVOLUTION = os.getenv("ENABLE_KNOWLEDGE_EVOLUTION", "true").lower() == "true"
ENABLE_DOCUMENT_AGENT = os.getenv("ENABLE_DOCUMENT_AGENT", "true").lower() == "true"
ENABLE_GOOGLE_DOCS_WRITE = os.getenv("ENABLE_GOOGLE_DOCS_WRITE", "true").lower() == "true"
ENABLE_DRIVE_REFRESH = os.getenv("ENABLE_DRIVE_REFRESH", "false").lower() == "true"

AI_OS_ROOT_FOLDER_ID = os.getenv("AI_OS_ROOT_FOLDER_ID", "").strip()
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()

SCOPES = [
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive",
]

app = FastAPI(title=APP_NAME, version=VERSION)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _check_token(request: Request) -> None:
    if not API_TOKEN:
        raise HTTPException(status_code=503, detail="API_TOKEN is not configured")
    header_token = request.headers.get("x-api-token", "").strip()
    query_token = request.query_params.get("token", "").strip()
    auth = request.headers.get("authorization", "").strip()
    bearer_token = auth.replace("Bearer ", "", 1).strip() if auth.lower().startswith("bearer ") else ""
    if (header_token or query_token or bearer_token) != API_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")


def _safe_limit(limit: Optional[int], default: int = 5, min_value: int = 1, max_value: int = 20) -> int:
    try:
        value = int(limit if limit is not None else default)
    except Exception:
        value = default
    return max(min_value, min(value, max_value))


def _safe_response(payload: Dict[str, Any], status_code: int = 200) -> JSONResponse:
    payload.setdefault("time_utc", utc_now())
    return JSONResponse(status_code=status_code, content=payload)


def _safe_error(e: Exception, request_id: Optional[str] = None) -> JSONResponse:
    if isinstance(e, HTTPException):
        return _safe_response({"status": "error", "error_type": "http", "detail": e.detail, "request_id": request_id or str(uuid.uuid4())}, e.status_code)
    return _safe_response({"status": "safe_error", "error_type": e.__class__.__name__, "detail": str(e), "request_id": request_id or str(uuid.uuid4())}, 200)


def _google_config_status() -> Dict[str, Any]:
    return {
        "google_docs_write_enabled": ENABLE_GOOGLE_DOCS_WRITE,
        "service_account_json_configured": bool(GOOGLE_SERVICE_ACCOUNT_JSON),
        "root_folder_id_configured": bool(AI_OS_ROOT_FOLDER_ID),
    }


def _load_google_credentials():
    if not GOOGLE_SERVICE_ACCOUNT_JSON:
        raise RuntimeError("GOOGLE_CONFIG_MISSING")
    try:
        info = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
    except Exception as e:
        raise RuntimeError(f"GOOGLE_CONFIG_INVALID_JSON: {e}")
    return service_account.Credentials.from_service_account_info(info, scopes=SCOPES)


def _google_services():
    creds = _load_google_credentials()
    docs_service = build("docs", "v1", credentials=creds, cache_discovery=False)
    drive_service = build("drive", "v3", credentials=creds, cache_discovery=False)
    return docs_service, drive_service


def _check_google_docs_connection() -> Dict[str, Any]:
    if not ENABLE_GOOGLE_DOCS_WRITE:
        return {"status": "SKIP", "reason": "ENABLE_GOOGLE_DOCS_WRITE=false"}
    if not GOOGLE_SERVICE_ACCOUNT_JSON:
        return {"status": "FAIL", "code": "GOOGLE_CONFIG_MISSING"}
    if not AI_OS_ROOT_FOLDER_ID:
        return {"status": "FAIL", "code": "ROOT_FOLDER_MISSING"}
    try:
        _, drive_service = _google_services()
        folder = drive_service.files().get(fileId=AI_OS_ROOT_FOLDER_ID, fields="id,name,mimeType", supportsAllDrives=True).execute()
        return {"status": "PASS", "folder_id": folder.get("id"), "folder_name": folder.get("name"), "mimeType": folder.get("mimeType")}
    except HttpError as e:
        return {"status": "FAIL", "code": "GOOGLE_API_ERROR", "details": str(e)[:1000]}
    except Exception as e:
        return {"status": "FAIL", "code": e.__class__.__name__, "details": str(e)[:1000]}


def _create_google_doc(title: str, content: str, folder_id: Optional[str] = None) -> Dict[str, Any]:
    if not ENABLE_GOOGLE_DOCS_WRITE:
        return {"status": "error", "code": "GOOGLE_DOCS_WRITE_DISABLED", "message": "ENABLE_GOOGLE_DOCS_WRITE=false"}
    target_folder_id = (folder_id or AI_OS_ROOT_FOLDER_ID or "").strip()
    if not GOOGLE_SERVICE_ACCOUNT_JSON:
        return {"status": "error", "code": "GOOGLE_CONFIG_MISSING", "message": "GOOGLE_SERVICE_ACCOUNT_JSON is missing"}
    if not target_folder_id:
        return {"status": "error", "code": "ROOT_FOLDER_MISSING", "message": "AI_OS_ROOT_FOLDER_ID is missing"}

    try:
        docs_service, drive_service = _google_services()
        doc = docs_service.documents().create(body={"title": title}).execute()
        document_id = doc.get("documentId")
        if content:
            docs_service.documents().batchUpdate(
                documentId=document_id,
                body={"requests": [{"insertText": {"location": {"index": 1}, "text": content}}]},
            ).execute()
        file_meta = drive_service.files().get(fileId=document_id, fields="parents", supportsAllDrives=True).execute()
        previous_parents = ",".join(file_meta.get("parents", []))
        drive_service.files().update(
            fileId=document_id,
            addParents=target_folder_id,
            removeParents=previous_parents,
            fields="id, parents",
            supportsAllDrives=True,
        ).execute()
        return {"status": "success", "document": {"id": document_id, "title": title, "url": f"https://docs.google.com/document/d/{document_id}/edit", "folder_id": target_folder_id, "created": True}}
    except HttpError as e:
        return {"status": "error", "code": "GOOGLE_API_ERROR", "details": str(e)[:2000]}
    except RuntimeError as e:
        return {"status": "error", "code": str(e).split(":")[0], "details": str(e)[:1000]}
    except Exception as e:
        return {"status": "error", "code": e.__class__.__name__, "details": str(e)[:2000]}


CAPABILITIES: Dict[str, Dict[str, Any]] = {
    "CAP-001": {"id": "CAP-001", "name": "Working Context", "type": "Capability", "status": "ACTIVE", "priority": "P0", "enabled": True},
    "CAP-002": {"id": "CAP-002", "name": "Executive Assistant", "type": "Capability", "status": "ACTIVE", "priority": "P0", "enabled": ENABLE_EXECUTIVE_ASSISTANT, "endpoint": "/assistant"},
    "CAP-003": {"id": "CAP-003", "name": "Capability Runtime", "type": "Capability", "status": "ACTIVE", "priority": "P0", "enabled": ENABLE_CAPABILITY_RUNTIME, "endpoint": "/capability/run"},
    "CAP-004": {"id": "CAP-004", "name": "Document Agent Adapter", "type": "Capability Adapter", "status": "ACTIVE", "priority": "P0", "enabled": ENABLE_DOCUMENT_AGENT, "endpoint": "/capability/document"},
    "CAP-004.1": {"id": "CAP-004.1", "name": "Google Docs Physical Write", "type": "Execution Adapter", "status": "ACTIVE", "priority": "P0", "enabled": ENABLE_GOOGLE_DOCS_WRITE, "endpoint": "/document/create"},
    "CAP-DOC": {"id": "CAP-DOC", "name": "Document Agent", "type": "Capability", "status": "PHYSICAL_WRITE_ENABLED" if ENABLE_GOOGLE_DOCS_WRITE else "ADAPTER_ONLY", "priority": "P0", "enabled": ENABLE_DOCUMENT_AGENT},
    "CAP-KNOW": {"id": "CAP-KNOW", "name": "Knowledge Evolution", "type": "Shared Service Consumer", "status": "ACTIVE", "priority": "P0", "enabled": ENABLE_KNOWLEDGE_EVOLUTION},
}


def _classify_intent(message: str) -> Dict[str, Any]:
    m = (message or "").lower().strip()
    if not m:
        return {"intent": "empty", "capability_id": "CAP-002", "confidence": 0.2}
    if any(w in m for w in ["vytvor dokument", "nový dokument", "dokument", "doc", "docs", "zapíš", "ulož"]):
        return {"intent": "document", "capability_id": "CAP-DOC", "confidence": 0.9}
    if any(w in m for w in ["knowledge", "znalosť", "reuse", "merge", "aktualizuj znalosti", "vyhodnoť"]):
        return {"intent": "knowledge", "capability_id": "CAP-KNOW", "confidence": 0.8}
    if any(w in m for w in ["stav", "health", "status", "funguje", "test"]):
        return {"intent": "status", "capability_id": "CAP-003", "confidence": 0.75}
    return {"intent": "general", "capability_id": "CAP-002", "confidence": 0.65}


def _knowledge_decision(message: str) -> Dict[str, Any]:
    m = (message or "").lower()
    if any(w in m for w in ["vytvor", "nový", "new"]):
        decision = "CREATE NEW"
        reason = "Požiadavka smeruje k vytvoreniu nového artefaktu."
    elif any(w in m for w in ["aktualizuj", "uprav", "merge", "zlúč"]):
        decision = "MERGE"
        reason = "Požiadavka smeruje k úprave alebo zlúčeniu existujúcej znalosti."
    else:
        decision = "REUSE"
        reason = "Bezpečný predvolený režim: najprv použiť existujúce znalosti."
    return {"service": "SRV-001 Knowledge Evolution Engine", "decision": decision, "confidence": 0.8, "reason": reason, "allowed_actions": ["REUSE", "MERGE", "UPDATE", "ARCHIVE", "REMOVE", "CREATE NEW"]}


def _extract_document_title(message: str) -> str:
    raw = (message or "").strip()
    if not raw:
        return "AI_OS Document"
    clean = raw
    for p in ["vytvor nový dokument", "vytvor dokument", "nový dokument", "create document", "document"]:
        if clean.lower().startswith(p):
            clean = clean[len(p):].strip(" :-–—")
            break
    return clean[:120] if clean else "AI_OS Document"


def _default_document_content(title: str, message: str, request_id: str) -> str:
    return f"""# {title}

Status: DRAFT
Created by: AI_OS CAP-004.1 Google Docs Physical Write
Request ID: {request_id}
Created at: {utc_now()}

## Zadanie

{message}

## Poznámka

Tento dokument bol fyzicky vytvorený cez Google Docs API, ak odpoveď obsahuje created=true a document.url.
"""


async def _run_document_capability(message: str, request_id: str, debug: bool = False) -> Dict[str, Any]:
    title = _extract_document_title(message)
    content = _default_document_content(title, message, request_id)
    write_result = _create_google_doc(title=title, content=content)
    ok = write_result.get("status") == "success"
    result = {
        "status": write_result.get("status", "error"),
        "capability_id": "CAP-DOC",
        "capability_name": "Document Agent",
        "action": "CREATE_DOCUMENT",
        "answer": "Dokument bol úspešne fyzicky vytvorený v Google Docs." if ok else "Dokument sa nepodarilo fyzicky vytvoriť.",
        "next_action": "Otvoriť document.url a overiť obsah." if ok else "Skontrolovať GOOGLE_SERVICE_ACCOUNT_JSON, AI_OS_ROOT_FOLDER_ID a zdieľanie priečinka so service accountom.",
        "document": write_result.get("document"),
        "google_write": write_result,
        "knowledge_decision": _knowledge_decision(message),
    }
    if debug:
        result["debug"] = {"title": title, "google_config": _google_config_status(), "content_preview": content[:1000]}
    return result


async def _run_capability(capability_id: str, message: str, request_id: str, debug: bool = False) -> Dict[str, Any]:
    cap = CAPABILITIES.get(capability_id)
    if not cap:
        return {"status": "error", "error": "unknown_capability", "capability_id": capability_id, "answer": "Neznáma Capability.", "next_action": "Over Capability Registry."}
    if not cap.get("enabled", True):
        return {"status": "disabled", "capability_id": cap["id"], "capability_name": cap["name"], "answer": "Capability je vypnutá.", "next_action": "Zapni feature flag alebo vyber inú Capability."}
    if cap["id"] in ["CAP-DOC", "CAP-004", "CAP-004.1"]:
        return await _run_document_capability(message, request_id, debug=debug)

    kd = _knowledge_decision(message)
    if cap["id"] == "CAP-KNOW":
        answer = f"Knowledge Evolution rozhodnutie: {kd['decision']}. Dôvod: {kd['reason']}"
        action = "KNOWLEDGE_DECISION"
    elif cap["id"] == "CAP-003":
        answer = "Capability Runtime je aktívny."
        action = "RUNTIME_STATUS"
    else:
        answer = "Požiadavka bola prijatá Executive Assistantom."
        action = "GENERAL_ASSISTANT_WORKFLOW"
    return {"status": "success", "capability_id": cap["id"], "capability_name": cap["name"], "action": action, "answer": answer, "next_action": "Pokračovať podľa výsledku.", "knowledge_decision": kd}


@app.head("/")
def root_head():
    return JSONResponse(status_code=200, content={})


@app.get("/")
def root():
    return _safe_response({"service": APP_NAME, "status": "running", "message": "AI_OS CAP-004.1 Google Docs Physical Write is available.", "version": VERSION, "google_config": _google_config_status()})


@app.get("/health")
def global_health(request: Request):
    request_id = str(uuid.uuid4())
    try:
        _check_token(request)
        return _safe_response({"status": "ok", "service": APP_NAME, "version": VERSION, "google_config": _google_config_status(), "request_id": request_id})
    except Exception as e:
        return _safe_error(e, request_id)


@app.get("/assistant/health")
def assistant_health(request: Request):
    request_id = str(uuid.uuid4())
    try:
        _check_token(request)
        return _safe_response({"status": "ok", "assistant": "Executive Assistant", "version": VERSION, "enabled": ENABLE_EXECUTIVE_ASSISTANT, "google_docs_physical_write": _google_config_status(), "rollback": "ENABLE_GOOGLE_DOCS_WRITE=false", "request_id": request_id})
    except Exception as e:
        return _safe_error(e, request_id)


@app.get("/orchestrator/health")
def orchestrator_health(request: Request):
    request_id = str(uuid.uuid4())
    try:
        _check_token(request)
        return _safe_response({"status": "ok", "service": APP_NAME, "orchestrator": "enabled", "executive_assistant": "enabled" if ENABLE_EXECUTIVE_ASSISTANT else "disabled", "capability_runtime": "enabled" if ENABLE_CAPABILITY_RUNTIME else "disabled", "document_adapter": "enabled" if ENABLE_DOCUMENT_AGENT else "disabled", "google_docs_physical_write": "enabled" if ENABLE_GOOGLE_DOCS_WRITE else "disabled", "request_id": request_id})
    except Exception as e:
        return _safe_error(e, request_id)


@app.get("/capability/registry")
def capability_registry(request: Request):
    request_id = str(uuid.uuid4())
    try:
        _check_token(request)
        return _safe_response({"status": "success", "registry": list(CAPABILITIES.values()), "count": len(CAPABILITIES), "request_id": request_id})
    except Exception as e:
        return _safe_error(e, request_id)


@app.get("/capability/run")
async def capability_run(request: Request, message: str = Query(""), capability_id: Optional[str] = Query(None), debug: bool = Query(False)):
    request_id = str(uuid.uuid4())
    try:
        _check_token(request)
        if not ENABLE_CAPABILITY_RUNTIME:
            return _safe_response({"status": "disabled", "answer": "Capability Runtime je vypnutý.", "request_id": request_id})
        selected = capability_id or _classify_intent(message)["capability_id"]
        result = await _run_capability(selected, message, request_id, debug=debug)
        result["router"] = _classify_intent(message)
        result["request_id"] = request_id
        return _safe_response(result)
    except Exception as e:
        return _safe_error(e, request_id)


@app.get("/capability/document")
async def capability_document(request: Request, message: str = Query(""), title: Optional[str] = Query(None), content: Optional[str] = Query(None), folder_id: Optional[str] = Query(None), debug: bool = Query(False)):
    request_id = str(uuid.uuid4())
    try:
        _check_token(request)
        msg = message or f"Vytvor dokument {title or 'AI_OS Document'}"
        doc_title = title or _extract_document_title(msg)
        doc_content = content or _default_document_content(doc_title, msg, request_id)
        write_result = _create_google_doc(title=doc_title, content=doc_content, folder_id=folder_id)
        return _safe_response({"status": write_result.get("status", "error"), "capability": "CAP-DOC", "adapter": "CAP-004.1 Google Docs Physical Write", "action": "CREATE_DOCUMENT", "document": write_result.get("document"), "google_write": write_result, "request_id": request_id})
    except Exception as e:
        return _safe_error(e, request_id)


@app.post("/document/create")
async def document_create(request: Request):
    request_id = str(uuid.uuid4())
    try:
        _check_token(request)
        try:
            payload = await request.json()
            if not isinstance(payload, dict):
                payload = {}
        except Exception:
            payload = {}
        title = str(payload.get("title") or "AI_OS Document")[:120]
        content = str(payload.get("content") or _default_document_content(title, "Internal document/create request", request_id))
        folder_id = str(payload.get("folder_id") or "").strip() or None
        write_result = _create_google_doc(title=title, content=content, folder_id=folder_id)
        return _safe_response({"status": write_result.get("status", "error"), "service": "Google Docs Physical Write", "version": VERSION, "document": write_result.get("document"), "google_write": write_result, "request_id": request_id})
    except Exception as e:
        return _safe_error(e, request_id)


@app.get("/assistant")
async def assistant(request: Request, message: str = Query(""), debug: bool = Query(False)):
    request_id = str(uuid.uuid4())
    try:
        _check_token(request)
        if not ENABLE_EXECUTIVE_ASSISTANT:
            return _safe_response({"status": "disabled", "assistant": "Executive Assistant", "answer": "Executive Assistant je vypnutý.", "request_id": request_id})
        router = _classify_intent(message)
        result = await _run_capability(router["capability_id"], message, request_id, debug=debug)
        return _safe_response({"status": result.get("status", "success"), "assistant": "Executive Assistant", "version": VERSION, "route": router, "answer": result.get("answer"), "next_action": result.get("next_action"), "document": result.get("document"), "capability_result": result, "request_id": request_id})
    except Exception as e:
        return _safe_error(e, request_id)


@app.get("/orchestrator/ask")
async def orchestrator_ask(request: Request, message: str = Query(""), limit: int = Query(5), debug: bool = Query(False)):
    request_id = str(uuid.uuid4())
    try:
        _check_token(request)
        router = _classify_intent(message)
        result = await _run_capability(router["capability_id"], message, request_id, debug=debug)
        return _safe_response({"status": "success" if result.get("status") == "success" else result.get("status"), "answer": result.get("answer"), "next_action": result.get("next_action"), "router": router, "limit": _safe_limit(limit), "document": result.get("document"), "capability_result": result, "request_id": request_id})
    except Exception as e:
        return _safe_error(e, request_id)


@app.get("/orchestrator/knowledge-evolution")
def knowledge_evolution(request: Request, message: str = Query(""), limit: int = Query(5), debug: bool = Query(False)):
    request_id = str(uuid.uuid4())
    try:
        _check_token(request)
        return _safe_response({"status": "success", "service": "SRV-001 Knowledge Evolution Engine", "version": VERSION, "message": message, "limit": _safe_limit(limit), "knowledge_evolution": _knowledge_decision(message), "request_id": request_id})
    except Exception as e:
        return _safe_error(e, request_id)


@app.get("/refresh-index")
def refresh_index(request: Request):
    request_id = str(uuid.uuid4())
    try:
        _check_token(request)
        if not ENABLE_DRIVE_REFRESH:
            return _safe_response({"status": "success", "action": "REFRESH_INDEX", "index_status": "ready_safe_noop", "document_count": 0, "note": "Drive refresh je vypnutý v safe runtime režime.", "request_id": request_id})
        return _safe_response({"status": "success", "action": "REFRESH_INDEX", "index_status": "refresh_requested", "document_count": 0, "request_id": request_id})
    except Exception as e:
        return _safe_error(e, request_id)


@app.get("/self-test")
async def self_test(request: Request):
    request_id = str(uuid.uuid4())
    try:
        _check_token(request)
        tests: List[Dict[str, Any]] = []
        tests.append({"name": "root", "status": "PASS"})
        tests.append({"name": "capability_registry", "status": "PASS", "count": len(CAPABILITIES)})
        router = _classify_intent("Vytvor dokument AI_OS Test")
        tests.append({"name": "document_intent_router", "status": "PASS" if router["capability_id"] == "CAP-DOC" else "FAIL", "router": router})
        google_check = _check_google_docs_connection()
        tests.append({"name": "google_docs_connection", **google_check})
        overall = "PASS" if all(t.get("status") in ["PASS", "SKIP"] for t in tests) else "FAIL"
        return _safe_response({"status": "success", "self_test": overall, "version": VERSION, "tests": tests, "request_id": request_id})
    except Exception as e:
        return _safe_error(e, request_id)
