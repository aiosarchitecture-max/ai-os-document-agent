
import os
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.responses import JSONResponse

APP_NAME = "AI_OS_ORCHESTRATOR_V1_4_5_CAP0042_DOCS_SAFE_WRITE"
VERSION = "1.4.5-cap0042-docs-safe-write"

API_TOKEN = os.getenv("API_TOKEN", "").strip()
AI_OS_ROOT_FOLDER_ID = os.getenv("AI_OS_ROOT_FOLDER_ID", "").strip()
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()

ENABLE_EXECUTIVE_ASSISTANT = os.getenv("ENABLE_EXECUTIVE_ASSISTANT", "true").lower() == "true"
ENABLE_CAPABILITY_RUNTIME = os.getenv("ENABLE_CAPABILITY_RUNTIME", "true").lower() == "true"
ENABLE_DOCUMENT_AGENT = os.getenv("ENABLE_DOCUMENT_AGENT", "true").lower() == "true"
ENABLE_GOOGLE_DOCS_WRITE = os.getenv("ENABLE_GOOGLE_DOCS_WRITE", "true").lower() == "true"

GOOGLE_DOC_MIME = "application/vnd.google-apps.document"
TEXT_MIME = "text/plain"

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/documents",
]

app = FastAPI(title=APP_NAME, version=VERSION)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def response(payload: Dict[str, Any], status_code: int = 200) -> JSONResponse:
    payload.setdefault("time_utc", utc_now())
    return JSONResponse(status_code=status_code, content=payload)


def safe_error(e: Exception, request_id: str) -> JSONResponse:
    if isinstance(e, HTTPException):
        return response({"status": "error", "detail": e.detail, "request_id": request_id}, e.status_code)
    return response({
        "status": "safe_error",
        "error_type": e.__class__.__name__,
        "detail": str(e)[:2500],
        "request_id": request_id,
    }, 200)


def check_token(request: Request) -> None:
    if not API_TOKEN:
        raise HTTPException(status_code=503, detail="API_TOKEN is not configured")
    query_token = request.query_params.get("token", "").strip()
    header_token = request.headers.get("x-api-token", "").strip()
    auth = request.headers.get("authorization", "").strip()
    bearer_token = auth.replace("Bearer ", "", 1).strip() if auth.lower().startswith("bearer ") else ""
    supplied = query_token or header_token or bearer_token
    if supplied != API_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")


def google_info() -> Dict[str, Any]:
    try:
        info = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON or "{}")
    except Exception:
        info = {}
    return {
        "service_account_json_configured": bool(GOOGLE_SERVICE_ACCOUNT_JSON),
        "root_folder_id_configured": bool(AI_OS_ROOT_FOLDER_ID),
        "client_email": info.get("client_email"),
        "project_id": info.get("project_id"),
    }


def load_google():
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaInMemoryUpload
        return service_account, build, MediaInMemoryUpload
    except Exception as e:
        raise RuntimeError(f"GOOGLE_LIB_IMPORT_ERROR: {e}")


def services():
    if not GOOGLE_SERVICE_ACCOUNT_JSON:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON missing")
    if not AI_OS_ROOT_FOLDER_ID:
        raise RuntimeError("AI_OS_ROOT_FOLDER_ID missing")

    service_account, build, MediaInMemoryUpload = load_google()
    info = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
    creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    drive = build("drive", "v3", credentials=creds, cache_discovery=False)
    docs = build("docs", "v1", credentials=creds, cache_discovery=False)
    return drive, docs, MediaInMemoryUpload


def folder_probe() -> Dict[str, Any]:
    try:
        drive, _, _ = services()
        folder = drive.files().get(
            fileId=AI_OS_ROOT_FOLDER_ID,
            fields="id,name,mimeType,capabilities(canAddChildren,canEdit)",
            supportsAllDrives=True,
        ).execute()
        caps = folder.get("capabilities", {})
        return {
            "status": "PASS" if caps.get("canAddChildren") else "FAIL",
            "folder_id": folder.get("id"),
            "folder_name": folder.get("name"),
            "canAddChildren": bool(caps.get("canAddChildren")),
            "canEdit": bool(caps.get("canEdit")),
        }
    except Exception as e:
        return {"status": "FAIL", "error_type": e.__class__.__name__, "detail": str(e)[:1500]}


def extract_title(message: str) -> str:
    text = (message or "").strip()
    for prefix in ["vytvor nový dokument", "vytvor dokument", "nový dokument", "create document"]:
        if text.lower().startswith(prefix):
            text = text[len(prefix):].strip(" :-–—")
            break
    return (text or "AI_OS Document")[:120]


def default_content(title: str, message: str, request_id: str) -> str:
    return f"""# {title}

Status: DRAFT
Created by: AI_OS v1.4.5 CAP-004.2 Docs Safe Write
Request ID: {request_id}
Created at: {utc_now()}

## Zadanie

{message}

## Technický režim

CAP-004.2 používa dvojitú stratégiu:
1. primárne Drive upload + konverzia text/plain na Google Docs v cieľovom priečinku,
2. fallback Drive direct empty Google Doc + Docs batchUpdate.

Tým sa obchádza chyba predchádzajúcej verzie, kde zlyhával samostatný zápis do už vytvoreného dokumentu.
"""


def create_doc_safe(title: str, content: str, folder_id: Optional[str] = None) -> Dict[str, Any]:
    if not ENABLE_GOOGLE_DOCS_WRITE:
        return {"status": "error", "code": "GOOGLE_DOCS_WRITE_DISABLED"}

    target_folder = (folder_id or AI_OS_ROOT_FOLDER_ID or "").strip()
    if not target_folder:
        return {"status": "error", "code": "ROOT_FOLDER_MISSING"}

    drive, docs, MediaInMemoryUpload = services()
    diagnostics = []

    # STRATEGY A: upload text/plain and convert directly to Google Docs.
    try:
        media = MediaInMemoryUpload(
            content.encode("utf-8"),
            mimetype=TEXT_MIME,
            resumable=False,
        )
        metadata = {
            "name": title,
            "mimeType": GOOGLE_DOC_MIME,
            "parents": [target_folder],
        }
        created = drive.files().create(
            body=metadata,
            media_body=media,
            fields="id,name,mimeType,parents,webViewLink",
            supportsAllDrives=True,
        ).execute()

        return {
            "status": "success",
            "strategy": "A_DRIVE_UPLOAD_TEXT_CONVERT_TO_GOOGLE_DOC",
            "document": {
                "id": created.get("id"),
                "title": created.get("name"),
                "url": created.get("webViewLink") or f"https://docs.google.com/document/d/{created.get('id')}/edit",
                "folder_id": target_folder,
                "parents": created.get("parents", []),
                "mimeType": created.get("mimeType"),
                "created": True,
                "content_written": True,
            },
            "diagnostics": diagnostics,
        }
    except Exception as e:
        diagnostics.append({
            "strategy": "A_DRIVE_UPLOAD_TEXT_CONVERT_TO_GOOGLE_DOC",
            "status": "FAIL",
            "error_type": e.__class__.__name__,
            "detail": str(e)[:1800],
        })

    # STRATEGY B: create empty Google Doc in folder and write via Docs API.
    try:
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

        docs.documents().batchUpdate(
            documentId=doc_id,
            body={"requests": [{"insertText": {"location": {"index": 1}, "text": content}}]},
        ).execute()

        final = drive.files().get(
            fileId=doc_id,
            fields="id,name,mimeType,parents,webViewLink",
            supportsAllDrives=True,
        ).execute()

        return {
            "status": "success",
            "strategy": "B_DRIVE_CREATE_EMPTY_THEN_DOCS_BATCHUPDATE",
            "document": {
                "id": final.get("id"),
                "title": final.get("name"),
                "url": final.get("webViewLink") or f"https://docs.google.com/document/d/{doc_id}/edit",
                "folder_id": target_folder,
                "parents": final.get("parents", []),
                "mimeType": final.get("mimeType"),
                "created": True,
                "content_written": True,
            },
            "diagnostics": diagnostics,
        }
    except Exception as e:
        diagnostics.append({
            "strategy": "B_DRIVE_CREATE_EMPTY_THEN_DOCS_BATCHUPDATE",
            "status": "FAIL",
            "error_type": e.__class__.__name__,
            "detail": str(e)[:1800],
        })

    return {
        "status": "error",
        "code": "ALL_WRITE_STRATEGIES_FAILED",
        "service_account_email": google_info().get("client_email"),
        "project_id": google_info().get("project_id"),
        "folder_id": target_folder,
        "folder_probe": folder_probe(),
        "diagnostics": diagnostics,
    }


@app.head("/")
def root_head():
    return JSONResponse(status_code=200, content={})


@app.get("/")
def root():
    return response({
        "service": APP_NAME,
        "status": "running",
        "version": VERSION,
        "message": "CAP-004.2 Docs Safe Write is online.",
        "google_config": google_info(),
    })


@app.get("/debug/google")
def debug_google(request: Request):
    request_id = str(uuid.uuid4())
    try:
        check_token(request)
        return response({
            "status": "success",
            "version": VERSION,
            "google": google_info(),
            "folder_probe": folder_probe(),
            "request_id": request_id,
        })
    except Exception as e:
        return safe_error(e, request_id)


@app.get("/self-test")
def self_test(request: Request):
    request_id = str(uuid.uuid4())
    try:
        check_token(request)
        fp = folder_probe()
        tests = [
            {"name": "root", "status": "PASS"},
            {"name": "google_config", "status": "PASS" if google_info().get("client_email") and AI_OS_ROOT_FOLDER_ID else "FAIL", "google": google_info()},
            {"name": "folder_permission", **fp},
        ]
        overall = "PASS" if all(t.get("status") == "PASS" for t in tests) else "FAIL"
        return response({
            "status": "success",
            "self_test": overall,
            "version": VERSION,
            "tests": tests,
            "request_id": request_id,
        })
    except Exception as e:
        return safe_error(e, request_id)


@app.get("/assistant")
def assistant(request: Request, message: str = Query(""), debug: bool = Query(False)):
    request_id = str(uuid.uuid4())
    try:
        check_token(request)
        title = extract_title(message)
        content = default_content(title, message, request_id)
        result = create_doc_safe(title, content)

        ok = result.get("status") == "success"
        return response({
            "status": "success" if ok else "error",
            "assistant": "Executive Assistant",
            "version": VERSION,
            "route": {"intent": "document", "capability_id": "CAP-DOC", "confidence": 0.94},
            "answer": "Dokument bol fyzicky vytvorený v Google Docs." if ok else "Dokument sa nepodarilo vytvoriť ani jednou stratégiou.",
            "next_action": "Otvoriť document.url." if ok else "Pozri diagnostics; chyba je mimo Renderu.",
            "document": result.get("document"),
            "capability_result": result if debug or not ok else {"status": result.get("status"), "strategy": result.get("strategy")},
            "request_id": request_id,
        })
    except Exception as e:
        return safe_error(e, request_id)


@app.get("/orchestrator/ask")
def orchestrator_ask(request: Request, message: str = Query(""), limit: int = Query(5), debug: bool = Query(False)):
    return assistant(request=request, message=message, debug=debug)


@app.get("/capability/document")
def capability_document(
    request: Request,
    message: str = Query(""),
    title: Optional[str] = Query(None),
    content: Optional[str] = Query(None),
    folder_id: Optional[str] = Query(None),
    debug: bool = Query(False),
):
    request_id = str(uuid.uuid4())
    try:
        check_token(request)
        doc_title = title or extract_title(message)
        doc_content = content or default_content(doc_title, message, request_id)
        result = create_doc_safe(doc_title, doc_content, folder_id)
        return response({
            "status": result.get("status"),
            "version": VERSION,
            "capability": "CAP-004.2 Docs Safe Write",
            "document": result.get("document"),
            "write_result": result if debug or result.get("status") != "success" else {"status": result.get("status"), "strategy": result.get("strategy")},
            "request_id": request_id,
        })
    except Exception as e:
        return safe_error(e, request_id)


@app.post("/document/create")
async def document_create(request: Request):
    request_id = str(uuid.uuid4())
    try:
        check_token(request)
        try:
            body = await request.json()
            if not isinstance(body, dict):
                body = {}
        except Exception:
            body = {}

        title = str(body.get("title") or "AI_OS Document")[:120]
        content = str(body.get("content") or default_content(title, "POST /document/create", request_id))
        folder_id = str(body.get("folder_id") or "").strip() or None
        result = create_doc_safe(title, content, folder_id)

        return response({
            "status": result.get("status"),
            "version": VERSION,
            "service": "CAP-004.2 Docs Safe Write",
            "document": result.get("document"),
            "write_result": result,
            "request_id": request_id,
        })
    except Exception as e:
        return safe_error(e, request_id)


@app.get("/capability/registry")
def capability_registry(request: Request):
    request_id = str(uuid.uuid4())
    try:
        check_token(request)
        return response({
            "status": "success",
            "registry": [
                {"id": "CAP-002", "name": "Executive Assistant", "status": "ACTIVE"},
                {"id": "CAP-003", "name": "Capability Runtime", "status": "ACTIVE"},
                {"id": "CAP-004", "name": "Document Agent Adapter", "status": "ACTIVE"},
                {"id": "CAP-004.2", "name": "Docs Safe Write", "status": "ACTIVE"},
            ],
            "request_id": request_id,
        })
    except Exception as e:
        return safe_error(e, request_id)


@app.get("/refresh-index")
def refresh_index(request: Request):
    request_id = str(uuid.uuid4())
    try:
        check_token(request)
        return response({
            "status": "success",
            "action": "REFRESH_INDEX",
            "index_status": "ready_safe_noop",
            "request_id": request_id,
        })
    except Exception as e:
        return safe_error(e, request_id)
