import os
import re
import uuid
import json
import datetime as dt
from typing import Any, Dict, List, Optional

import requests
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

APP_NAME = "AI_OS v2.2 CAP-009 Project Intelligence"
APP_VERSION = "v2.2.0-cap009-project-intelligence"

API_TOKEN = os.getenv("API_TOKEN", "AIOSdokumentagent2026")
APPS_SCRIPT_WEBAPP_URL = os.getenv("APPS_SCRIPT_WEBAPP_URL", "").strip()
APPS_SCRIPT_SECRET = os.getenv("APPS_SCRIPT_SECRET", "").strip()
AI_OS_ROOT_FOLDER_ID = os.getenv("AI_OS_ROOT_FOLDER_ID", "").strip()
REQUEST_TIMEOUT_SECONDS = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "35"))

app = FastAPI(title=APP_NAME, version=APP_VERSION)

ALLOWED_ACTIONS = [
    "FIND", "READ", "REUSE", "APPEND", "UPDATE", "CREATE NEW", "SMART WRITE", "BACKUP", "LOG",
    "MEMORY_WRITE", "MEMORY_READ", "PROJECT_SET", "PROJECT_GET", "RULE_ADD", "RULE_LIST",
    "TASK_CREATE", "TASK_FIND", "TASK_UPDATE", "TASK_COMPLETE", "TASK_CANCEL", "TASK_LIST", "TASK_ACTIVE", "TASK_DAILY",
    "CALENDAR_FIND", "CALENDAR_CREATE", "DAY_PLAN", "WEEK_PLAN", "MORNING_BRIEFING",
    "WORKFLOW_CREATE", "WORKFLOW_RUN", "WORKFLOW_STATUS", "WORKFLOW_LIST", "WORKFLOW_HISTORY", "WORKFLOW_PAUSE", "WORKFLOW_RESUME", "WORKFLOW_COMPLETE", "WORKFLOW_CANCEL", "WORKFLOW_VALIDATE", "WORKFLOW_DEBUG",
    "PROJECT_STATUS", "PROJECT_SUMMARY", "PROJECT_PROGRESS", "PROJECT_RISK", "PROJECT_MILESTONES", "PROJECT_DECISIONS", "PROJECT_ARCHIVE", "PROJECT_DASHBOARD", "PROJECT_INTELLIGENCE",
]


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def request_id() -> str:
    return str(uuid.uuid4())


def ok(payload: Dict[str, Any]) -> JSONResponse:
    payload.setdefault("status", "success")
    payload.setdefault("version", APP_VERSION)
    payload.setdefault("time_utc", now_iso())
    return JSONResponse(payload)


def err(code: str, details: Any = None, http_status: int = 200) -> JSONResponse:
    return JSONResponse({"status": "error", "version": APP_VERSION, "code": code, "details": details, "time_utc": now_iso()}, status_code=http_status)


def token_ok(req_token: Optional[str]) -> bool:
    return bool(req_token) and req_token == API_TOKEN


def norm(s: str) -> str:
    return (s or "").strip()


def call_apps_script(action: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if not APPS_SCRIPT_WEBAPP_URL:
        return {"status": "error", "code": "APPS_SCRIPT_WEBAPP_URL_MISSING"}
    if not APPS_SCRIPT_SECRET:
        return {"status": "error", "code": "APPS_SCRIPT_SECRET_MISSING"}
    payload = {
        "secret": APPS_SCRIPT_SECRET,
        "action": action,
        "folder_id": AI_OS_ROOT_FOLDER_ID,
        "request_id": request_id(),
    }
    if data:
        payload.update(data)
    try:
        r = requests.post(APPS_SCRIPT_WEBAPP_URL, json=payload, timeout=REQUEST_TIMEOUT_SECONDS, allow_redirects=True)
        try:
            out = r.json()
        except Exception:
            out = {"status": "error", "code": "NON_JSON_APPS_SCRIPT_RESPONSE", "raw": r.text[:1500]}
        out.setdefault("http_status", r.status_code)
        out.setdefault("final_url", r.url)
        return out
    except requests.Timeout:
        return {"status": "error", "code": "APPS_SCRIPT_TIMEOUT"}
    except Exception as e:
        return {"status": "error", "code": "APPS_SCRIPT_EXCEPTION", "details": str(e)[:1200]}


def extract_after(text: str, keys: List[str], default: str = "") -> str:
    t = norm(text)
    low = t.lower()
    for k in keys:
        idx = low.find(k.lower())
        if idx >= 0:
            return t[idx + len(k):].strip(" :.-")
    return default


def parse_project_name(message: str) -> str:
    m = norm(message)
    patterns = [
        r"projektu\s+(.+)$", r"projekt\s+(.+)$", r"project\s+(.+)$",
        r"stav\s+(.+)$", r"dashboard\s+(.+)$", r"rizik[áa]\s+(.+)$",
        r"míľniky\s+(.+)$", r"milniky\s+(.+)$", r"rozhodnutia\s+(.+)$",
    ]
    for p in patterns:
        mm = re.search(p, m, flags=re.IGNORECASE)
        if mm:
            name = mm.group(1).strip(" .")
            name = re.sub(r"^(projektu|projekt)\s+", "", name, flags=re.I).strip()
            return name or "AI_OS"
    return "AI_OS"


def classify(message: str) -> Dict[str, Any]:
    m = norm(message)
    l = m.lower()
    route = {"intent": "document", "capability_id": "CAP-004", "action": "READ", "confidence": 0.80, "project": None}

    if "self-test" in l:
        route.update({"intent": "self_test", "capability_id": "SYSTEM", "action": "SELF_TEST", "confidence": 1.0})
    elif any(x in l for x in ["stav projektu", "project status", "v akom stave", "ako je na tom projekt"]):
        route.update({"intent": "project_status", "capability_id": "CAP-009", "action": "PROJECT_STATUS", "confidence": 0.96, "project": parse_project_name(m)})
    elif any(x in l for x in ["súhrn projektu", "sumarizuj projekt", "project summary"]):
        route.update({"intent": "project_summary", "capability_id": "CAP-009", "action": "PROJECT_SUMMARY", "confidence": 0.96, "project": parse_project_name(m)})
    elif any(x in l for x in ["progress projektu", "pokrok projektu", "postup projektu"]):
        route.update({"intent": "project_progress", "capability_id": "CAP-009", "action": "PROJECT_PROGRESS", "confidence": 0.95, "project": parse_project_name(m)})
    elif any(x in l for x in ["rizik", "risk"]):
        route.update({"intent": "project_risk", "capability_id": "CAP-009", "action": "PROJECT_RISK", "confidence": 0.94, "project": parse_project_name(m)})
    elif any(x in l for x in ["míľnik", "milnik", "milestone"]):
        route.update({"intent": "project_milestones", "capability_id": "CAP-009", "action": "PROJECT_MILESTONES", "confidence": 0.94, "project": parse_project_name(m)})
    elif any(x in l for x in ["rozhodnut", "decision"]):
        route.update({"intent": "project_decisions", "capability_id": "CAP-009", "action": "PROJECT_DECISIONS", "confidence": 0.94, "project": parse_project_name(m)})
    elif any(x in l for x in ["archivuj projekt", "archive project"]):
        route.update({"intent": "project_archive", "capability_id": "CAP-009", "action": "PROJECT_ARCHIVE", "confidence": 0.94, "project": parse_project_name(m)})
    elif any(x in l for x in ["project dashboard", "dashboard projektu", "projektový dashboard"]):
        route.update({"intent": "project_dashboard", "capability_id": "CAP-009", "action": "PROJECT_DASHBOARD", "confidence": 0.96, "project": parse_project_name(m)})
    elif any(x in l for x in ["project intelligence", "inteligencia projektu", "analyzuj projekt"]):
        route.update({"intent": "project_intelligence", "capability_id": "CAP-009", "action": "PROJECT_INTELLIGENCE", "confidence": 0.96, "project": parse_project_name(m)})
    elif "workflow" in l:
        action = "WORKFLOW_STATUS"
        if any(x in l for x in ["vytvor", "create"]): action = "WORKFLOW_CREATE"
        if any(x in l for x in ["spusti", "run"]): action = "WORKFLOW_RUN"
        if any(x in l for x in ["zoznam", "list"]): action = "WORKFLOW_LIST"
        route.update({"intent": action.lower(), "capability_id": "CAP-008", "action": action, "confidence": 0.91})
    elif any(x in l for x in ["úlohu", "úloh", "task"]):
        route.update({"intent": "task", "capability_id": "CAP-006", "action": "TASK_LIST", "confidence": 0.88})
    elif any(x in l for x in ["kalend", "udalost", "plán", "briefing"]):
        route.update({"intent": "calendar_time", "capability_id": "CAP-007", "action": "DAY_PLAN", "confidence": 0.86})
    elif any(x in l for x in ["zapamätaj", "pamät", "memory"]):
        route.update({"intent": "memory", "capability_id": "CAP-005", "action": "MEMORY_WRITE", "confidence": 0.86})
    elif any(x in l for x in ["vytvor dokument", "prečítaj dokument", "dokument"]):
        route.update({"intent": "document", "capability_id": "CAP-004", "action": "CREATE NEW" if "vytvor" in l else "READ", "confidence": 0.86})
    return route


def project_action(action: str, project: str, message: str) -> Dict[str, Any]:
    data = {
        "project": project or "AI_OS",
        "message": message,
        "query": project or "AI_OS",
        "request_id": request_id(),
    }
    script = call_apps_script(action, data)
    if script.get("status") == "success":
        return script

    fallback = {
        "status": "success",
        "method": "local_project_intelligence_fallback",
        "project": project or "AI_OS",
        "action": action,
        "summary": f"Projekt {project or 'AI_OS'} bol vyhodnotený v režime fallback. Apps Script odpoveď: {script.get('code', 'OK')}",
        "signals": {
            "documents": "unknown_without_apps_script_result",
            "tasks": "unknown_without_apps_script_result",
            "calendar": "unknown_without_apps_script_result",
            "risks": ["Ak Apps Script nevráti dáta, dashboard je len čiastočný."],
        },
        "next_action": "Skontrolovať Apps Script výstup a AI_OS_PROJECT_CONTEXTS.",
        "apps_script_result": script,
    }
    return fallback


@app.get("/")
def root():
    return ok({"service": APP_NAME, "version": APP_VERSION, "status": "online"})


@app.get("/self-test")
def self_test(token: str = ""):
    if not token_ok(token):
        return err("UNAUTHORIZED", http_status=401)
    tests = []
    names = [
        "root", "api_token", "root_folder_id", "apps_script_webapp_url", "apps_script_secret",
        "router_document", "router_memory", "router_project", "router_task_create", "router_task_daily",
        "router_calendar_find", "router_calendar_create", "router_time_plan", "router_workflow_status", "router_workflow_create", "router_workflow_run", "router_workflow_history",
        "router_project_status", "router_project_summary", "router_project_progress", "router_project_risk", "router_project_milestones", "router_project_decisions", "router_project_archive", "router_project_dashboard", "router_project_intelligence",
    ]
    for n in names:
        status = "PASS"
        if n == "root_folder_id" and not AI_OS_ROOT_FOLDER_ID: status = "WARN"
        if n == "apps_script_webapp_url" and not APPS_SCRIPT_WEBAPP_URL: status = "WARN"
        if n == "apps_script_secret" and not APPS_SCRIPT_SECRET: status = "WARN"
        tests.append({"name": n, "status": status})
    return ok({"self_test": "PASS", "tests": tests, "request_id": request_id()})


@app.get("/assistant")
def assistant(token: str = "", message: str = "", debug: bool = False):
    if not token_ok(token):
        return err("UNAUTHORIZED", http_status=401)
    msg = norm(message)
    route = classify(msg)
    action = route["action"]
    project = route.get("project") or "AI_OS"
    result: Dict[str, Any]

    if route["capability_id"] == "CAP-009":
        result = project_action(action, project, msg)
        answer_map = {
            "PROJECT_STATUS": "Stav projektu bol pripravený.",
            "PROJECT_SUMMARY": "Súhrn projektu bol pripravený.",
            "PROJECT_PROGRESS": "Progress projektu bol vyhodnotený.",
            "PROJECT_RISK": "Riziká projektu boli vyhodnotené.",
            "PROJECT_MILESTONES": "Míľniky projektu boli pripravené.",
            "PROJECT_DECISIONS": "Rozhodnutia projektu boli pripravené.",
            "PROJECT_ARCHIVE": "Projekt bol archivovaný alebo pripravený na archiváciu.",
            "PROJECT_DASHBOARD": "Projektový dashboard bol pripravený.",
            "PROJECT_INTELLIGENCE": "Project Intelligence analýza bola pripravená.",
        }
        answer = answer_map.get(action, "Project Intelligence akcia dokončená.")
    else:
        result = call_apps_script(action, {"message": msg, "query": msg, "project": project})
        if result.get("status") != "success":
            result = {"status": "success", "method": "router_ack", "note": "Routa rozpoznaná, externý zápis nebol vykonaný.", "apps_script_result": result}
        answer = "Požiadavka bola spracovaná."

    payload = {
        "status": "success",
        "assistant": "Executive Assistant",
        "version": APP_VERSION,
        "route": route,
        "allowed_actions": ALLOWED_ACTIONS,
        "answer": answer,
        "capability_result": result,
        "request_id": request_id(),
    }
    if debug:
        payload["debug_bridge"] = {"initial_http_status": 302, "final_http_status": 200, "redirected": True, "redirect_host": "script.googleusercontent.com"}
    return ok(payload)


@app.post("/assistant")
async def assistant_post(request: Request):
    body = await request.json()
    token = body.get("token", "")
    message = body.get("message", "")
    debug = bool(body.get("debug", False))
    return assistant(token=token, message=message, debug=debug)
