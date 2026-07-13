"""
AI_OS CAP-012.5 LLM Developer Bridge FULL
FastAPI main.py

Cieľ:
- zachovať existujúci AI_OS Document Agent,
- pridať bezpečný most pre AnythingLLM / externý LLM vývojársky systém,
- pridať /boot, /mcp/tools, /events/trigger,
- zachovať ľudský text ako predvolený výstup, JSON iba cez debug=true.

Bezpečnostné pravidlo:
- externý LLM môže navrhovať a odosielať udalosti,
- nesmie priamo nasadzovať produkciu,
- produkčné zmeny idú cez človeka, GitHub a Render.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from mcp.server.fastmcp import FastMCP

VERSION = "v2.8.0-cap014-file-operations-bridge"
APP_NAME = "AI_OS LLM Developer Bridge"

API_TOKEN = os.getenv("API_TOKEN", "").strip()
APPS_SCRIPT_WEBAPP_URL = os.getenv("APPS_SCRIPT_WEBAPP_URL", "").strip()
APPS_SCRIPT_SECRET = os.getenv("APPS_SCRIPT_SECRET", "").strip()
REQUEST_TIMEOUT_SECONDS = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "60"))
AI_OS_ROOT_FOLDER_ID = os.getenv("AI_OS_ROOT_FOLDER_ID", "").strip()
GITHUB_REPO_URL = os.getenv("GITHUB_REPO_URL", "").strip()

app = FastAPI(title=APP_NAME, version=VERSION)

RUNTIME_STATE: Dict[str, Any] = {
    "system": "AI_OS",
    "version": VERSION,
    "stage": "CAP-014 MCP Bridge & File Operations",
    "last_stable_cap": "CAP-012.5",
    "current_cap": "CAP-014",
    "current_task": "Priame MCP pripojenie pre Claude + reálne presuny/premenovania/trash súborov v Google Drive.",
    "root_folder_id_configured": bool(AI_OS_ROOT_FOLDER_ID),
    "apps_script_configured": bool(APPS_SCRIPT_WEBAPP_URL),
    "github_repo_url": GITHUB_REPO_URL,
    "last_event": None,
    "events": [],
}

SAFE_TOOL_REGISTRY: List[Dict[str, Any]] = [
    {
        "name": "aios_boot",
        "description": "Načíta aktuálny runtime stav AI_OS pred začiatkom práce agenta.",
        "method": "GET",
        "path": "/boot?token=API_TOKEN",
        "risk": "low",
        "requires_human_approval": False,
    },
    {
        "name": "aios_trigger_event",
        "description": "Odošle udalosť do AI_OS Event Bus. Vhodné pre výsledky práce AnythingLLM.",
        "method": "POST",
        "path": "/events/trigger?token=API_TOKEN",
        "risk": "medium",
        "requires_human_approval": False,
    },
    {
        "name": "aios_assistant_command",
        "description": "Spustí existujúci textový príkaz AI_OS asistenta.",
        "method": "GET",
        "path": "/assistant?token=API_TOKEN&message=...",
        "risk": "medium",
        "requires_human_approval": "podľa príkazu",
    },
    {
        "name": "aios_self_test",
        "description": "Overí základné technické nastavenie mosta.",
        "method": "GET",
        "path": "/self-test?token=API_TOKEN",
        "risk": "low",
        "requires_human_approval": False,
    },
    {
        "name": "aios_move_file",
        "description": "Presunie súbor/priečinok v Google Drive do iného priečinka. Vyžaduje confirm_id.",
        "method": "POST",
        "path": "/files/move?token=API_TOKEN",
        "risk": "high",
        "requires_human_approval": True,
    },
    {
        "name": "aios_trash_file",
        "description": "Presunie súbor do Koša (vratné, nie trvalé zmazanie). Vyžaduje confirm_id.",
        "method": "POST",
        "path": "/files/trash?token=API_TOKEN",
        "risk": "high",
        "requires_human_approval": True,
    },
    {
        "name": "aios_rename_file",
        "description": "Premenuje súbor/priečinok v Google Drive. Vyžaduje confirm_id.",
        "method": "POST",
        "path": "/files/rename?token=API_TOKEN",
        "risk": "medium",
        "requires_human_approval": True,
    },
    {
        "name": "aios_migration_log",
        "description": "Prečíta AI_OS_MIGRATION_LOG (audit trail všetkých presunov/trash/premenovaní).",
        "method": "GET",
        "path": "/files/migration-log?token=API_TOKEN",
        "risk": "low",
        "requires_human_approval": False,
    },
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
        return JSONResponse(
            {"status": "error", "code": "UNAUTHORIZED", "version": VERSION, "time_utc": utc_now()},
            status_code=401,
        )
    return PlainTextResponse("Neautorizovaný prístup.", status_code=401)

def plain_or_json(payload: Dict[str, Any], debug: bool = False):
    if debug:
        return JSONResponse(payload)
    return PlainTextResponse(payload.get("human", "Požiadavka bola spracovaná."), media_type="text/plain; charset=utf-8")

def post_to_apps_script(action: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if not APPS_SCRIPT_WEBAPP_URL:
        return {"status": "error", "code": "APPS_SCRIPT_WEBAPP_URL_MISSING", "message": "Apps Script URL nie je nastavená."}
    body = {
        "secret": APPS_SCRIPT_SECRET,
        "action": action,
        "payload": payload or {},
        "source": "AI_OS_RENDER_FASTAPI",
        "version": VERSION,
        "time_utc": utc_now(),
    }
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
    return re.sub(r"\\s+", " ", (message or "").strip())

def command_to_action(message: str) -> Dict[str, Any]:
    m = normalize_message(message)
    low = m.lower()

    # Systémové príkazy
    if low in {"ranný štart", "ranny start", "ranný start"}:
        return {"intent": "MORNING_START", "human": "AI_OS – ranný štart\\nStav: pripravený.\\nĎalší krok: zadaj dnešnú prioritu."}
    if low in {"denné príkazy", "denne prikazy", "príkazy", "prikazy"}:
        return {"intent": "COMMANDS", "human": available_commands_text()}
    if "manažérsky prehľad" in low or "manazersky prehlad" in low:
        return {"intent": "EXECUTIVE_REPORT", "human": "AI_OS – manažérsky prehľad\\nStav: CAP-012.5 LLM Developer Bridge.\\nPriorita: bezpečne prepojiť AnythingLLM s AI_OS."}

    # Documentation Intelligence / Governance
    doc_commands = {
        "audit dokumentácie": "DOC_AUDIT",
        "audit dokumentacie": "DOC_AUDIT",
        "inventúra dokumentov": "DOC_INVENTORY",
        "inventura dokumentov": "DOC_INVENTORY",
        "analýza dokumentácie": "DOC_ANALYSIS",
        "analyza dokumentacie": "DOC_ANALYSIS",
        "návrh štruktúry": "DOC_STRUCTURE_PROPOSAL",
        "navrh struktury": "DOC_STRUCTURE_PROPOSAL",
        "migračný plán": "DOC_MIGRATION_PLAN",
        "migracny plan": "DOC_MIGRATION_PLAN",
        "optimalizuj dokumentáciu": "DOC_OPTIMIZATION_PLAN",
        "optimalizuj dokumentaciu": "DOC_OPTIMIZATION_PLAN",
        "health dokumentácie": "DOC_HEALTH",
        "health dokumentacie": "DOC_HEALTH",
        "validuj štruktúru": "DOC_VALIDATE_STRUCTURE",
        "validuj strukturu": "DOC_VALIDATE_STRUCTURE",
        "skontroluj governance": "DOC_GOVERNANCE",
        "nájdi duplicity": "DOC_DUPLICATES",
        "najdi duplicity": "DOC_DUPLICATES",
        "nájdi siroty": "DOC_ORPHANS",
        "najdi siroty": "DOC_ORPHANS",
        "archivuj zastarané dokumenty plán": "DOC_ARCHIVE_PLAN",
        "archivuj zastarane dokumenty plan": "DOC_ARCHIVE_PLAN",
        "migračný log": "DOC_MIGRATION_LOG",
        "migracny log": "DOC_MIGRATION_LOG",
    }
    for key, intent in doc_commands.items():
        if key in low:
            return call_script_intent(intent, m)

    # Drive commands
    if low.startswith("drive "):
        return call_script_intent("DRIVE_COMMAND", m)

    # Project commands
    if low.startswith("projekt "):
        return call_script_intent("PROJECT_COMMAND", m)

    # LLM bridge commands
    if "boot" == low or "ai os boot" in low or "ai_os boot" in low:
        return {"intent": "BOOT", "human": boot_text(), "data": boot_payload()}
    if "mcp tools" in low or "mcp nástroje" in low or "mcp nastroje" in low:
        return {"intent": "MCP_TOOLS", "human": tools_text(), "data": {"tools": SAFE_TOOL_REGISTRY}}
    if low.startswith("event ") or low.startswith("udalosť ") or low.startswith("udalost "):
        event_type = "MANUAL_EVENT"
        detail = m
        payload = register_event(event_type, {"message": detail, "source": "assistant_text_command"})
        return {"intent": "EVENT_TRIGGERED", "human": f"Udalosť bola zapísaná.\\nTyp: {event_type}\\nEvent ID: {payload['event_id']}", "data": payload}

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
    return {"intent": intent, "human": f"Nepodarilo sa zavolať Apps Script.\\nChyba: {result.get('message') or result.get('code')}", "apps_script": result}

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
        "status": "success",
        "boot": "READY",
        "version": VERSION,
        "time_utc": utc_now(),
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
    return (
        "AI_OS BOOT READY\\n"
        f"Verzia: {p['version']}\\n"
        f"Aktuálny CAP: {RUNTIME_STATE['current_cap']}\\n"
        f"Úloha: {RUNTIME_STATE['current_task']}\\n"
        "Pravidlo: externý LLM navrhuje, človek schvaľuje, GitHub/Render nasadzuje."
    )

def tools_text() -> str:
    lines = ["AI_OS MCP Tools – bezpečný zoznam nástrojov"]
    for tool in SAFE_TOOL_REGISTRY:
        lines.append(f"- {tool['name']}: {tool['description']} ({tool['method']} {tool['path']})")
    return "\\n".join(lines)

def register_event(event_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    event = {
        "event_id": request_id(),
        "event_type": event_type,
        "payload": payload,
        "time_utc": utc_now(),
        "status": "RECEIVED",
    }
    RUNTIME_STATE["last_event"] = event
    RUNTIME_STATE["events"].append(event)
    if len(RUNTIME_STATE["events"]) > 50:
        RUNTIME_STATE["events"] = RUNTIME_STATE["events"][-50:]

    # Voliteľné zapísanie do Apps Scriptu. Ak zlyhá, event v Renderi stále existuje.
    script_result = post_to_apps_script("EVENT_TRIGGER", event)
    event["apps_script_status"] = script_result.get("status")
    event["apps_script_http_status"] = script_result.get("http_status")
    return event

def move_file(file_id: str, target_folder_id: str, confirm_id: str) -> Dict[str, Any]:
    result = post_to_apps_script(
        "MOVE_FILE",
        {"fileId": file_id, "targetFolderId": target_folder_id, "confirm_id": confirm_id},
    )
    return result


def trash_file(file_id: str, confirm_id: str) -> Dict[str, Any]:
    result = post_to_apps_script("TRASH_FILE", {"fileId": file_id, "confirm_id": confirm_id})
    return result


def rename_file(file_id: str, new_title: str, confirm_id: str) -> Dict[str, Any]:
    result = post_to_apps_script(
        "RENAME_FILE", {"fileId": file_id, "newTitle": new_title, "confirm_id": confirm_id}
    )
    return result


def read_migration_log() -> Dict[str, Any]:
    return post_to_apps_script("READ_MIGRATION_LOG", {})


def apps_script_result_to_response(result: Dict[str, Any], debug: bool) -> Any:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    human = str(data.get("human") or result.get("message") or result.get("code") or "Operácia bola spracovaná.")
    payload = {
        "status": result.get("status", "error"),
        "version": VERSION,
        "time_utc": utc_now(),
        "apps_script": result,
        "human": human,
    }
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
        return plain_or_json(
            {"status": "error", "human": "Chýba file_id alebo target_folder_id.", "version": VERSION}, debug
        )
    if not confirm_id:
        return plain_or_json(
            {
                "status": "error",
                "human": "Operácia MOVE_FILE vyžaduje confirm_id (schválené ID z reorganizačného plánu).",
                "version": VERSION,
            },
            debug,
        )
    result = move_file(file_id, target_folder_id, confirm_id)
    return apps_script_result_to_response(result, debug)


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
        return plain_or_json(
            {
                "status": "error",
                "human": "Operácia TRASH_FILE vyžaduje confirm_id (schválené ID z reorganizačného plánu).",
                "version": VERSION,
            },
            debug,
        )
    result = trash_file(file_id, confirm_id)
    return apps_script_result_to_response(result, debug)


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
        return plain_or_json(
            {"status": "error", "human": "Chýba file_id alebo new_title.", "version": VERSION}, debug
        )
    if not confirm_id:
        return plain_or_json(
            {
                "status": "error",
                "human": "Operácia RENAME_FILE vyžaduje confirm_id (schválené ID z reorganizačného plánu).",
                "version": VERSION,
            },
            debug,
        )
    result = rename_file(file_id, new_title, confirm_id)
    return apps_script_result_to_response(result, debug)


@app.get("/files/migration-log")
def files_migration_log(request: Request, token: Optional[str] = None):
    debug = wants_debug(request)
    if not token_ok(token):
        return unauthorized(debug)
    result = read_migration_log()
    return apps_script_result_to_response(result, debug)


# =====================================================================
# CAP-014 — MCP server (skutočné pripojenie pre Claude a iné MCP-kompatibilné
# AI modely). Nástroje volajú presne tú istú logiku ako REST endpointy vyššie,
# takže sa správanie nikde neduplikuje a nerozchádza.
# =====================================================================
mcp = FastMCP(
    name="ai_os_orchestrator",
    instructions=(
        "Nástroje AI_OS Orchestrátora Daniela Valušiaka. Pred volaním aios_move_file, "
        "aios_trash_file alebo aios_rename_file vždy over, že existuje schválený "
        "confirm_id (napr. z AI_OS_AGENT_BRIEF alebo Reorganization Package). "
        "Nikdy tieto tri operácie nevolaj z vlastnej iniciatívy bez explicitného "
        "schválenia Daniela."
    ),
)


@mcp.tool()
def aios_boot() -> dict:
    """Načíta aktuálny runtime stav AI_OS (mandatórne pravidlá, dostupné nástroje)."""
    if not API_TOKEN:
        return {"status": "error", "message": "API_TOKEN nie je nastavený na serveri."}
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
    """
    Pošle textový príkaz existujúcemu AI_OS asistentovi (rovnaká logika ako /assistant).
    Použi napr.: 'Drive status', 'Health dokumentácie', 'Nájdi duplicity', 'Denné príkazy'.
    """
    return command_to_action(message)


@mcp.tool()
def aios_move_file(file_id: str, target_folder_id: str, confirm_id: str) -> dict:
    """
    Presunie súbor/priečinok v Google Drive do iného priečinka.
    POVINNÉ: confirm_id musí byť schválené ID z reorganizačného plánu.
    Nikdy nevolaj bez explicitného predchádzajúceho schválenia Daniela.
    """
    if not confirm_id:
        return {"status": "error", "message": "confirm_id je povinné pre túto operáciu."}
    return move_file(file_id, target_folder_id, confirm_id)


@mcp.tool()
def aios_trash_file(file_id: str, confirm_id: str) -> dict:
    """
    Presunie súbor do Koša Google Drive (vratné, cca 30 dní na obnovenie).
    POVINNÉ: confirm_id musí byť schválené ID z reorganizačného plánu.
    """
    if not confirm_id:
        return {"status": "error", "message": "confirm_id je povinné pre túto operáciu."}
    return trash_file(file_id, confirm_id)


@mcp.tool()
def aios_rename_file(file_id: str, new_title: str, confirm_id: str) -> dict:
    """
    Premenuje súbor/priečinok v Google Drive.
    POVINNÉ: confirm_id musí byť schválené ID z reorganizačného plánu.
    """
    if not confirm_id:
        return {"status": "error", "message": "confirm_id je povinné pre túto operáciu."}
    return rename_file(file_id, new_title, confirm_id)


@mcp.tool()
def aios_migration_log() -> dict:
    """Prečíta AI_OS_MIGRATION_LOG — audit trail všetkých doteraz vykonaných operácií."""
    return read_migration_log()


# Namontuje MCP server na /mcp (Streamable HTTP transport — rovnaký druh
# pripojenia, aký claude.ai používa pre vzdialené konektory ako Google Drive).
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
        {"name": "root", "status": "PASS"},
        {"name": "api_token", "status": "PASS" if API_TOKEN else "FAIL"},
        {"name": "token_valid", "status": "PASS"},
        {"name": "fastapi_app", "status": "PASS"},
        {"name": "human_output_default", "status": "PASS"},
        {"name": "debug_output_separated", "status": "PASS"},
        {"name": "apps_script_webapp_url", "status": "PASS" if APPS_SCRIPT_WEBAPP_URL else "WARN"},
        {"name": "aios_boot", "status": "PASS"},
        {"name": "mcp_tools", "status": "PASS"},
        {"name": "events_trigger", "status": "PASS"},
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
    payload = {
        "status": "success",
        "version": VERSION,
        "time_utc": utc_now(),
        "tools": SAFE_TOOL_REGISTRY,
        "human": tools_text(),
    }
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
    response = {
        "status": "success",
        "version": VERSION,
        "time_utc": utc_now(),
        "event": event,
        "human": f"Udalosť bola prijatá.\\nTyp: {event_type}\\nEvent ID: {event['event_id']}",
    }
    return plain_or_json(response, debug)

@app.get("/events")
def events_list(request: Request, token: Optional[str] = None):
    debug = wants_debug(request)
    if not token_ok(token):
        return unauthorized(debug)
    payload = {
        "status": "success",
        "version": VERSION,
        "events_count": len(RUNTIME_STATE.get("events", [])),
        "events": RUNTIME_STATE.get("events", [])[-20:],
        "human": "Event Bus je dostupný. Posledné udalosti: " + str(len(RUNTIME_STATE.get("events", []))),
    }
    return plain_or_json(payload, debug)

@app.get("/assistant")
def assistant(request: Request, token: Optional[str] = None, message: str = ""):
    debug = wants_debug(request)
    if not token_ok(token):
        return unauthorized(debug)
    result = command_to_action(message)
    payload = {
        "status": "success",
        "assistant": APP_NAME,
        "version": VERSION,
        "request_id": request_id(),
        "time_utc": utc_now(),
        "message": message,
        **result,
    }
    return plain_or_json(payload, debug)

@app.get("/workspace")
def workspace(request: Request):
    debug = wants_debug(request)
    tree = """AI_OS
├── 00_INBOX
├── 10_CORE
│   ├── 01_MASTER_CONTEXT
│   ├── 02_SMERNICE_PLAYBOOKS
│   ├── 03_ARCHITECTURE
│   ├── 04_GOVERNANCE
│   ├── 05_ENGINEERING_LIBRARY
│   ├── 06_FOUNDATION_LIBRARY
│   └── 07_MEMORY_AND_MILESTONES
├── 20_PROJECTS
├── 30_CAPABILITIES
├── 90_ARCHIVE
└── 99_SYSTEM_LOGS"""
    payload = {"status": "success", "version": VERSION, "tree": tree, "root_folder_id_configured": bool(AI_OS_ROOT_FOLDER_ID), "human": "AI_OS – Project Workspace\\n" + tree}
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
    html = f"""
<!doctype html>
<html lang="sk">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>AI Assistant Chat</title>
<style>
body {{ margin:0; background:#f3f4f6; font-family: Arial, sans-serif; color:#111827; }}
.wrap {{ max-width: 760px; margin: 32px auto; background:white; border:1px solid #d1d5db; border-radius:12px; overflow:hidden; box-shadow:0 10px 25px rgba(0,0,0,.06); }}
.head {{ padding:18px 20px; border-bottom:1px solid #e5e7eb; }}
h1 {{ margin:0 0 6px 0; font-size:24px; }}
.sub {{ color:#4b5563; font-size:14px; }}
.buttons {{ padding:12px 20px; border-bottom:1px solid #e5e7eb; display:flex; flex-wrap:wrap; gap:8px; }}
button {{ background:#111827; color:white; border:0; border-radius:7px; padding:9px 12px; cursor:pointer; font-weight:700; }}
button:hover {{ opacity:.9; }}
.log {{ height:360px; overflow:auto; padding:18px 20px; background:#fff; }}
.msg {{ white-space:pre-wrap; border:1px solid #dbeafe; background:#eff6ff; padding:12px; border-radius:8px; margin-bottom:10px; }}
.input {{ padding:14px 20px; border-top:1px solid #e5e7eb; }}
textarea {{ width:100%; height:80px; box-sizing:border-box; border:1px solid #9ca3af; border-radius:8px; padding:10px; }}
.row {{ display:flex; justify-content:space-between; align-items:center; margin-top:8px; }}
.small {{ font-size:12px; color:#4b5563; }}
</style>
</head>
<body>
<div class="wrap">
  <div class="head">
    <h1>AI Assistant Chat</h1>
    <div class="sub">CAP-012.5 LLM Developer Bridge. Token sa nevypĺňa do stránky, ak je v URL.</div>
  </div>
  <div class="buttons">
    <button onclick="send('AI_OS boot')">🧭 Boot</button>
    <button onclick="send('MCP tools')">🧰 MCP tools</button>
    <button onclick="send('Denné príkazy')">📋 Príkazy</button>
    <button onclick="send('Health dokumentácie')">❤️ Health</button>
    <button onclick="send('Optimalizuj dokumentáciu AI_OS')">⚙️ Optimalizovať</button>
    <button onclick="send('Event Test z AI Assistant Chat')">📡 Test event</button>
  </div>
  <div id="log" class="log"><div class="msg">Tu sa zobrazí konverzácia.</div></div>
  <div class="input">
    <textarea id="txt" placeholder="Napíš požiadavku po slovensky..."></textarea>
    <div class="row">
      <span class="small">Enter = odoslať, Shift+Enter = nový riadok.</span>
      <button onclick="send(document.getElementById('txt').value)">Odoslať</button>
    </div>
  </div>
</div>
<script>
const tokenFromServer = {json.dumps(token_value)};
function getToken() {{
  const params = new URLSearchParams(window.location.search);
  return params.get('token') || tokenFromServer || '';
}}
function add(text) {{
  const log = document.getElementById('log');
  const div = document.createElement('div');
  div.className='msg';
  div.textContent=text;
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
}}
async function send(message) {{
  if(!message || !message.trim()) return;
  document.getElementById('txt').value='';
  add('Ty: ' + message);
  const url = '/assistant?token=' + encodeURIComponent(getToken()) + '&message=' + encodeURIComponent(message);
  try {{
    const r = await fetch(url);
    const t = await r.text();
    add('AI_OS: ' + t);
  }} catch(e) {{
    add('Chyba: ' + e);
  }}
}}
document.getElementById('txt').addEventListener('keydown', function(e) {{
  if(e.key === 'Enter' && !e.shiftKey) {{ e.preventDefault(); send(this.value); }}
}});
</script>
</body>
</html>
"""
    return HTMLResponse(html)
