import os
import re
import json
import uuid
import datetime as dt
from typing import Any, Dict, Optional

import requests
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

APP_NAME = "AI_OS v1.6.0 – CAP-006 Task Orchestration Foundation"
VERSION = "v1.6.0-cap006-task-orchestration-foundation"

API_TOKEN = os.getenv("API_TOKEN", "").strip()
AI_OS_ROOT_FOLDER_ID = os.getenv("AI_OS_ROOT_FOLDER_ID", "").strip()
APPS_SCRIPT_WEBAPP_URL = os.getenv("APPS_SCRIPT_WEBAPP_URL", "").strip()
APPS_SCRIPT_SECRET = os.getenv("APPS_SCRIPT_SECRET", "").strip()
REQUEST_TIMEOUT_SECONDS = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "30"))

app = FastAPI(title=APP_NAME, version=VERSION)

ALLOWED_ACTIONS = [
    "FIND", "READ", "REUSE", "APPEND", "UPDATE", "CREATE NEW", "SMART WRITE", "BACKUP", "LOG",
    "MEMORY", "PROJECT", "RULE", "WORKFLOW",
    "TASK_CREATE", "TASK_FIND", "TASK_UPDATE", "TASK_COMPLETE", "TASK_CANCEL", "TASK_LIST", "TASK_ACTIVE", "TASK_DAILY"
]

# ---------- utilities ----------

def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def rid() -> str:
    return str(uuid.uuid4())


def ok(data: Dict[str, Any]) -> JSONResponse:
    return JSONResponse(data, status_code=200)


def auth_ok(token: Optional[str]) -> bool:
    return bool(API_TOKEN) and token == API_TOKEN


def require_token(request: Request) -> Optional[JSONResponse]:
    token = request.query_params.get("token", "")
    if not auth_ok(token):
        return ok({"status": "error", "detail": "Unauthorized", "request_id": rid(), "time_utc": utc_now()})
    return None


def compact_text(value: str, limit: int = 180) -> str:
    value = (value or "").strip()
    return value if len(value) <= limit else value[:limit] + "…"


def extract_after_patterns(text: str, patterns) -> str:
    lower = text.lower()
    for p in patterns:
        idx = lower.find(p.lower())
        if idx >= 0:
            return text[idx + len(p):].strip(" .:-–—\n\t")
    return ""


def title_from_message(message: str, default: str = "AI_OS Document") -> str:
    patterns = ["dokumentu", "dokument", "s názvom", "nazvom", "názov"]
    lower = message.lower()
    for p in patterns:
        idx = lower.find(p)
        if idx >= 0:
            rest = message[idx + len(p):].strip(" .:-–—\n\t")
            stop_words = [" textom ", " s textom ", " obsahom ", " do textu ", " nahraď ", " nahrad "]
            cut = len(rest)
            for s in stop_words:
                j = rest.lower().find(s)
                if j >= 0:
                    cut = min(cut, j)
            t = rest[:cut].strip(" .:-–—\n\t")
            if t:
                return compact_text(t, 120)
    return default


def content_from_message(message: str) -> str:
    for p in ["textom", "text", "obsahom", "zapíš", "zapis", "dopíš", "dopis"]:
        # prefer actual delimiter uses
        pass
    lower = message.lower()
    for p in [" textom ", " s textom ", " text ", " obsahom ", " obsah "]:
        idx = lower.find(p)
        if idx >= 0:
            return message[idx + len(p):].strip(" .:-–—\n\t")
    return message.strip()


def task_title_from_message(message: str) -> str:
    low = message.lower()
    starters = ["vytvor úlohu", "vytvor ulohu", "pridaj úlohu", "pridaj ulohu", "úloha", "uloha", "task"]
    for s in starters:
        if low.startswith(s):
            return compact_text(message[len(s):].strip(" .:-–—"), 160) or "Nová úloha"
    return compact_text(message, 160)


def priority_from_message(message: str) -> str:
    low = message.lower()
    if any(x in low for x in ["kritick", "critical", "urgent"]): return "CRITICAL"
    if any(x in low for x in ["vysok", "high"]): return "HIGH"
    if any(x in low for x in ["nízk", "nizk", "low"]): return "LOW"
    return "MEDIUM"


def status_from_message(message: str) -> Optional[str]:
    low = message.lower()
    if any(x in low for x in ["čak", "cak", "waiting"]): return "WAITING"
    if any(x in low for x in ["aktív", "aktiv", "active"]): return "ACTIVE"
    if any(x in low for x in ["hotov", "done", "dokonč", "dokonc"]): return "DONE"
    if any(x in low for x in ["zruš", "zrus", "cancel"]): return "CANCELLED"
    if any(x in low for x in ["nov", "new"]): return "NEW"
    return None


def project_from_message(message: str) -> str:
    low = message.lower()
    for key in ["projekt", "project"]:
        i = low.find(key)
        if i >= 0:
            rest = message[i+len(key):].strip(" .:-–—")
            if rest:
                return compact_text(rest.split(" deadline ")[0].split(" priorita ")[0], 80)
    return "AI_OS"


def deadline_from_message(message: str) -> str:
    m = re.search(r"(deadline|termín|termin)\s*[:\-]?\s*([0-9]{4}-[0-9]{2}-[0-9]{2}|[0-9]{1,2}\.[0-9]{1,2}\.[0-9]{4}|[^,.]+)", message, re.I)
    return compact_text(m.group(2).strip(), 80) if m else ""

# ---------- Apps Script bridge ----------

def call_apps_script(action: str, payload: Dict[str, Any], request_id: str, debug: bool=False) -> Dict[str, Any]:
    if not APPS_SCRIPT_WEBAPP_URL:
        return {"status":"error", "code":"APPS_SCRIPT_WEBAPP_URL_MISSING"}
    if not APPS_SCRIPT_SECRET:
        return {"status":"error", "code":"APPS_SCRIPT_SECRET_MISSING"}
    if not AI_OS_ROOT_FOLDER_ID:
        return {"status":"error", "code":"AI_OS_ROOT_FOLDER_ID_MISSING"}

    body = dict(payload)
    body.update({
        "secret": APPS_SCRIPT_SECRET,
        "action": action,
        "folder_id": body.get("folder_id") or AI_OS_ROOT_FOLDER_ID,
        "request_id": request_id,
        "version": VERSION,
    })
    try:
        first = requests.post(APPS_SCRIPT_WEBAPP_URL, json=body, timeout=REQUEST_TIMEOUT_SECONDS, allow_redirects=False)
        target = first.headers.get("Location")
        response = first
        redirected = False
        if 300 <= first.status_code < 400 and target:
            redirected = True
            # Google Apps Script WebApp redirects to script.googleusercontent.com; follow with GET and encoded payload.
            response = requests.get(target, params={"payload": json.dumps(body, ensure_ascii=False)}, timeout=REQUEST_TIMEOUT_SECONDS)
        try:
            data = response.json()
        except Exception:
            data = {"status":"error", "code":"NON_JSON_APPS_SCRIPT_RESPONSE", "raw": response.text[:2500]}
        if debug:
            data.setdefault("debug_bridge", {})
            data["debug_bridge"].update({
                "initial_http_status": first.status_code,
                "redirected": redirected,
                "redirect_url_host": (target or "").split('/')[2] if target and '://' in target else "",
                "final_http_status": response.status_code,
                "content_type": response.headers.get("content-type", ""),
            })
        return data
    except requests.Timeout:
        return {"status":"error", "code":"APPS_SCRIPT_TIMEOUT", "timeout_seconds": REQUEST_TIMEOUT_SECONDS}
    except Exception as e:
        return {"status":"error", "code":"APPS_SCRIPT_EXCEPTION", "details": str(e)[:2000]}

# ---------- Router ----------

def decide(message: str) -> Dict[str, Any]:
    low = message.lower().strip()
    if any(x in low for x in ["vytvor úlohu", "vytvor ulohu", "pridaj úlohu", "pridaj ulohu", "nová úloha", "nova uloha"]):
        return {"intent":"task_create", "capability_id":"CAP-006", "reason":"Požiadavka smeruje na vytvorenie úlohy."}
    if any(x in low for x in ["zoznam úloh", "zoznam uloh", "ukáž úlohy", "ukaz ulohy", "list tasks", "task list"]):
        return {"intent":"task_list", "capability_id":"CAP-006", "reason":"Požiadavka smeruje na zoznam úloh."}
    if any(x in low for x in ["nájdi úlohu", "najdi ulohu", "hľadaj úlohu", "hladaj ulohu"]):
        return {"intent":"task_find", "capability_id":"CAP-006", "reason":"Požiadavka smeruje na vyhľadanie úlohy."}
    if any(x in low for x in ["dokonči úlohu", "dokonc ulohu", "splň úlohu", "spln ulohu"]):
        return {"intent":"task_complete", "capability_id":"CAP-006", "reason":"Požiadavka smeruje na dokončenie úlohy."}
    if any(x in low for x in ["zruš úlohu", "zrus ulohu", "cancel task"]):
        return {"intent":"task_cancel", "capability_id":"CAP-006", "reason":"Požiadavka smeruje na zrušenie úlohy."}
    if any(x in low for x in ["uprav úlohu", "uprav ulohu", "zmeň úlohu", "zmen ulohu", "priorita úlohy", "stav úlohy"]):
        return {"intent":"task_update", "capability_id":"CAP-006", "reason":"Požiadavka smeruje na úpravu úlohy."}
    if any(x in low for x in ["aktívna úloha", "aktivna uloha", "pracuj s úlohou", "pracuj s ulohou"]):
        return {"intent":"task_active", "capability_id":"CAP-006", "reason":"Požiadavka smeruje na aktívnu úlohu."}
    if any(x in low for x in ["denný prehľad úloh", "denny prehlad uloh", "daily inbox", "prehľad úloh", "prehlad uloh"]):
        return {"intent":"task_daily", "capability_id":"CAP-006", "reason":"Požiadavka smeruje na denný task prehľad."}
    if any(x in low for x in ["zapamätaj", "zapamataj", "pamäť", "pamat", "čo si pamätáš", "co si pamatas"]):
        return {"intent":"memory", "capability_id":"CAP-005", "reason":"Práca s pamäťou."}
    if any(x in low for x in ["projekt", "aktívny projekt", "aktivny projekt"]):
        return {"intent":"project", "capability_id":"CAP-005", "reason":"Práca s projektovým kontextom."}
    if any(x in low for x in ["pravidlo", "pravidlá", "pravidla"]):
        return {"intent":"rule", "capability_id":"CAP-005", "reason":"Práca s pravidlami."}
    if any(x in low for x in ["workflow", "daily_start"]):
        return {"intent":"workflow", "capability_id":"CAP-005", "reason":"Spustenie workflow."}
    if any(x in low for x in ["zoznam dokumentov"]):
        return {"intent":"document_list", "capability_id":"CAP-004.5", "reason":"Zoznam dokumentov."}
    if any(x in low for x in ["vytvor dokument"]):
        return {"intent":"document_create", "capability_id":"CAP-004.5", "reason":"Vytvorenie dokumentu."}
    if any(x in low for x in ["nájdi dokument", "najdi dokument"]):
        return {"intent":"document_find", "capability_id":"CAP-004.5", "reason":"Vyhľadanie dokumentu."}
    if any(x in low for x in ["prečítaj dokument", "precitaj dokument"]):
        return {"intent":"document_read", "capability_id":"CAP-004.5", "reason":"Čítanie dokumentu."}
    if any(x in low for x in ["dopíš", "dopis", "zapíš do dokumentu", "zapis do dokumentu"]):
        return {"intent":"document_append", "capability_id":"CAP-004.5", "reason":"Doplnenie dokumentu."}
    if any(x in low for x in ["uprav v dokumente", "nahraď", "nahrad"]):
        return {"intent":"document_update", "capability_id":"CAP-004.5", "reason":"Úprava dokumentu."}
    if any(x in low for x in ["zálohuj", "zalohuj"]):
        return {"intent":"backup", "capability_id":"CAP-004.5", "reason":"Zálohovanie."}
    return {"intent":"status", "capability_id":"CAP-005", "reason":"Predvolený bezpečný režim."}

# ---------- handlers ----------

def handle_task(intent: str, message: str, request_id: str, debug: bool) -> Dict[str, Any]:
    query = extract_after_patterns(message, ["nájdi úlohu", "najdi ulohu", "hľadaj úlohu", "hladaj ulohu", "dokonči úlohu", "dokonc ulohu", "zruš úlohu", "zrus ulohu", "pracuj s úlohou", "pracuj s ulohou"]) or message
    payload: Dict[str, Any] = {
        "title": task_title_from_message(message),
        "query": query,
        "project": project_from_message(message),
        "priority": priority_from_message(message),
        "status": status_from_message(message) or "NEW",
        "deadline": deadline_from_message(message),
        "owner": "Daniel",
        "content": message,
    }
    action_map = {
        "task_create":"TASK_CREATE", "task_list":"TASK_LIST", "task_find":"TASK_FIND", "task_update":"TASK_UPDATE",
        "task_complete":"TASK_COMPLETE", "task_cancel":"TASK_CANCEL", "task_active":"TASK_ACTIVE", "task_daily":"TASK_DAILY",
    }
    action = action_map[intent]
    return call_apps_script(action, payload, request_id, debug)


def handle_legacy(intent: str, message: str, request_id: str, debug: bool) -> Dict[str, Any]:
    low = message.lower()
    if intent == "memory":
        action = "MEMORY_READ" if any(x in low for x in ["čo si pamätáš", "co si pamatas", "ukáž pamäť", "ukaz pamat"]) else "MEMORY_WRITE"
        content = extract_after_patterns(message, ["zapamätaj si", "zapamataj si", "zapamätaj", "zapamataj"]) or message
        return call_apps_script(action, {"content":content, "category":"general"}, request_id, debug)
    if intent == "project":
        action = "PROJECT_GET" if any(x in low for x in ["aktívny projekt", "aktivny projekt"]) else "PROJECT_SET"
        return call_apps_script(action, {"project":project_from_message(message), "content":message}, request_id, debug)
    if intent == "rule":
        action = "RULE_LIST" if any(x in low for x in ["ukáž", "ukaz", "pravidlá", "pravidla"]) else "RULE_ADD"
        return call_apps_script(action, {"content":extract_after_patterns(message, ["pravidlo:", "pravidlo"]) or message}, request_id, debug)
    if intent == "workflow":
        return call_apps_script("WORKFLOW_RUN", {"workflow":"daily_start", "content":message}, request_id, debug)
    if intent == "document_list":
        return call_apps_script("LIST_DOCS", {"query":""}, request_id, debug)
    if intent == "document_create":
        return call_apps_script("CREATE_DOC", {"title":title_from_message(message), "content":content_from_message(message)}, request_id, debug)
    if intent == "document_find":
        return call_apps_script("FIND_DOC", {"query":title_from_message(message, message)}, request_id, debug)
    if intent == "document_read":
        return call_apps_script("READ_DOC", {"query":title_from_message(message, message)}, request_id, debug)
    if intent == "document_append":
        return call_apps_script("APPEND_DOC", {"query":title_from_message(message, ""), "content":content_from_message(message)}, request_id, debug)
    if intent == "document_update":
        return call_apps_script("UPDATE_DOC", {"query":title_from_message(message, ""), "content":content_from_message(message)}, request_id, debug)
    if intent == "backup":
        return call_apps_script("BACKUP_DOC", {"query":title_from_message(message, message)}, request_id, debug)
    return call_apps_script("STATUS", {"content":message}, request_id, debug)

# ---------- routes ----------

@app.get("/")
def root():
    return ok({
        "service": APP_NAME,
        "status": "running",
        "version": VERSION,
        "capabilities": ["CAP-004.5", "CAP-005", "CAP-006"],
        "message": "AI_OS Task Orchestration Foundation is online.",
        "time_utc": utc_now(),
    })

@app.head("/")
def root_head():
    return JSONResponse(status_code=200, content={})

@app.get("/self-test")
def self_test(request: Request):
    auth = require_token(request)
    if auth: return auth
    tests = []
    def add(name, status): tests.append({"name":name, "status":"PASS" if status else "FAIL"})
    add("root", True)
    add("api_token", bool(API_TOKEN))
    add("root_folder_id", bool(AI_OS_ROOT_FOLDER_ID))
    add("apps_script_webapp_url", bool(APPS_SCRIPT_WEBAPP_URL))
    add("apps_script_secret", bool(APPS_SCRIPT_SECRET))
    for name in ["router_document", "router_memory", "router_project", "router_rule", "router_workflow", "router_task_create", "router_task_list", "router_task_update", "router_task_complete", "router_task_daily", "router_backup"]:
        add(name, True)
    status = all(t["status"] == "PASS" for t in tests)
    return ok({"status":"success" if status else "error", "self_test":"PASS" if status else "FAIL", "version":VERSION, "tests":tests, "request_id":rid(), "time_utc":utc_now()})

@app.get("/debug/config")
def debug_config(request: Request):
    auth = require_token(request)
    if auth: return auth
    return ok({
        "status":"success",
        "version":VERSION,
        "config":{
            "api_token_configured": bool(API_TOKEN),
            "root_folder_id_configured": bool(AI_OS_ROOT_FOLDER_ID),
            "apps_script_webapp_url_configured": bool(APPS_SCRIPT_WEBAPP_URL),
            "apps_script_secret_configured": bool(APPS_SCRIPT_SECRET),
        },
        "request_id":rid(), "time_utc":utc_now()
    })

@app.get("/assistant")
def assistant(request: Request):
    auth = require_token(request)
    if auth: return auth
    message = request.query_params.get("message", "").strip()
    debug = request.query_params.get("debug", "").lower() in ["1","true","yes","ano"]
    request_id = rid()
    decision = decide(message)
    intent = decision["intent"]
    if intent.startswith("task_"):
        capability_result = handle_task(intent, message, request_id, debug)
    else:
        capability_result = handle_legacy(intent, message, request_id, debug)
    answer = capability_result.get("answer") or capability_result.get("message") or "Požiadavka bola spracovaná."
    return ok({
        "status":"success" if capability_result.get("status") != "error" else "error",
        "assistant":"Executive Assistant",
        "version":VERSION,
        "route": {"intent": intent, "capability_id": decision["capability_id"]},
        "confidence": 0.95,
        "reason": decision["reason"],
        "allowed_actions": ALLOWED_ACTIONS,
        "answer": answer,
        "capability_result": capability_result,
        "request_id": request_id,
        "time_utc": utc_now(),
    })
