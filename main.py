import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests
from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.responses import JSONResponse

APP_NAME = "AI_OS_ORCHESTRATOR_V1_5_0_CAP005_ORCHESTRATOR_FOUNDATION"
VERSION = "1.5.0-cap005-orchestrator-foundation"

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
    supplied = request.query_params.get("token", "").strip() or request.headers.get("x-api-token", "").strip() or bearer
    if supplied != API_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")


def public_config() -> Dict[str, Any]:
    return {
        "api_token_configured": bool(API_TOKEN),
        "root_folder_id_configured": bool(AI_OS_ROOT_FOLDER_ID),
        "apps_script_webapp_url_configured": bool(APPS_SCRIPT_WEBAPP_URL),
        "apps_script_secret_configured": bool(APPS_SCRIPT_SECRET),
        "write_mode": "APPS_SCRIPT_OWNER_CONTEXT",
        "capability": "CAP-005 Orchestrator Foundation",
    }


def _strip_quotes(text: str) -> str:
    return (text or "").strip().strip('"“”„').strip("'‘’").strip()


def _safe_title(title: str) -> str:
    clean = re.sub(r"\s+", " ", _strip_quotes(title))
    return (clean or "AI_OS Document")[:120]


def _safe_content(content: str) -> str:
    return str(content or "").replace("\r\n", "\n").replace("\r", "\n")[:90000]


def _bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "áno", "ano", "on"}


def _int(value: Any, default: int, min_value: int, max_value: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = default
    return max(min_value, min(max_value, parsed))


def parse_title_list(raw: Any) -> List[str]:
    if isinstance(raw, list):
        return [_safe_title(str(x)) for x in raw if str(x).strip()]
    text = str(raw or "").strip()
    if not text:
        return []
    parts = re.split(r"\s*(?:,|;|\|)\s*", text)
    return [_safe_title(p) for p in parts if p.strip()]


# -----------------------------------------------------------------------------
# Intent parsing
# -----------------------------------------------------------------------------

def make_default_content(title: str, message: str, rid: str) -> str:
    return f"""# {title}

Status: DRAFT
Created by: AI_OS v1.5.0 CAP-005 Orchestrator Foundation
Request ID: {rid}
Created at: {utc_now()}

## Zadanie

{message}

## Technický režim

Zápis, pamäť, projekty, pravidlá a workflow idú cez CAP-005, Apps Script Web App a owner-context Google Drive zápis.
"""


def _split_title_content(text: str, default_title: str = "") -> Tuple[str, str]:
    body = (text or "").strip()
    lowered = body.lower()
    markers = [" s textom ", " textom ", " s obsahom ", " obsahom ", " content "]
    for marker in markers:
        idx = lowered.find(marker)
        if idx >= 0:
            return _safe_title(body[:idx] or default_title), _strip_quotes(body[idx + len(marker):])
    return _safe_title(body or default_title), ""


def extract_title_from_create(message: str) -> str:
    text = (message or "").strip()
    low = text.lower()
    prefixes = ["vytvor nový dokument", "vytvor dokument", "nový dokument", "create document", "create doc"]
    for p in prefixes:
        if low.startswith(p):
            text = text[len(p):].strip(" :-–—")
            break
    title, _ = _split_title_content(text, "AI_OS Document")
    return title


def extract_content_from_create(message: str, title: str, rid: str) -> str:
    text = (message or "").strip()
    low = text.lower()
    prefixes = ["vytvor nový dokument", "vytvor dokument", "nový dokument", "create document", "create doc"]
    for p in prefixes:
        if low.startswith(p):
            text = text[len(p):].strip(" :-–—")
            break
    _, content = _split_title_content(text, title)
    return _safe_content(content or make_default_content(title, message, rid))


def parse_append_command(message: str) -> Tuple[str, str]:
    text = (message or "").strip()
    patterns = [
        r"(?is)^\s*dopíš\s+do\s+dokumentu\s+(.+?)\s+(?:text|obsah)\s+(.+)$",
        r"(?is)^\s*dopis\s+do\s+dokumentu\s+(.+?)\s+(?:text|obsah)\s+(.+)$",
        r"(?is)^\s*append\s+to\s+document\s+(.+?)\s+text\s+(.+)$",
    ]
    for pattern in patterns:
        m = re.match(pattern, text)
        if m:
            return _safe_title(m.group(1)), _safe_content(_strip_quotes(m.group(2)))

    # CAP-004.5 active-document syntax: "Dopíš text X" / "Dopíš obsah X"
    patterns_active = [
        r"(?is)^\s*dopíš\s+(?:text|obsah)\s+(.+)$",
        r"(?is)^\s*dopis\s+(?:text|obsah)\s+(.+)$",
        r"(?is)^\s*append\s+text\s+(.+)$",
    ]
    for pattern in patterns_active:
        m = re.match(pattern, text)
        if m:
            return "", _safe_content(_strip_quotes(m.group(1)))
    return "", ""


def parse_update_command(message: str) -> Tuple[str, str, str]:
    text = (message or "").strip()
    patterns = [
        r"(?is)^\s*uprav\s+v\s+dokumente\s+(.+?)\s+nahraď\s+(.+?)\s+za\s+(.+)$",
        r"(?is)^\s*uprav\s+v\s+dokumente\s+(.+?)\s+nahrad\s+(.+?)\s+za\s+(.+)$",
        r"(?is)^\s*aktualizuj\s+dokument\s+(.+?)\s+nahraď\s+(.+?)\s+za\s+(.+)$",
        r"(?is)^\s*aktualizuj\s+dokument\s+(.+?)\s+nahrad\s+(.+?)\s+za\s+(.+)$",
        r"(?is)^\s*update\s+document\s+(.+?)\s+replace\s+(.+?)\s+with\s+(.+)$",
    ]
    for pattern in patterns:
        m = re.match(pattern, text)
        if m:
            return _safe_title(m.group(1)), _strip_quotes(m.group(2)), _strip_quotes(m.group(3))

    # Active-document syntax: "Nahraď A za B"
    patterns_active = [r"(?is)^\s*nahraď\s+(.+?)\s+za\s+(.+)$", r"(?is)^\s*nahrad\s+(.+?)\s+za\s+(.+)$"]
    for pattern in patterns_active:
        m = re.match(pattern, text)
        if m:
            return "", _strip_quotes(m.group(1)), _strip_quotes(m.group(2))
    return "", "", ""


def parse_smart_write_command(message: str) -> Tuple[str, str, str]:
    text = (message or "").strip()
    patterns = [
        r"(?is)^\s*(?:zapíš|zapis|ulož|uloz)\s+do\s+dokumentu\s+(.+?)\s+(?:text|obsah)\s+(.+)$",
        r"(?is)^\s*smart\s+(?:write|zapíš|zapis)\s+(.+?)\s+(?:text|obsah)\s+(.+)$",
        r"(?is)^\s*(?:zapíš|zapis|ulož|uloz)\s+(?:text|obsah)\s+(.+)$",
    ]
    for i, pattern in enumerate(patterns):
        m = re.match(pattern, text)
        if m and i < 2:
            return _safe_title(m.group(1)), _safe_content(_strip_quotes(m.group(2))), "AUTO_APPEND_OR_CREATE"
        if m and i == 2:
            return "", _safe_content(_strip_quotes(m.group(1))), "AUTO_ACTIVE_OR_CREATE"
    return "", "", ""


def parse_title_after_keywords(message: str, keywords: List[str]) -> str:
    text = (message or "").strip()
    low = text.lower()
    for keyword in keywords:
        if low.startswith(keyword):
            return _safe_title(text[len(keyword):].strip(" :-–—"))
    return _safe_title(text)



def parse_memory_command(message: str) -> str:
    text = (message or "").strip()
    patterns = [
        r"(?is)^\s*(?:zapamätaj si|zapamataj si|pamätaj si|pamataj si|ulož do pamäte|uloz do pamate|remember)\s+(.+)$",
        r"(?is)^\s*(?:memory|pamäť|pamat)\s*[:\-–—]\s*(.+)$",
    ]
    for pattern in patterns:
        m = re.match(pattern, text)
        if m:
            return _safe_content(_strip_quotes(m.group(1)))
    return ""


def parse_project_set_command(message: str) -> str:
    text = (message or "").strip()
    patterns = [
        r"(?is)^\s*(?:nastav projekt|prepni projekt|projekt|pracuj na projekte|set project)\s+(.+)$",
        r"(?is)^\s*(?:aktívny projekt|aktivny projekt)\s*[:\-–—]\s*(.+)$",
    ]
    for pattern in patterns:
        m = re.match(pattern, text)
        if m:
            return _safe_title(m.group(1))
    return ""


def parse_rule_command(message: str) -> str:
    text = (message or "").strip()
    patterns = [
        r"(?is)^\s*(?:pravidlo|rule)\s*[:\-–—]?\s*(.+)$",
        r"(?is)^\s*(?:pridaj pravidlo|nastav pravidlo|add rule)\s+(.+)$",
    ]
    for pattern in patterns:
        m = re.match(pattern, text)
        if m:
            return _safe_content(_strip_quotes(m.group(1)))
    return ""


def parse_workflow_command(message: str) -> str:
    text = (message or "").strip()
    patterns = [
        r"(?is)^\s*(?:spusti workflow|spusti proces|workflow|run workflow)\s+(.+)$",
        r"(?is)^\s*(?:ranný štart|ranny start|daily start|denný štart|denny start)\s*$",
    ]
    for pattern in patterns:
        m = re.match(pattern, text)
        if m:
            if m.lastindex:
                return _safe_title(m.group(1))
            return "daily_start"
    return ""

def intent_router(message: str) -> Dict[str, Any]:
    m = (message or "").lower().strip()
    if any(x in m for x in ["zapamätaj si", "zapamataj si", "pamätaj si", "pamataj si", "ulož do pamäte", "uloz do pamate", "remember"]):
        return {"intent": "memory_write", "capability_id": "CAP-005", "confidence": 0.97}
    if any(x in m for x in ["čo si pamätáš", "co si pamatas", "ukáž pamäť", "ukaz pamat", "čítaj pamäť", "citaj pamat", "read memory"]):
        return {"intent": "memory_read", "capability_id": "CAP-005", "confidence": 0.94}
    if any(x in m for x in ["nastav projekt", "prepni projekt", "pracuj na projekte", "set project"]):
        return {"intent": "project_set", "capability_id": "CAP-005", "confidence": 0.96}
    if any(x in m for x in ["aktívny projekt", "aktivny projekt", "aký je projekt", "aky je projekt", "current project"]):
        return {"intent": "project_get", "capability_id": "CAP-005", "confidence": 0.93}
    if any(x in m for x in ["pridaj pravidlo", "nastav pravidlo", "pravidlo:", "rule:", "add rule"]):
        return {"intent": "rule_add", "capability_id": "CAP-005", "confidence": 0.95}
    if any(x in m for x in ["ukáž pravidlá", "ukaz pravidla", "zoznam pravidiel", "read rules", "rules"]):
        return {"intent": "rule_list", "capability_id": "CAP-005", "confidence": 0.92}
    if any(x in m for x in ["spusti workflow", "spusti proces", "run workflow", "ranný štart", "ranny start", "daily start", "denný štart", "denny start"]):
        return {"intent": "workflow_run", "capability_id": "CAP-005", "confidence": 0.94}
    if any(x in m for x in ["orchestruj", "orchestrate", "vykonaj plán", "vykonaj plan"]):
        return {"intent": "orchestrate", "capability_id": "CAP-005", "confidence": 0.90}
    if any(x in m for x in ["zoznam dokumentov", "posledné dokumenty", "posledne dokumenty", "list documents", "recent documents"]):
        return {"intent": "document_list", "capability_id": "CAP-004.5", "confidence": 0.95}
    if any(x in m for x in ["aktívny dokument", "aktivny dokument", "current document", "active document"]):
        return {"intent": "document_active_get", "capability_id": "CAP-004.5", "confidence": 0.92}
    if any(x in m for x in ["pracuj s dokumentom", "nastav aktívny dokument", "nastav aktivny dokument", "set active document"]):
        return {"intent": "document_active_set", "capability_id": "CAP-004.5", "confidence": 0.95}
    if any(x in m for x in ["zálohuj dokument", "zalohuj dokument", "backup document"]):
        return {"intent": "document_backup", "capability_id": "CAP-004.5", "confidence": 0.95}
    if any(x in m for x in ["história zmien", "historia zmien", "change log", "changelog"]):
        return {"intent": "document_changelog", "capability_id": "CAP-004.5", "confidence": 0.91}
    if any(x in m for x in ["zapíš do dokumentu", "zapis do dokumentu", "ulož do dokumentu", "uloz do dokumentu", "smart write"]):
        return {"intent": "document_smart_write", "capability_id": "CAP-004.5", "confidence": 0.96}
    if any(x in m for x in ["dopíš do dokumentu", "dopis do dokumentu", "append to document", "dopíš text", "dopis text"]):
        return {"intent": "document_append", "capability_id": "CAP-004.4", "confidence": 0.96}
    if any(x in m for x in ["uprav v dokumente", "aktualizuj dokument", "nahraď", "nahrad", "replace"]):
        return {"intent": "document_update", "capability_id": "CAP-004.4", "confidence": 0.94}
    if any(x in m for x in ["prečítaj dokument", "precitaj dokument", "read document", "prečítaj posledný", "precitaj posledny"]):
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
    if intent in {"memory_write", "project_set", "rule_add", "workflow_run", "orchestrate"}:
        decision = "ORCHESTRATE"
        reason = "CAP-005 smeruje požiadavku do pamäte, projektu, pravidiel alebo workflow."
    elif intent in {"memory_read", "project_get", "rule_list"}:
        decision = "REUSE"
        reason = "CAP-005 načítava existujúci kontext, pravidlá alebo pamäť."
    elif intent == "document_smart_write":
        decision = "AUTO ROUTE"
        reason = "CAP-004.5 rozhodne, či použiť aktívny/existujúci dokument alebo vytvoriť nový."
    elif intent in {"document_create"}:
        decision = "CREATE NEW"
        reason = "Požiadavka smeruje k vytvoreniu nového dokumentu."
    elif intent in {"document_find", "document_read", "document_list", "document_active_get", "document_changelog"}:
        decision = "REUSE"
        reason = "Požiadavka smeruje k použitiu alebo čítaniu existujúcich znalostí."
    elif intent in {"document_append", "document_update", "document_active_set"}:
        decision = "UPDATE"
        reason = "Požiadavka smeruje k úprave alebo nastaveniu pracovného kontextu."
    elif intent == "document_backup":
        decision = "ARCHIVE"
        reason = "Požiadavka smeruje k bezpečnostnej zálohe dokumentu."
    else:
        decision = "REUSE"
        reason = "Predvolený režim: najprv opätovne použiť existujúce znalosti."
    return {
        "service": "SRV-001 Knowledge Evolution Engine",
        "decision": decision,
        "confidence": route.get("confidence", 0.8),
        "reason": reason,
        "allowed_actions": ["FIND", "READ", "REUSE", "APPEND", "UPDATE", "CREATE NEW", "SMART_WRITE", "BACKUP", "LOG", "MEMORY", "PROJECT", "RULE", "WORKFLOW"],
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
        first = requests.post(APPS_SCRIPT_WEBAPP_URL, json=payload, timeout=REQUEST_TIMEOUT_SECONDS, allow_redirects=False)
        redirect_statuses = {301, 302, 303, 307, 308}
        if first.status_code in redirect_statuses and first.headers.get("Location"):
            redirect_url = first.headers["Location"]
            second = requests.get(redirect_url, timeout=REQUEST_TIMEOUT_SECONDS, allow_redirects=True)
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


# Document wrappers

def create_document(title: str, content: str, rid: str, folder_id: Optional[str] = None) -> Dict[str, Any]:
    return call_apps_script_action("CREATE_DOC", rid, title=_safe_title(title), content=_safe_content(content), folder_id=folder_id)


def find_document(title: str, rid: str, folder_id: Optional[str] = None, limit: int = 10) -> Dict[str, Any]:
    return call_apps_script_action("FIND_DOC", rid, title=_safe_title(title), folder_id=folder_id, limit=max(1, min(limit, 50)))


def list_documents(rid: str, query: str = "", folder_id: Optional[str] = None, limit: int = 10) -> Dict[str, Any]:
    return call_apps_script_action("LIST_DOCS", rid, query=_strip_quotes(query), folder_id=folder_id, limit=max(1, min(limit, 50)))


def read_document(title: Optional[str], rid: str, document_id: Optional[str] = None, folder_id: Optional[str] = None) -> Dict[str, Any]:
    return call_apps_script_action("READ_DOC", rid, title=_safe_title(title or ""), document_id=document_id, folder_id=folder_id)


def append_document(title: Optional[str], content: str, rid: str, document_id: Optional[str] = None, folder_id: Optional[str] = None) -> Dict[str, Any]:
    return call_apps_script_action("APPEND_DOC", rid, title=_safe_title(title or ""), document_id=document_id, content=_safe_content(content), folder_id=folder_id)


def update_document(title: Optional[str], find_text: str, replace_text: str, rid: str, document_id: Optional[str] = None, folder_id: Optional[str] = None, backup: bool = True) -> Dict[str, Any]:
    return call_apps_script_action("UPDATE_DOC", rid, title=_safe_title(title or ""), document_id=document_id, find_text=find_text, replace_text=replace_text, folder_id=folder_id, backup=backup)


def smart_write_document(title: Optional[str], content: str, rid: str, mode: str = "AUTO_APPEND_OR_CREATE", folder_id: Optional[str] = None) -> Dict[str, Any]:
    return call_apps_script_action("SMART_WRITE", rid, title=_safe_title(title or ""), content=_safe_content(content), mode=mode, folder_id=folder_id)


def set_active_document(title: Optional[str], rid: str, document_id: Optional[str] = None, folder_id: Optional[str] = None) -> Dict[str, Any]:
    return call_apps_script_action("SET_ACTIVE_DOC", rid, title=_safe_title(title or ""), document_id=document_id, folder_id=folder_id)


def get_active_document(rid: str, folder_id: Optional[str] = None) -> Dict[str, Any]:
    return call_apps_script_action("GET_ACTIVE_DOC", rid, folder_id=folder_id)


def backup_document(title: Optional[str], rid: str, document_id: Optional[str] = None, folder_id: Optional[str] = None) -> Dict[str, Any]:
    return call_apps_script_action("BACKUP_DOC", rid, title=_safe_title(title or ""), document_id=document_id, folder_id=folder_id)


def read_change_log(rid: str, limit_chars: int = 5000, folder_id: Optional[str] = None) -> Dict[str, Any]:
    return call_apps_script_action("READ_CHANGE_LOG", rid, limit_chars=max(1000, min(limit_chars, 20000)), folder_id=folder_id)


def read_multiple_documents(titles: List[str], rid: str, folder_id: Optional[str] = None) -> Dict[str, Any]:
    return call_apps_script_action("READ_MULTI_DOC", rid, titles=titles[:10], folder_id=folder_id)



def write_memory(content: str, rid: str, category: str = "general", folder_id: Optional[str] = None) -> Dict[str, Any]:
    return call_apps_script_action("WRITE_MEMORY", rid, content=_safe_content(content), category=_safe_title(category), folder_id=folder_id)


def read_memory(rid: str, query: str = "", limit_chars: int = 7000, folder_id: Optional[str] = None) -> Dict[str, Any]:
    return call_apps_script_action("READ_MEMORY", rid, query=_strip_quotes(query), limit_chars=max(1000, min(limit_chars, 30000)), folder_id=folder_id)


def set_project(project: str, rid: str, note: str = "", folder_id: Optional[str] = None) -> Dict[str, Any]:
    return call_apps_script_action("SET_PROJECT", rid, project=_safe_title(project), note=_safe_content(note), folder_id=folder_id)


def get_project(rid: str, folder_id: Optional[str] = None) -> Dict[str, Any]:
    return call_apps_script_action("GET_PROJECT", rid, folder_id=folder_id)


def add_rule(rule: str, rid: str, scope: str = "global", folder_id: Optional[str] = None) -> Dict[str, Any]:
    return call_apps_script_action("ADD_RULE", rid, rule=_safe_content(rule), scope=_safe_title(scope), folder_id=folder_id)


def read_rules(rid: str, folder_id: Optional[str] = None) -> Dict[str, Any]:
    return call_apps_script_action("READ_RULES", rid, folder_id=folder_id)


def run_workflow(workflow: str, rid: str, message: str = "", folder_id: Optional[str] = None) -> Dict[str, Any]:
    return call_apps_script_action("RUN_WORKFLOW", rid, workflow=_safe_title(workflow), message=_safe_content(message), folder_id=folder_id)


def orchestrate_request(message: str, rid: str, folder_id: Optional[str] = None) -> Dict[str, Any]:
    return call_apps_script_action("ORCHESTRATE", rid, message=_safe_content(message), folder_id=folder_id)

# -----------------------------------------------------------------------------
# HTTP endpoints
# -----------------------------------------------------------------------------

@app.head("/")
def root_head():
    return JSONResponse(status_code=200, content={})


@app.get("/")
def root():
    return json_response({
        "service": APP_NAME,
        "status": "running",
        "version": VERSION,
        "message": "AI_OS CAP-005 Orchestrator Foundation is online.",
        "use": [
            "/assistant?token=...&message=Zoznam%20dokumentov",
            "/assistant?token=...&message=Pracuj%20s%20dokumentom%20Test",
            "/assistant?token=...&message=Zapíš%20do%20dokumentu%20Test%20text%20Nový%20riadok",
            "/assistant?token=...&message=Dopíš%20text%20Text%20do%20aktívneho%20dokumentu",
            "/assistant?token=...&message=História%20zmien",
            "/assistant?token=...&message=Zapamätaj%20si%20Dôležitá%20poznámka",
            "/assistant?token=...&message=Nastav%20projekt%20AI_OS",
            "/assistant?token=...&message=Pravidlo:%20všetko%20zapisuj%20stručne",
            "/assistant?token=...&message=Spusti%20workflow%20daily_start",
        ],
        "config": public_config(),
    })


@app.get("/orchestrator/health")
def orchestrator_health(request: Request):
    rid = request_id()
    try:
        check_token(request)
        return json_response({"status": "ok", "service": APP_NAME, "version": VERSION, "orchestrator": "enabled", "document_management": "enabled", "context_aware_orchestration": "enabled", "orchestrator_foundation": "enabled", "memory": "enabled", "project_contexts": "enabled", "rules_engine": "enabled", "workflow_runtime": "enabled", "write_mode": "apps_script_owner_context", "request_id": rid})
    except Exception as e:
        return safe_error(e, rid)


@app.get("/assistant/health")
def assistant_health(request: Request):
    rid = request_id()
    try:
        check_token(request)
        return json_response({"status": "ok", "assistant": "Executive Assistant", "version": VERSION, "uses": ["CAP-002", "CAP-003", "CAP-004", "CAP-004.3", "CAP-004.4", "CAP-004.5", "CAP-005", "SRV-001"], "request_id": rid})
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
            {"name": "router_memory_write", "status": "PASS" if intent_router("Zapamätaj si toto je test")["intent"] == "memory_write" else "FAIL"},
            {"name": "router_memory_read", "status": "PASS" if intent_router("Čo si pamätáš")["intent"] == "memory_read" else "FAIL"},
            {"name": "router_project_set", "status": "PASS" if intent_router("Nastav projekt AI_OS")["intent"] == "project_set" else "FAIL"},
            {"name": "router_project_get", "status": "PASS" if intent_router("Aktívny projekt")["intent"] == "project_get" else "FAIL"},
            {"name": "router_rule_add", "status": "PASS" if intent_router("Pravidlo: odpovedaj stručne")["intent"] == "rule_add" else "FAIL"},
            {"name": "router_rule_list", "status": "PASS" if intent_router("Ukáž pravidlá")["intent"] == "rule_list" else "FAIL"},
            {"name": "router_workflow", "status": "PASS" if intent_router("Spusti workflow daily_start")["intent"] == "workflow_run" else "FAIL"},
            {"name": "router_create", "status": "PASS" if intent_router("Vytvor dokument Test")["intent"] == "document_create" else "FAIL"},
            {"name": "router_find", "status": "PASS" if intent_router("Nájdi dokument Test")["intent"] == "document_find" else "FAIL"},
            {"name": "router_read", "status": "PASS" if intent_router("Prečítaj dokument Test")["intent"] == "document_read" else "FAIL"},
            {"name": "router_append", "status": "PASS" if intent_router("Dopíš do dokumentu Test text Ahoj")["intent"] == "document_append" else "FAIL"},
            {"name": "router_update", "status": "PASS" if intent_router("Uprav v dokumente Test nahraď A za B")["intent"] == "document_update" else "FAIL"},
            {"name": "router_list", "status": "PASS" if intent_router("Zoznam dokumentov")["intent"] == "document_list" else "FAIL"},
            {"name": "router_smart_write", "status": "PASS" if intent_router("Zapíš do dokumentu Test text Ahoj")["intent"] == "document_smart_write" else "FAIL"},
            {"name": "router_active", "status": "PASS" if intent_router("Aktívny dokument")["intent"] == "document_active_get" else "FAIL"},
            {"name": "router_backup", "status": "PASS" if intent_router("Zálohuj dokument Test")["intent"] == "document_backup" else "FAIL"},
            {"name": "router_changelog", "status": "PASS" if intent_router("História zmien")["intent"] == "document_changelog" else "FAIL"},
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


        if intent == "memory_write":
            content = parse_memory_command(message)
            if not content:
                result = _assistant_result(False, "", "Nerozumiem príkazu na zápis do pamäte.", {"status": "error", "code": "MEMORY_COMMAND_PARSE_FAILED"})
            else:
                mem = write_memory(content, rid)
                ok = mem.get("status") == "success"
                result = _assistant_result(ok, "Poznámka bola uložená do pamäte AI_OS.", "Poznámku sa nepodarilo uložiť do pamäte.", mem)

        elif intent == "memory_read":
            mem = read_memory(rid)
            ok = mem.get("status") == "success"
            result = _assistant_result(ok, "Pamäť AI_OS bola načítaná.", "Pamäť sa nepodarilo načítať.", mem)

        elif intent == "project_set":
            project = parse_project_set_command(message)
            proj = set_project(project or "AI_OS", rid, note=message)
            ok = proj.get("status") == "success"
            result = _assistant_result(ok, "Aktívny projekt bol nastavený.", "Projekt sa nepodarilo nastaviť.", proj)

        elif intent == "project_get":
            proj = get_project(rid)
            ok = proj.get("status") == "success"
            result = _assistant_result(ok, "Aktívny projekt bol načítaný.", "Aktívny projekt zatiaľ nie je nastavený.", proj)

        elif intent == "rule_add":
            rule = parse_rule_command(message)
            if not rule:
                result = _assistant_result(False, "", "Nerozumiem pravidlu.", {"status": "error", "code": "RULE_PARSE_FAILED"})
            else:
                rules = add_rule(rule, rid)
                ok = rules.get("status") == "success"
                result = _assistant_result(ok, "Pravidlo bolo uložené.", "Pravidlo sa nepodarilo uložiť.", rules)

        elif intent == "rule_list":
            rules = read_rules(rid)
            ok = rules.get("status") == "success"
            result = _assistant_result(ok, "Pravidlá boli načítané.", "Pravidlá sa nepodarilo načítať.", rules)

        elif intent == "workflow_run":
            workflow = parse_workflow_command(message) or "daily_start"
            wf = run_workflow(workflow, rid, message=message)
            ok = wf.get("status") == "success"
            result = _assistant_result(ok, "Workflow bol spustený.", "Workflow sa nepodarilo spustiť.", wf)

        elif intent == "orchestrate":
            orch = orchestrate_request(message, rid)
            ok = orch.get("status") == "success"
            result = _assistant_result(ok, "Požiadavka bola orchestrátorom spracovaná.", "Orchestrácia zlyhala.", orch)

        elif intent == "document_create":
            title = extract_title_from_create(message)
            content = extract_content_from_create(message, title, rid)
            write = create_document(title, content, rid)
            ok = write.get("status") == "success"
            result = _assistant_result(ok, "Dokument bol fyzicky vytvorený v Google Docs.", "Dokument sa nepodarilo vytvoriť.", write)

        elif intent == "document_find":
            title = parse_title_after_keywords(message, ["nájdi dokument", "najdi dokument", "find document"])
            found = find_document(title, rid)
            ok = found.get("status") == "success"
            result = _assistant_result(ok, f"Našiel som {found.get('count', 0)} dokument(ov).", "Dokument sa nepodarilo nájsť.", found)

        elif intent == "document_read":
            title = parse_title_after_keywords(message, ["prečítaj dokument", "precitaj dokument", "read document", "prečítaj posledný", "precitaj posledny"])
            if "posled" in message.lower() or "aktív" in message.lower() or "aktiv" in message.lower():
                title = ""
            read = read_document(title, rid)
            ok = read.get("status") == "success"
            result = _assistant_result(ok, "Obsah dokumentu bol načítaný.", "Dokument sa nepodarilo načítať.", read)

        elif intent == "document_append":
            title, content = parse_append_command(message)
            if not content:
                result = _assistant_result(False, "", "Nerozumiem príkazu na dopísanie.", {"status": "error", "code": "APPEND_COMMAND_PARSE_FAILED"})
            else:
                append = append_document(title or None, content, rid)
                ok = append.get("status") == "success"
                result = _assistant_result(ok, "Text bol dopísaný do dokumentu.", "Text sa nepodarilo dopísať.", append)

        elif intent == "document_update":
            title, find_text, replace_text = parse_update_command(message)
            if not find_text:
                result = _assistant_result(False, "", "Nerozumiem príkazu na úpravu.", {"status": "error", "code": "UPDATE_COMMAND_PARSE_FAILED"})
            else:
                update = update_document(title or None, find_text, replace_text, rid, backup=True)
                ok = update.get("status") == "success"
                result = _assistant_result(ok, "Dokument bol upravený a zmena bola zalogovaná.", "Dokument sa nepodarilo upraviť.", update)

        elif intent == "document_list":
            docs = list_documents(rid, limit=10)
            ok = docs.get("status") == "success"
            result = _assistant_result(ok, f"Načítal som zoznam dokumentov: {docs.get('count', 0)} položiek.", "Zoznam dokumentov sa nepodarilo načítať.", docs)

        elif intent == "document_smart_write":
            title, content, mode = parse_smart_write_command(message)
            if not content:
                result = _assistant_result(False, "", "Nerozumiem príkazu na inteligentný zápis.", {"status": "error", "code": "SMART_WRITE_PARSE_FAILED"})
            else:
                smart = smart_write_document(title or None, content, rid, mode=mode)
                ok = smart.get("status") == "success"
                result = _assistant_result(ok, "Inteligentný zápis prebehol úspešne.", "Inteligentný zápis zlyhal.", smart)

        elif intent == "document_active_set":
            title = parse_title_after_keywords(message, ["pracuj s dokumentom", "nastav aktívny dokument", "nastav aktivny dokument", "set active document"])
            active = set_active_document(title, rid)
            ok = active.get("status") == "success"
            result = _assistant_result(ok, "Aktívny dokument bol nastavený.", "Aktívny dokument sa nepodarilo nastaviť.", active)

        elif intent == "document_active_get":
            active = get_active_document(rid)
            ok = active.get("status") == "success"
            result = _assistant_result(ok, "Aktívny dokument bol načítaný.", "Aktívny dokument nie je nastavený alebo sa nepodarilo načítať.", active)

        elif intent == "document_backup":
            title = parse_title_after_keywords(message, ["zálohuj dokument", "zalohuj dokument", "backup document"])
            backup = backup_document(title, rid)
            ok = backup.get("status") == "success"
            result = _assistant_result(ok, "Záloha dokumentu bola vytvorená.", "Zálohu dokumentu sa nepodarilo vytvoriť.", backup)

        elif intent == "document_changelog":
            log = read_change_log(rid)
            ok = log.get("status") == "success"
            result = _assistant_result(ok, "História zmien bola načítaná.", "Históriu zmien sa nepodarilo načítať.", log)

        else:
            result = {"status": "success", "answer": "Asistent je pripravený.", "next_action": "Zadaj požiadavku na dokument.", "document": None, "capability_result": None}

        capability_result = result["capability_result"] if debug or result["status"] != "success" else _summarize_capability_result(result["capability_result"])
        return json_response({"status": result["status"], "assistant": "Executive Assistant", "version": VERSION, "route": route, "knowledge_decision": knowledge_decision(message), "answer": result["answer"], "next_action": result["next_action"], "document": result["document"], "capability_result": capability_result, "request_id": rid})
    except Exception as e:
        return safe_error(e, rid)


def _assistant_result(ok: bool, success_msg: str, error_msg: str, capability: Dict[str, Any]) -> Dict[str, Any]:
    doc = capability.get("document")
    if not doc and isinstance(capability.get("documents"), list) and capability["documents"]:
        doc = capability["documents"][0]
    return {
        "status": "success" if ok else "error",
        "answer": success_msg if ok else error_msg,
        "next_action": "Otvoriť document.url alebo pokračovať ďalším príkazom." if ok else "Skontrolovať názov dokumentu, Apps Script deployment alebo debug výstup.",
        "document": doc,
        "capability_result": capability,
    }


def _summarize_capability_result(result: Any) -> Any:
    if not isinstance(result, dict):
        return result
    summary = {"status": result.get("status"), "method": result.get("method"), "count": result.get("count"), "operation": result.get("operation")}
    for key in ["document", "active_document", "backup", "documents", "memory", "project", "rules", "workflow", "steps"]:
        if result.get(key) is not None:
            summary[key] = result.get(key)
    return {k: v for k, v in summary.items() if v is not None}


@app.get("/orchestrator/ask")
def orchestrator_ask(request: Request, message: str = Query(""), limit: int = Query(5), debug: bool = Query(False)):
    return assistant(request=request, message=message, debug=debug)


@app.get("/document/list")
def document_list_endpoint(request: Request, query: str = Query(""), limit: int = Query(10), debug: bool = Query(False)):
    rid = request_id()
    try:
        check_token(request)
        result = list_documents(rid, query=query, limit=limit)
        return json_response({"status": result.get("status"), "version": VERSION, "result": result if debug else _summarize_capability_result(result), "request_id": rid})
    except Exception as e:
        return safe_error(e, rid)


@app.get("/document/find")
def document_find_endpoint(request: Request, title: str = Query(""), limit: int = Query(10), debug: bool = Query(False)):
    rid = request_id()
    try:
        check_token(request)
        result = find_document(title, rid, limit=limit)
        return json_response({"status": result.get("status"), "version": VERSION, "result": result if debug else _summarize_capability_result(result), "request_id": rid})
    except Exception as e:
        return safe_error(e, rid)


@app.get("/document/read")
def document_read_endpoint(request: Request, title: str = Query(""), document_id: str = Query(""), debug: bool = Query(False)):
    rid = request_id()
    try:
        check_token(request)
        result = read_document(title, rid, document_id.strip() or None)
        return json_response({"status": result.get("status"), "version": VERSION, "result": result if debug else _summarize_capability_result(result), "request_id": rid})
    except Exception as e:
        return safe_error(e, rid)


@app.get("/document/smart-write")
def document_smart_write_endpoint(request: Request, title: str = Query(""), content: str = Query(""), mode: str = Query("AUTO_APPEND_OR_CREATE"), debug: bool = Query(False)):
    rid = request_id()
    try:
        check_token(request)
        result = smart_write_document(title or None, content, rid, mode=mode)
        return json_response({"status": result.get("status"), "version": VERSION, "result": result if debug else _summarize_capability_result(result), "request_id": rid})
    except Exception as e:
        return safe_error(e, rid)


@app.get("/document/active")
def document_active_endpoint(request: Request, title: str = Query(""), document_id: str = Query(""), debug: bool = Query(False)):
    rid = request_id()
    try:
        check_token(request)
        if title or document_id:
            result = set_active_document(title or None, rid, document_id.strip() or None)
        else:
            result = get_active_document(rid)
        return json_response({"status": result.get("status"), "version": VERSION, "result": result if debug else _summarize_capability_result(result), "request_id": rid})
    except Exception as e:
        return safe_error(e, rid)


@app.get("/document/backup")
def document_backup_endpoint(request: Request, title: str = Query(""), document_id: str = Query(""), debug: bool = Query(False)):
    rid = request_id()
    try:
        check_token(request)
        result = backup_document(title or None, rid, document_id.strip() or None)
        return json_response({"status": result.get("status"), "version": VERSION, "result": result if debug else _summarize_capability_result(result), "request_id": rid})
    except Exception as e:
        return safe_error(e, rid)


@app.get("/document/changelog")
def document_changelog_endpoint(request: Request, limit_chars: int = Query(5000), debug: bool = Query(False)):
    rid = request_id()
    try:
        check_token(request)
        result = read_change_log(rid, limit_chars=limit_chars)
        return json_response({"status": result.get("status"), "version": VERSION, "result": result if debug else _summarize_capability_result(result), "request_id": rid})
    except Exception as e:
        return safe_error(e, rid)


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
        content = _safe_content(str(body.get("content") or ""))
        document_id = str(body.get("document_id") or "").strip() or None
        folder_id = str(body.get("folder_id") or "").strip() or None
        find_text = str(body.get("find_text") or "")
        replace_text = str(body.get("replace_text") or "")
        limit = _int(body.get("limit"), 10, 1, 50)

        if action == "CREATE_DOC":
            result = create_document(title, content or make_default_content(title, "POST /document/action", rid), rid, folder_id)
        elif action == "FIND_DOC":
            result = find_document(title, rid, folder_id, limit)
        elif action == "LIST_DOCS":
            result = list_documents(rid, query=title, folder_id=folder_id, limit=limit)
        elif action == "READ_DOC":
            result = read_document(title, rid, document_id, folder_id)
        elif action == "APPEND_DOC":
            result = append_document(title or None, content, rid, document_id, folder_id)
        elif action == "UPDATE_DOC":
            result = update_document(title or None, find_text, replace_text, rid, document_id, folder_id, backup=_bool(body.get("backup"), True))
        elif action == "SMART_WRITE":
            result = smart_write_document(title or None, content, rid, mode=str(body.get("mode") or "AUTO_APPEND_OR_CREATE"), folder_id=folder_id)
        elif action == "SET_ACTIVE_DOC":
            result = set_active_document(title or None, rid, document_id, folder_id)
        elif action == "GET_ACTIVE_DOC":
            result = get_active_document(rid, folder_id)
        elif action == "BACKUP_DOC":
            result = backup_document(title or None, rid, document_id, folder_id)
        elif action == "READ_CHANGE_LOG":
            result = read_change_log(rid, folder_id=folder_id)
        elif action == "READ_MULTI_DOC":
            result = read_multiple_documents(parse_title_list(body.get("titles")), rid, folder_id)
        elif action == "WRITE_MEMORY":
            result = write_memory(content, rid, category=str(body.get("category") or "general"), folder_id=folder_id)
        elif action == "READ_MEMORY":
            result = read_memory(rid, query=str(body.get("query") or ""), folder_id=folder_id)
        elif action == "SET_PROJECT":
            result = set_project(str(body.get("project") or title or "AI_OS"), rid, note=content, folder_id=folder_id)
        elif action == "GET_PROJECT":
            result = get_project(rid, folder_id=folder_id)
        elif action == "ADD_RULE":
            result = add_rule(str(body.get("rule") or content), rid, scope=str(body.get("scope") or "global"), folder_id=folder_id)
        elif action == "READ_RULES":
            result = read_rules(rid, folder_id=folder_id)
        elif action == "RUN_WORKFLOW":
            result = run_workflow(str(body.get("workflow") or title or "daily_start"), rid, message=content, folder_id=folder_id)
        elif action == "ORCHESTRATE":
            result = orchestrate_request(content or str(body.get("message") or ""), rid, folder_id=folder_id)
        else:
            result = {"status": "error", "code": "UNKNOWN_DOCUMENT_ACTION", "allowed_actions": ["CREATE_DOC", "FIND_DOC", "LIST_DOCS", "READ_DOC", "APPEND_DOC", "UPDATE_DOC", "SMART_WRITE", "SET_ACTIVE_DOC", "GET_ACTIVE_DOC", "BACKUP_DOC", "READ_CHANGE_LOG", "READ_MULTI_DOC", "WRITE_MEMORY", "READ_MEMORY", "SET_PROJECT", "GET_PROJECT", "ADD_RULE", "READ_RULES", "RUN_WORKFLOW", "ORCHESTRATE"]}
        return json_response({"status": result.get("status"), "version": VERSION, "result": result, "request_id": rid})
    except Exception as e:
        return safe_error(e, rid)



@app.get("/memory")
def memory_endpoint(request: Request, write: str = Query(""), query: str = Query(""), debug: bool = Query(False)):
    rid = request_id()
    try:
        check_token(request)
        result = write_memory(write, rid) if write else read_memory(rid, query=query)
        return json_response({"status": result.get("status"), "version": VERSION, "result": result if debug else _summarize_capability_result(result), "request_id": rid})
    except Exception as e:
        return safe_error(e, rid)


@app.get("/project")
def project_endpoint(request: Request, name: str = Query(""), debug: bool = Query(False)):
    rid = request_id()
    try:
        check_token(request)
        result = set_project(name, rid) if name else get_project(rid)
        return json_response({"status": result.get("status"), "version": VERSION, "result": result if debug else _summarize_capability_result(result), "request_id": rid})
    except Exception as e:
        return safe_error(e, rid)


@app.get("/rules")
def rules_endpoint(request: Request, add: str = Query(""), debug: bool = Query(False)):
    rid = request_id()
    try:
        check_token(request)
        result = add_rule(add, rid) if add else read_rules(rid)
        return json_response({"status": result.get("status"), "version": VERSION, "result": result if debug else _summarize_capability_result(result), "request_id": rid})
    except Exception as e:
        return safe_error(e, rid)


@app.get("/workflow/run")
def workflow_run_endpoint(request: Request, name: str = Query("daily_start"), message: str = Query(""), debug: bool = Query(False)):
    rid = request_id()
    try:
        check_token(request)
        result = run_workflow(name, rid, message=message)
        return json_response({"status": result.get("status"), "version": VERSION, "result": result if debug else _summarize_capability_result(result), "request_id": rid})
    except Exception as e:
        return safe_error(e, rid)

@app.get("/capability/registry")
def capability_registry(request: Request):
    rid = request_id()
    try:
        check_token(request)
        return json_response({
            "status": "success",
            "registry": [
                {"id": "CAP-001", "name": "Working Context", "status": "ACTIVE"},
                {"id": "CAP-002", "name": "Executive Assistant", "status": "ACTIVE"},
                {"id": "CAP-003", "name": "Capability Runtime", "status": "ACTIVE"},
                {"id": "CAP-004", "name": "Document Agent Adapter", "status": "ACTIVE"},
                {"id": "CAP-004.3", "name": "Apps Script Physical Write", "status": "ACTIVE"},
                {"id": "CAP-004.4", "name": "Intelligent Document Management", "status": "ACTIVE"},
                {"id": "CAP-004.5", "name": "Context-Aware Document Orchestration", "status": "ACTIVE"},
                {"id": "CAP-005", "name": "Orchestrator Foundation", "status": "ACTIVE"},
            ],
            "request_id": rid,
        })
    except Exception as e:
        return safe_error(e, rid)


@app.get("/refresh-index")
def refresh_index(request: Request):
    rid = request_id()
    try:
        check_token(request)
        return json_response({"status": "success", "action": "REFRESH_INDEX", "index_status": "ready_safe_noop", "note": "Index refresh is disabled in launch runtime to avoid Render free-tier instability.", "request_id": rid})
    except Exception as e:
        return safe_error(e, rid)
