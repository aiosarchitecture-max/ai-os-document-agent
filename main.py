
import os
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, List

from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.responses import JSONResponse

APP_NAME = "AI_OS_ORCHESTRATOR_V1_4_4_2_CAP0041_DRIVE_DIRECT_WRITE"
VERSION = "1.4.4.2-cap0041-drive-direct-write"

API_TOKEN = os.getenv("API_TOKEN", "").strip()
AI_OS_ROOT_FOLDER_ID = os.getenv("AI_OS_ROOT_FOLDER_ID", "").strip()
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()

ENABLE_EXECUTIVE_ASSISTANT = os.getenv("ENABLE_EXECUTIVE_ASSISTANT", "true").lower() == "true"
ENABLE_CAPABILITY_RUNTIME = os.getenv("ENABLE_CAPABILITY_RUNTIME", "true").lower() == "true"
ENABLE_KNOWLEDGE_EVOLUTION = os.getenv("ENABLE_KNOWLEDGE_EVOLUTION", "true").lower() == "true"
ENABLE_DOCUMENT_AGENT = os.getenv("ENABLE_DOCUMENT_AGENT", "true").lower() == "true"
ENABLE_GOOGLE_DOCS_WRITE = os.getenv("ENABLE_GOOGLE_DOCS_WRITE", "true").lower() == "true"
ENABLE_DRIVE_REFRESH = os.getenv("ENABLE_DRIVE_REFRESH", "false").lower() == "true"

GOOGLE_DOC_MIME = "application/vnd.google-apps.document"
FOLDER_MIME = "application/vnd.google-apps.folder"

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/documents",
]

app = FastAPI(title=APP_NAME, version=VERSION)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_response(payload: Dict[str, Any], status_code: int = 200) -> JSONResponse:
    payload.setdefault("time_utc", utc_now())
    return JSONResponse(status_code=status_code, content=payload)


def _safe_error(e: Exception, request_id: Optional[str] = None) -> JSONResponse:
    rid = request_id or str(uuid.uuid4())
    if isinstance(e, HTTPException):
        return _json_response({"status": "error", "detail": e.detail, "request_id": rid}, e.status_code)
    return _json_response({
        "status": "safe_error",
        "error_type": e.__class__.__name__,
        "detail": str(e),
        "request_id": rid,
    }, 200)


def _check_token(request: Request) -> None:
    if not API_TOKEN:
        raise HTTPException(status_code=503, detail="API_TOKEN is not configured")
    header_token = request.headers.get("x-api-token", "").strip()
    query_token = request.query_params.get("token", "").strip()
    auth = request.headers.get("authorization", "").strip()
    bearer_token = auth.replace("Bearer ", "", 1).strip() if auth.lower().startswith("bearer ") else ""
    supplied = header_token or query_token or bearer_token
    if supplied != API_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")


def _client_email() -> Optional[str]:
    try:
        return json.loads(GOOGLE_SERVICE_ACCOUNT_JSON or "{}").get("client_email")
    except Exception:
        return None


def _project_id() -> Optional[str]:
    try:
        return json.loads(GOOGLE_SERVICE_ACCOUNT_JSON or "{}").get("project_id")
    except Exception:
        return None


def _load_google_modules():
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        from googleapiclient.errors import HttpError
        return service_account, build, HttpError
    except Exception as e:
        raise RuntimeError(f"GOOGLE_LIB_IMPORT_ERROR: {e}")


def _google_services():
    if not GOOGLE_SERVICE_ACCOUNT_JSON:
        raise RuntimeError("GOOGLE_CONFIG_MISSING")
    if not AI_OS_ROOT_FOLDER_ID:
        raise RuntimeError("ROOT_FOLDER_MISSING")

    service_account, build, _ = _load_google_modules()

    try:
        info = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
    except Exception as e:
        raise RuntimeError(f"GOOGLE_CONFIG_INVALID_JSON: {e}")

    creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    drive = build("drive", "v3", credentials=creds, cache_discovery=False)
    docs = build("docs", "v1", credentials=creds, cache_discovery=False)
    return drive, docs


def _folder_probe() -> Dict[str, Any]:
    if not GOOGLE_SERVICE_ACCOUNT_JSON:
        return {"status": "FAIL", "code": "GOOGLE_CONFIG_MISSING"}
    if not AI_OS_ROOT_FOLDER_ID:
        return {"status": "FAIL", "code": "ROOT_FOLDER_MISSING"}

    try:
        drive, _ = _google_services()
        fields = "id,name,mimeType,capabilities(canAddChildren,canEdit),permissions(id,emailAddress,role,type)"
        folder = drive.files().get(
            fileId=AI_OS_ROOT_FOLDER_ID,
            fields=fields,
            supportsAllDrives=True,
        ).execute()

        can_add = bool(folder.get("capabilities", {}).get("canAddChildren"))
        can_edit = bool(folder.get("capabilities", {}).get("canEdit"))

        return {
            "status": "PASS" if can_add else "FAIL",
            "code": None if can_add else "FOLDER_NO_ADD_CHILDREN_PERMISSION",
            "folder_id": folder.get("id"),
            "folder_name": folder.get("name"),
            "mimeType": folder.get("mimeType"),
            "can_add_children": can_add,
            "can_edit": can_edit,
            "service_account_email": _client_email(),
            "project_id": _project_id(),
        }
    except Exception as e:
        return {
            "status": "FAIL",
            "code": e.__class__.__name__,
            "details": str(e)[:1500],
            "service_account_email": _client_email(),
            "project_id": _project_id(),
        }


def _create_doc_drive_direct(title: str, content: str, folder_id: Optional[str] = None) -> Dict[str, Any]:
    if not ENABLE_GOOGLE_DOCS_WRITE:
        return {"status": "error", "code": "GOOGLE_DOCS_WRITE_DISABLED"}

    target_folder = (folder_id or AI_OS_ROOT_FOLDER_ID or "").strip()
    if not GOOGLE_SERVICE_ACCOUNT_JSON:
        return {"status": "error", "code": "GOOGLE_CONFIG_MISSING"}
    if not target_folder:
        return {"status": "error", "code": "ROOT_FOLDER_MISSING"}

    try:
        drive, docs = _google_services()

        # Najdôležitejšia oprava v1.4.4.2:
        # Vytvoríme Google Docs súbor priamo v cieľovom priečinku cez Drive files.create.
        # Nepoužívame documents.create + následný move, ktorý zlyháva na právach pri presune.
        metadata = {
            "name": title,
            "mimeType": GOOGLE_DOC_MIME,
            "parents": [target_folder],
        }
        created = drive.files().create(
            body=metadata,
            fields="id,name,mimeType,parents,webViewLink",
            supportsAllDrives=True,
        ).execute()

        doc_id = created.get("id")

        if content:
            docs.documents().batchUpdate(
                documentId=doc_id,
                body={
                    "requests": [
                        {
                            "insertText": {
                                "location": {"index": 1},
                                "text": content,
                            }
                        }
                    ]
                },
            ).execute()

        final = drive.files().get(
            fileId=doc_id,
            fields="id,name,mimeType,parents,webViewLink",
            supportsAllDrives=True,
        ).execute()

        return {
            "status": "success",
            "method": "drive.files.create_direct_parent_then_docs.batchUpdate",
            "document": {
                "id": final.get("id"),
                "title": final.get("name"),
                "url": final.get("webViewLink") or f"https://docs.google.com/document/d/{doc_id}/edit",
                "folder_id": target_folder,
                "parents": final.get("parents", []),
                "mimeType": final.get("mimeType"),
                "created": True,
            },
        }
    except Exception as e:
        return {
            "status": "error",
            "code": e.__class__.__name__,
            "details": str(e)[:2500],
            "method": "drive.files.create_direct_parent_then_docs.batchUpdate",
            "service_account_email": _client_email(),
            "project_id": _project_id(),
            "folder_id": target_folder,
        }


def _extract_document_title(message: str) -> str:
    text = (message or "").strip()
    if not text:
        return "AI_OS Document"
    low = text.lower()
    for prefix in ["vytvor nový dokument", "vytvor dokument", "nový dokument", "create document", "document"]:
        if low.startswith(prefix):
            text = text[len(prefix):].strip(" :-–—")
            break
    return (text or "AI_OS Document")[:120]


def _default_content(title: str, message: str, request_id: str) -> str:
    return f"""# {title}

Status: DRAFT
Created by: AI_OS v1.4.4.2 CAP-004.1 Drive Direct Write
Request ID: {request_id}
Created at: {utc_now()}

## Zadanie

{message}

## Technická poznámka

Dokument bol vytvorený priamo v cieľovom priečinku cez Google Drive files.create s mimeType application/vnd.google-apps.document a rodičom AI_OS_ROOT_FOLDER_ID.
"""


def _classify_intent(message: str) -> Dict[str, Any]:
    m = (message or "").lower()
    if any(w in m for w in ["vytvor dokument", "nový dokument", "dokument", "docs", "zapíš", "ulož"]):
        return {"intent": "document", "capability_id": "CAP-DOC", "confidence": 0.92}
    if any(w in m for w in ["knowledge", "znalosť", "reuse", "merge", "vyhodnoť"]):
        return {"intent": "knowledge", "capability_id": "CAP-KNOW", "confidence": 0.8}
    if any(w in m for w in ["stav", "health", "status", "test"]):
        return {"intent": "status", "capability_id": "CAP-003", "confidence": 0.75}
    return {"intent": "general", "capability_id": "CAP-002", "confidence": 0.65}


def _knowledge_decision(message: str) -> Dict[str, Any]:
    m = (message or "").lower()
    if any(w in m for w in ["vytvor", "nový", "new"]):
        decision, reason = "CREATE NEW", "Požiadavka smeruje k vytvoreniu nového artefaktu."
    elif any(w in m for w in ["aktualizuj", "uprav", "merge", "zlúč"]):
        decision, reason = "MERGE", "Požiadavka smeruje ku konsolidácii alebo aktualizácii."
    else:
        decision, reason = "REUSE", "Bezpečný predvolený režim: najprv použiť existujúce znalosti."
    return {
        "service": "SRV-001 Knowledge Evolution Engine",
        "decision": decision,
        "confidence": 0.82,
        "reason": reason,
        "allowed_actions": ["REUSE", "MERGE", "UPDATE", "ARCHIVE", "REMOVE", "CREATE NEW"],
    }


CAPABILITIES = {
    "CAP-001": {"id": "CAP-001", "name": "Working Context", "status": "ACTIVE", "enabled": True},
    "CAP-002": {"id": "CAP-002", "name": "Executive Assistant", "status": "ACTIVE", "enabled": ENABLE_EXECUTIVE_ASSISTANT},
    "CAP-003": {"id": "CAP-003", "name": "Capability Runtime", "status": "ACTIVE", "enabled": ENABLE_CAPABILITY_RUNTIME},
    "CAP-004": {"id": "CAP-004", "name": "Document Agent Adapter", "status": "ACTIVE", "enabled": ENABLE_DOCUMENT_AGENT},
    "CAP-004.1": {"id": "CAP-004.1", "name": "Google Docs Physical Write", "status": "DRIVE_DIRECT_WRITE", "enabled": ENABLE_GOOGLE_DOCS_WRITE},
    "CAP-DOC": {"id": "CAP-DOC", "name": "Document Agent", "status": "PHYSICAL_WRITE_ENABLED", "enabled": ENABLE_DOCUMENT_AGENT},
    "CAP-KNOW": {"id": "CAP-KNOW", "name": "Knowledge Evolution", "status": "ACTIVE", "enabled": ENABLE_KNOWLEDGE_EVOLUTION},
}


@app.head("/")
def root_head():
    return JSONResponse(status_code=200, content={})


@app.get("/")
def root():
    return _json_response({
        "service": APP_NAME,
        "status": "running",
        "version": VERSION,
        "message": "AI_OS v1.4.4.2 uses Drive files.create directly in AI_OS_ROOT_FOLDER_ID.",
        "google_config": {
            "root_folder_id_configured": bool(AI_OS_ROOT_FOLDER_ID),
            "service_account_json_configured": bool(GOOGLE_SERVICE_ACCOUNT_JSON),
            "service_account_email": _client_email(),
            "project_id": _project_id(),
        },
    })


@app.get("/orchestrator/health")
def orchestrator_health(request: Request):
    request_id = str(uuid.uuid4())
    try:
        _check_token(request)
        return _json_response({
            "status": "ok",
            "version": VERSION,
            "orchestrator": "enabled",
            "executive_assistant": "enabled" if ENABLE_EXECUTIVE_ASSISTANT else "disabled",
            "capability_runtime": "enabled" if ENABLE_CAPABILITY_RUNTIME else "disabled",
            "document_adapter": "enabled" if ENABLE_DOCUMENT_AGENT else "disabled",
            "google_docs_write": "drive_direct",
            "request_id": request_id,
        })
    except Exception as e:
        return _safe_error(e, request_id)


@app.get("/assistant/health")
def assistant_health(request: Request):
    request_id = str(uuid.uuid4())
    try:
        _check_token(request)
        return _json_response({
            "status": "ok",
            "assistant": "Executive Assistant",
            "version": VERSION,
            "uses": ["CAP-003 Capability Runtime", "CAP-004 Document Agent Adapter", "CAP-004.1 Drive Direct Write"],
            "request_id": request_id,
        })
    except Exception as e:
        return _safe_error(e, request_id)


@app.get("/debug/google")
def debug_google(request: Request):
    request_id = str(uuid.uuid4())
    try:
        _check_token(request)
        return _json_response({
            "status": "success",
            "version": VERSION,
            "client_email": _client_email(),
            "project_id": _project_id(),
            "root_folder_id": AI_OS_ROOT_FOLDER_ID,
            "folder_probe": _folder_probe(),
            "request_id": request_id,
        })
    except Exception as e:
        return _safe_error(e, request_id)


@app.get("/capability/registry")
def capability_registry(request: Request):
    request_id = str(uuid.uuid4())
    try:
        _check_token(request)
        return _json_response({
            "status": "success",
            "registry": list(CAPABILITIES.values()),
            "count": len(CAPABILITIES),
            "request_id": request_id,
        })
    except Exception as e:
        return _safe_error(e, request_id)


async def _run_document(message: str, request_id: str, debug: bool = False) -> Dict[str, Any]:
    title = _extract_document_title(message)
    content = _default_content(title, message, request_id)
    result = _create_doc_drive_direct(title, content)
    ok = result.get("status") == "success"
    payload = {
        "status": "success" if ok else "error",
        "capability_id": "CAP-DOC",
        "capability_name": "Document Agent",
        "action": "CREATE_DOCUMENT",
        "answer": "Dokument bol fyzicky vytvorený v Google Docs." if ok else "Dokument sa nepodarilo vytvoriť.",
        "next_action": "Otvoriť document.url." if ok else "Pozri google_write.details a /debug/google.",
        "document": result.get("document"),
        "google_write": result,
        "knowledge_decision": _knowledge_decision(message),
    }
    if debug:
        payload["debug"] = {"title": title, "folder_probe": _folder_probe()}
    return payload


@app.get("/assistant")
async def assistant(request: Request, message: str = Query(""), debug: bool = Query(False)):
    request_id = str(uuid.uuid4())
    try:
        _check_token(request)
        router = _classify_intent(message)
        if router["capability_id"] == "CAP-DOC":
            result = await _run_document(message, request_id, debug)
        else:
            result = {
                "status": "success",
                "capability_id": router["capability_id"],
                "answer": "Požiadavka bola prijatá.",
                "next_action": "Pokračovať cez príslušnú Capability.",
                "knowledge_decision": _knowledge_decision(message),
            }
        return _json_response({
            "status": result.get("status"),
            "assistant": "Executive Assistant",
            "version": VERSION,
            "route": router,
            "answer": result.get("answer"),
            "next_action": result.get("next_action"),
            "document": result.get("document"),
            "capability_result": result,
            "request_id": request_id,
        })
    except Exception as e:
        return _safe_error(e, request_id)


@app.get("/orchestrator/ask")
async def orchestrator_ask(request: Request, message: str = Query(""), limit: int = Query(5), debug: bool = Query(False)):
    return await assistant(request=request, message=message, debug=debug)


@app.get("/capability/run")
async def capability_run(request: Request, message: str = Query(""), capability_id: Optional[str] = Query(None), debug: bool = Query(False)):
    request_id = str(uuid.uuid4())
    try:
        _check_token(request)
        selected = capability_id or _classify_intent(message)["capability_id"]
        if selected in ["CAP-DOC", "CAP-004", "CAP-004.1"]:
            result = await _run_document(message, request_id, debug)
        else:
            result = {
                "status": "success",
                "capability_id": selected,
                "answer": "Capability Runtime je aktívny.",
                "next_action": "Spusti dokumentovú požiadavku.",
                "knowledge_decision": _knowledge_decision(message),
            }
        result["request_id"] = request_id
        return _json_response(result)
    except Exception as e:
        return _safe_error(e, request_id)


@app.get("/capability/document")
async def capability_document(request: Request, message: str = Query(""), title: Optional[str] = Query(None), content: Optional[str] = Query(None), folder_id: Optional[str] = Query(None), debug: bool = Query(False)):
    request_id = str(uuid.uuid4())
    try:
        _check_token(request)
        doc_title = title or _extract_document_title(message)
        doc_content = content or _default_content(doc_title, message, request_id)
        result = _create_doc_drive_direct(doc_title, doc_content, folder_id)
        return _json_response({
            "status": result.get("status"),
            "capability_id": "CAP-DOC",
            "adapter": "CAP-004.1 Drive Direct Write",
            "document": result.get("document"),
            "google_write": result,
            "debug": {"folder_probe": _folder_probe()} if debug else None,
            "request_id": request_id,
        })
    except Exception as e:
        return _safe_error(e, request_id)


@app.post("/document/create")
async def document_create(request: Request):
    request_id = str(uuid.uuid4())
    try:
        _check_token(request)
        try:
            body = await request.json()
        except Exception:
            body = {}
        title = str(body.get("title") or "AI_OS Document")[:120]
        content = str(body.get("content") or _default_content(title, "POST /document/create", request_id))
        folder_id = str(body.get("folder_id") or "").strip() or None
        result = _create_doc_drive_direct(title, content, folder_id)
        return _json_response({
            "status": result.get("status"),
            "service": "CAP-004.1 Drive Direct Write",
            "document": result.get("document"),
            "google_write": result,
            "request_id": request_id,
        })
    except Exception as e:
        return _safe_error(e, request_id)


@app.get("/orchestrator/knowledge-evolution")
def knowledge_evolution(request: Request, message: str = Query(""), limit: int = Query(5)):
    request_id = str(uuid.uuid4())
    try:
        _check_token(request)
        return _json_response({
            "status": "success",
            "service": "SRV-001 Knowledge Evolution Engine",
            "knowledge_evolution": _knowledge_decision(message),
            "limit": max(1, min(int(limit or 5), 20)),
            "request_id": request_id,
        })
    except Exception as e:
        return _safe_error(e, request_id)


@app.get("/refresh-index")
def refresh_index(request: Request):
    request_id = str(uuid.uuid4())
    try:
        _check_token(request)
        return _json_response({
            "status": "success",
            "action": "REFRESH_INDEX",
            "index_status": "ready_safe_noop" if not ENABLE_DRIVE_REFRESH else "refresh_requested",
            "note": "Drive refresh je zámerne oddelený od fyzického zápisu dokumentov.",
            "request_id": request_id,
        })
    except Exception as e:
        return _safe_error(e, request_id)


@app.get("/self-test")
async def self_test(request: Request):
    request_id = str(uuid.uuid4())
    try:
        _check_token(request)
        folder = _folder_probe()
        router = _classify_intent("Vytvor dokument AI_OS Test")
        tests = [
            {"name": "root", "status": "PASS"},
            {"name": "capability_registry", "status": "PASS", "count": len(CAPABILITIES)},
            {"name": "document_intent_router", "status": "PASS" if router["capability_id"] == "CAP-DOC" else "FAIL", "router": router},
            {"name": "google_folder_permission", **folder},
        ]
        overall = "PASS" if all(t.get("status") == "PASS" for t in tests) else "FAIL"
        return _json_response({
            "status": "success",
            "self_test": overall,
            "version": VERSION,
            "tests": tests,
            "request_id": request_id,
        })
    except Exception as e:
        return _safe_error(e, request_id)
