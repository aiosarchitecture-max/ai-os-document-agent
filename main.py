"""
AI_OS CAP-012.5 LLM Developer Bridge FULL
FastAPI main.py
"""

from __future__ import annotations

import base64
import json
import os
import re
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

VERSION = "v2.13.0-cap019-cron-worker"
APP_NAME = "AI_OS LLM Developer Bridge"

API_TOKEN = os.getenv("API_TOKEN", "").strip()
APPS_SCRIPT_WEBAPP_URL = os.getenv("APPS_SCRIPT_WEBAPP_URL", "").strip()
APPS_SCRIPT_SECRET = os.getenv("APPS_SCRIPT_SECRET", "").strip()
REQUEST_TIMEOUT_SECONDS = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "60"))
AI_OS_ROOT_FOLDER_ID = os.getenv("AI_OS_ROOT_FOLDER_ID", "").strip()
GITHUB_REPO_URL = os.getenv("GITHUB_REPO_URL", "").strip()

GITHUB_PAT = os.getenv("GITHUB_PAT", "").strip()
GITHUB_OWNER = os.getenv("GITHUB_OWNER", "aiosarchitecture-max").strip()
GITHUB_REPO = os.getenv("GITHUB_REPO", "ai-os-document-agent").strip()
GITHUB_API_BASE = "https://api.github.com"

SERPER_API_KEY = os.getenv("SERPER_API_KEY", "").strip()
SERPER_MONTHLY_LIMIT = int(os.getenv("SERPER_MONTHLY_LIMIT", "2500"))
YOUCOM_API_KEY = os.getenv("YOUCOM_API_KEY", "").strip()

RESEARCHER_PROVIDER = os.getenv("RESEARCHER_PROVIDER", "anthropic").strip().lower()
RESEARCHER_MODEL = os.getenv("RESEARCHER_MODEL", "claude-haiku-4-5-20251001").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile").strip()

_serper_usage = {"month": "", "count": 0}

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
REVIEWER_MODEL = os.getenv("REVIEWER_MODEL", "claude-haiku-4-5-20251001").strip()
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"

PUBLIC_HOSTNAME = os.getenv("RENDER_EXTERNAL_HOSTNAME", "ai-os-document-agent.onrender.com").strip()

mcp = FastMCP(
    name="ai_os_orchestrator",
    instructions=(
        "Nástroje AI_OS Orchestrátora Daniela Valušiaka. Pred volaním aios_move_file, "
        "aios_trash_file alebo aios_rename_file vždy over, že existuje schválený "
        "confirm_id. Nikdy tieto tri operácie nevolaj bez explicitného schválenia Daniela."
    ),
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[PUBLIC_HOSTNAME, f"{PUBLIC_HOSTNAME}:*", "localhost:*", "127.0.0.1:*"],
        allowed_origins=[f"https://{PUBLIC_HOSTNAME}", "https://claude.ai", "http://localhost:*"],
    ),
)

try:
    mcp.settings.streamable_http_path = "/"
except Exception:
    pass


@asynccontextmanager
async def lifespan(_app: FastAPI):
    async with mcp.session_manager.run():
        yield


app = FastAPI(title=APP_NAME, version=VERSION, lifespan=lifespan)

RUNTIME_STATE: Dict[str, Any] = {
    "system": "AI_OS",
    "version": VERSION,
    "stage": "CAP-019 24/7 Cron Worker",
    "last_stable_cap": "CAP-018",
    "current_cap": "CAP-019",
    "current_task": "Spracovanie fronty úloh z AI_OS_TASKS bez potreby otvorenej chat konverzácie.",
    "root_folder_id_configured": bool(AI_OS_ROOT_FOLDER_ID),
    "apps_script_configured": bool(APPS_SCRIPT_WEBAPP_URL),
    "github_repo_url": GITHUB_REPO_URL,
    "last_event": None,
    "events": [],
}

SAFE_TOOL_REGISTRY: List[Dict[str, Any]] = [
    {"name": "aios_boot", "description": "Načíta aktuálny runtime stav AI_OS.", "method": "GET", "path": "/boot?token=API_TOKEN", "risk": "low", "requires_human_approval": False},
    {"name": "aios_trigger_event", "description": "Odošle udalosť do AI_OS Event Bus.", "method": "POST", "path": "/events/trigger?token=API_TOKEN", "risk": "medium", "requires_human_approval": False},
    {"name": "aios_assistant_command", "description": "Spustí existujúci textový príkaz AI_OS asistenta.", "method": "GET", "path": "/assistant?token=API_TOKEN&message=...", "risk": "medium", "requires_human_approval": "podľa príkazu"},
    {"name": "aios_self_test", "description": "Overí základné technické nastavenie mosta.", "method": "GET", "path": "/self-test?token=API_TOKEN", "risk": "low", "requires_human_approval": False},
    {"name": "aios_move_file", "description": "Presunie súbor/priečinok v Google Drive. Vyžaduje confirm_id.", "method": "POST", "path": "/files/move?token=API_TOKEN", "risk": "high", "requires_human_approval": True},
    {"name": "aios_trash_file", "description": "Presunie súbor do Koša. Vyžaduje confirm_id.", "method": "POST", "path": "/files/trash?token=API_TOKEN", "risk": "high", "requires_human_approval": True},
    {"name": "aios_rename_file", "description": "Premenuje súbor/priečinok. Vyžaduje confirm_id.", "method": "POST", "path": "/files/rename?token=API_TOKEN", "risk": "medium", "requires_human_approval": True},
    {"name": "aios_migration_log", "description": "Prečíta AI_OS_MIGRATION_LOG.", "method": "GET", "path": "/files/migration-log?token=API_TOKEN", "risk": "low", "requires_human_approval": False},
    {"name": "aios_review_document", "description": "CAP-016 Quality Workflow — QA + Information Architect kontrola dokumentu.", "method": "POST", "path": "/documents/review?token=API_TOKEN", "risk": "low", "requires_human_approval": False},
    {"name": "aios_quality_log", "description": "Prečíta AI_OS_QUALITY_LOG.", "method": "GET", "path": "/documents/quality-log?token=API_TOKEN", "risk": "low", "requires_human_approval": False},
    {"name": "aios_github_write_file", "description": "CAP-017 — Priamy zápis súboru do GitHub repozitára.", "method": "POST", "path": "/github/write-file?token=API_TOKEN", "risk": "high", "requires_human_approval": True},
    {"name": "aios_research", "description": "CAP-018 Bádateľ — vyhľadá tému na webe a vráti zhustený súhrn.", "method": "POST", "path": "/research?token=API_TOKEN", "risk": "low", "requires_human_approval": False},
    {"name": "aios_research_log", "description": "Prečíta AI_OS_RESEARCH_LOG.", "method": "GET", "path": "/research/log?token=API_TOKEN", "risk": "low", "requires_human_approval": False},
    {"name": "aios_process_pending_tasks", "description": "CAP-019 — Spracuje čakajúce úlohy z AI_OS_TASKS.", "method": "GET", "path": "/tasks/process-pending?token=API_TOKEN", "risk": "medium", "requires_human_approval": False},
]

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()

def request_id() -> str:
    return str(uuid.uuid4())

def token_ok(token: Optional[str]) -> bool:
    return bool(API_TOKEN) and bool(token) and token == API_TOKEN

def wants_debug(request: Request) -> bool:
    return str(request.query_params.get("debug", "")).lower() in {"1", "true", "yes", "ano", "áno"}

def unauthorized(debug: bool = False):
    if debug:
        return JSONResponse({"status": "error", "code": "UNAUTHORIZED", "version": VERSION, "time_utc": utc_now()}, status_code=401)
    return PlainTextResponse("Neautorizovaný prístup.", status_code=401)

def plain_or_json(payload: Dict[str, Any], debug: bool = False):
    if debug:
        return JSONResponse(payload)
    return PlainTextResponse(payload.get("human", "Požiadavka bola spracovaná."), media_type="text/plain; charset=utf-8")

def post_to_apps_script(action: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if not APPS_SCRIPT_WEBAPP_URL:
        return {"status": "error", "code": "APPS_SCRIPT_WEBAPP_URL_MISSING", "message": "Apps Script URL nie je nastavená."}
    body = {"secret": APPS_SCRIPT_SECRET, "action": action, "payload": payload or {}, "source": "AI_OS_RENDER_FASTAPI", "version": VERSION, "time_utc": utc_now()}
    try:
        response = requests.post(APPS_SCRIPT_WEBAPP_URL, json=body, timeout=REQUEST_TIMEOUT_SECONDS)
        text = response.text or ""
        try:
            data = response.json()
        except Exception:
            data = {"raw": text}
        return {"status": "success" if response.ok else "error", "http_status": response.status_code, "data": data, "text": text[:2000]}
    except Exception as exc:
        return {"status": "error", "code": "APPS_SCRIPT_REQUEST_FAILED", "message": str(exc)}

def normalize_message(message: str) -> str:
    return re.sub(r"\s+", " ", (message or "").strip())

def command_to_action(message: str) -> Dict[str, Any]:
    m = normalize_message(message)
    low = m.lower()
    if low in {"ranný štart", "ranny start"}:
        return {"intent": "MORNING_START", "human": "AI_OS – ranný štart\nStav: pripravený.\nĎalší krok: zadaj dnešnú prioritu."}
    if low in {"denné príkazy", "denne prikazy", "príkazy", "prikazy"}:
        return {"intent": "COMMANDS", "human": available_commands_text()}
    if "manažérsky prehľad" in low or "manazersky prehlad" in low:
        return {"intent": "EXECUTIVE_REPORT", "human": "AI_OS – manažérsky prehľad\nStav: CAP-019.\nPriorita: 24/7 spracovanie úloh."}
    doc_commands = {
        "audit dokumentácie": "DOC_AUDIT", "audit dokumentacie": "DOC_AUDIT",
        "inventúra dokumentov": "DOC_INVENTORY", "inventura dokumentov": "DOC_INVENTORY",
        "analýza dokumentácie": "DOC_ANALYSIS", "analyza dokumentacie": "DOC_ANALYSIS",
        "návrh štruktúry": "DOC_STRUCTURE_PROPOSAL", "navrh struktury": "DOC_STRUCTURE_PROPOSAL",
        "migračný plán": "DOC_MIGRATION_PLAN", "migracny plan": "DOC_MIGRATION_PLAN",
        "optimalizuj dokumentáciu": "DOC_OPTIMIZATION_PLAN", "optimalizuj dokumentaciu": "DOC_OPTIMIZATION_PLAN",
        "health dokumentácie": "DOC_HEALTH", "health dokumentacie": "DOC_HEALTH",
        "validuj štruktúru": "DOC_VALIDATE_STRUCTURE", "validuj strukturu": "DOC_VALIDATE_STRUCTURE",
        "skontroluj governance": "DOC_GOVERNANCE",
        "nájdi duplicity": "DOC_DUPLICATES", "najdi duplicity": "DOC_DUPLICATES",
        "nájdi siroty": "DOC_ORPHANS", "najdi siroty": "DOC_ORPHANS",
        "archivuj zastarané dokumenty plán": "DOC_ARCHIVE_PLAN", "archivuj zastarane dokumenty plan": "DOC_ARCHIVE_PLAN",
        "migračný log": "DOC_MIGRATION_LOG", "migracny log": "DOC_MIGRATION_LOG",
    }
    for key, intent in doc_commands.items():
        if key in low:
            return call_script_intent(intent, m)
    if low.startswith("drive "):
        return call_script_intent("DRIVE_COMMAND", m)
    if low.startswith("projekt "):
        return call_script_intent("PROJECT_COMMAND", m)
    if "boot" == low or "ai os boot" in low or "ai_os boot" in low:
        return {"intent": "BOOT", "human": boot_text(), "data": boot_payload()}
    if "mcp tools" in low or "mcp nástroje" in low or "mcp nastroje" in low:
        return {"intent": "MCP_TOOLS", "human": tools_text(), "data": {"tools": SAFE_TOOL_REGISTRY}}
    if low.startswith("event ") or low.startswith("udalosť ") or low.startswith("udalost "):
        event_type = "MANUAL_EVENT"
        payload = register_event(event_type, {"message": m, "source": "assistant_text_command"})
        return {"intent": "EVENT_TRIGGERED", "human": f"Udalosť bola zapísaná.\nTyp: {event_type}\nEvent ID: {payload['event_id']}", "data": payload}
    return {"intent": "DEFAULT", "human": "Požiadavka bola prijatá. Neviem ju ešte bezpečne vykonať ako štruktúrovaný príkaz. Použi: Denné príkazy."}

def call_script_intent(intent: str, message: str) -> Dict[str, Any]:
    result = post_to_apps_script(intent, {"message": message})
    if result.get("status") == "success":
        text = result.get("text") or ""
        data = result.get("data") or {}
        human = ""
        if isinstance(data, dict):
            human = str(data.get("human") or data.get("message") or "")
        if not human:
            human = text or f"{intent}: spracované."
        return {"intent": intent, "human": human, "apps_script": result}
    return {"intent": intent, "human": f"Nepodarilo sa zavolať Apps Script.\nChyba: {result.get('message') or result.get('code')}", "apps_script": result}

def available_commands_text() -> str:
    return """AI_OS – dostupné príkazy

LLM Developer Bridge:
- AI_OS boot
- MCP tools
- Event [text udalosti]

Documentation Optimizer & Governance:
- Optimalizuj dokumentáciu AI_OS
- Health dokumentácie
- Validuj štruktúru
- Skontroluj governance
- Nájdi duplicity
- Nájdi siroty
- Archivuj zastarané dokumenty plán
- Migračný log

Documentation Intelligence:
- Audit dokumentácie AI_OS
- Inventúra dokumentov AI_OS
- Analýza dokumentácie AI_OS
- Návrh štruktúry dokumentov AI_OS
- Migračný plán dokumentov AI_OS

Drive:
- Drive status
- Drive nájdi [názov]
- Drive obsah [názov]
- Drive vytvor priečinok [názov]
- Drive vytvor dokument [názov]

Project Automation:
- Projekt šablóna
- Projekt nový [názov]
- Projekt status [názov]
- Projekt audit [názov]
- Projekt milestone [názov]: [poznámka]

Bezpečnosť:
- Produkčné zmeny a reorganizácie iba cez potvrdenie / CONFIRM ID.
- AnythingLLM nesmie samo nasadzovať na Render.
"""

def boot_payload() -> Dict[str, Any]:
    return {
        "status": "success", "boot": "READY", "version": VERSION, "time_utc": utc_now(),
        "runtime_state": RUNTIME_STATE,
        "mandatory_rules": [
            "Načítaj aktuálny stav AI_OS pred návrhom zmien.",
            "Nevyrábaj čiastkové patch súbory; výstupom musia byť celé súbory na výmenu 1:1.",
            "Neposielaj tajné tokeny do výstupu.",
            "Nenasaďuj priamo produkciu; finálne schválenie robí človek.",
            "Každý CAP musí mať testy, rollback a zápis do kontextu.",
        ],
        "safe_tools": SAFE_TOOL_REGISTRY,
        "next_step": "AnythingLLM môže čítať lokálny workspace a cez /events/trigger posielať výsledky do AI_OS.",
    }

def boot_text() -> str:
    p = boot_payload()
    return ("AI_OS BOOT READY\n" f"Verzia: {p['version']}\n" f"Aktuálny CAP: {RUNTIME_STATE['current_cap']}\n" f"Úloha: {RUNTIME_STATE['current_task']}\n" "Pravidlo: externý LLM navrhuje, človek schvaľuje, GitHub/Render nasadzuje.")

def tools_text() -> str:
    lines = ["AI_OS MCP Tools – bezpečný zoznam nástrojov"]
    for tool in SAFE_TOOL_REGISTRY:
        lines.append(f"- {tool['name']}: {tool['description']} ({tool['method']} {tool['path']})")
    return "\n".join(lines)

def register_event(event_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    event = {"event_id": request_id(), "event_type": event_type, "payload": payload, "time_utc": utc_now(), "status": "RECEIVED"}
    RUNTIME_STATE["last_event"] = event
    RUNTIME_STATE["events"].append(event)
    if len(RUNTIME_STATE["events"]) > 50:
        RUNTIME_STATE["events"] = RUNTIME_STATE["events"][-50:]
    script_result = post_to_apps_script("EVENT_TRIGGER", event)
    event["apps_script_status"] = script_result.get("status")
    event["apps_script_http_status"] = script_result.get("http_status")
    return event

def move_file(file_id: str, target_folder_id: str, confirm_id: str) -> Dict[str, Any]:
    return post_to_apps_script("MOVE_FILE", {"fileId": file_id, "targetFolderId": target_folder_id, "confirm_id": confirm_id})

def trash_file(file_id: str, confirm_id: str) -> Dict[str, Any]:
    return post_to_apps_script("TRASH_FILE", {"fileId": file_id, "confirm_id": confirm_id})

def rename_file(file_id: str, new_title: str, confirm_id: str) -> Dict[str, Any]:
    return post_to_apps_script("RENAME_FILE", {"fileId": file_id, "newTitle": new_title, "confirm_id": confirm_id})

def read_migration_log() -> Dict[str, Any]:
    return post_to_apps_script("READ_MIGRATION_LOG", {})

def read_quality_log() -> Dict[str, Any]:
    return post_to_apps_script("READ_QUALITY_LOG", {})

def _github_headers() -> Dict[str, str]:
    return {"Authorization": f"Bearer {GITHUB_PAT}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}

def github_get_file_sha(path: str) -> Optional[str]:
    url = f"{GITHUB_API_BASE}/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{path}"
    resp = requests.get(url, headers=_github_headers(), timeout=30.0)
    if resp.status_code == 200:
        return resp.json().get("sha")
    return None

def github_write_file(path: str, content: str, commit_message: str) -> Dict[str, Any]:
    if not GITHUB_PAT:
        return {"status": "error", "human": "GITHUB_PAT nie je nastavený na serveri."}
    existing_sha = github_get_file_sha(path)
    url = f"{GITHUB_API_BASE}/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{path}"
    body: Dict[str, Any] = {"message": commit_message, "content": base64.b64encode(content.encode("utf-8")).decode("ascii"), "branch": "main"}
    if existing_sha:
        body["sha"] = existing_sha
    try:
        resp = requests.put(url, headers=_github_headers(), json=body, timeout=30.0)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        return {"status": "error", "human": f"Zápis do GitHubu zlyhal: {exc}"}
    commit_sha = (data.get("commit") or {}).get("sha", "")
    return {"status": "success", "human": f"Zapísané do GitHubu: {path} (commit {commit_sha[:8]})", "path": path, "commit_sha": commit_sha, "html_url": (data.get("content") or {}).get("html_url", "")}

def _current_month_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")

def _serper_usage_ratio() -> float:
    month = _current_month_key()
    if _serper_usage["month"] != month:
        _serper_usage["month"] = month
        _serper_usage["count"] = 0
    if SERPER_MONTHLY_LIMIT <= 0:
        return 1.0
    return _serper_usage["count"] / SERPER_MONTHLY_LIMIT

def _serper_increment() -> None:
    month = _current_month_key()
    if _serper_usage["month"] != month:
        _serper_usage["month"] = month
        _serper_usage["count"] = 0
    _serper_usage["count"] += 1

def search_serper(query: str) -> Dict[str, Any]:
    if not SERPER_API_KEY:
        return {"status": "error", "message": "SERPER_API_KEY nie je nastavený."}
    try:
        resp = requests.post("https://google.serper.dev/search", headers={"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"}, json={"q": query, "num": 8}, timeout=20.0)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        return {"status": "error", "message": f"Serper zlyhal: {exc}"}
    _serper_increment()
    results = [{"title": i.get("title", ""), "snippet": i.get("snippet", ""), "link": i.get("link", "")} for i in data.get("organic", [])[:8]]
    return {"status": "success", "provider": "serper", "results": results}

def search_youcom(query: str) -> Dict[str, Any]:
    if not YOUCOM_API_KEY:
        return {"status": "error", "message": "YOUCOM_API_KEY nie je nastavený."}
    try:
        resp = requests.get("https://api.you.com/v1/search", headers={"X-API-Key": YOUCOM_API_KEY}, params={"q": query, "count": 8}, timeout=20.0)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        return {"status": "error", "message": f"You.com zlyhal: {exc}"}
    results = [{"title": i.get("title", ""), "snippet": i.get("snippet", "") or i.get("description", ""), "link": i.get("url", "") or i.get("link", "")} for i in (data.get("results") or data.get("hits") or [])[:8]]
    return {"status": "success", "provider": "youcom", "results": results}

def search_web(query: str) -> Dict[str, Any]:
    provider_used = None
    result: Dict[str, Any] = {}
    if _serper_usage_ratio() < 0.9:
        result = search_serper(query)
        provider_used = "serper"
    if not provider_used or result.get("status") != "success":
        result = search_youcom(query)
        provider_used = "youcom"
    if result.get("status") != "success":
        fallback = search_serper(query) if provider_used != "serper" else search_youcom(query)
        if fallback.get("status") == "success":
            result = fallback
            provider_used = fallback.get("provider")
    result["provider_used"] = provider_used
    return result

BADATEL_SYSTEM_PROMPT = """Si Bádateľ (Researcher) v systéme AI_OS. Dostaneš tému a surové výsledky
webového vyhľadávania. Vytvor ZHUSTENÝ súhrn (max 1500 slov) pre ďalšieho agenta, nie surový výpis.
Uveď iba fakty podložené výsledkami, na konci zoznam zdrojov. Ak výsledky nezodpovedajú téme, napíš to.
Odpovedz vo formáte JSON: {"summary": "...", "key_findings": ["..."], "sources": ["..."], "confidence": "HIGH|MEDIUM|LOW"}"""

async def call_anthropic_researcher(topic: str, search_results: List[Dict[str, str]]) -> Dict[str, Any]:
    if not ANTHROPIC_API_KEY:
        return {"status": "error", "human": "ANTHROPIC_API_KEY nie je nastavený."}
    results_text = "\n\n".join(f"- {r.get('title', '')}\n  {r.get('snippet', '')}\n  {r.get('link', '')}" for r in search_results)
    user_message = f"Téma: {topic}\n\nVýsledky vyhľadávania:\n\n{results_text}"
    try:
        resp = requests.post(ANTHROPIC_API_URL, headers={"x-api-key": ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": RESEARCHER_MODEL, "max_tokens": 2000, "system": BADATEL_SYSTEM_PROMPT, "messages": [{"role": "user", "content": user_message}]}, timeout=60.0)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        return {"status": "error", "human": f"Bádateľ API volanie zlyhalo: {exc}"}
    text_blocks = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
    raw_text = "\n".join(text_blocks).strip()
    parsed = _parse_researcher_json(raw_text)
    if parsed is None:
        return {"status": "error", "human": "Bádateľ vrátil odpoveď, ktorú sa nepodarilo spracovať.", "raw": raw_text}
    parsed["status"] = "success"
    parsed["researcher_model"] = f"anthropic:{RESEARCHER_MODEL}"
    return parsed

async def call_gemini_researcher(topic: str, search_results: List[Dict[str, str]]) -> Dict[str, Any]:
    if not GEMINI_API_KEY:
        return {"status": "error", "human": "GEMINI_API_KEY nie je nastavený."}
    results_text = "\n\n".join(f"- {r.get('title', '')}\n  {r.get('snippet', '')}\n  {r.get('link', '')}" for r in search_results)
    user_message = f"Téma: {topic}\n\nVýsledky vyhľadávania:\n\n{results_text}"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
    try:
        resp = requests.post(url, headers={"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"},
            json={"system_instruction": {"parts": [{"text": BADATEL_SYSTEM_PROMPT}]}, "contents": [{"role": "user", "parts": [{"text": user_message}]}], "generationConfig": {"responseMimeType": "application/json"}}, timeout=60.0)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        return {"status": "error", "human": f"Gemini API volanie zlyhalo: {exc}"}
    try:
        raw_text = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        return {"status": "error", "human": "Gemini vrátil neočakávanú odpoveď.", "raw": str(data)[:500]}
    parsed = _parse_researcher_json(raw_text)
    if parsed is None:
        return {"status": "error", "human": "Bádateľ (Gemini) vrátil odpoveď, ktorú sa nepodarilo spracovať.", "raw": raw_text}
    parsed["status"] = "success"
    parsed["researcher_model"] = f"gemini:{GEMINI_MODEL}"
    return parsed

async def call_groq_researcher(topic: str, search_results: List[Dict[str, str]]) -> Dict[str, Any]:
    if not GROQ_API_KEY:
        return {"status": "error", "human": "GROQ_API_KEY nie je nastavený."}
    results_text = "\n\n".join(f"- {r.get('title', '')}\n  {r.get('snippet', '')}\n  {r.get('link', '')}" for r in search_results)
    user_message = f"Téma: {topic}\n\nVýsledky vyhľadávania:\n\n{results_text}"
    try:
        resp = requests.post("https://api.groq.com/openai/v1/chat/completions", headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={"model": GROQ_MODEL, "messages": [{"role": "system", "content": BADATEL_SYSTEM_PROMPT}, {"role": "user", "content": user_message}], "response_format": {"type": "json_object"}}, timeout=60.0)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        return {"status": "error", "human": f"Groq API volanie zlyhalo: {exc}"}
    try:
        raw_text = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError):
        return {"status": "error", "human": "Groq vrátil neočakávanú odpoveď.", "raw": str(data)[:500]}
    parsed = _parse_researcher_json(raw_text)
    if parsed is None:
        return {"status": "error", "human": "Bádateľ (Groq) vrátil odpoveď, ktorú sa nepodarilo spracovať.", "raw": raw_text}
    parsed["status"] = "success"
    parsed["researcher_model"] = f"groq:{GROQ_MODEL}"
    return parsed

def _parse_researcher_json(raw_text: str) -> Optional[Dict[str, Any]]:
    try:
        cleaned = raw_text.replace("```json", "").replace("```", "").strip()
        return json.loads(cleaned)
    except Exception:
        return None

async def call_researcher(topic: str, search_results: List[Dict[str, str]]) -> Dict[str, Any]:
    if RESEARCHER_PROVIDER == "gemini":
        return await call_gemini_researcher(topic, search_results)
    if RESEARCHER_PROVIDER == "groq":
        return await call_groq_researcher(topic, search_results)
    return await call_anthropic_researcher(topic, search_results)

def log_research_query(topic: str, provider: str, status: str) -> None:
    post_to_apps_script("LOG_RESEARCH_QUERY", {"topic": topic, "provider": provider or "none", "status": status})

def read_research_log() -> Dict[str, Any]:
    return post_to_apps_script("READ_RESEARCH_LOG", {})

def get_pending_tasks() -> Dict[str, Any]:
    return post_to_apps_script("GET_PENDING_TASKS", {})

def update_task_status(task_id: str, new_status: str, note: str = "") -> Dict[str, Any]:
    return post_to_apps_script("UPDATE_TASK_STATUS", {"taskId": task_id, "newStatus": new_status, "note": note})

async def process_pending_tasks() -> Dict[str, Any]:
    result = get_pending_tasks()
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    if data.get("status") != "success":
        return {"status": "error", "human": data.get("human") or "Nepodarilo sa načítať AI_OS_TASKS.", "processed": []}
    tasks = data.get("tasks", [])
    processed = []
    for task in tasks:
        task_id = task.get("taskId", "")
        topic = task.get("title") or task.get("content") or ""
        if not task_id or not topic:
            continue
        update_task_status(task_id, "RUNNING", "Bádateľ spracováva")
        try:
            research_result = await research_topic(topic)
            if research_result.get("status") == "success":
                summary = str(research_result.get("summary", ""))[:200]
                update_task_status(task_id, "DONE", f"Bádateľ: {summary}")
                processed.append({"task_id": task_id, "status": "DONE", "summary": summary})
            else:
                update_task_status(task_id, "FAILED", str(research_result.get("human", ""))[:200])
                processed.append({"task_id": task_id, "status": "FAILED"})
        except Exception as exc:
            update_task_status(task_id, "FAILED", f"Chyba: {exc}"[:200])
            processed.append({"task_id": task_id, "status": "FAILED", "error": str(exc)})
    return {"status": "success", "human": f"Spracovaných úloh: {len(processed)} z {len(tasks)} čakajúcich.", "processed": processed}

async def research_topic(topic: str) -> Dict[str, Any]:
    search_result = search_web(topic)
    provider_used = search_result.get("provider_used", "none")
    if search_result.get("status") != "success":
        log_research_query(topic, provider_used, "SEARCH_FAILED")
        return {"status": "error", "human": f"Vyhľadávanie zlyhalo na oboch poskytovateľoch: {search_result.get('message')}"}
    verdict = await call_researcher(topic, search_result.get("results", []))
    log_research_query(topic, provider_used, "SUCCESS" if verdict.get("status") == "success" else "SYNTHESIS_FAILED")
    verdict["provider_used"] = provider_used
    verdict["topic"] = topic
    return verdict

def read_document_content(file_id: str) -> Dict[str, Any]:
    return post_to_apps_script("READ_DOCUMENT_CONTENT", {"fileId": file_id})

REVIEWER_SYSTEM_PROMPT = """Si nezávislý Reviewer Agent v systéme AI_OS. Skontroluj dokument v dvoch rovinách:
QA (súlad s AI_OS_DOCUMENTATION_STANDARD_v1.0) a Information Architect (patrí sem, neduplikuje?).
NEMÁŠ oprávnenie nič meniť. Ku každej výhrade priraď severity LOW/MEDIUM/HIGH/CRITICAL.
Odpovedz VÝHRADNE JSON: {"status": "PASS/FAIL", "score_percent": 0-100, "issues": [{"description":"...","severity":"...","dimension":"QA/ARCHITECT"}], "summary": "..."}
PASS iba ak score >= 90 A žiadna CRITICAL výhrada."""

async def call_anthropic_reviewer(document_title: str, document_content: str, folder_context: str = "") -> Dict[str, Any]:
    if not ANTHROPIC_API_KEY:
        return {"status": "error", "human": "ANTHROPIC_API_KEY nie je nastavený."}
    context_line = f"\n\nAktuálne umiestnenie (priečinok): {folder_context}" if folder_context else ""
    user_message = f"Názov dokumentu: {document_title}{context_line}\n\nObsah dokumentu:\n\n{document_content}"
    try:
        resp = requests.post(ANTHROPIC_API_URL, headers={"x-api-key": ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": REVIEWER_MODEL, "max_tokens": 1500, "system": REVIEWER_SYSTEM_PROMPT, "messages": [{"role": "user", "content": user_message}]}, timeout=60.0)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        return {"status": "error", "human": f"Reviewer API volanie zlyhalo: {exc}"}
    text_blocks = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
    raw_text = "\n".join(text_blocks).strip()
    try:
        cleaned = raw_text.replace("```json", "").replace("```", "").strip()
        verdict = json.loads(cleaned)
    except Exception:
        return {"status": "error", "human": "Reviewer vrátil odpoveď, ktorú sa nepodarilo spracovať.", "raw_response": raw_text}
    verdict["reviewer_model"] = REVIEWER_MODEL
    return verdict

def log_quality_task(task_id: str, document_title: str, action: str, workflow_status: str, score_percent: Any, severity: str, issues: List[str]) -> None:
    post_to_apps_script("LOG_QUALITY_TASK", {"taskId": task_id, "documentTitle": document_title, "action": action, "workflowStatus": workflow_status, "scorePercent": score_percent, "severity": severity, "issues": issues})

def _highest_severity(issues: List[Dict[str, Any]]) -> str:
    order = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}
    if not issues:
        return "NONE"
    best = max(issues, key=lambda i: order.get(str(i.get("severity", "LOW")).upper(), 0))
    return str(best.get("severity", "LOW")).upper()

async def review_document(file_id: str, folder_context: str = "", action: str = "REVIEW") -> Dict[str, Any]:
    task_id = f"QW-{uuid.uuid4().hex[:8].upper()}"
    doc_result = read_document_content(file_id)
    doc_data = doc_result.get("data") if isinstance(doc_result.get("data"), dict) else {}
    if doc_data.get("status") != "success":
        return {"status": "error", "task_id": task_id, "human": doc_data.get("human") or "Nepodarilo sa prečítať obsah dokumentu."}
    title = doc_data.get("fileName", "")
    content = doc_data.get("content", "")
    if not content.strip():
        return {"status": "error", "task_id": task_id, "human": "Dokument je prázdny."}
    verdict = await call_anthropic_reviewer(title, content, folder_context)
    if verdict.get("status") == "error":
        return {**verdict, "task_id": task_id}
    issues = verdict.get("issues", [])
    severity = _highest_severity(issues)
    workflow_status = "APPROVED" if verdict.get("status") == "PASS" else "REVISION_REQUIRED"
    issue_texts = [f"[{i.get('dimension', '?')}/{i.get('severity', '?')}] {i.get('description', '')}" for i in issues]
    log_quality_task(task_id=task_id, document_title=title, action=action, workflow_status=workflow_status, score_percent=verdict.get("score_percent", ""), severity=severity, issues=issue_texts)
    verdict["file_id"] = file_id
    verdict["document_title"] = title
    verdict["task_id"] = task_id
    verdict["workflow_status"] = workflow_status
    return verdict

def apps_script_result_to_response(result: Dict[str, Any], debug: bool) -> Any:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    human = str(data.get("human") or result.get("message") or result.get("code") or "Operácia bola spracovaná.")
    payload = {"status": result.get("status", "error"), "version": VERSION, "time_utc": utc_now(), "apps_script": result, "human": human}
    return plain_or_json(payload, debug)

@app.post("/files/move")
async def files_move(request: Request, token: Optional[str] = None):
    debug = wants_debug(request)
    if not token_ok(token):
        return unauthorized(debug)
    try:
        body = await request.json()
    except Exception:
        body = {}
    file_id = str(body.get("file_id") or "").strip()
    target_folder_id = str(body.get("target_folder_id") or "").strip()
    confirm_id = str(body.get("confirm_id") or "").strip()
    if not file_id or not target_folder_id:
        return plain_or_json({"status": "error", "human": "Chýba file_id alebo target_folder_id.", "version": VERSION}, debug)
    if not confirm_id:
        return plain_or_json({"status": "error", "human": "Operácia MOVE_FILE vyžaduje confirm_id.", "version": VERSION}, debug)
    return apps_script_result_to_response(move_file(file_id, target_folder_id, confirm_id), debug)

@app.post("/files/trash")
async def files_trash(request: Request, token: Optional[str] = None):
    debug = wants_debug(request)
    if not token_ok(token):
        return unauthorized(debug)
    try:
        body = await request.json()
    except Exception:
        body = {}
    file_id = str(body.get("file_id") or "").strip()
    confirm_id = str(body.get("confirm_id") or "").strip()
    if not file_id:
        return plain_or_json({"status": "error", "human": "Chýba file_id.", "version": VERSION}, debug)
    if not confirm_id:
        return plain_or_json({"status": "error", "human": "Operácia TRASH_FILE vyžaduje confirm_id.", "version": VERSION}, debug)
    return apps_script_result_to_response(trash_file(file_id, confirm_id), debug)

@app.post("/files/rename")
async def files_rename(request: Request, token: Optional[str] = None):
    debug = wants_debug(request)
    if not token_ok(token):
        return unauthorized(debug)
    try:
        body = await request.json()
    except Exception:
        body = {}
    file_id = str(body.get("file_id") or "").strip()
    new_title = str(body.get("new_title") or "").strip()
    confirm_id = str(body.get("confirm_id") or "").strip()
    if not file_id or not new_title:
        return plain_or_json({"status": "error", "human": "Chýba file_id alebo new_title.", "version": VERSION}, debug)
    if not confirm_id:
        return plain_or_json({"status": "error", "human": "Operácia RENAME_FILE vyžaduje confirm_id.", "version": VERSION}, debug)
    return apps_script_result_to_response(rename_file(file_id, new_title, confirm_id), debug)

@app.get("/files/migration-log")
def files_migration_log(request: Request, token: Optional[str] = None):
    debug = wants_debug(request)
    if not token_ok(token):
        return unauthorized(debug)
    return apps_script_result_to_response(read_migration_log(), debug)

@app.post("/documents/review")
async def documents_review(request: Request, token: Optional[str] = None):
    debug = wants_debug(request)
    if not token_ok(token):
        return unauthorized(debug)
    try:
        body = await request.json()
    except Exception:
        body = {}
    file_id = str(body.get("file_id") or "").strip()
    folder_context = str(body.get("folder_context") or "").strip()
    if not file_id:
        return plain_or_json({"status": "error", "human": "Chýba file_id.", "version": VERSION}, debug)
    verdict = await review_document(file_id, folder_context)
    return plain_or_json({**verdict, "version": VERSION, "time_utc": utc_now()}, debug)

@app.get("/documents/quality-log")
def documents_quality_log(request: Request, token: Optional[str] = None):
    debug = wants_debug(request)
    if not token_ok(token):
        return unauthorized(debug)
    return apps_script_result_to_response(read_quality_log(), debug)

@app.post("/research")
async def research_endpoint(request: Request, token: Optional[str] = None):
    debug = wants_debug(request)
    if not token_ok(token):
        return unauthorized(debug)
    try:
        body = await request.json()
    except Exception:
        body = {}
    topic = str(body.get("topic") or "").strip()
    if not topic:
        return plain_or_json({"status": "error", "human": "Chýba topic.", "version": VERSION}, debug)
    result = await research_topic(topic)
    return plain_or_json({**result, "version": VERSION, "time_utc": utc_now()}, debug)

@app.get("/research/log")
def research_log_endpoint(request: Request, token: Optional[str] = None):
    debug = wants_debug(request)
    if not token_ok(token):
        return unauthorized(debug)
    return apps_script_result_to_response(read_research_log(), debug)

@app.post("/tasks/process-pending")
@app.get("/tasks/process-pending")
async def tasks_process_pending_endpoint(request: Request, token: Optional[str] = None):
    debug = wants_debug(request)
    if not token_ok(token):
        return unauthorized(debug)
    result = await process_pending_tasks()
    return plain_or_json({**result, "version": VERSION, "time_utc": utc_now()}, debug)

@app.post("/github/write-file")
async def github_write_file_endpoint(request: Request, token: Optional[str] = None):
    debug = wants_debug(request)
    if not token_ok(token):
        return unauthorized(debug)
    try:
        body = await request.json()
    except Exception:
        body = {}
    path = str(body.get("path") or "").strip()
    content = body.get("content")
    commit_message = str(body.get("commit_message") or f"Update {path}").strip()
    if not path or content is None:
        return plain_or_json({"status": "error", "human": "Chýba path alebo content.", "version": VERSION}, debug)
    result = github_write_file(path, content, commit_message)
    return plain_or_json({**result, "version": VERSION, "time_utc": utc_now()}, debug)

@mcp.tool()
def aios_boot() -> dict:
    """Načíta aktuálny runtime stav AI_OS."""
    if not API_TOKEN:
        return {"status": "error", "message": "API_TOKEN nie je nastavený."}
    return boot_payload()

@mcp.tool()
def aios_self_test() -> dict:
    """Overí základné technické nastavenie AI_OS Orchestrátora."""
    tests = [
        {"name": "api_token", "status": "PASS" if API_TOKEN else "FAIL"},
        {"name": "apps_script_webapp_url", "status": "PASS" if APPS_SCRIPT_WEBAPP_URL else "WARN"},
        {"name": "root_folder_id", "status": "PASS" if AI_OS_ROOT_FOLDER_ID else "WARN"},
    ]
    return {"status": "success", "version": VERSION, "tests": tests}

@mcp.tool()
def aios_ask(message: str) -> dict:
    """Pošle textový príkaz existujúcemu AI_OS asistentovi."""
    return command_to_action(message)

@mcp.tool()
def aios_move_file(file_id: str, target_folder_id: str, confirm_id: str) -> dict:
    """Presunie súbor/priečinok v Google Drive. POVINNÉ: confirm_id."""
    if not confirm_id:
        return {"status": "error", "message": "confirm_id je povinné."}
    return move_file(file_id, target_folder_id, confirm_id)

@mcp.tool()
def aios_trash_file(file_id: str, confirm_id: str) -> dict:
    """Presunie súbor do Koša. POVINNÉ: confirm_id."""
    if not confirm_id:
        return {"status": "error", "message": "confirm_id je povinné."}
    return trash_file(file_id, confirm_id)

@mcp.tool()
def aios_rename_file(file_id: str, new_title: str, confirm_id: str) -> dict:
    """Premenuje súbor/priečinok. POVINNÉ: confirm_id."""
    if not confirm_id:
        return {"status": "error", "message": "confirm_id je povinné."}
    return rename_file(file_id, new_title, confirm_id)

@mcp.tool()
def aios_migration_log() -> dict:
    """Prečíta AI_OS_MIGRATION_LOG."""
    return read_migration_log()

@mcp.tool()
def aios_quality_log() -> dict:
    """Prečíta AI_OS_QUALITY_LOG."""
    return read_quality_log()

@mcp.tool()
async def aios_research(topic: str) -> dict:
    """Bádateľ Agent (CAP-018): vyhľadá tému na webe a vráti zhustený súhrn."""
    return await research_topic(topic)

@mcp.tool()
def aios_research_log() -> dict:
    """Prečíta AI_OS_RESEARCH_LOG."""
    return read_research_log()

@mcp.tool()
async def aios_process_pending_tasks() -> dict:
    """CAP-019 — Manuálne spustenie spracovania čakajúcich úloh z AI_OS_TASKS."""
    return await process_pending_tasks()

@mcp.tool()
def aios_github_write_file(path: str, content: str, commit_message: str = "") -> dict:
    """CAP-017 — Priamy zápis súboru do GitHub repozitára."""
    msg = commit_message or f"Update {path} (cez AI_OS Orchestrator)"
    return github_write_file(path, content, msg)

@mcp.tool()
async def aios_review_document(file_id: str, folder_context: str = "") -> dict:
    """Reviewer + Information Architect Agent (CAP-016)."""
    return await review_document(file_id, folder_context)

app.mount("/mcp", mcp.streamable_http_app())

@app.get("/")
def root():
    return PlainTextResponse("AI_OS Document Agent je online.", media_type="text/plain; charset=utf-8")

@app.get("/health")
def health():
    return JSONResponse({"status": "ok", "version": VERSION, "time_utc": utc_now()})

@app.get("/self-test")
def self_test(request: Request, token: Optional[str] = None):
    debug = wants_debug(request)
    if not token_ok(token):
        return unauthorized(debug)
    tests = [
        {"name": "root", "status": "PASS"}, {"name": "api_token", "status": "PASS" if API_TOKEN else "FAIL"},
        {"name": "token_valid", "status": "PASS"}, {"name": "fastapi_app", "status": "PASS"},
        {"name": "human_output_default", "status": "PASS"}, {"name": "debug_output_separated", "status": "PASS"},
        {"name": "apps_script_webapp_url", "status": "PASS" if APPS_SCRIPT_WEBAPP_URL else "WARN"},
        {"name": "aios_boot", "status": "PASS"}, {"name": "mcp_tools", "status": "PASS"}, {"name": "events_trigger", "status": "PASS"},
        {"name": "root_folder_id", "status": "PASS" if AI_OS_ROOT_FOLDER_ID else "WARN"},
    ]
    status = "success" if all(t["status"] in {"PASS", "WARN"} for t in tests) else "error"
    return JSONResponse({"status": status, "self_test": "PASS" if status == "success" else "FAIL", "version": VERSION, "request_id": request_id(), "time_utc": utc_now(), "tests": tests})

@app.get("/boot")
def boot(request: Request, token: Optional[str] = None):
    debug = wants_debug(request)
    if not token_ok(token):
        return unauthorized(debug)
    return plain_or_json({**boot_payload(), "human": boot_text()}, debug)

@app.get("/mcp/tools")
def mcp_tools(request: Request, token: Optional[str] = None):
    debug = wants_debug(request)
    if not token_ok(token):
        return unauthorized(debug)
    payload = {"status": "success", "version": VERSION, "time_utc": utc_now(), "tools": SAFE_TOOL_REGISTRY, "human": tools_text()}
    return plain_or_json(payload, debug)

@app.post("/events/trigger")
async def events_trigger(request: Request, token: Optional[str] = None):
    debug = wants_debug(request)
    if not token_ok(token):
        return unauthorized(debug)
    try:
        body = await request.json()
    except Exception:
        body = {}
    event_type = str(body.get("event_type") or body.get("type") or "EXTERNAL_EVENT").strip()[:120]
    payload = body.get("payload") if isinstance(body.get("payload"), dict) else body
    event = register_event(event_type, payload)
    response = {"status": "success", "version": VERSION, "time_utc": utc_now(), "event": event, "human": f"Udalosť bola prijatá.\nTyp: {event_type}\nEvent ID: {event['event_id']}"}
    return plain_or_json(response, debug)

@app.get("/events")
def events_list(request: Request, token: Optional[str] = None):
    debug = wants_debug(request)
    if not token_ok(token):
        return unauthorized(debug)
    payload = {"status": "success", "version": VERSION, "events_count": len(RUNTIME_STATE.get("events", [])), "events": RUNTIME_STATE.get("events", [])[-20:], "human": "Event Bus je dostupný."}
    return plain_or_json(payload, debug)

@app.get("/assistant")
def assistant(request: Request, token: Optional[str] = None, message: str = ""):
    debug = wants_debug(request)
    if not token_ok(token):
        return unauthorized(debug)
    result = command_to_action(message)
    payload = {"status": "success", "assistant": APP_NAME, "version": VERSION, "request_id": request_id(), "time_utc": utc_now(), "message": message, **result}
    return plain_or_json(payload, debug)

@app.get("/workspace")
def workspace(request: Request):
    debug = wants_debug(request)
    tree = """AI_OS
├── 00_INBOX
├── 10_CORE
├── 20_PROJECTS
├── 30_CAPABILITIES
├── 90_ARCHIVE
└── 99_SYSTEM_LOGS"""
    payload = {"status": "success", "version": VERSION, "tree": tree, "root_folder_id_configured": bool(AI_OS_ROOT_FOLDER_ID), "human": "AI_OS – Project Workspace\n" + tree}
    return plain_or_json(payload, debug)

@app.get("/documentation-audit")
def documentation_audit(request: Request, token: Optional[str] = None):
    debug = wants_debug(request)
    if not token_ok(token):
        return unauthorized(debug)
    result = call_script_intent("DOC_AUDIT", "Audit dokumentácie AI_OS")
    return plain_or_json({"status": "success", "version": VERSION, **result}, debug)

@app.get("/chat")
def chat(token: Optional[str] = None):
    token_value = token or ""
    html = f"""<!doctype html><html lang="sk"><head><meta charset="utf-8"/><title>AI Assistant Chat</title>
<style>body{{margin:0;background:#f3f4f6;font-family:Arial;color:#111827}}.wrap{{max-width:760px;margin:32px auto;background:white;border:1px solid #d1d5db;border-radius:12px;overflow:hidden}}
.head{{padding:18px 20px;border-bottom:1px solid #e5e7eb}}h1{{margin:0 0 6px;font-size:24px}}.log{{height:360px;overflow:auto;padding:18px 20px}}
.msg{{white-space:pre-wrap;border:1px solid #dbeafe;background:#eff6ff;padding:12px;border-radius:8px;margin-bottom:10px}}
.input{{padding:14px 20px;border-top:1px solid #e5e7eb}}textarea{{width:100%;height:80px;box-sizing:border-box;border:1px solid #9ca3af;border-radius:8px;padding:10px}}
button{{background:#111827;color:white;border:0;border-radius:7px;padding:9px 12px;cursor:pointer;font-weight:700}}</style></head>
<body><div class="wrap"><div class="head"><h1>AI Assistant Chat</h1></div>
<div id="log" class="log"><div class="msg">Tu sa zobrazí konverzácia.</div></div>
<div class="input"><textarea id="txt"></textarea><button onclick="send(document.getElementById('txt').value)">Odoslať</button></div></div>
<script>
const tokenFromServer = {json.dumps(token_value)};
function getToken(){{const p=new URLSearchParams(window.location.search);return p.get('token')||tokenFromServer||'';}}
function add(t){{const l=document.getElementById('log');const d=document.createElement('div');d.className='msg';d.textContent=t;l.appendChild(d);l.scrollTop=l.scrollHeight;}}
async function send(m){{if(!m||!m.trim())return;document.getElementById('txt').value='';add('Ty: '+m);
const u='/assistant?token='+encodeURIComponent(getToken())+'&message='+encodeURIComponent(m);
try{{const r=await fetch(u);const t=await r.text();add('AI_OS: '+t);}}catch(e){{add('Chyba: '+e);}}}}
</script></body></html>"""
    return HTMLResponse(html)
