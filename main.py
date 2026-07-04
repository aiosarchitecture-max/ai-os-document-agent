import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

import requests
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse

APP_NAME = "AI_OS v2.1 CAP-008 Workflow Engine"
VERSION = "v2.1.0-cap008-workflow-engine"
REQUEST_TIMEOUT_SECONDS = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "35"))

API_TOKEN = os.getenv("API_TOKEN", "")
AI_OS_ROOT_FOLDER_ID = os.getenv("AI_OS_ROOT_FOLDER_ID", "")
APPS_SCRIPT_WEBAPP_URL = os.getenv("APPS_SCRIPT_WEBAPP_URL", "")
APPS_SCRIPT_SECRET = os.getenv("APPS_SCRIPT_SECRET", "")

app = FastAPI(title=APP_NAME, version=VERSION)

ALLOWED_ACTIONS = [
    "FIND", "READ", "REUSE", "APPEND", "UPDATE", "CREATE_NEW", "SMART_WRITE", "BACKUP", "LOG",
    "MEMORY_WRITE", "MEMORY_READ", "PROJECT_SET", "PROJECT_GET", "RULE_ADD", "RULE_LIST",
    "WORKFLOW", "TASK_CREATE", "TASK_FIND", "TASK_UPDATE", "TASK_COMPLETE", "TASK_CANCEL", "TASK_LIST",
    "TASK_ACTIVE", "TASK_DAILY", "TASK_REMINDER", "TASK_DEADLINE", "CALENDAR_FIND", "CALENDAR_CREATE",
    "CALENDAR_READ", "DAY_PLAN", "WEEK_PLAN", "MORNING_BRIEFING", "SYSTEM_STATUS",
    "WORKFLOW_CREATE", "WORKFLOW_FIND", "WORKFLOW_LIST", "WORKFLOW_RUN", "WORKFLOW_PAUSE",
    "WORKFLOW_RESUME", "WORKFLOW_CANCEL", "WORKFLOW_COMPLETE", "WORKFLOW_STATUS", "WORKFLOW_HISTORY",
    "WORKFLOW_TEMPLATE_CREATE", "WORKFLOW_TEMPLATE_RUN", "WORKFLOW_VALIDATE", "WORKFLOW_DEBUG"
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def rid() -> str:
    return str(uuid.uuid4())


def ok(data: Optional[Dict[str, Any]] = None, request_id: Optional[str] = None) -> Dict[str, Any]:
    base = {"status": "success", "version": VERSION, "request_id": request_id or rid(), "time_utc": now_iso()}
    if data:
        base.update(data)
    return base


def err(code: str, details: str = "", request_id: Optional[str] = None, http_status: int = 200) -> JSONResponse:
    return JSONResponse(
        status_code=http_status,
        content={"status": "error", "version": VERSION, "code": code, "details": details, "request_id": request_id or rid(), "time_utc": now_iso()},
    )


def clean_text(value: Optional[str]) -> str:
    return (value or "").strip()


def token_ok(token: Optional[str]) -> bool:
    return bool(API_TOKEN) and token == API_TOKEN


def require_token(request: Request) -> Optional[JSONResponse]:
    token = request.query_params.get("token") or request.headers.get("x-ai-os-token")
    if not token_ok(token):
        return err("UNAUTHORIZED", "Invalid or missing token.", http_status=401)
    return None


def norm(s: str) -> str:
    return clean_text(s).lower()


def extract_after(message: str, patterns: list[str]) -> str:
    for p in patterns:
        m = re.search(p, message, flags=re.IGNORECASE | re.DOTALL)
        if m:
            return clean_text(m.group(1))
    return ""


def extract_named_doc(message: str) -> str:
    m = re.search(r"(?:dokument(?:u|e)?|doc)\s+([A-Za-z0-9_\- .ÁÄČĎÉÍĹĽŇÓÔŔŠŤÚÝŽáäčďéíĺľňóôŕšťúýž]+?)(?:\s+(?:text|textom|s textom|nahraď|nahrad|za|pridaj|dopíš|dopisal|deadline|priorita|stav)|$)", message, re.I)
    return clean_text(m.group(1)) if m else ""


def extract_task_title(message: str) -> str:
    m = re.search(r"(?:úlohu|uloha|task)\s+([A-Za-z0-9_\- .ÁÄČĎÉÍĹĽŇÓÔŔŠŤÚÝŽáäčďéíĺľňóôŕšťúýž]+?)(?:\s+(?:priorita|projekt|stav|deadline|termín|termin|text|na|do)|$)", message, re.I)
    return clean_text(m.group(1)) if m else ""


def extract_project(message: str) -> str:
    m = re.search(r"projekt\s+([A-Za-z0-9_\- .ÁÄČĎÉÍĹĽŇÓÔŔŠŤÚÝŽáäčďéíĺľňóôŕšťúýž]+?)(?:\s+(?:priorita|stav|deadline|termín|termin)|$)", message, re.I)
    return clean_text(m.group(1)) if m else ""


def extract_workflow_name(message: str) -> str:
    patterns = [
        r"(?:workflow|pracovný proces|pracovny proces)\s+([A-Za-z0-9_\- .ÁÄČĎÉÍĹĽŇÓÔŔŠŤÚÝŽáäčďéíĺľňóôŕšťúýž]+?)(?:\s+(?:šablóna|sablona|template|projekt|priorita|spusti|run|stav|status|$))",
        r"(?:spusti|vytvor|nájdi|najdi|zruš|zrus|pozastav|obnov|dokonči|dokonc)\s+(?:workflow|pracovný proces|pracovny proces)\s+(.+)$",
    ]
    for p in patterns:
        m = re.search(p, message, flags=re.IGNORECASE | re.DOTALL)
        if m:
            return clean_text(m.group(1))
    return ""

def extract_template(message: str) -> str:
    t = norm(message)
    if "nový produkt" in t or "novy produkt" in t:
        return "NEW_PRODUCT"
    if "nový projekt" in t or "novy projekt" in t:
        return "NEW_PROJECT"
    if "release" in t or "nasaden" in t:
        return "RELEASE"
    if "audit" in t:
        return "PROJECT_AUDIT"
    if "denný" in t or "denny" in t or "daily" in t:
        return "DAILY_BRIEFING"
    if "týžden" in t or "tyzden" in t or "weekly" in t:
        return "WEEKLY_BRIEFING"
    return extract_after(message, [r"(?:šablóna|sablona|template)\s+(.+)$"]) or "CUSTOM"


def extract_priority(message: str) -> str:
    t = norm(message)
    if any(x in t for x in ["kritická", "kriticka", "critical"]):
        return "CRITICAL"
    if any(x in t for x in ["vysoká", "vysoka", "high"]):
        return "HIGH"
    if any(x in t for x in ["nízka", "nizka", "low"]):
        return "LOW"
    if any(x in t for x in ["stredná", "stredna", "medium"]):
        return "MEDIUM"
    return "MEDIUM"


def extract_status(message: str) -> str:
    t = norm(message)
    for st in ["ACTIVE", "WAITING", "DONE", "CANCELLED", "NEW"]:
        if st.lower() in t:
            return st
    if "hotovo" in t or "dokon" in t:
        return "DONE"
    return "ACTIVE" if "akt" in t else "NEW"


def extract_date(message: str) -> str:
    m = re.search(r"(20\d{2}-\d{2}-\d{2})", message)
    if m:
        return m.group(1)
    if "zajtra" in norm(message):
        return "TOMORROW"
    if "dnes" in norm(message):
        return "TODAY"
    return ""


def route_message(message: str) -> Dict[str, Any]:
    msg = clean_text(message)
    t = norm(msg)

    if not msg:
        return {"intent": "system_status", "capability_id": "CORE", "action": "SYSTEM_STATUS", "confidence": 0.80, "payload": {}}

    # Memory / rules / projects
    if any(x in t for x in ["zapamätaj", "zapamataj", "pamätaj", "pamataj"]):
        content = extract_after(msg, [r"(?:zapamätaj si|zapamataj si|zapamätaj|zapamataj)\s+(.+)$"]) or msg
        return {"intent": "memory_write", "capability_id": "CAP-005", "action": "MEMORY_WRITE", "confidence": 0.97, "payload": {"content": content}}
    if "čo si pam" in t or "co si pam" in t or "ukáž pam" in t:
        return {"intent": "memory_read", "capability_id": "CAP-005", "action": "MEMORY_READ", "confidence": 0.94, "payload": {}}
    if t.startswith("nastav projekt") or t.startswith("projekt nastav"):
        project = extract_after(msg, [r"nastav projekt\s+(.+)$", r"projekt nastav\s+(.+)$"]) or extract_project(msg)
        return {"intent": "project_set", "capability_id": "CAP-005", "action": "PROJECT_SET", "confidence": 0.96, "payload": {"project": project}}
    if "aktívny projekt" in t or "aktivny projekt" in t:
        return {"intent": "project_get", "capability_id": "CAP-005", "action": "PROJECT_GET", "confidence": 0.94, "payload": {}}
    if t.startswith("pravidlo") or t.startswith("rule"):
        content = extract_after(msg, [r"pravidlo\s*:\s*(.+)$", r"rule\s*:\s*(.+)$"]) or msg
        return {"intent": "rule_add", "capability_id": "CAP-005", "action": "RULE_ADD", "confidence": 0.95, "payload": {"content": content}}
    if "ukáž pravid" in t or "ukaz pravid" in t:
        return {"intent": "rule_list", "capability_id": "CAP-005", "action": "RULE_LIST", "confidence": 0.94, "payload": {}}
    # CAP-008 Workflow Engine
    if "história workflow" in t or "historia workflow" in t or "workflow history" in t:
        return {"intent": "workflow_history", "capability_id": "CAP-008", "action": "WORKFLOW_HISTORY", "confidence": 0.96, "payload": {"workflow": extract_workflow_name(msg)}}
    if "stav workflow" in t or "status workflow" in t or "workflow status" in t:
        return {"intent": "workflow_status", "capability_id": "CAP-008", "action": "WORKFLOW_STATUS", "confidence": 0.96, "payload": {"workflow": extract_workflow_name(msg)}}
    if "zoznam workflow" in t or "zoznam pracovných procesov" in t or "zoznam pracovnych procesov" in t or "workflow list" in t:
        return {"intent": "workflow_list", "capability_id": "CAP-008", "action": "WORKFLOW_LIST", "confidence": 0.96, "payload": {}}
    if "nájdi workflow" in t or "najdi workflow" in t or "workflow find" in t:
        return {"intent": "workflow_find", "capability_id": "CAP-008", "action": "WORKFLOW_FIND", "confidence": 0.96, "payload": {"query": extract_workflow_name(msg) or msg}}
    if "validuj workflow" in t or "over workflow" in t or "workflow validate" in t:
        return {"intent": "workflow_validate", "capability_id": "CAP-008", "action": "WORKFLOW_VALIDATE", "confidence": 0.96, "payload": {"workflow": extract_workflow_name(msg)}}
    if "debug workflow" in t or "workflow debug" in t:
        return {"intent": "workflow_debug", "capability_id": "CAP-008", "action": "WORKFLOW_DEBUG", "confidence": 0.96, "payload": {"workflow": extract_workflow_name(msg)}}
    if "pozastav workflow" in t or "pause workflow" in t:
        return {"intent": "workflow_pause", "capability_id": "CAP-008", "action": "WORKFLOW_PAUSE", "confidence": 0.96, "payload": {"workflow": extract_workflow_name(msg)}}
    if "obnov workflow" in t or "resume workflow" in t:
        return {"intent": "workflow_resume", "capability_id": "CAP-008", "action": "WORKFLOW_RESUME", "confidence": 0.96, "payload": {"workflow": extract_workflow_name(msg)}}
    if "zruš workflow" in t or "zrus workflow" in t or "cancel workflow" in t:
        return {"intent": "workflow_cancel", "capability_id": "CAP-008", "action": "WORKFLOW_CANCEL", "confidence": 0.96, "payload": {"workflow": extract_workflow_name(msg)}}
    if "dokonči workflow" in t or "dokonc workflow" in t or "complete workflow" in t:
        return {"intent": "workflow_complete", "capability_id": "CAP-008", "action": "WORKFLOW_COMPLETE", "confidence": 0.96, "payload": {"workflow": extract_workflow_name(msg)}}
    if "vytvor šablónu workflow" in t or "vytvor sablonu workflow" in t or "workflow template create" in t:
        return {"intent": "workflow_template_create", "capability_id": "CAP-008", "action": "WORKFLOW_TEMPLATE_CREATE", "confidence": 0.95, "payload": {"template": extract_template(msg), "workflow": extract_workflow_name(msg) or extract_template(msg), "message": msg}}
    if "spusti šablónu workflow" in t or "spusti sablonu workflow" in t or "workflow template run" in t:
        return {"intent": "workflow_template_run", "capability_id": "CAP-008", "action": "WORKFLOW_TEMPLATE_RUN", "confidence": 0.95, "payload": {"template": extract_template(msg), "workflow": extract_workflow_name(msg) or extract_template(msg), "project": extract_project(msg) or "AI_OS", "message": msg}}
    if "spusti workflow" in t or "run workflow" in t or "daily_start" in t:
        wf = extract_workflow_name(msg) or extract_after(msg, [r"spusti workflow\s+(.+)$", r"workflow\s+(.+)$"]) or "daily_start"
        return {"intent": "workflow_run", "capability_id": "CAP-008", "action": "WORKFLOW_RUN", "confidence": 0.96, "payload": {"workflow": wf, "template": extract_template(msg), "project": extract_project(msg) or "AI_OS", "message": msg}}
    if "vytvor workflow" in t or "vytvor pracovný proces" in t or "vytvor pracovny proces" in t or "workflow create" in t:
        wf = extract_workflow_name(msg) or extract_after(msg, [r"vytvor workflow\s+(.+)$"]) or "Nový workflow"
        return {"intent": "workflow_create", "capability_id": "CAP-008", "action": "WORKFLOW_CREATE", "confidence": 0.96, "payload": {"workflow": wf, "template": extract_template(msg), "project": extract_project(msg) or "AI_OS", "message": msg}}
    if "workflow" in t:
        wf = extract_workflow_name(msg) or "daily_start"
        return {"intent": "workflow_status", "capability_id": "CAP-008", "action": "WORKFLOW_STATUS", "confidence": 0.88, "payload": {"workflow": wf}}

    # Task orchestration
    if "denný prehľad úloh" in t or "denny prehlad uloh" in t:
        return {"intent": "task_daily", "capability_id": "CAP-006", "action": "TASK_DAILY", "confidence": 0.95, "payload": {}}
    if "zoznam úloh" in t or "zoznam uloh" in t:
        return {"intent": "task_list", "capability_id": "CAP-006", "action": "TASK_LIST", "confidence": 0.95, "payload": {}}
    if "nájdi úlohu" in t or "najdi ulohu" in t:
        return {"intent": "task_find", "capability_id": "CAP-006", "action": "TASK_FIND", "confidence": 0.95, "payload": {"query": extract_task_title(msg) or msg}}
    if "dokonči úlohu" in t or "dokonc ulohu" in t:
        return {"intent": "task_complete", "capability_id": "CAP-006", "action": "TASK_COMPLETE", "confidence": 0.95, "payload": {"title": extract_task_title(msg) or msg}}
    if "zruš úlohu" in t or "zrus ulohu" in t:
        return {"intent": "task_cancel", "capability_id": "CAP-006", "action": "TASK_CANCEL", "confidence": 0.95, "payload": {"title": extract_task_title(msg) or msg}}
    if "uprav úlohu" in t or "uprav ulohu" in t:
        return {"intent": "task_update", "capability_id": "CAP-006", "action": "TASK_UPDATE", "confidence": 0.95, "payload": {"title": extract_task_title(msg) or msg, "priority": extract_priority(msg), "status": extract_status(msg), "deadline": extract_date(msg)}}
    if "vytvor úlohu" in t or "vytvor ulohu" in t or "nová úloha" in t or "nova uloha" in t:
        return {"intent": "task_create", "capability_id": "CAP-006", "action": "TASK_CREATE", "confidence": 0.95, "payload": {"title": extract_task_title(msg) or msg, "priority": extract_priority(msg), "project": extract_project(msg) or "AI_OS", "owner": "Daniel", "deadline": extract_date(msg), "content": msg}}
    if "aktívna úloha" in t or "aktivna uloha" in t:
        return {"intent": "task_active", "capability_id": "CAP-006", "action": "TASK_ACTIVE", "confidence": 0.92, "payload": {}}

    # Calendar and time
    if "ranný briefing" in t or "ranny briefing" in t:
        return {"intent": "morning_briefing", "capability_id": "CAP-007", "action": "MORNING_BRIEFING", "confidence": 0.95, "payload": {}}
    if "týždenný plán" in t or "tyzdenny plan" in t:
        return {"intent": "week_plan", "capability_id": "CAP-007", "action": "WEEK_PLAN", "confidence": 0.95, "payload": {}}
    if "denný plán" in t or "denny plan" in t or "časový plán" in t or "casovy plan" in t:
        return {"intent": "day_plan", "capability_id": "CAP-007", "action": "DAY_PLAN", "confidence": 0.95, "payload": {}}
    if "nájdi udal" in t or "najdi udal" in t or "udalosti" in t:
        return {"intent": "calendar_find", "capability_id": "CAP-007", "action": "CALENDAR_FIND", "confidence": 0.95, "payload": {"query": msg, "date": extract_date(msg)}}
    if "vytvor udalosť" in t or "vytvor udalost" in t or "kalendár" in t or "kalendar" in t:
        return {"intent": "calendar_create", "capability_id": "CAP-007", "action": "CALENDAR_CREATE", "confidence": 0.94, "payload": {"title": msg, "date": extract_date(msg)}}
    if "pripomien" in t:
        return {"intent": "task_reminder", "capability_id": "CAP-007", "action": "TASK_REMINDER", "confidence": 0.93, "payload": {"title": extract_task_title(msg) or msg, "date": extract_date(msg)}}
    if "deadline" in t or "termín" in t or "termin" in t:
        return {"intent": "task_deadline", "capability_id": "CAP-007", "action": "TASK_DEADLINE", "confidence": 0.93, "payload": {"title": extract_task_title(msg) or msg, "deadline": extract_date(msg)}}

    # Documents
    if "zoznam dokument" in t:
        return {"intent": "document_list", "capability_id": "CAP-004.5", "action": "FIND", "confidence": 0.92, "payload": {"query": ""}}
    if "nájdi dokument" in t or "najdi dokument" in t:
        return {"intent": "document_find", "capability_id": "CAP-004.5", "action": "FIND", "confidence": 0.95, "payload": {"query": extract_named_doc(msg) or msg}}
    if "prečítaj dokument" in t or "precitaj dokument" in t:
        return {"intent": "document_read", "capability_id": "CAP-004.5", "action": "READ", "confidence": 0.95, "payload": {"title": extract_named_doc(msg) or msg}}
    if "zálohuj dokument" in t or "zalohuj dokument" in t:
        return {"intent": "document_backup", "capability_id": "CAP-004.5", "action": "BACKUP", "confidence": 0.95, "payload": {"title": extract_named_doc(msg) or msg}}
    if "dopíš" in t or "dopis" in t:
        doc_title = extract_named_doc(msg)
        content = extract_after(msg, [r"(?:text|textom)\s+(.+)$", r"dopíš\s+(.+)$", r"dopis\s+(.+)$"]) or msg
        return {"intent": "document_append", "capability_id": "CAP-004.5", "action": "APPEND", "confidence": 0.94, "payload": {"title": doc_title, "content": content}}
    if "uprav v dokumente" in t or "nahraď" in t or "nahrad" in t:
        return {"intent": "document_update", "capability_id": "CAP-004.5", "action": "UPDATE", "confidence": 0.92, "payload": {"title": extract_named_doc(msg), "content": msg}}
    if "vytvor dokument" in t:
        title = extract_named_doc(msg) or extract_after(msg, [r"vytvor dokument\s+(.+?)(?:\s+text|\s+textom|$)"])
        content = extract_after(msg, [r"(?:textom|s textom|text)\s+(.+)$"]) or msg
        return {"intent": "document_create", "capability_id": "CAP-004.5", "action": "CREATE_NEW", "confidence": 0.95, "payload": {"title": title or "AI_OS Document", "content": content}}

    return {"intent": "smart_write", "capability_id": "CORE", "action": "SMART_WRITE", "confidence": 0.84, "payload": {"content": msg}}


def call_apps_script(route: Dict[str, Any], original_message: str, request_id: str) -> Dict[str, Any]:
    if not APPS_SCRIPT_WEBAPP_URL:
        return {"status": "error", "code": "APPS_SCRIPT_WEBAPP_URL_MISSING"}
    if not APPS_SCRIPT_SECRET:
        return {"status": "error", "code": "APPS_SCRIPT_SECRET_MISSING"}
    if not AI_OS_ROOT_FOLDER_ID:
        return {"status": "error", "code": "AI_OS_ROOT_FOLDER_ID_MISSING"}

    payload = {
        "secret": APPS_SCRIPT_SECRET,
        "request_id": request_id,
        "version": VERSION,
        "action": route["action"],
        "intent": route["intent"],
        "capability_id": route["capability_id"],
        "folder_id": AI_OS_ROOT_FOLDER_ID,
        "message": original_message,
        "payload": route.get("payload", {}),
    }
    try:
        response = requests.post(APPS_SCRIPT_WEBAPP_URL, json=payload, timeout=REQUEST_TIMEOUT_SECONDS, allow_redirects=True)
        content_type = response.headers.get("content-type", "")
        try:
            data = response.json()
        except Exception:
            data = {"status": "error", "code": "NON_JSON_APPS_SCRIPT_RESPONSE", "raw": response.text[:2000]}
        if response.status_code >= 400:
            data.setdefault("status", "error")
            data.setdefault("code", "APPS_SCRIPT_HTTP_ERROR")
            data["http_status"] = response.status_code
        data["debug_bridge"] = {
            "initial_http_status": response.history[0].status_code if response.history else response.status_code,
            "final_http_status": response.status_code,
            "content_type": content_type,
            "redirected": bool(response.history),
            "redirect_host": response.url.split('/')[2] if response.url.startswith("http") else "",
        }
        return data
    except requests.Timeout:
        return {"status": "error", "code": "APPS_SCRIPT_TIMEOUT", "timeout_seconds": REQUEST_TIMEOUT_SECONDS}
    except Exception as exc:
        return {"status": "error", "code": exc.__class__.__name__, "details": str(exc)[:2000]}


@app.get("/")
def root():
    return ok({
        "service": APP_NAME,
        "message": "AI_OS v2.1 CAP-008 Workflow Engine is running.",
        "config": {
            "api_token_configured": bool(API_TOKEN),
            "root_folder_id_configured": bool(AI_OS_ROOT_FOLDER_ID),
            "apps_script_webapp_url_configured": bool(APPS_SCRIPT_WEBAPP_URL),
            "apps_script_secret_configured": bool(APPS_SCRIPT_SECRET),
        },
    })


@app.head("/")
def root_head():
    return PlainTextResponse("")


@app.get("/debug/config")
def debug_config(request: Request):
    auth = require_token(request)
    if auth:
        return auth
    return ok({
        "config": {
            "api_token_configured": bool(API_TOKEN),
            "root_folder_id_configured": bool(AI_OS_ROOT_FOLDER_ID),
            "apps_script_webapp_url_configured": bool(APPS_SCRIPT_WEBAPP_URL),
            "apps_script_secret_configured": bool(APPS_SCRIPT_SECRET),
            "allowed_actions": ALLOWED_ACTIONS,
        }
    })


@app.get("/self-test")
def self_test(request: Request):
    auth = require_token(request)
    if auth:
        return auth
    tests = []
    checks = {
        "root": True,
        "api_token": bool(API_TOKEN),
        "root_folder_id": bool(AI_OS_ROOT_FOLDER_ID),
        "apps_script_webapp_url": bool(APPS_SCRIPT_WEBAPP_URL),
        "apps_script_secret": bool(APPS_SCRIPT_SECRET),
        "router_document": route_message("Vytvor dokument Test textom A")["action"] == "CREATE_NEW",
        "router_memory": route_message("Zapamätaj si test")["action"] == "MEMORY_WRITE",
        "router_project": route_message("Nastav projekt AI_OS")["action"] == "PROJECT_SET",
        "router_rule": route_message("Pravidlo: odpovedaj slovensky")["action"] == "RULE_ADD",
        "router_task_create": route_message("Vytvor úlohu Test priorita vysoká projekt AI_OS")["action"] == "TASK_CREATE",
        "router_task_daily": route_message("Denný prehľad úloh")["action"] == "TASK_DAILY",
        "router_calendar_find": route_message("Nájdi udalosti dnes")["action"] == "CALENDAR_FIND",
        "router_calendar_create": route_message("Vytvor udalosť test dnes")["action"] == "CALENDAR_CREATE",
        "router_time_plan": route_message("Denný plán")["action"] == "DAY_PLAN",
        "router_morning_briefing": route_message("Ranný briefing")["action"] == "MORNING_BRIEFING",
        "router_workflow_create": route_message("Vytvor workflow CAP008 Test projekt AI_OS")["action"] == "WORKFLOW_CREATE",
        "router_workflow_run": route_message("Spusti workflow CAP008 Test")["action"] == "WORKFLOW_RUN",
        "router_workflow_status": route_message("Stav workflow CAP008 Test")["action"] == "WORKFLOW_STATUS",
        "router_workflow_history": route_message("História workflow CAP008 Test")["action"] == "WORKFLOW_HISTORY",
    }
    for name, passed in checks.items():
        tests.append({"name": name, "status": "PASS" if passed else "FAIL"})
    return ok({"self_test": "PASS" if all(checks.values()) else "FAIL", "tests": tests})


@app.get("/assistant")
def assistant(request: Request, message: str = "", debug: bool = False):
    auth = require_token(request)
    if auth:
        return auth
    request_id = rid()
    route = route_message(message)
    result = call_apps_script(route, message, request_id)
    response = ok({
        "assistant": "Executive Assistant",
        "route": route,
        "allowed_actions": ALLOWED_ACTIONS,
        "answer": result.get("answer") or result.get("message") or "Hotovo.",
        "capability_result": result,
    }, request_id=request_id)
    if not debug:
        response.pop("allowed_actions", None)
    return JSONResponse(content=response)


@app.post("/assistant")
async def assistant_post(request: Request):
    auth = require_token(request)
    if auth:
        return auth
    body = await request.json()
    message = clean_text(body.get("message", ""))
    debug = bool(body.get("debug", False))
    request_id = rid()
    route = route_message(message)
    result = call_apps_script(route, message, request_id)
    return JSONResponse(content=ok({
        "assistant": "Executive Assistant",
        "route": route,
        "answer": result.get("answer") or result.get("message") or "Hotovo.",
        "capability_result": result,
        "debug": debug,
    }, request_id=request_id))
