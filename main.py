import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests
from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.responses import JSONResponse

APP_NAME = "AI_OS_ORCHESTRATOR_V1_4_8_CAP0044_INTELLIGENT_DOCUMENT_MANAGEMENT"
VERSION = "1.4.8-cap0044-intelligent-document-management"

API_TOKEN = os.getenv("API_TOKEN", "").strip()
AI_OS_ROOT_FOLDER_ID = os.getenv("AI_OS_ROOT_FOLDER_ID", "").strip()
APPS_SCRIPT_WEBAPP_URL = os.getenv("APPS_SCRIPT_WEBAPP_URL", "").strip()
APPS_SCRIPT_SECRET = os.getenv("APPS_SCRIPT_SECRET", "").strip()
REQUEST_TIMEOUT_SECONDS = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "45"))
DEBUG_APPS_SCRIPT = os.getenv("DEBUG_APPS_SCRIPT", "false").strip().lower() in {"1", "true", "yes", "on"}

app = FastAPI(title=APP_NAME, version=VERSION)


# -----------------------------------------------------------------------------
# Core helpers
# -----------------------------------------------------------------------------

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
        "capability": "CAP-004.4 Intelligent Document Management",
    }


def _strip_quotes(text: str) -> str:
    return (text or "").strip().strip('"“”„').strip("'‘’").strip()


def _first_nonempty(*values: Optional[str]) -> str:
    for value in values:
        if value and str(value).strip():
            return str(value).strip()
    return ""


def _safe_title(title: str) -> str:
    clean = re.sub(r"\s+", " ", _strip_quotes(title))
    return (clean or "AI_OS Document")[:120]


# -----------------------------------------------------------------------------
# Intent parsing
# -----------------------------------------------------------------------------

def extract_title_from_create(message: str) -> str:
    text = (message or "").strip()
    low = text.lower()
    prefixes = [
        "vytvor nový dokument",
        "vytvor dokument",
        "nový dokument",
        "create document",
        "create doc",
    ]
    for p in prefixes:
        if low.startswith(p):
            text = text[len(p):].strip(" :-–—")
            break

    # Remove optional trailing content directive from title.
    splitters = [" s textom ", " textom ", " obsahom ", " s obsahom "]
    lowered = text.lower()
    for marker in splitters:
        idx = lowered.find(marker)
        if idx > 0:
            text = text[:idx]
            break
    return _safe_title(text)


def extract_content_from_create(message: str, title: str, rid: str) -> str:
    text = (message or "").strip()
    lowered = text.lower()
    markers = [" s textom ", " textom ", " s obsahom ", " obsahom "]
    for marker in markers:
        idx = lowered.find(marker)
        if idx >= 0:
            return _strip_quotes(text[idx + len(marker):]) or make_default_content(title, message, rid)
    return make_default_content(title, message, rid)


def make_default_content(title: str, message: str, rid: str) -> str:
    return f"""# {title}

Status: DRAFT
Created by: AI_OS v1.4.8 CAP-004.4 Intelligent Document Management
Request ID: {rid}
Created at: {utc_now()}

## Zadanie

{message}

## Technický režim

Zápis a správa dokumentu idú cez CAP-004.4 a Apps Script Web App spustený ako vlastník Google Drive.
"""


def parse_append_command(message: str) -> Tuple[str, str]:
    text = (message or "").strip()
    # Supported: "Dopíš do dokumentu X text Y"
    patterns = [
        r"(?is)^\s*dopíš\s+do\s+dokumentu\s+(.+?)\s+(?:text|obsah)\s+(.+)$",
        r"(?is)^\s*dopis\s+do\s+dokumentu\s+(.+?)\s+(?:text|obsah)\s+(.+)$",
        r"(?is)^\s*append\s+to\s+document\s+(.+?)\s+text\s+(.+)$",
    ]
    for pattern in patterns:
        m = re.match(pattern, text)
        if m:
            return _safe_title(m.group(1)), _strip_quotes(m.group(2))
    return "", ""


def parse_update_command(message: str) -> Tuple[str, str, str]:
    text = (message or "").strip()
    # Supported: "Uprav v dokumente X nahraď A za B"
    patterns = [
        r"(?is)^\s*uprav\s+v\s+dokumente\s+(.+?)\s+nahraď\s+(.+?)\s+za\s+(.+)$",
        r"(?is)^\s*uprav\s+v\s+dokumente\s+(.+?)\s+nahrad\s+(.+?)\s+za\s+(.+)$",
        r"(?is)^\s*aktualizuj\s+dokument\s+(.+?)\s+nahraď\s+(.+?)\s+za\s+(.+)$",
        r"(?is)^\s*update\s+document\s+(.+?)\s+replace\s+(.+?)\s+with\s+(.+)$",
    ]
    for pattern in patterns:
        m = re.match(pattern, text)
        if m:
            return _safe_title(m.group(1)), _strip_quotes(m.group(2)), _strip_quotes(m.group(3))
    return "", "", ""


def parse_title_after_keywords(message: str, keywords: List[str]) -> str:
    text = (message or "").strip()
    low = text.lower()
    for keyword in keywords:
        if low.startswith(keyword):
            return _safe_title(text[len(keyword):].strip(" :-–—"))
    return _safe_title(text)


def intent_router(message: str) -> Dict[str, Any]:
    m = (message or "").lower().strip()
    if any(x in m for x in ["dopíš do dokumentu", "dopis do dokumentu", "append to document"]):
        return {"intent": "document_append", "capability_id": "CAP-004.4", "confidence": 0.96}
    if any(x in m for x in ["uprav v dokumente", "aktualizuj dokument", "replace"]):
        return {"intent": "document_update", "capability_id": "CAP-004.4", "confidence": 0.94}
    if any(x in m for x in ["prečítaj dokument", "precitaj dokument", "read document"]):
        return {"intent": "document_read", "capability_id": "CAP-004.4", "confidence": 0.94}
    if any(x in m for x in ["nájdi dokument", "najdi dokument", "find document"]):
        return {"intent": "document_find", "capability_id": "CAP-004.4", "confidence": 0.94}
    if any(x in m for x in ["vytvor dokument", "vytvor nový dokument", "create document", "create doc"]):
        return {"intent": "document_create", "capability_id": "CAP-004.4", "confidence": 0.98}
    if any(x in m for x in ["test", "stav", "status", "health"]):
        return {"intent": "status", "capability_id": "CAP-003", "confidence": 0.86}
    return {"intent": "assistant", "capability_id": "CAP-002", "confidence": 0.72}


def knowledge_decision(message: str) -> Dict[str, Any]:
    route = intent_router(message)
    intent = route["intent"]
    if intent == "document_create":
        decision = "CREATE NEW"
        reason = "Požiadavka smeruje k vytvoreniu nového dokumentu."
    elif intent == "document_find":
        decision = "REUSE"
        reason = "Požiadavka smeruje k nájdeniu existujúceho dokumentu."
    elif intent in {"document_read", "document_append", "document_update"}:
        decision = "UPDATE" if intent in {"document_append", "document_update"} else "REUSE"
        reason = "Požiadavka smeruje k práci s existujúcim dokumentom."
    else:
        decision = "REUSE"
        reason = "Predvolený režim: najprv opätovne použiť existujúce znalosti."
    return {
        "service": "SRV-001 Knowledge Evolution Engine",
        "decision": decision,
        "confidence": 0.88,
        "reason": reason,
        "allowed_actions": ["FIND", "READ", "REUSE", "APPEND", "UPDATE", "CREATE NEW"],
    }


# -----------------------------------------------------------------------------
# Apps Script bridge
# -----------------------------------------------------------------------------

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

    if isinstance(data, dict):
        if data.get("status") != "success":
            data.setdefault("status", "error")
        data.setdefault("http_status", r.status_code)
        data.setdefault("content_type", content_type)
        data.setdefault("final_url", r.url)
        data.setdefault("request_id", rid)
        return data

    return {"status": "error", "code": "APPS_SCRIPT_RESPONSE_NOT_OBJECT", "response": data, "request_id": rid}


def call_apps_script_action(action: str, rid: str, **kwargs: Any) -> Dict[str, Any]:
    if not APPS_SCRIPT_WEBAPP_URL:
        return {"status": "error", "code": "APPS_SCRIPT_WEBAPP_URL_MISSING", "request_id": rid}
    if not APPS_SCRIPT_SECRET:
        return {"status": "error", "code": "APPS_SCRIPT_SECRET_MISSING", "request_id": rid}
    if not AI_OS_ROOT_FOLDER_ID and not kwargs.get("folder_id"):
        return {"status": "error", "code": "AI_OS_ROOT_FOLDER_ID_MISSING", "request_id": rid}

    payload: Dict[str, Any] = {
        "secret": APPS_SCRIPT_SECRET,
        "action": action,
        "folder_id": kwargs.pop("folder_id", None) or AI_OS_ROOT_FOLDER_ID,
        "request_id": rid,
    }
    payload.update({k: v for k, v in kwargs.items() if v is not None})

    try:
        first = requests.post(
            APPS_SCRIPT_WEBAPP_URL,
            json=payload,
            timeout=REQUEST_TIMEOUT_SECONDS,
            allow_redirects=False,
        )

        redirect_statuses = {301, 302, 303, 307, 308}
        if first.status_code in redirect_statuses and first.headers.get("Location"):
            redirect_url = first.headers["Location"]
            second = requests.get(
                redirect_url,
                timeout=REQUEST_TIMEOUT_SECONDS,
                allow_redirects=True,
            )
            result = _parse_apps_script_response(second, rid)
            result.setdefault("redirect_handled", True)
            result.setdefault("redirect_follow_method", "GET")
            result.setdefault("initial_http_status", first.status_code)
            result.setdefault("redirect_url_host", redirect_url.split("/")[2] if "://" in redirect_url else "")
            if DEBUG_APPS_SCRIPT:
                print("===== APPS SCRIPT DEBUG =====")
                print("ACTION:", action)
                print("FIRST STATUS:", first.status_code)
                print("SECOND STATUS:", second.status_code)
                print("FINAL URL:", second.url)
                print("RESULT STATUS:", result.get("status"))
                print("=============================")
            return result

        result = _parse_apps_script_response(first, rid)
        result.setdefault("redirect_handled", False)
        result.setdefault("initial_http_status", first.status_code)
        if DEBUG_APPS_SCRIPT:
            print("===== APPS SCRIPT DEBUG =====")
            print("ACTION:", action)
            print("STATUS:", first.status_code)
            print("FINAL URL:", first.url)
            print("RESULT STATUS:", result.get("status"))
            print("=============================")
        return result

    except requests.Timeout:
        return {"status": "error", "code": "APPS_SCRIPT_TIMEOUT", "timeout_seconds": REQUEST_TIMEOUT_SECONDS, "request_id": rid}
    except Exception as e:
        return {"status": "error", "code": e.__class__.__name__, "details": str(e)[:2500], "request_id": rid}


def create_document(title: str, content: str, rid: str, folder_id: Optional[str] = None) -> Dict[str, Any]:
    return call_apps_script_action("CREATE_DOC", rid, title=_safe_title(title), content=content, folder_id=folder_id)


def find_document(title: str, rid: str, folder_id: Optional[str] = None, limit: int = 10) -> Dict[str, Any]:
    return call_apps_script_action("FIND_DOC", rid, title=_safe_title(title), folder_id=folder_id, limit=max(1, min(limit, 20)))


def read_document(title: Optional[str], rid: str, document_id: Optional[str] = None, folder_id: Optional[str] = None) -> Dict[str, Any]:
    return call_apps_script_action("READ_DOC", rid, title=_safe_title(title or ""), document_id=document_id, folder_id=folder_id)


def append_document(title: Optional[str], content: str, rid: str, document_id: Optional[str] = None, folder_id: Optional[str] = None) -> Dict[str, Any]:
    return call_apps_script_action("APPEND_DOC", rid, title=_safe_title(title or ""), document_id=document_id, content=content, folder_id=folder_id)


def update_document(title: Optional[str], find_text: str, replace_text: str, rid: str, document_id: Optional[str] = None, folder_id: Optional[str] = None) -> Dict[str, Any]:
    return call_apps_script_action(
        "UPDATE_DOC",
        rid,
        title=_safe_title(title or ""),
        document_id=document_id,
        find_text=find_text,
        replace_text=replace_text,
        folder_id=folder_id,
    )


# -----------------------------------------------------------------------------
# HTTP endpoints
# -----------------------------------------------------------------------------

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
            "message": "AI_OS CAP-004.4 Intelligent Document Management is online.",
            "use": [
                "/assistant?message=Vytvor%20dokument%20Test%20textom%20Ahoj&token=...",
                "/assistant?message=Nájdi%20dokument%20Test&token=...",
                "/assistant?message=Prečítaj%20dokument%20Test&token=...",
                "/assistant?message=Dopíš%20do%20dokumentu%20Test%20text%20Druhý%20riadok&token=...",
                "/assistant?message=Uprav%20v%20dokumente%20Test%20nahraď%20Ahoj%20za%20Ahoj%20Daniel&token=...",
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
                "document_management": "enabled",
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
                    "CAP-004.4 Intelligent Document Management",
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
            {"name": "router_create", "status": "PASS" if intent_router("Vytvor dokument Test") ["intent"] == "document_create" else "FAIL"},
            {"name": "router_find", "status": "PASS" if intent_router("Nájdi dokument Test") ["intent"] == "document_find" else "FAIL"},
            {"name": "router_read", "status": "PASS" if intent_router("Prečítaj dokument Test") ["intent"] == "document_read" else "FAIL"},
            {"name": "router_append", "status": "PASS" if intent_router("Dopíš do dokumentu Test text Ahoj") ["intent"] == "document_append" else "FAIL"},
            {"name": "router_update", "status": "PASS" if intent_router("Uprav v dokumente Test nahraď A za B") ["intent"] == "document_update" else "FAIL"},
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
        intent = route["intent"]
        result: Dict[str, Any]

        if intent == "document_create":
            title = extract_title_from_create(message)
            content = extract_content_from_create(message, title, rid)
            write = create_document(title, content, rid)
            ok = write.get("status") == "success"
            result = {
                "status": "success" if ok else "error",
                "answer": "Dokument bol fyzicky vytvorený v Google Docs." if ok else "Dokument sa nepodarilo vytvoriť.",
                "next_action": "Otvoriť document.url." if ok else "Skontrolovať Apps Script deployment a APPS_SCRIPT_SECRET.",
                "document": write.get("document"),
                "capability_result": write,
            }

        elif intent == "document_find":
            title = parse_title_after_keywords(message, ["nájdi dokument", "najdi dokument", "find document"])
            found = find_document(title, rid)
            ok = found.get("status") == "success"
            count = found.get("count", 0)
            result = {
                "status": "success" if ok else "error",
                "answer": f"Našiel som {count} dokument(ov)." if ok else "Dokument sa nepodarilo nájsť.",
                "next_action": "Použi document.id alebo document.url." if ok and count else "Skontroluj názov dokumentu.",
                "document": found.get("documents", [None])[0] if found.get("documents") else None,
                "capability_result": found,
            }

        elif intent == "document_read":
            title = parse_title_after_keywords(message, ["prečítaj dokument", "precitaj dokument", "read document"])
            read = read_document(title, rid)
            ok = read.get("status") == "success"
            result = {
                "status": "success" if ok else "error",
                "answer": "Obsah dokumentu bol načítaný." if ok else "Dokument sa nepodarilo načítať.",
                "next_action": "Skontrolovať document.content_preview alebo document.content." if ok else "Skontroluj názov dokumentu.",
                "document": read.get("document"),
                "capability_result": read,
            }

        elif intent == "document_append":
            title, content = parse_append_command(message)
            if not title or not content:
                result = {
                    "status": "error",
                    "answer": "Nerozumiem príkazu na dopísanie.",
                    "next_action": "Použi formát: Dopíš do dokumentu NÁZOV text TEXT.",
                    "document": None,
                    "capability_result": {"status": "error", "code": "APPEND_COMMAND_PARSE_FAILED"},
                }
            else:
                append = append_document(title, content, rid)
                ok = append.get("status") == "success"
                result = {
                    "status": "success" if ok else "error",
                    "answer": "Text bol dopísaný do dokumentu." if ok else "Text sa nepodarilo dopísať.",
                    "next_action": "Otvoriť document.url a skontrolovať koniec dokumentu." if ok else "Skontroluj názov dokumentu.",
                    "document": append.get("document"),
                    "capability_result": append,
                }

        elif intent == "document_update":
            title, find_text, replace_text = parse_update_command(message)
            if not title or not find_text:
                result = {
                    "status": "error",
                    "answer": "Nerozumiem príkazu na úpravu.",
                    "next_action": "Použi formát: Uprav v dokumente NÁZOV nahraď STARÝ_TEXT za NOVÝ_TEXT.",
                    "document": None,
                    "capability_result": {"status": "error", "code": "UPDATE_COMMAND_PARSE_FAILED"},
                }
            else:
                update = update_document(title, find_text, replace_text, rid)
                ok = update.get("status") == "success"
                result = {
                    "status": "success" if ok else "error",
                    "answer": "Dokument bol upravený." if ok else "Dokument sa nepodarilo upraviť.",
                    "next_action": "Otvoriť document.url a skontrolovať upravený text." if ok else "Skontroluj názov dokumentu a hľadaný text.",
                    "document": update.get("document"),
                    "capability_result": update,
                }

        else:
            result = {
                "status": "success",
                "answer": "Asistent je pripravený.",
                "next_action": "Zadaj požiadavku na vytvorenie, nájdenie, čítanie, dopísanie alebo úpravu dokumentu.",
                "document": None,
                "capability_result": None,
            }

        capability_result = result["capability_result"] if debug or result["status"] != "success" else _summarize_capability_result(result["capability_result"])
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
                "capability_result": capability_result,
                "request_id": rid,
            }
        )
    except Exception as e:
        return safe_error(e, rid)


def _summarize_capability_result(result: Any) -> Any:
    if not isinstance(result, dict):
        return result
    summary = {"status": result.get("status"), "method": result.get("method"), "count": result.get("count")}
    if result.get("document"):
        summary["document"] = result.get("document")
    return {k: v for k, v in summary.items() if v is not None}


@app.get("/orchestrator/ask")
def orchestrator_ask(request: Request, message: str = Query(""), limit: int = Query(5), debug: bool = Query(False)):
    return assistant(request=request, message=message, debug=debug)


@app.post("/document/action")
async def document_action(request: Request):
    rid = request_id()
    try:
        check_token(request)
        try:
            body = await request.json()
            if not isinstance(body, dict):
                body = {}
        except Exception:
            body = {}

        action = str(body.get("action") or "").strip().upper()
        title = _safe_title(str(body.get("title") or ""))
        content = str(body.get("content") or "")
        document_id = str(body.get("document_id") or "").strip() or None
        folder_id = str(body.get("folder_id") or "").strip() or None
        find_text = str(body.get("find_text") or "")
        replace_text = str(body.get("replace_text") or "")

        if action == "CREATE_DOC":
            result = create_document(title, content or make_default_content(title, "POST /document/action", rid), rid, folder_id)
        elif action == "FIND_DOC":
            result = find_document(title, rid, folder_id)
        elif action == "READ_DOC":
            result = read_document(title, rid, document_id, folder_id)
        elif action == "APPEND_DOC":
            result = append_document(title, content, rid, document_id, folder_id)
        elif action == "UPDATE_DOC":
            result = update_document(title, find_text, replace_text, rid, document_id, folder_id)
        else:
            result = {"status": "error", "code": "UNKNOWN_DOCUMENT_ACTION", "allowed_actions": ["CREATE_DOC", "FIND_DOC", "READ_DOC", "APPEND_DOC", "UPDATE_DOC"]}

        return json_response({"status": result.get("status"), "version": VERSION, "result": result, "request_id": rid})
    except Exception as e:
        return safe_error(e, rid)


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
        title = _safe_title(str(body.get("title") or "AI_OS Document"))
        content = str(body.get("content") or make_default_content(title, "POST /document/create", rid))
        folder_id = str(body.get("folder_id") or "").strip() or None
        write = create_document(title, content, rid, folder_id)
        return json_response({"status": write.get("status"), "version": VERSION, "document": write.get("document"), "write_result": write, "request_id": rid})
    except Exception as e:
        return safe_error(e, rid)


@app.get("/document/find")
def document_find(request: Request, title: str = Query(""), debug: bool = Query(False)):
    rid = request_id()
    try:
        check_token(request)
        result = find_document(title, rid)
        return json_response({"status": result.get("status"), "version": VERSION, "result": result if debug else _summarize_capability_result(result), "request_id": rid})
    except Exception as e:
        return safe_error(e, rid)


@app.get("/document/read")
def document_read(request: Request, title: str = Query(""), document_id: str = Query(""), debug: bool = Query(False)):
    rid = request_id()
    try:
        check_token(request)
        result = read_document(title, rid, document_id.strip() or None)
        return json_response({"status": result.get("status"), "version": VERSION, "result": result if debug else _summarize_capability_result(result), "request_id": rid})
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
                    {"id": "CAP-004.4", "name": "Intelligent Document Management", "status": "ACTIVE"},
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
                "note": "Index refresh is disabled in launch runtime to avoid Render free-tier instability.",
                "request_id": rid,
            }
        )
    except Exception as e:
        return safe_error(e, rid)
