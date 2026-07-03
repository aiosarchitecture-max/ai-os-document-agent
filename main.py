
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import requests
from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.responses import JSONResponse

APP_NAME = "AI_OS_ORCHESTRATOR_V1_4_7_2_APPS_SCRIPT_POST_REDIRECT_FIX"
VERSION = "1.4.7.2-apps-script-post-redirect-fix"

API_TOKEN = os.getenv("API_TOKEN", "").strip()
AI_OS_ROOT_FOLDER_ID = os.getenv("AI_OS_ROOT_FOLDER_ID", "").strip()
APPS_SCRIPT_WEBAPP_URL = os.getenv("APPS_SCRIPT_WEBAPP_URL", "").strip()
APPS_SCRIPT_SECRET = os.getenv("APPS_SCRIPT_SECRET", "").strip()

REQUEST_TIMEOUT_SECONDS = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "45"))

app = FastAPI(title=APP_NAME, version=VERSION)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def request_id() -> str:
    return str(uuid.uuid4())


def json_response(payload: Dict[str, Any], status_code: int = 200) -> JSONResponse:
    payload.setdefault("time_utc", utc_now())
    return JSONResponse(status_code=status_code, content=payload)


def safe_error(e: Exception, rid: str) -> JSONResponse:
    if isinstance(e, HTTPException):
        return json_response({"status": "error", "detail": e.detail, "request_id": rid}, e.status_code)
    return json_response(
        {
            "status": "safe_error",
            "error_type": e.__class__.__name__,
            "detail": str(e)[:2500],
            "request_id": rid,
        },
        200,
    )


def check_token(request: Request) -> None:
    if not API_TOKEN:
        raise HTTPException(status_code=503, detail="API_TOKEN is not configured")

    auth = request.headers.get("authorization", "").strip()
    bearer = auth.replace("Bearer ", "", 1).strip() if auth.lower().startswith("bearer ") else ""
    supplied = (
        request.query_params.get("token", "").strip()
        or request.headers.get("x-api-token", "").strip()
        or bearer
    )

    if supplied != API_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")


def public_config() -> Dict[str, Any]:
    return {
        "api_token_configured": bool(API_TOKEN),
        "root_folder_id_configured": bool(AI_OS_ROOT_FOLDER_ID),
        "apps_script_webapp_url_configured": bool(APPS_SCRIPT_WEBAPP_URL),
        "apps_script_secret_configured": bool(APPS_SCRIPT_SECRET),
        "write_mode": "APPS_SCRIPT_OWNER_CONTEXT",
    }


def extract_title(message: str) -> str:
    text = (message or "").strip()
    prefixes = [
        "vytvor nový dokument",
        "vytvor dokument",
        "nový dokument",
        "create document",
        "create doc",
    ]
    low = text.lower()
    for p in prefixes:
        if low.startswith(p):
            text = text[len(p):].strip(" :-–—")
            break
    return (text or "AI_OS Document")[:120]


def make_content(title: str, message: str, rid: str) -> str:
    return f"""# {title}

Status: DRAFT
Created by: AI_OS v1.4.7 Assistant Launch Stable
Request ID: {rid}
Created at: {utc_now()}

## Zadanie

{message}

## Technický režim

Zápis ide cez CAP-004.3 Apps Script Write.
Apps Script je spustený ako vlastník Google Drive, preto nevzniká chyba service account storageQuotaExceeded.
"""


def intent_router(message: str) -> Dict[str, Any]:
    m = (message or "").lower()
    if any(x in m for x in ["dokument", "document", "docs", "zapíš", "ulož", "vytvor"]):
        return {"intent": "document", "capability_id": "CAP-004.3", "confidence": 0.98}
    if any(x in m for x in ["test", "stav", "status", "health"]):
        return {"intent": "status", "capability_id": "CAP-003", "confidence": 0.86}
    return {"intent": "assistant", "capability_id": "CAP-002", "confidence": 0.72}


def knowledge_decision(message: str) -> Dict[str, Any]:
    m = (message or "").lower()
    if any(x in m for x in ["vytvor", "nový", "create"]):
        decision = "CREATE NEW"
        reason = "Požiadavka smeruje k vytvoreniu nového artefaktu."
    elif any(x in m for x in ["uprav", "aktualizuj", "merge", "zlúč"]):
        decision = "MERGE"
        reason = "Požiadavka smeruje k úprave alebo zlúčeniu existujúceho obsahu."
    else:
        decision = "REUSE"
        reason = "Predvolený režim: najprv opätovne použiť existujúce znalosti."
    return {
        "service": "SRV-001 Knowledge Evolution Engine",
        "decision": decision,
        "confidence": 0.84,
        "reason": reason,
        "allowed_actions": ["REUSE", "MERGE", "UPDATE", "ARCHIVE", "REMOVE", "CREATE NEW"],
    }


def _parse_apps_script_response(r: requests.Response, rid: str) -> Dict[str, Any]:
    content_type = r.headers.get("Content-Type", "")

    try:
        data = r.json()
    except Exception:
        data = {
            "status": "error",
            "code": "NON_JSON_APPS_SCRIPT_RESPONSE",
            "http_status": r.status_code,
            "content_type": content_type,
            "final_url": r.url,
            "raw": r.text[:2000],
            "request_id": rid,
        }

    if r.status_code >= 400:
        return {
            "status": "error",
            "code": "APPS_SCRIPT_HTTP_ERROR",
            "http_status": r.status_code,
            "content_type": content_type,
            "final_url": r.url,
            "response": data,
            "request_id": rid,
        }

    if data.get("status") != "success":
        data.setdefault("status", "error")
    data.setdefault("http_status", r.status_code)
    data.setdefault("content_type", content_type)
    data.setdefault("final_url", r.url)
    return data


def call_apps_script(title: str, content: str, folder_id: Optional[str], rid: str) -> Dict[str, Any]:
    if not APPS_SCRIPT_WEBAPP_URL:
        return {"status": "error", "code": "APPS_SCRIPT_WEBAPP_URL_MISSING"}
    if not APPS_SCRIPT_SECRET:
        return {"status": "error", "code": "APPS_SCRIPT_SECRET_MISSING"}
    if not (folder_id or AI_OS_ROOT_FOLDER_ID):
        return {"status": "error", "code": "AI_OS_ROOT_FOLDER_ID_MISSING"}

    payload = {
        "secret": APPS_SCRIPT_SECRET,
        "action": "CREATE_DOC",
        "title": title,
        "content": content,
        "folder_id": folder_id or AI_OS_ROOT_FOLDER_ID,
        "request_id": rid,
    }

    try:
        # Google Apps Script Web Apps commonly answer /macros/s/.../exec with 302.
        # The Python requests library follows 302 by converting POST to GET.
        # That causes doGet() to run instead of doPost().
        # Therefore we stop automatic redirects and repeat POST manually to Location.
        first = requests.post(
            APPS_SCRIPT_WEBAPP_URL,
            json=payload,
            timeout=REQUEST_TIMEOUT_SECONDS,
            allow_redirects=False,
        )

        redirect_statuses = {301, 302, 303, 307, 308}
        if first.status_code in redirect_statuses and first.headers.get("Location"):
            redirect_url = first.headers["Location"]
            second = requests.post(
                redirect_url,
                json=payload,
                timeout=REQUEST_TIMEOUT_SECONDS,
                allow_redirects=False,
            )
            result = _parse_apps_script_response(second, rid)
            result.setdefault("redirect_handled", True)
            result.setdefault("initial_http_status", first.status_code)
            result.setdefault("redirect_url_host", redirect_url.split("/")[2] if "://" in redirect_url else "")
            return result

        result = _parse_apps_script_response(first, rid)
        result.setdefault("redirect_handled", False)
        result.setdefault("initial_http_status", first.status_code)
        return result

    except requests.Timeout:
        return {"status": "error", "code": "APPS_SCRIPT_TIMEOUT", "timeout_seconds": REQUEST_TIMEOUT_SECONDS, "request_id": rid}
    except Exception as e:
        return {"status": "error", "code": e.__class__.__name__, "details": str(e)[:2500], "request_id": rid}


@app.head("/")
def root_head():
    return JSONResponse(status_code=200, content={})


@app.get("/")
def root():
    return json_response(
        {
            "service": APP_NAME,
            "status": "running",
            "version": VERSION,
            "message": "AI_OS Assistant launch runtime is online.",
            "use": [
                "/assistant?message=test&token=...",
                "/assistant?message=Vytvor%20dokument%20AI_OS%20Test&token=...",
                "/self-test?token=...",
            ],
            "config": public_config(),
        }
    )


@app.get("/orchestrator/health")
def orchestrator_health(request: Request):
    rid = request_id()
    try:
        check_token(request)
        return json_response(
            {
                "status": "ok",
                "service": APP_NAME,
                "version": VERSION,
                "orchestrator": "enabled",
                "executive_assistant": "enabled",
                "capability_runtime": "enabled",
                "document_agent": "enabled",
                "write_mode": "apps_script_owner_context",
                "request_id": rid,
            }
        )
    except Exception as e:
        return safe_error(e, rid)


@app.get("/assistant/health")
def assistant_health(request: Request):
    rid = request_id()
    try:
        check_token(request)
        return json_response(
            {
                "status": "ok",
                "assistant": "Executive Assistant",
                "version": VERSION,
                "uses": [
                    "CAP-002 Executive Assistant",
                    "CAP-003 Capability Runtime",
                    "CAP-004 Document Agent Adapter",
                    "CAP-004.3 Apps Script Physical Write",
                    "SRV-001 Knowledge Evolution Engine",
                ],
                "request_id": rid,
            }
        )
    except Exception as e:
        return safe_error(e, rid)


@app.get("/debug/config")
def debug_config(request: Request):
    rid = request_id()
    try:
        check_token(request)
        return json_response({"status": "success", "version": VERSION, "config": public_config(), "request_id": rid})
    except Exception as e:
        return safe_error(e, rid)


@app.get("/self-test")
def self_test(request: Request):
    rid = request_id()
    try:
        check_token(request)
        tests = [
            {"name": "root", "status": "PASS"},
            {"name": "api_token", "status": "PASS" if API_TOKEN else "FAIL"},
            {"name": "root_folder_id", "status": "PASS" if AI_OS_ROOT_FOLDER_ID else "FAIL"},
            {"name": "apps_script_webapp_url", "status": "PASS" if APPS_SCRIPT_WEBAPP_URL else "FAIL"},
            {"name": "apps_script_secret", "status": "PASS" if APPS_SCRIPT_SECRET else "FAIL"},
            {"name": "router_document", "status": "PASS" if intent_router("Vytvor dokument AI_OS Test")["capability_id"] == "CAP-004.3" else "FAIL"},
        ]
        overall = "PASS" if all(t["status"] == "PASS" for t in tests) else "FAIL"
        return json_response({"status": "success", "self_test": overall, "version": VERSION, "tests": tests, "request_id": rid})
    except Exception as e:
        return safe_error(e, rid)


@app.get("/assistant")
def assistant(request: Request, message: str = Query(""), debug: bool = Query(False)):
    rid = request_id()
    try:
        check_token(request)
        route = intent_router(message)

        if route["intent"] == "document":
            title = extract_title(message)
            content = make_content(title, message, rid)
            write = call_apps_script(title, content, None, rid)
            ok = write.get("status") == "success"
            result = {
                "status": "success" if ok else "error",
                "answer": "Dokument bol fyzicky vytvorený v Google Docs." if ok else "Dokument sa nepodarilo vytvoriť.",
                "next_action": "Otvoriť document.url." if ok else "Skontrolovať APPS_SCRIPT_WEBAPP_URL, APPS_SCRIPT_SECRET a Apps Script deployment.",
                "document": write.get("document"),
                "write_result": write if debug or not ok else {"status": write.get("status"), "method": write.get("method")},
            }
        else:
            result = {
                "status": "success",
                "answer": "Asistent je pripravený.",
                "next_action": "Zadaj požiadavku alebo vytvor dokument.",
                "document": None,
                "write_result": None,
            }

        return json_response(
            {
                "status": result["status"],
                "assistant": "Executive Assistant",
                "version": VERSION,
                "route": route,
                "knowledge_decision": knowledge_decision(message),
                "answer": result["answer"],
                "next_action": result["next_action"],
                "document": result["document"],
                "capability_result": {
                    "capability_id": route["capability_id"],
                    "write_result": result["write_result"],
                },
                "request_id": rid,
            }
        )
    except Exception as e:
        return safe_error(e, rid)


@app.get("/orchestrator/ask")
def orchestrator_ask(request: Request, message: str = Query(""), limit: int = Query(5), debug: bool = Query(False)):
    return assistant(request=request, message=message, debug=debug)


@app.post("/document/create")
async def document_create(request: Request):
    rid = request_id()
    try:
        check_token(request)
        try:
            body = await request.json()
            if not isinstance(body, dict):
                body = {}
        except Exception:
            body = {}

        title = str(body.get("title") or "AI_OS Document")[:120]
        content = str(body.get("content") or make_content(title, "POST /document/create", rid))
        folder_id = str(body.get("folder_id") or "").strip() or None
        write = call_apps_script(title, content, folder_id, rid)

        return json_response(
            {
                "status": write.get("status"),
                "version": VERSION,
                "service": "CAP-004.3 Apps Script Physical Write",
                "document": write.get("document"),
                "write_result": write,
                "request_id": rid,
            }
        )
    except Exception as e:
        return safe_error(e, rid)


@app.get("/capability/registry")
def capability_registry(request: Request):
    rid = request_id()
    try:
        check_token(request)
        return json_response(
            {
                "status": "success",
                "registry": [
                    {"id": "CAP-001", "name": "Working Context", "status": "ACTIVE"},
                    {"id": "CAP-002", "name": "Executive Assistant", "status": "ACTIVE"},
                    {"id": "CAP-003", "name": "Capability Runtime", "status": "ACTIVE"},
                    {"id": "CAP-004", "name": "Document Agent Adapter", "status": "ACTIVE"},
                    {"id": "CAP-004.3", "name": "Apps Script Physical Write", "status": "ACTIVE"},
                ],
                "request_id": rid,
            }
        )
    except Exception as e:
        return safe_error(e, rid)


@app.get("/refresh-index")
def refresh_index(request: Request):
    rid = request_id()
    try:
        check_token(request)
        return json_response(
            {
                "status": "success",
                "action": "REFRESH_INDEX",
                "index_status": "ready_safe_noop",
                "note": "Index refresh is disabled in launch stable runtime to avoid Render free-tier instability.",
                "request_id": rid,
            }
        )
    except Exception as e:
        return safe_error(e, rid)
