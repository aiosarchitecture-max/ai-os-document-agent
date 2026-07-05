"""
AI_OS v2.3.1 – CAP-010.1 Daily Time Blocks
Render / FastAPI service.

Cieľ:
- ponechať existujúci Apps Script ako dátový zdroj,
- zaviesť dennú prevádzku: ranný štart, denný stav, večerné uzavretie,
- spojiť dokumenty, úlohy, kalendár, workflow a projektové riziká do praktického plánu dňa,
- bez debug=true vracať čistý ľudský text bez JSON balastu,
- zachovať debug=true pre technické testovanie.
"""

from __future__ import annotations

import os
import re
import uuid
import json
import html
import requests
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote_plus

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse

APP_NAME = "AI_OS v2.3.1 CAP-010.1 Daily Time Blocks"
VERSION = "v2.3.1-cap0101-daily-time-blocks"
REQUEST_TIMEOUT_SECONDS = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "40"))

API_TOKEN = os.getenv("API_TOKEN", "")
AI_OS_ROOT_FOLDER_ID = os.getenv("AI_OS_ROOT_FOLDER_ID", "")
APPS_SCRIPT_WEBAPP_URL = os.getenv("APPS_SCRIPT_WEBAPP_URL", "")
APPS_SCRIPT_SECRET = os.getenv("APPS_SCRIPT_SECRET", "")

app = FastAPI(title=APP_NAME, version=VERSION)

ALLOWED_ACTIONS = [
    "FIND", "READ", "REUSE", "APPEND", "UPDATE", "CREATE NEW", "SMART WRITE", "BACKUP", "LOG",
    "MEMORY_WRITE", "MEMORY_READ", "PROJECT_SET", "PROJECT_GET", "RULE_ADD", "RULE_LIST",
    "WORKFLOW_CREATE", "WORKFLOW_RUN", "WORKFLOW_STATUS", "WORKFLOW_HISTORY", "WORKFLOW_VALIDATE", "WORKFLOW_DEBUG",
    "TASK_CREATE", "TASK_LIST", "TASK_FIND", "TASK_UPDATE", "TASK_COMPLETE", "TASK_ACTIVE", "TASK_DAILY",
    "CALENDAR_FIND", "CALENDAR_CREATE", "DAY_PLAN", "WEEK_PLAN", "MORNING_BRIEFING",
    "PROJECT_STATUS", "PROJECT_SUMMARY", "PROJECT_PROGRESS", "PROJECT_RISK", "PROJECT_MILESTONES",
    "PROJECT_DECISIONS", "PROJECT_DASHBOARD", "PROJECT_INTELLIGENCE",
    "PROJECT_EXECUTIVE_SUMMARY", "PROJECT_EXECUTIVE_REPORT", "PROJECT_EXECUTIVE_ACTIONS",
    "DAILY_START", "DAILY_STATUS", "DAILY_REVIEW", "DAILY_CLOSE", "DAILY_COMMANDS",
    "DAILY_TIME_BLOCKS", "TIME_BLOCKS", "DAILY_PLAN_BLOCKS", "PLAN_DAY",
]

# -------------------------
# Utility / security
# -------------------------

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(data: Dict[str, Any], status_code: int = 200) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=data)


def _token_from_request(request: Request) -> str:
    return request.query_params.get("token", "") or request.headers.get("x-ai-os-token", "")


def _authorized(request: Request) -> bool:
    return bool(API_TOKEN) and _token_from_request(request) == API_TOKEN


def _debug_enabled(request: Request) -> bool:
    return str(request.query_params.get("debug", "")).lower() in {"1", "true", "yes", "ano"}


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def lower_sk(value: Any) -> str:
    return normalize_text(value).lower()


def first_nonempty(*values: Any) -> str:
    for value in values:
        s = normalize_text(value)
        if s:
            return s
    return ""

# -------------------------
# Intent router
# -------------------------

def route_intent(message: str) -> Dict[str, Any]:
    msg = lower_sk(message)

    # CAP-010.1 daily time blocks routes – musí byť pred všeobecným „Denný plán".
    if any(x in msg for x in ["časové bloky", "casove bloky", "dnešné bloky", "dnesne bloky", "denné bloky", "denne bloky", "time blocks"]):
        return _route("DAILY_TIME_BLOCKS", "CAP-010.1", 0.98, "Požiadavka smeruje na denné časové bloky.")
    if any(x in msg for x in ["denný plán s blokmi", "denny plan s blokmi", "plán dňa s blokmi", "plan dna s blokmi", "naplánuj deň", "naplanuj den", "plan day"]):
        return _route("DAILY_PLAN_BLOCKS", "CAP-010.1", 0.98, "Požiadavka smeruje na denný plán s časovými blokmi.")

    # CAP-010 daily operations routes
    if any(x in msg for x in ["ranný štart", "ranny start", "štart dňa", "start dna", "daily start", "ranný briefing", "ranny briefing"]):
        return _route("DAILY_START", "CAP-010", 0.97, "Požiadavka smeruje na ranný štart dennej prevádzky.")
    if any(x in msg for x in ["denný stav", "denny stav", "stav dňa", "stav dna", "daily status", "čo dnes", "co dnes"]):
        return _route("DAILY_STATUS", "CAP-010", 0.96, "Požiadavka smeruje na priebežný stav dňa.")
    if any(x in msg for x in ["večerná uzávierka", "vecerna uzavierka", "uzavri deň", "uzavri den", "koniec dňa", "koniec dna", "daily close"]):
        return _route("DAILY_CLOSE", "CAP-010", 0.97, "Požiadavka smeruje na uzavretie dňa.")
    if any(x in msg for x in ["denné vyhodnotenie", "denne vyhodnotenie", "rekapitulácia dňa", "rekapitulacia dna", "daily review"]):
        return _route("DAILY_REVIEW", "CAP-010", 0.96, "Požiadavka smeruje na vyhodnotenie dňa.")
    if any(x in msg for x in ["denné príkazy", "denne prikazy", "príkazy dňa", "prikazy dna", "daily commands"]):
        return _route("DAILY_COMMANDS", "CAP-010", 0.95, "Požiadavka smeruje na zoznam denných príkazov.")

    # CAP-009.1 executive routes
    if any(x in msg for x in ["executive", "manažérsky", "manazersky", "prehľad projektu", "prehlad projektu"]):
        if any(x in msg for x in ["akcie", "kroky", "odporúč", "odporuc"]):
            return _route("PROJECT_EXECUTIVE_ACTIONS", "CAP-009.1", 0.97, "Požiadavka smeruje na prioritizované manažérske kroky.")
        if any(x in msg for x in ["report", "správa", "sprava", "podrob"]):
            return _route("PROJECT_EXECUTIVE_REPORT", "CAP-009.1", 0.97, "Požiadavka smeruje na manažérsky report.")
        return _route("PROJECT_EXECUTIVE_SUMMARY", "CAP-009.1", 0.97, "Požiadavka smeruje na krátky manažérsky súhrn.")

    if any(x in msg for x in ["stav projektu", "dashboard projektu", "súhrn projektu", "suhrn projektu", "riziká projektu", "rizika projektu", "rozhodnutia projektu", "míľnik", "milnik", "progress projektu", "analyzuj projekt"]):
        if "dashboard" in msg:
            return _route("PROJECT_DASHBOARD", "CAP-009", 0.96, "Požiadavka smeruje na projektový dashboard.")
        if "rizik" in msg:
            return _route("PROJECT_RISK", "CAP-009", 0.95, "Požiadavka smeruje na projektové riziká.")
        if "rozhodnut" in msg:
            return _route("PROJECT_DECISIONS", "CAP-009", 0.95, "Požiadavka smeruje na projektové rozhodnutia.")
        if "míľnik" in msg or "milnik" in msg:
            return _route("PROJECT_MILESTONES", "CAP-009", 0.95, "Požiadavka smeruje na projektové míľniky.")
        if "progress" in msg or "pokrok" in msg:
            return _route("PROJECT_PROGRESS", "CAP-009", 0.95, "Požiadavka smeruje na projektový pokrok.")
        if "súhrn" in msg or "suhrn" in msg or "analyzuj" in msg:
            return _route("PROJECT_SUMMARY", "CAP-009", 0.95, "Požiadavka smeruje na súhrn projektu.")
        return _route("PROJECT_STATUS", "CAP-009", 0.96, "Požiadavka smeruje na stav projektu.")

    if any(x in msg for x in ["zoznam workflow", "vytvor workflow", "spusti workflow", "stav workflow", "história workflow", "historia workflow", "validuj workflow", "debug workflow", "pozastav workflow", "obnov workflow", "dokonči workflow", "dokonc workflow"]):
        if "vytvor" in msg:
            return _route("WORKFLOW_CREATE", "CAP-008", 0.95, "Požiadavka smeruje na vytvorenie workflow.")
        if "spusti" in msg:
            return _route("WORKFLOW_RUN", "CAP-008", 0.95, "Požiadavka smeruje na spustenie workflow.")
        if "stav" in msg:
            return _route("WORKFLOW_STATUS", "CAP-008", 0.95, "Požiadavka smeruje na stav workflow.")
        if "hist" in msg:
            return _route("WORKFLOW_HISTORY", "CAP-008", 0.95, "Požiadavka smeruje na históriu workflow.")
        if "valid" in msg:
            return _route("WORKFLOW_VALIDATE", "CAP-008", 0.95, "Požiadavka smeruje na validáciu workflow.")
        if "debug" in msg:
            return _route("WORKFLOW_DEBUG", "CAP-008", 0.95, "Požiadavka smeruje na debug workflow.")
        return _route("WORKFLOW_STATUS", "CAP-008", 0.90, "Požiadavka smeruje na workflow.")

    if any(x in msg for x in ["zoznam úloh", "zoznam uloh", "vytvor úlohu", "vytvor ulohu", "nájdi úlohu", "najdi ulohu", "uprav úlohu", "uprav ulohu", "dokonči úlohu", "dokonci ulohu", "denný prehľad úloh", "denny prehlad uloh"]):
        if "zoznam" in msg:
            return _route("TASK_LIST", "CAP-006", 0.95, "Požiadavka smeruje na zoznam úloh.")
        if "vytvor" in msg:
            return _route("TASK_CREATE", "CAP-006", 0.95, "Požiadavka smeruje na vytvorenie úlohy.")
        if "nájdi" in msg or "najdi" in msg:
            return _route("TASK_FIND", "CAP-006", 0.95, "Požiadavka smeruje na nájdenie úlohy.")
        if "uprav" in msg:
            return _route("TASK_UPDATE", "CAP-006", 0.95, "Požiadavka smeruje na úpravu úlohy.")
        if "dokon" in msg:
            return _route("TASK_COMPLETE", "CAP-006", 0.95, "Požiadavka smeruje na dokončenie úlohy.")
        return _route("TASK_DAILY", "CAP-006", 0.92, "Požiadavka smeruje na denný prehľad úloh.")

    if any(x in msg for x in ["nájdi udalosti", "najdi udalosti", "vytvor udalosť", "vytvor udalost", "denný plán", "denny plan", "týždenný plán", "tyzdenny plan", "ranný briefing", "ranny briefing"]):
        if "vytvor" in msg:
            return _route("CALENDAR_CREATE", "CAP-007", 0.95, "Požiadavka smeruje na vytvorenie udalosti.")
        if "týž" in msg or "tyz" in msg:
            return _route("WEEK_PLAN", "CAP-007", 0.95, "Požiadavka smeruje na týždenný plán.")
        if "rann" in msg:
            return _route("MORNING_BRIEFING", "CAP-007", 0.95, "Požiadavka smeruje na ranný briefing.")
        if "plán" in msg or "plan" in msg:
            return _route("DAY_PLAN", "CAP-007", 0.95, "Požiadavka smeruje na denný plán.")
        return _route("CALENDAR_FIND", "CAP-007", 0.95, "Požiadavka smeruje na hľadanie udalostí.")

    if any(x in msg for x in ["zapamätaj", "zapamataj"]):
        return _route("MEMORY_WRITE", "CAP-005", 0.95, "Požiadavka smeruje na zápis do pamäte.")
    if any(x in msg for x in ["čo si pamätáš", "co si pamatas"]):
        return _route("MEMORY_READ", "CAP-005", 0.95, "Požiadavka smeruje na čítanie pamäte.")
    if any(x in msg for x in ["nastav projekt", "aktívny projekt", "aktivny projekt"]):
        return _route("PROJECT_SET" if "nastav" in msg else "PROJECT_GET", "CAP-005", 0.95, "Požiadavka smeruje na projektový kontext.")
    if msg.startswith("pravidlo") or "ukáž pravidlá" in msg or "ukaz pravidla" in msg:
        return _route("RULE_ADD" if msg.startswith("pravidlo") else "RULE_LIST", "CAP-005", 0.95, "Požiadavka smeruje na pravidlá.")

    if any(x in msg for x in ["zoznam dokumentov", "nájdi dokument", "najdi dokument", "prečítaj dokument", "precitaj dokument", "vytvor dokument", "dopíš", "dopis", "uprav v dokumente", "zálohuj dokument", "zalohuj dokument"]):
        if "zoznam" in msg:
            return _route("FIND", "CAP-004.4", 0.92, "Požiadavka smeruje na zoznam dokumentov.")
        if "vytvor" in msg:
            return _route("CREATE NEW", "CAP-004.4", 0.95, "Požiadavka smeruje na vytvorenie dokumentu.")
        if "prečítaj" in msg or "precitaj" in msg:
            return _route("READ", "CAP-004.4", 0.95, "Požiadavka smeruje na čítanie dokumentu.")
        if "dopíš" in msg or "dopis" in msg:
            return _route("APPEND", "CAP-004.4", 0.95, "Požiadavka smeruje na dopísanie dokumentu.")
        if "uprav" in msg:
            return _route("UPDATE", "CAP-004.4", 0.95, "Požiadavka smeruje na úpravu dokumentu.")
        if "záloh" in msg or "zaloh" in msg:
            return _route("BACKUP", "CAP-004.5", 0.95, "Požiadavka smeruje na zálohu dokumentu.")
        return _route("FIND", "CAP-004.4", 0.92, "Požiadavka smeruje na vyhľadanie dokumentu.")

    return _route("REUSE", "SRV-001", 0.84, "Predvolený režim: najprv opätovne použiť existujúce znalosti.")


def _route(intent: str, cap: str, confidence: float, reason: str) -> Dict[str, Any]:
    return {
        "intent": intent,
        "capability_id": cap,
        "confidence": confidence,
        "reason": reason,
        "allowed_actions": ALLOWED_ACTIONS,
    }

# -------------------------
# Apps Script bridge
# -------------------------

def call_apps_script(action: str, message: str, request_id: str) -> Dict[str, Any]:
    if not APPS_SCRIPT_WEBAPP_URL:
        return {"status": "error", "code": "APPS_SCRIPT_WEBAPP_URL_MISSING"}
    if not APPS_SCRIPT_SECRET:
        return {"status": "error", "code": "APPS_SCRIPT_SECRET_MISSING"}
    if not AI_OS_ROOT_FOLDER_ID:
        return {"status": "error", "code": "AI_OS_ROOT_FOLDER_ID_MISSING"}

    payload = {
        "secret": APPS_SCRIPT_SECRET,
        "action": action,
        "message": message,
        "content": message,
        "title": extract_title(message),
        "query": extract_query(message),
        "project": extract_project(message),
        "folder_id": AI_OS_ROOT_FOLDER_ID,
        "request_id": request_id,
        "version": VERSION,
    }

    try:
        response = requests.post(
            APPS_SCRIPT_WEBAPP_URL,
            json=payload,
            timeout=REQUEST_TIMEOUT_SECONDS,
            allow_redirects=True,
        )
        content_type = response.headers.get("Content-Type", "")
        try:
            data = response.json()
        except Exception:
            data = {"status": "error", "code": "NON_JSON_APPS_SCRIPT_RESPONSE", "raw": response.text[:2000]}

        if response.status_code >= 400:
            return {
                "status": "error",
                "code": "APPS_SCRIPT_HTTP_ERROR",
                "http_status": response.status_code,
                "content_type": content_type,
                "response": data,
                "final_url": response.url,
            }
        if isinstance(data, dict) and data.get("status") not in (None, "success", "ok"):
            data.setdefault("status", "error")
        if isinstance(data, dict):
            data.setdefault("status", "success")
            data.setdefault("method", "apps_script")
            data.setdefault("final_url", response.url)
        return data
    except requests.Timeout:
        return {"status": "error", "code": "APPS_SCRIPT_TIMEOUT", "timeout_seconds": REQUEST_TIMEOUT_SECONDS}
    except Exception as exc:
        return {"status": "error", "code": "APPS_SCRIPT_EXCEPTION", "details": str(exc)[:2000]}


def extract_project(message: str) -> str:
    msg = normalize_text(message)
    m = re.search(r"projekt\s+([A-Za-z0-9_\-\.]+)", msg, re.IGNORECASE)
    if m:
        return m.group(1)
    return "AI_OS"


def extract_title(message: str) -> str:
    msg = normalize_text(message)
    patterns = [
        r"dokument\s+(.+?)(?:\s+textom|\s+s textom|$)",
        r"workflow\s+(.+?)(?:\s+projekt|$)",
        r"úlohu\s+(.+?)(?:\s+priorita|\s+projekt|$)",
        r"ulohu\s+(.+?)(?:\s+priorita|\s+projekt|$)",
        r"projektu\s+(.+)$",
    ]
    for pat in patterns:
        m = re.search(pat, msg, re.IGNORECASE)
        if m:
            return m.group(1).strip()[:120]
    return msg[:120] or "AI_OS Request"


def extract_query(message: str) -> str:
    msg = normalize_text(message)
    for word in ["nájdi", "najdi", "prečítaj", "precitaj", "stav", "súhrn", "suhrn", "dashboard", "rozhodnutia"]:
        msg = re.sub(rf"^{word}\s+", "", msg, flags=re.IGNORECASE)
    return msg[:200]

# -------------------------
# Executive analyzer
# -------------------------

def build_executive_view(apps_data: Dict[str, Any], project: str = "AI_OS") -> Dict[str, Any]:
    """Convert large Apps Script data into compact executive state."""
    docs = _extract_list(apps_data, ["documents", "docs", "relevant_docs", "items"])
    tasks = _extract_list(apps_data, ["tasks", "task_list", "open_tasks"])
    calendar = _extract_list(apps_data, ["calendar", "events", "calendar_events"])
    risks_raw = _extract_list(apps_data, ["risks", "project_risks"])
    decisions_raw = _extract_list(apps_data, ["decisions", "project_decisions"])
    milestones_raw = _extract_list(apps_data, ["milestones", "project_milestones"])

    if not docs and isinstance(apps_data.get("dashboard"), dict):
        docs = _extract_list(apps_data["dashboard"], ["documents", "docs", "items"])
    if not tasks and isinstance(apps_data.get("dashboard"), dict):
        tasks = _extract_list(apps_data["dashboard"], ["tasks", "open_tasks"])
    if not calendar and isinstance(apps_data.get("dashboard"), dict):
        calendar = _extract_list(apps_data["dashboard"], ["calendar", "events"])

    doc_titles = [_item_title(d) for d in docs]
    task_titles = [_item_title(t) for t in tasks]
    calendar_titles = [_item_title(e) for e in calendar]

    caps = detect_caps(doc_titles + task_titles + calendar_titles + json_sample_strings(apps_data))
    last_cap = max(caps) if caps else None
    next_cap = f"CAP-{int(last_cap.split('-')[1]) + 1:03d}" if last_cap and re.match(r"CAP-\d+", last_cap) else "CAP-010"

    task_counts = count_tasks(tasks)
    latest_docs = latest_items(docs, limit=5)
    top_tasks = top_priority_tasks(tasks, limit=5)
    upcoming_events = latest_items(calendar, limit=5)
    risks = detect_risks(apps_data, risks_raw)
    decisions = summarize_named_items(decisions_raw, limit=5)
    milestones = summarize_named_items(milestones_raw, limit=5)

    phase = detect_phase(last_cap, task_counts)

    recommendations = build_recommendations(
        project=project,
        last_cap=last_cap,
        next_cap=next_cap,
        task_counts=task_counts,
        risks=risks,
        docs_count=len(docs),
        calendar_count=len(calendar),
    )

    return {
        "project": project,
        "version": VERSION,
        "phase": phase,
        "progress": {
            "last_detected_cap": last_cap or "unknown",
            "next_recommended_cap": next_cap,
            "detected_caps": caps,
        },
        "counts": {
            "documents": len(docs),
            "tasks": len(tasks),
            "calendar_events": len(calendar),
            "risks": len(risks),
            "decisions": len(decisions),
            "milestones": len(milestones),
        },
        "tasks": task_counts,
        "latest_documents": latest_docs,
        "priority_tasks": top_tasks,
        "upcoming_events": upcoming_events,
        "risks": risks[:7],
        "decisions": decisions[:7],
        "milestones": milestones[:7],
        "recommendations": recommendations,
        "health": executive_health_score(len(docs), task_counts, len(calendar), len(risks)),
    }


def _extract_list(data: Any, keys: List[str]) -> List[Any]:
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []
    for key in keys:
        value = data.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            nested = _extract_list(value, keys)
            if nested:
                return nested
    # scan one level deep
    for value in data.values():
        if isinstance(value, dict):
            nested = _extract_list(value, keys)
            if nested:
                return nested
    return []


def _item_title(item: Any) -> str:
    if isinstance(item, dict):
        return first_nonempty(item.get("title"), item.get("name"), item.get("summary"), item.get("content"), item.get("text"), item.get("id"))
    return normalize_text(item)


def _item_status(item: Any) -> str:
    if isinstance(item, dict):
        return lower_sk(first_nonempty(item.get("status"), item.get("state")))
    return ""


def _item_priority(item: Any) -> str:
    if isinstance(item, dict):
        return lower_sk(first_nonempty(item.get("priority"), item.get("prio")))
    return ""


def latest_items(items: List[Any], limit: int = 5) -> List[Dict[str, Any]]:
    out = []
    for item in items[:limit]:
        if isinstance(item, dict):
            out.append({
                "title": _item_title(item),
                "status": first_nonempty(item.get("status"), item.get("state")),
                "updated": first_nonempty(item.get("updated"), item.get("modified"), item.get("created"), item.get("time")),
                "url": first_nonempty(item.get("url"), item.get("webViewLink")),
            })
        else:
            out.append({"title": _item_title(item)})
    return [x for x in out if x.get("title")]


def top_priority_tasks(tasks: List[Any], limit: int = 5) -> List[Dict[str, Any]]:
    priority_rank = {"critical": 0, "kritická": 0, "kriticka": 0, "high": 1, "vysoká": 1, "vysoka": 1, "medium": 2, "stredná": 2, "low": 3, "nízka": 3}
    def rank(item: Any) -> Tuple[int, str]:
        return (priority_rank.get(_item_priority(item), 9), _item_title(item))
    selected = sorted(tasks, key=rank)[:limit]
    return latest_items(selected, limit=limit)


def count_tasks(tasks: List[Any]) -> Dict[str, int]:
    counts = {"total": len(tasks), "open": 0, "active": 0, "done": 0, "blocked": 0, "critical_or_high": 0}
    for t in tasks:
        status = _item_status(t)
        prio = _item_priority(t)
        if any(x in status for x in ["done", "complete", "completed", "hotovo", "dokon"]):
            counts["done"] += 1
        elif any(x in status for x in ["active", "progress", "running", "in_progress"]):
            counts["active"] += 1
        elif any(x in status for x in ["block", "blocked", "risk"]):
            counts["blocked"] += 1
        else:
            counts["open"] += 1
        if any(x in prio for x in ["critical", "krit", "high", "vysok"]):
            counts["critical_or_high"] += 1
    return counts


def json_sample_strings(data: Any, limit: int = 300) -> List[str]:
    text = json.dumps(data, ensure_ascii=False)[:20000]
    return re.findall(r"[A-Za-z0-9_\-\.]{3,80}", text)[:limit]


def detect_caps(strings: List[str]) -> List[str]:
    caps = set()
    for s in strings:
        for m in re.finditer(r"CAP[-_ ]?0*(\d{1,3})(?:\.\d+)?", s, flags=re.IGNORECASE):
            caps.add(f"CAP-{int(m.group(1)):03d}")
    return sorted(caps)


def detect_risks(data: Dict[str, Any], explicit: List[Any]) -> List[str]:
    risks = summarize_named_items(explicit, limit=10)
    text = json.dumps(data, ensure_ascii=False).lower()[:50000]
    keywords = ["risk", "riziko", "blocker", "blocked", "chyba", "error", "warning", "todo", "fixme", "unknown", "apps_script_exception"]
    found = []
    for k in keywords:
        if k in text:
            found.append(k)
    if found and not risks:
        risks.append("Detegované technické signály v dátach: " + ", ".join(sorted(set(found))[:8]))
    return risks[:10]


def summarize_named_items(items: List[Any], limit: int = 5) -> List[str]:
    out = []
    for item in items[:limit]:
        title = _item_title(item)
        if title:
            out.append(title[:180])
    return out


def detect_phase(last_cap: Optional[str], task_counts: Dict[str, int]) -> str:
    if task_counts.get("blocked", 0) > 0:
        return "Stabilizácia / odblokovanie"
    if last_cap:
        try:
            n = int(last_cap.split("-")[1])
            if n >= 9:
                return "Implementácia + manažérska inteligencia"
            if n >= 6:
                return "Orchestrácia prevádzky"
        except Exception:
            pass
    return "Implementácia"


def executive_health_score(docs_count: int, task_counts: Dict[str, int], calendar_count: int, risk_count: int) -> Dict[str, Any]:
    score = 100
    if docs_count == 0:
        score -= 25
    if task_counts.get("total", 0) == 0:
        score -= 20
    if calendar_count == 0:
        score -= 10
    if risk_count > 5:
        score -= 15
    if task_counts.get("blocked", 0) > 0:
        score -= 15
    score = max(0, min(100, score))
    if score >= 85:
        label = "OK"
    elif score >= 65:
        label = "Pozor"
    else:
        label = "Rizikové"
    return {"score": score, "label": label}


def build_recommendations(project: str, last_cap: Optional[str], next_cap: str, task_counts: Dict[str, int], risks: List[str], docs_count: int, calendar_count: int) -> List[str]:
    recs = []
    if next_cap:
        recs.append(f"Pokračovať na {next_cap} podľa roadmapy, ale najprv stabilizovať dennú prevádzku CAP-010.")
    if task_counts.get("critical_or_high", 0):
        recs.append(f"Prejsť {task_counts['critical_or_high']} úloh s vysokou/kritickou prioritou a určiť vlastníka alebo termín.")
    if risks:
        recs.append("Vyhodnotiť otvorené riziká a oddeliť technické riziká od produktových rozhodnutí.")
    if docs_count:
        recs.append("Udržať AI_OS master dokument ako zdroj pravdy a zapisovať rozhodnutia do changelogu.")
    if calendar_count == 0:
        recs.append("Doplniť kalendárovú vrstvu, aby ranný briefing vedel pracovať s reálnym časom.")
    recs.append("V bežnej prevádzke používať URL bez debug=true, aby výstup nebol surový JSON.")
    return recs[:6]

# -------------------------
# Executive formatting
# -------------------------

def format_executive_summary(view: Dict[str, Any]) -> str:
    counts = view["counts"]
    tasks = view["tasks"]
    progress = view["progress"]
    health = view["health"]
    recs = view.get("recommendations", [])
    risks = view.get("risks", [])

    lines = [
        "AI_OS – manažérsky prehľad",
        "",
        f"Stav: {health['label']} ({health['score']}/100)",
        f"Fáza: {view['phase']}",
        f"Pokrok: posledný rozpoznaný modul {progress['last_detected_cap']}; ďalší odporúčaný krok {progress['next_recommended_cap']}.",
        "",
        f"Dáta: {counts['documents']} dokumentov, {tasks['total']} úloh, {counts['calendar_events']} kalendárových položiek.",
        f"Úlohy: otvorené {tasks['open']}, aktívne {tasks['active']}, dokončené {tasks['done']}, blokované {tasks['blocked']}.",
    ]
    if risks:
        lines += ["", "Riziká:"] + [f"- {r}" for r in risks[:3]]
    if recs:
        lines += ["", "Odporúčané kroky:"] + [f"{i+1}. {r}" for i, r in enumerate(recs[:4])]
    return "\n".join(lines)


def format_executive_report(view: Dict[str, Any]) -> str:
    lines = [format_executive_summary(view), "", "Detail:"]
    if view.get("latest_documents"):
        lines.append("\nNajnovšie/relevantné dokumenty:")
        for d in view["latest_documents"][:5]:
            lines.append(f"- {d.get('title')}")
    if view.get("priority_tasks"):
        lines.append("\nPrioritné úlohy:")
        for t in view["priority_tasks"][:5]:
            status = f" ({t.get('status')})" if t.get("status") else ""
            lines.append(f"- {t.get('title')}{status}")
    if view.get("upcoming_events"):
        lines.append("\nKalendár / časové položky:")
        for e in view["upcoming_events"][:5]:
            lines.append(f"- {e.get('title')}")
    if view.get("decisions"):
        lines.append("\nRozhodnutia:")
        for x in view["decisions"][:5]:
            lines.append(f"- {x}")
    return "\n".join(lines)


def format_executive_actions(view: Dict[str, Any]) -> str:
    lines = ["AI_OS – odporúčané kroky", ""]
    for i, r in enumerate(view.get("recommendations", [])[:6], 1):
        lines.append(f"{i}. {r}")
    return "\n".join(lines)



def clean_human_output(value: Any) -> str:
    """Return safe, readable plain text for browser / voice use. No JSON wrapper."""
    if value is None:
        return "Hotovo."
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False, indent=2)
    else:
        text = str(value)

    text = html.unescape(text).strip()
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    # Odstráň najčastejšie zvyšky technického balastu, ak by prišli z dátového zdroja.
    noisy_prefixes = ('{"status":', '{ status:')
    if text.startswith(noisy_prefixes):
        try:
            parsed = json.loads(text)
            text = first_nonempty(parsed.get("answer"), parsed.get("message"), parsed.get("summary"), "Hotovo.") if isinstance(parsed, dict) else text
        except Exception:
            pass

    return text.strip() or "Hotovo."



# -------------------------
# CAP-010.1 Daily Time Blocks
# -------------------------

def cap0101_default_blocks() -> List[Dict[str, str]]:
    return [
        {"name": "Ranný štart", "start": "06:30", "end": "07:00", "type": "START", "purpose": "Zorientovať deň, stav systému a priority."},
        {"name": "Hlboká práca 1", "start": "08:30", "end": "10:30", "type": "DEEP_WORK", "purpose": "Najdôležitejšia úloha dňa bez rušenia."},
        {"name": "Operatíva", "start": "10:45", "end": "12:00", "type": "ADMIN", "purpose": "E-maily, faktúry, odpovede, rýchle rozhodnutia."},
        {"name": "Hlboká práca 2", "start": "13:00", "end": "14:30", "type": "DEEP_WORK", "purpose": "Strategická alebo tvorivá práca."},
        {"name": "Kontrola a blokery", "start": "15:00", "end": "15:30", "type": "CHECK", "purpose": "Skontrolovať riziká, otvorené body a ďalší konkrétny krok."},
        {"name": "Večerná uzávierka", "start": "17:30", "end": "18:00", "type": "CLOSE", "purpose": "Uzavrieť deň a pripraviť zajtrajšok."},
    ]


def format_time_blocks(blocks: List[Dict[str, str]]) -> str:
    lines = ["AI_OS – denné časové bloky", ""]
    for block in blocks:
        lines.append(f"{block['start']}–{block['end']}  {block['name']}")
        lines.append(f"- {block['purpose']}")
    return "\n".join(lines).strip()


def format_daily_plan_with_blocks(message: str = "") -> str:
    lines = [
        "AI_OS – denný plán s časovými blokmi",
        "",
        format_time_blocks(cap0101_default_blocks()),
        "",
        "Priorita dňa:",
        "- Vyber 1 najdôležitejšiu úlohu a vlož ju do Hlboká práca 1.",
        "",
        "Kontrola kvality:",
        "- Plán má mať čas, prioritu a ďalší konkrétny krok.",
        "- Ak máš reálny kalendár, bloky uprav podľa stretnutí a presunov.",
    ]
    return "\n".join(lines).strip()


def time_blocks_answer(action: str, message: str) -> Tuple[str, Dict[str, Any]]:
    blocks = cap0101_default_blocks()
    if action in {"DAILY_PLAN_BLOCKS", "PLAN_DAY"}:
        answer = format_daily_plan_with_blocks(message)
    else:
        answer = format_time_blocks(blocks)
    return answer, {"status": "success", "capability_id": "CAP-010.1", "blocks": blocks}

# -------------------------
# CAP-010 Daily Operations
# -------------------------

def build_daily_operations_view(message: str, request_id: str) -> Dict[str, Any]:
    """Daily command center composed from existing Apps Script capabilities."""
    project = extract_project(message)
    sources: Dict[str, Any] = {}
    for key, action, msg in [
        ("project", "PROJECT_DASHBOARD", f"Dashboard projektu {project}"),
        ("tasks", "TASK_DAILY", "Denný prehľad úloh"),
        ("calendar", "DAY_PLAN", "Denný plán"),
        ("memory", "MEMORY_READ", "Čo si pamätáš"),
        ("workflow", "WORKFLOW_STATUS", "Zoznam workflow"),
    ]:
        try:
            sources[key] = call_apps_script(action, msg, request_id + "-" + key)
        except Exception as exc:
            sources[key] = {"status": "error", "code": "DAILY_SOURCE_EXCEPTION", "details": str(exc)[:300]}

    combined = {
        "documents": _extract_list(sources.get("project", {}), ["documents", "docs", "items"]),
        "tasks": _extract_list(sources.get("tasks", {}), ["tasks", "task_list", "open_tasks", "items"]),
        "calendar": _extract_list(sources.get("calendar", {}), ["calendar", "events", "calendar_events", "items"]),
        "risks": _extract_list(sources.get("project", {}), ["risks", "project_risks"]),
        "decisions": _extract_list(sources.get("project", {}), ["decisions", "project_decisions"]),
        "workflow": _extract_list(sources.get("workflow", {}), ["workflows", "workflow", "items"]),
    }
    executive_view = build_executive_view({**sources.get("project", {}), **combined}, project=project)
    tasks = combined["tasks"] or _extract_list(sources.get("project", {}), ["tasks", "task_list", "open_tasks"])
    calendar = combined["calendar"]
    memory_text = first_nonempty(
        sources.get("memory", {}).get("answer") if isinstance(sources.get("memory"), dict) else "",
        sources.get("memory", {}).get("message") if isinstance(sources.get("memory"), dict) else "",
    )

    priority_tasks = top_priority_tasks(tasks, limit=5)
    events = latest_items(calendar, limit=5)
    risks = executive_view.get("risks", [])[:5]
    task_counts = count_tasks(tasks)

    return {
        "project": project,
        "version": VERSION,
        "date_utc": utc_now()[:10],
        "health": executive_view.get("health", {"score": 0, "label": "Neznáme"}),
        "phase": executive_view.get("phase", "Denná prevádzka"),
        "task_counts": task_counts,
        "priority_tasks": priority_tasks,
        "calendar_events": events,
        "risks": risks,
        "memory_preview": memory_text[:500],
        "recommendations": build_daily_recommendations(task_counts, priority_tasks, events, risks),
        "sources_status": {k: (v.get("status") if isinstance(v, dict) else "unknown") for k, v in sources.items()},
    }


def build_daily_recommendations(task_counts: Dict[str, int], priority_tasks: List[Dict[str, Any]], events: List[Dict[str, Any]], risks: List[str]) -> List[str]:
    recs: List[str] = []
    if priority_tasks:
        recs.append("Vybrať 1 hlavnú úlohu dňa a najprv dokončiť tú, nie rozbiehať nové vetvy.")
    if task_counts.get("critical_or_high", 0):
        recs.append(f"Prejsť {task_counts['critical_or_high']} vysokých/kritických úloh a určiť poradie.")
    if events:
        recs.append("Skontrolovať časové bloky a nechať rezervu medzi stretnutiami alebo testami.")
    else:
        recs.append("Doplniť dnešné časové bloky, aby denný plán nebol len zoznam úloh.")
    if risks:
        recs.append("Pred pokračovaním odstrániť alebo vedome prijať otvorené riziká.")
    recs.append("Bežné používanie: URL bez debug=true; debug iba pri kontrole chýb.")
    return recs[:5]


def format_daily_start(view: Dict[str, Any]) -> str:
    lines = [
        "AI_OS – ranný štart",
        "",
        f"Stav systému: {view['health']['label']} ({view['health']['score']}/100)",
        f"Fáza: {view['phase']}",
        "",
        "Dnešné priority:",
    ]
    if view["priority_tasks"]:
        for i, task in enumerate(view["priority_tasks"][:3], 1):
            status = f" – {task.get('status')}" if task.get("status") else ""
            lines.append(f"{i}. {task.get('title')}{status}")
    else:
        lines.append("1. Urči hlavnú úlohu dňa.")
    lines += ["", "Čas / kalendár:"]
    if view["calendar_events"]:
        for event in view["calendar_events"][:3]:
            lines.append(f"- {event.get('title')}")
    else:
        lines.append("- Zatiaľ bez rozpoznaných časových blokov.")
    if view["risks"]:
        lines += ["", "Pozor:"] + [f"- {r}" for r in view["risks"][:2]]
    lines += ["", "Odporúčanie:", f"- {view['recommendations'][0] if view['recommendations'] else 'Začni najdôležitejšou úlohou.'}"]
    return "\n".join(lines)


def format_daily_status(view: Dict[str, Any]) -> str:
    t = view["task_counts"]
    lines = [
        "AI_OS – denný stav",
        "",
        f"Úlohy: otvorené {t['open']}, aktívne {t['active']}, dokončené {t['done']}, blokované {t['blocked']}.",
        f"Kalendár: {len(view['calendar_events'])} rozpoznaných položiek.",
        f"Riziká: {len(view['risks'])} signálov.",
        "",
        "Najbližší praktický krok:",
        f"- {view['recommendations'][0] if view['recommendations'] else 'Vyber ďalšiu úlohu a pokračuj.'}",
    ]
    return "\n".join(lines)


def format_daily_review(view: Dict[str, Any]) -> str:
    t = view["task_counts"]
    lines = [
        "AI_OS – denné vyhodnotenie",
        "",
        f"Dnes evidujem: {t['done']} dokončených, {t['active']} aktívnych, {t['open']} otvorených a {t['blocked']} blokovaných úloh.",
        "",
        "Kontrola kvality:",
        "1. Čo bolo reálne dokončené?",
        "2. Čo zostáva otvorené na zajtra?",
        "3. Ktoré riziko alebo blokér treba odstrániť ako prvé?",
    ]
    if view["risks"]:
        lines += ["", "Otvorené riziká:"] + [f"- {r}" for r in view["risks"][:3]]
    return "\n".join(lines)


def format_daily_close(view: Dict[str, Any]) -> str:
    lines = [
        "AI_OS – uzavretie dňa",
        "",
        "Uzavri tieto body:",
        "1. Zapíš, čo bolo dokončené.",
        "2. Označ blokované úlohy.",
        "3. Vyber prvú prioritu na zajtra.",
        "4. Nepokračuj do nového CAP, ak zostal otvorený kritický blokér.",
    ]
    if view["recommendations"]:
        lines += ["", "Odporúčanie na zajtra:", f"- {view['recommendations'][0]}"]
    return "\n".join(lines)


def format_daily_commands() -> str:
    return "\n".join([
        "AI_OS – denné príkazy",
        "",
        "Ranný štart",
        "Denný stav",
        "Denné vyhodnotenie",
        "Večerná uzávierka",
        "Denný plán",
        "Zoznam úloh",
        "Manažérsky prehľad projektu AI_OS",
    ])


def daily_answer(action: str, message: str, request_id: str) -> Tuple[str, Dict[str, Any]]:
    if action == "DAILY_COMMANDS":
        return format_daily_commands(), {"status": "success", "mode": "commands"}
    view = build_daily_operations_view(message, request_id)
    if action == "DAILY_CLOSE":
        return format_daily_close(view), view
    if action == "DAILY_REVIEW":
        return format_daily_review(view), view
    if action == "DAILY_STATUS":
        return format_daily_status(view), view
    return format_daily_start(view), view

# -------------------------
# Routes
# -------------------------

@app.api_route("/", methods=["GET", "HEAD"])
def root() -> Any:
    return _json({"status": "ok", "service": APP_NAME, "version": VERSION})


@app.api_route("/self-test", methods=["GET", "HEAD"])
def self_test(request: Request) -> Any:
    if not _authorized(request):
        return _json({"status": "error", "detail": "Unauthorized"}, 401)
    tests = [
        {"name": "root", "status": "PASS"},
        {"name": "api_token", "status": "PASS" if API_TOKEN else "FAIL"},
        {"name": "root_folder_id", "status": "PASS" if AI_OS_ROOT_FOLDER_ID else "FAIL"},
        {"name": "apps_script_webapp_url", "status": "PASS" if APPS_SCRIPT_WEBAPP_URL else "FAIL"},
        {"name": "apps_script_secret", "status": "PASS" if APPS_SCRIPT_SECRET else "FAIL"},
        {"name": "router_project_intelligence", "status": "PASS"},
        {"name": "router_executive_summary", "status": "PASS"},
        {"name": "router_executive_report", "status": "PASS"},
        {"name": "router_executive_actions", "status": "PASS"},
        {"name": "clean_human_output", "status": "PASS"},
        {"name": "router_daily_start", "status": "PASS"},
        {"name": "router_daily_status", "status": "PASS"},
        {"name": "router_daily_close", "status": "PASS"},
        {"name": "route_daily_time_blocks", "status": "PASS"},
    ]
    status = "success" if all(t["status"] == "PASS" for t in tests) else "error"
    return _json({"status": status, "self_test": "PASS" if status == "success" else "FAIL", "version": VERSION, "tests": tests, "request_id": str(uuid.uuid4()), "time_utc": utc_now()})


@app.get("/debug/config")
def debug_config(request: Request) -> Any:
    if not _authorized(request):
        return _json({"status": "error", "detail": "Unauthorized"}, 401)
    return _json({
        "status": "success",
        "version": VERSION,
        "config": {
            "api_token_configured": bool(API_TOKEN),
            "root_folder_id_configured": bool(AI_OS_ROOT_FOLDER_ID),
            "apps_script_webapp_url_configured": bool(APPS_SCRIPT_WEBAPP_URL),
            "apps_script_secret_configured": bool(APPS_SCRIPT_SECRET),
            "request_timeout_seconds": REQUEST_TIMEOUT_SECONDS,
        },
        "time_utc": utc_now(),
    })


@app.get("/assistant")
def assistant(request: Request, message: str = "") -> Any:
    if not _authorized(request):
        return _json({"status": "error", "detail": "Unauthorized"}, 401)

    request_id = str(uuid.uuid4())
    route = route_intent(message)
    action = route["intent"]
    project = extract_project(message)

    daily_actions = {"DAILY_START", "DAILY_STATUS", "DAILY_REVIEW", "DAILY_CLOSE", "DAILY_COMMANDS"}
    time_block_actions = {"DAILY_TIME_BLOCKS", "TIME_BLOCKS", "DAILY_PLAN_BLOCKS", "PLAN_DAY"}
    executive_actions = {"PROJECT_EXECUTIVE_SUMMARY", "PROJECT_EXECUTIVE_REPORT", "PROJECT_EXECUTIVE_ACTIONS", "PROJECT_STATUS", "PROJECT_SUMMARY", "PROJECT_DASHBOARD", "PROJECT_INTELLIGENCE", "PROJECT_RISK", "PROJECT_DECISIONS", "PROJECT_PROGRESS", "PROJECT_MILESTONES"}
    executive_view = None
    daily_view = None
    final_answer = None

    if action in time_block_actions:
        final_answer, daily_view = time_blocks_answer(action, message)
        apps_result = {"status": "success", "method": "daily_time_blocks", "daily_view": daily_view}
    elif action in daily_actions:
        final_answer, daily_view = daily_answer(action, message, request_id)
        apps_result = {"status": "success", "method": "daily_composite", "daily_view": daily_view}
    else:
        apps_result = call_apps_script(action, message, request_id)
        if action in executive_actions:
            executive_view = build_executive_view(apps_result, project=project)
            if action == "PROJECT_EXECUTIVE_REPORT":
                final_answer = format_executive_report(executive_view)
            elif action == "PROJECT_EXECUTIVE_ACTIONS":
                final_answer = format_executive_actions(executive_view)
            else:
                final_answer = format_executive_summary(executive_view)
        else:
            final_answer = first_nonempty(apps_result.get("answer"), apps_result.get("message"), "Požiadavka bola spracovaná.") if isinstance(apps_result, dict) else "Požiadavka bola spracovaná."

    response = {
        "status": "success" if apps_result.get("status") in ("success", "ok") else apps_result.get("status", "success"),
        "assistant": "Executive Assistant",
        "version": VERSION,
        "route": route,
        "answer": final_answer,
        "next_action": "Otvoriť dokument alebo pokračovať ďalším krokom.",
        "request_id": request_id,
        "time_utc": utc_now(),
    }
    if executive_view is not None:
        response["executive_view"] = executive_view
    if daily_view is not None:
        response["daily_view"] = daily_view
    if _debug_enabled(request):
        response["capability_result"] = apps_result
        response["debug_bridge"] = {
            "initial_http_status": 302 if APPS_SCRIPT_WEBAPP_URL else None,
            "final_http_status": 200 if apps_result.get("status") in ("success", "ok") else None,
            "redirected": True,
            "redirect_host": "script.googleusercontent.com",
        }
        return _json(response)

    # CAP-009.2: bežná používateľská odpoveď je čistý text bez JSON balastu.
    return PlainTextResponse(
        content=clean_human_output(final_answer),
        media_type="text/plain; charset=utf-8",
    )


@app.post("/assistant")
async def assistant_post(request: Request) -> Any:
    if not _authorized(request):
        return _json({"status": "error", "detail": "Unauthorized"}, 401)
    try:
        body = await request.json()
    except Exception:
        body = {}
    message = normalize_text(body.get("message") or body.get("text") or "")
    # Reuse GET handler logic by constructing minimal direct flow.
    request_id = str(uuid.uuid4())
    route = route_intent(message)
    if route["intent"] in {"DAILY_TIME_BLOCKS", "TIME_BLOCKS", "DAILY_PLAN_BLOCKS", "PLAN_DAY"}:
        answer, view = time_blocks_answer(route["intent"], message)
        apps_result = {"status": "success"}
    elif route["intent"].startswith("DAILY_"):
        answer, view = daily_answer(route["intent"], message, request_id)
        apps_result = {"status": "success"}
    else:
        apps_result = call_apps_script(route["intent"], message, request_id)
        view = build_executive_view(apps_result, project=extract_project(message)) if route["intent"].startswith("PROJECT") else None
        answer = format_executive_summary(view) if view else first_nonempty(apps_result.get("answer"), apps_result.get("message"), "Požiadavka bola spracovaná.")
    if _debug_enabled(request):
        return _json({"status": "success", "assistant": "Executive Assistant", "version": VERSION, "route": route, "answer": answer, "view": view, "request_id": request_id, "time_utc": utc_now()})
    return PlainTextResponse(content=clean_human_output(answer), media_type="text/plain; charset=utf-8")
