import os
import re
import json
import uuid
import datetime as dt
from typing import Any, Dict, Optional, Tuple

import requests
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

APP_NAME = "AI_OS v1.7.0 – CAP-007 Calendar & Time Orchestration Foundation"
VERSION = "v1.7.0-cap007-calendar-time-orchestration-foundation"

API_TOKEN = os.getenv("API_TOKEN", "").strip()
AI_OS_ROOT_FOLDER_ID = os.getenv("AI_OS_ROOT_FOLDER_ID", "").strip()
APPS_SCRIPT_WEBAPP_URL = os.getenv("APPS_SCRIPT_WEBAPP_URL", "").strip()
APPS_SCRIPT_SECRET = os.getenv("APPS_SCRIPT_SECRET", "").strip()
REQUEST_TIMEOUT_SECONDS = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "30"))
DEFAULT_TZ = os.getenv("AI_OS_TIMEZONE", "Europe/Bratislava").strip() or "Europe/Bratislava"

app = FastAPI(title=APP_NAME, version=VERSION)

ALLOWED_ACTIONS = [
    "FIND", "READ", "REUSE", "APPEND", "UPDATE", "CREATE NEW", "SMART WRITE", "BACKUP", "LOG",
    "MEMORY", "PROJECT", "RULE", "WORKFLOW",
    "TASK_CREATE", "TASK_FIND", "TASK_UPDATE", "TASK_COMPLETE", "TASK_CANCEL", "TASK_LIST", "TASK_ACTIVE", "TASK_DAILY",
    "CALENDAR_CREATE", "CALENDAR_FIND", "CALENDAR_LIST", "CALENDAR_READ", "TASK_REMINDER", "TASK_DEADLINE",
    "DAY_PLAN", "WEEK_PLAN", "MORNING_BRIEFING"
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
                cut = len(rest)
                for marker in [" deadline ", " priorita ", " stav ", " termín ", " termin "]:
                    j = rest.lower().find(marker)
                    if j >= 0: cut = min(cut, j)
                return compact_text(rest[:cut], 80)
    return "AI_OS"

def deadline_from_message(message: str) -> str:
    m = re.search(r"(deadline|termín|termin)\s*[:\-]?\s*([0-9]{4}-[0-9]{2}-[0-9]{2}|[0-9]{1,2}\.[0-9]{1,2}\.[0-9]{4}|[^,.]+)", message, re.I)
    return compact_text(m.group(2).strip(), 80) if m else ""

# ---------- time parsing for CAP-007 ----------

def local_today() -> dt.date:
    # Server time is UTC; this is good enough for generated defaults. Apps Script uses its project timezone for final Calendar writes.
    return dt.datetime.utcnow().date()

def parse_date_from_message(message: str) -> dt.date:
    low = message.lower()
    today = local_today()
    if "pozajtra" in low:
        return today + dt.timedelta(days=2)
    if "zajtra" in low:
        return today + dt.timedelta(days=1)
    if "dnes" in low:
        return today
    m = re.search(r"\b(20\d{2})-(\d{1,2})-(\d{1,2})\b", message)
    if m:
        return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.search(r"\b(\d{1,2})\.(\d{1,2})\.(20\d{2})\b", message)
    if m:
        return dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    return today

def parse_time_from_message(message: str, default_hour: int = 9, default_minute: int = 0) -> Tuple[int, int]:
    low = message.lower()
    m = re.search(r"\b(?:o|od)?\s*(\d{1,2})[:.](\d{2})\b", low)
    if m:
        return max(0, min(23, int(m.group(1)))), max(0, min(59, int(m.group(2))))
    m = re.search(r"\b(?:o|od)\s+(\d{1,2})\b", low)
    if m:
        return max(0, min(23, int(m.group(1)))), 0
    if "ráno" in low or "rano" in low: return 8, 0
    if "obed" in low: return 12, 0
    if "poobede" in low or "popoludní" in low or "popoludni" in low: return 15, 0
    if "večer" in low or "vecer" in low: return 19, 0
    return default_hour, default_minute

def parse_duration_minutes(message: str, default: int = 60) -> int:
    low = message.lower()
    m = re.search(r"(\d{1,3})\s*(min|minute|minút|minut)", low)
    if m:
        return max(5, min(480, int(m.group(1))))
    m = re.search(r"(\d{1,2})\s*(h|hod|hodín|hodin)", low)
    if m:
        return max(15, min(480, int(m.group(1))*60))
    return default

def iso_local(d: dt.date, h: int, m: int) -> str:
    return f"{d.isoformat()}T{h:02d}:{m:02d}:00"

def calendar_title_from_message(message: str) -> str:
    low = message.lower()
    starters = [
        "vytvor udalosť", "vytvor udalost", "pridaj udalosť", "pridaj udalost",
        "vytvor event", "naplánuj", "naplanuj", "daj do kalendára", "daj do kalendara"
    ]
    for s in starters:
        if low.startswith(s):
            raw = message[len(s):].strip(" .:-–—")
            for marker in [" zajtra", " dnes", " pozajtra", " o ", " od ", " na "]:
                j = raw.lower().find(marker)
                if j > 3:
                    raw = raw[:j]
                    break
            return compact_text(raw or "AI_OS udalosť", 120)
    return compact_text(message, 120)

def calendar_query_from_message(message: str) -> str:
    return extract_after_patterns(message, ["nájdi udalosť", "najdi udalost", "hľadaj udalosť", "hladaj udalost", "udalosti", "kalendár", "kalendar"]) or ""

def plan_scope_from_message(message: str) -> str:
    low = message.lower()
    if any(x in low for x in ["týž", "tyzd", "week"]): return "week"
    return "day"

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
        "timezone": DEFAULT_TZ,
    })
    try:
        first = requests.post(APPS_SCRIPT_WEBAPP_URL, json=body, timeout=REQUEST_TIMEOUT_SECONDS, allow_redirects=False)
        target = first.headers.get("Location")
        response = first
        redirected = False
        if 300 <= first.status_code < 400 and target:
            redirected = True
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

    # CAP-007 calendar & time
    if any(x in low for x in ["vytvor udalosť", "vytvor udalost", "pridaj udalosť", "pridaj udalost", "daj do kalendára", "daj do kalendara", "naplánuj", "naplanuj"]):
        return {"intent":"calendar_create", "capability_id":"CAP-007", "reason":"Požiadavka smeruje na vytvorenie kalendárovej udalosti."}
    if any(x in low for x in ["zoznam udalostí", "zoznam udalosti", "nájdi udalosť", "najdi udalost", "hľadaj udalosť", "hladaj udalost", "čo mám v kalendári", "co mam v kalendari", "program dňa", "program dna"]):
        return {"intent":"calendar_find", "capability_id":"CAP-007", "reason":"Požiadavka smeruje na vyhľadanie udalostí v kalendári."}
    if any(x in low for x in ["pripomienka k úlohe", "pripomienka k ulohe", "pripomeň úlohu", "pripomen ulohu", "pripomeň mi úlohu", "pripomen mi ulohu"]):
        return {"intent":"task_reminder", "capability_id":"CAP-007", "reason":"Požiadavka smeruje na vytvorenie pripomienky k úlohe."}
    if "deadline" in low and any(x in low for x in ["úloh", "uloh", "task"]):
        return {"intent":"task_deadline", "capability_id":"CAP-007", "reason":"Požiadavka smeruje na priradenie deadline k úlohe."}
    if any(x in low for x in ["denný plán", "denny plan", "týždenný plán", "tyzdenny plan", "ranný briefing", "ranny briefing", "morning briefing"]):
        return {"intent":"time_plan", "capability_id":"CAP-007", "reason":"Požiadavka smeruje na denný/týždenný časový plán."}

    # CAP-006 tasks
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

    # CAP-005
    if any(x in low for x in ["zapamätaj", "zapamataj", "pamäť", "pamat", "čo si pamätáš", "co si pamatas"]):
        return {"intent":"memory", "capability_id":"CAP-005", "reason":"Práca s pamäťou."}
    if any(x in low for x in ["projekt", "aktívny projekt", "aktivny projekt"]):
        return {"intent":"project", "capability_id":"CAP-005", "reason":"Práca s projektovým kontextom."}
    if any(x in low for x in ["pravidlo", "pravidlá", "pravidla"]):
        return {"intent":"rule", "capability_id":"CAP-005", "reason":"Práca s pravidlami."}
    if any(x in low for x in ["workflow", "daily_start"]):
        return {"intent":"workflow", "capability_id":"CAP-005", "reason":"Spustenie workflow."}

    # CAP-004
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

def handle_calendar(intent: str, message: str, request_id: str, debug: bool) -> Dict[str, Any]:
    d = parse_date_from_message(message)
    hour, minute = parse_time_from_message(message)
    duration = parse_duration_minutes(message)
    start_dt = dt.datetime.combine(d, dt.time(hour, minute))
    end_dt = start_dt + dt.timedelta(minutes=duration)
    payload: Dict[str, Any] = {
        "title": calendar_title_from_message(message),
        "query": calendar_query_from_message(message) or calendar_title_from_message(message),
        "content": message,
        "date": d.isoformat(),
        "start_iso": start_dt.strftime("%Y-%m-%dT%H:%M:%S"),
        "end_iso": end_dt.strftime("%Y-%m-%dT%H:%M:%S"),
        "duration_minutes": duration,
        "timezone": DEFAULT_TZ,
        "project": project_from_message(message),
        "task_query": extract_after_patterns(message, ["úlohe", "ulohe", "úlohu", "ulohu"]) or "",
        "scope": plan_scope_from_message(message),
    }
    action_map = {
        "calendar_create": "CALENDAR_CREATE",
        "calendar_find": "CALENDAR_FIND",
        "task_reminder": "TASK_REMINDER",
        "task_deadline": "TASK_DEADLINE",
        "time_plan": "TIME_PLAN",
    }
    return call_apps_script(action_map[intent], payload, request_id, debug)

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
    return call_apps_script(action_map[intent], payload, request_id, debug)

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
        return call_apps_script(action, {"content":extract_after_patterns(message, ["pravidlo:","pravidlo"]) or message}, request_id, debug)
    if intent == "workflow":
        return call_apps_script("WORKFLOW_RUN", {"workflow":"daily_start", "content":message}, request_id, debug)

    # document actions
    action_map = {
        "document_list":"LIST_DOCS",
        "document_create":"CREATE_DOC",
        "document_find":"FIND_DOC",
        "document_read":"READ_DOC",
        "document_append":"APPEND_DOC",
        "document_update":"UPDATE_DOC",
        "backup":"BACKUP_DOC",
    }
    title = title_from_message(message)
    query = extract_after_patterns(message, ["nájdi dokument", "najdi dokument", "prečítaj dokument", "precitaj dokument", "zálohuj dokument", "zalohuj dokument"]) or title
    return call_apps_script(action_map.get(intent, "STATUS"), {"title":title, "query":query, "content":content_from_message(message)}, request_id, debug)

def route_message(message: str, debug: bool=False) -> Dict[str, Any]:
    request_id = rid()
    decision = decide(message)
    intent = decision["intent"]
    if intent.startswith("calendar") or intent in {"task_reminder", "task_deadline", "time_plan"}:
        result = handle_calendar(intent, message, request_id, debug)
    elif intent.startswith("task_"):
        result = handle_task(intent, message, request_id, debug)
    elif intent == "status":
        result = call_apps_script("STATUS", {"content":message}, request_id, debug)
    else:
        result = handle_legacy(intent, message, request_id, debug)

    return {
        "status": "success",
        "assistant": "Executive Assistant",
        "version": VERSION,
        "route": {
            "intent": intent,
            "capability_id": decision["capability_id"],
            "confidence": 0.95,
            "reason": decision["reason"],
            "allowed_actions": ALLOWED_ACTIONS,
        },
        "answer": result.get("answer") or result.get("message") or "Požiadavka bola spracovaná.",
        "next_action": result.get("next_action", "Skontrolovať výsledok v Google Drive alebo Google Calendar."),
        "capability_result": result,
        "request_id": request_id,
        "time_utc": utc_now(),
    }

# ---------- endpoints ----------

@app.head("/")
def root_head():
    return JSONResponse(status_code=200, content={})

@app.get("/")
def root():
    return ok({"service":APP_NAME, "status":"running", "version":VERSION, "message":"AI_OS v1.7.0 CAP-007 Calendar & Time Orchestration is available.", "time_utc":utc_now()})

@app.get("/self-test")
def self_test(request: Request):
    denied = require_token(request)
    if denied: return denied
    tests = [
        ("root", True),
        ("api_token", bool(API_TOKEN)),
        ("root_folder_id", bool(AI_OS_ROOT_FOLDER_ID)),
        ("apps_script_webapp_url", bool(APPS_SCRIPT_WEBAPP_URL)),
        ("apps_script_secret", bool(APPS_SCRIPT_SECRET)),
        ("router_document", decide("Vytvor dokument Test")["intent"] == "document_create"),
        ("router_memory", decide("Zapamätaj si test")["intent"] == "memory"),
        ("router_project", decide("Nastav projekt AI_OS")["intent"] == "project"),
        ("router_task_create", decide("Vytvor úlohu test")["intent"] == "task_create"),
        ("router_task_daily", decide("Denný prehľad úloh")["intent"] == "task_daily"),
        ("router_calendar_create", decide("Vytvor udalosť Test zajtra o 9:00")["intent"] == "calendar_create"),
        ("router_calendar_find", decide("Zoznam udalostí dnes")["intent"] == "calendar_find"),
        ("router_task_reminder", decide("Pripomienka k úlohe CAP007 zajtra o 9")["intent"] == "task_reminder"),
        ("router_task_deadline", decide("Deadline úlohy CAP007 2026-07-10")["intent"] == "task_deadline"),
        ("router_time_plan", decide("Denný plán")["intent"] == "time_plan"),
    ]
    return ok({
        "status":"success",
        "self_test":"PASS" if all(v for _, v in tests) else "FAIL",
        "version":VERSION,
        "tests":[{"name":n, "status":"PASS" if v else "FAIL"} for n,v in tests],
        "request_id":rid(),
        "time_utc":utc_now(),
    })

@app.get("/assistant")
def assistant(request: Request):
    denied = require_token(request)
    if denied: return denied
    message = request.query_params.get("message", "").strip()
    debug = request.query_params.get("debug", "").lower() in {"1","true","yes","ano"}
    if not message:
        return ok({"status":"error", "detail":"Missing message.", "request_id":rid(), "time_utc":utc_now()})
    return ok(route_message(message, debug=debug))

@app.post("/assistant")
async def assistant_post(request: Request):
    denied = require_token(request)
    if denied: return denied
    body = await request.json()
    message = str(body.get("message", "")).strip()
    debug = bool(body.get("debug", False))
    if not message:
        return ok({"status":"error", "detail":"Missing message.", "request_id":rid(), "time_utc":utc_now()})
    return ok(route_message(message, debug=debug))
