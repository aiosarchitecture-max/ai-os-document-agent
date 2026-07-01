import os
import time
import datetime as dt
from typing import Optional, Dict, Any, List
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

APP_NAME = "AI_OS_ORCHESTRATOR_V1_4_2_EXECUTIVE_ASSISTANT_SAFE_RUNTIME"
VERSION = "1.4.2"
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "https://ai-os-document-agent.onrender.com")
TIMEZONE_NAME = os.getenv("AI_OS_TIMEZONE", "Europe/Bratislava")
TZ = ZoneInfo(TIMEZONE_NAME)

ENABLE_EXECUTIVE_ASSISTANT = os.getenv("ENABLE_EXECUTIVE_ASSISTANT", "true").lower() not in {"0", "false", "no", "off"}
ENABLE_EXTERNAL_AI = os.getenv("ENABLE_EXTERNAL_AI", "false").lower() in {"1", "true", "yes", "on"}
ENABLE_DRIVE_REFRESH = os.getenv("ENABLE_DRIVE_REFRESH", "false").lower() in {"1", "true", "yes", "on"}
ENABLE_KNOWLEDGE_EVOLUTION_ENGINE = os.getenv("ENABLE_KNOWLEDGE_EVOLUTION_ENGINE", "true").lower() not in {"0", "false", "no", "off"}
ENABLE_KNOWLEDGE_RETRIEVAL = os.getenv("ENABLE_KNOWLEDGE_RETRIEVAL", "true").lower() not in {"0", "false", "no", "off"}
API_TOKEN = os.getenv("API_TOKEN", "").strip()

# Safe in-memory index. This version intentionally does not perform heavy Google Drive reads on request path.
AI_OS_INDEX: Dict[str, Any] = {
    "status": "safe_runtime",
    "created_utc": None,
    "document_count": 0,
    "documents": [],
    "errors": [],
    "note": "v1.4.2 protects public endpoints from Render 502/503 by avoiding heavy work in request path.",
}

app = FastAPI(title=APP_NAME, version=VERSION, servers=[{"url": PUBLIC_BASE_URL}])


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _now_local_iso() -> str:
    return dt.datetime.now(TZ).isoformat()


def _safe_text(value: Any, limit: int = 1200) -> str:
    text = str(value or "").strip()
    if len(text) > limit:
        return text[:limit] + "…"
    return text


def _check_token(request: Request) -> None:
    if not API_TOKEN:
        return
    supplied = request.headers.get("x-api-token") or request.query_params.get("token") or ""
    if supplied != API_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")


def _bool_query(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text.startswith(("1", "true", "yes", "on")):
        return True
    if text.startswith(("0", "false", "no", "off")):
        return False
    return default


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=200,
        content={
            "status": "safe_error",
            "service": APP_NAME,
            "path": request.url.path,
            "error": _safe_text(exc, 600),
            "time_utc": _now_iso(),
            "note": "Exception Shield active: endpoint returned JSON instead of 502/503.",
        },
    )


class OrchestratorRequest(BaseModel):
    message: str
    limit: Optional[int] = 5
    debug: Optional[bool] = False
    assistant_mode: Optional[bool] = True
    write_result: Optional[bool] = False
    result_title: Optional[str] = None
    project_id: Optional[str] = "AI_OS"


class ExecutiveAssistantRequest(BaseModel):
    message: str
    limit: Optional[int] = 5
    debug: Optional[bool] = False
    write_result: Optional[bool] = False
    result_title: Optional[str] = None
    project_id: Optional[str] = "AI_OS"


def _route(message: str) -> str:
    m = (message or "").lower()
    if any(x in m for x in ["dokument", "docx", "zapíš", "ulož", "vytvor"]):
        return "document_workflow"
    if any(x in m for x in ["audit", "skontroluj", "over", "chyba", "rizik"]):
        return "audit_workflow"
    if any(x in m for x in ["implement", "kód", "github", "render", "deploy"]):
        return "implementation_workflow"
    if any(x in m for x in ["ďalší krok", "plan", "plán", "roadmap", "čo teraz"]):
        return "planning_workflow"
    return "general_workflow"


def _knowledge_decision(message: str, limit: int = 5) -> Dict[str, Any]:
    m = (message or "").lower()
    if any(x in m for x in ["nový dokument", "vytvor dokument", "šablón", "capability", "architecture", "architekt"]):
        decision = "MERGE"
        reason = "Pred tvorbou nového obsahu treba overiť existujúce dokumenty a znížiť duplicity."
        confidence = 0.82
    elif any(x in m for x in ["north star", "stav", "roadmap", "princip", "princíp"]):
        decision = "REUSE"
        reason = "Otázka sa pravdepodobne týka existujúcej autoritatívnej znalosti."
        confidence = 0.86
    elif any(x in m for x in ["oprav", "update", "aktualiz", "zmeň"]):
        decision = "UPDATE"
        reason = "Požiadavka smeruje k zmene existujúceho artefaktu."
        confidence = 0.78
    else:
        decision = "CREATE NEW"
        reason = "Nie je zrejmá existujúca autoritatívna znalosť; vytvoriť pracovný návrh po overení."
        confidence = 0.55
    return {
        "enabled": ENABLE_KNOWLEDGE_EVOLUTION_ENGINE,
        "decision": decision,
        "confidence": confidence,
        "confidence_level": "high" if confidence >= 0.8 else "medium",
        "reason": reason,
        "actions": ["REUSE", "MERGE", "UPDATE", "ARCHIVE", "REMOVE", "CREATE NEW"],
        "used_document_count": 0,
        "limit": limit,
    }


def _deterministic_answer(message: str, route: Optional[str] = None) -> str:
    route = route or _route(message)
    if route == "document_workflow":
        return "1. Pochopenie zadania: Ide o dokumentačnú úlohu.\n\n2. Najbližší krok: Overiť existujúce dokumenty podľa Knowledge Reuse First a pripraviť návrh bez duplicít.\n\n3. Čo má Daniel schváliť: Potvrdiť, či ide o nový dokument alebo aktualizáciu existujúceho.\n\n4. Stav úlohy: Prijaté asistentom."
    if route == "implementation_workflow":
        return "1. Pochopenie zadania: Ide o implementačnú úlohu.\n\n2. Najbližší krok: Najprv stabilizovať endpointy, potom pripraviť malý nasaditeľný balík s rollbackom.\n\n3. Čo má Daniel schváliť: Nasadenie produkčne bezpečnej verzie.\n\n4. Stav úlohy: Prijaté asistentom."
    if route == "audit_workflow":
        return "1. Pochopenie zadania: Ide o audit alebo kontrolu.\n\n2. Najbližší krok: Porovnať aktuálny stav s autoritatívnymi dokumentmi a označiť riziká.\n\n3. Čo má Daniel schváliť: Či má audit viesť ku korekcii alebo iba k reportu.\n\n4. Stav úlohy: Prijaté asistentom."
    return "1. Pochopenie zadania: Požiadavka bola prijatá Executive Assistantom.\n\n2. Najbližší krok: Spracovať zadanie cez Orchestrator, Knowledge Evolution a existujúce registre.\n\n3. Čo má Daniel schváliť: Potvrdiť ďalšiu akciu alebo doplniť detail.\n\n4. Stav úlohy: Prijaté asistentom."


def _run_orchestrator(payload: OrchestratorRequest) -> Dict[str, Any]:
    if not payload.message or not payload.message.strip():
        return {"status": "error", "answer": "Chýba parameter message."}
    message = payload.message.strip()
    safe_limit = max(1, min(int(payload.limit or 5), 10))
    ke = _knowledge_decision(message, safe_limit) if ENABLE_KNOWLEDGE_EVOLUTION_ENGINE else {"enabled": False}
    answer = _deterministic_answer(message)
    result = {"status": "success", "answer": answer}
    if payload.debug:
        result["debug"] = {
            "service": APP_NAME,
            "version": VERSION,
            "route": _route(message),
            "knowledge_evolution": ke,
            "knowledge_retrieval": {
                "enabled": ENABLE_KNOWLEDGE_RETRIEVAL,
                "mode": "safe_runtime_no_heavy_drive_reads",
                "document_count": AI_OS_INDEX.get("document_count", 0),
            },
            "external_ai_enabled": ENABLE_EXTERNAL_AI,
            "write_result_requested": bool(payload.write_result),
            "time_utc": _now_iso(),
        }
    return result


def _run_assistant(payload: ExecutiveAssistantRequest) -> Dict[str, Any]:
    if not ENABLE_EXECUTIVE_ASSISTANT:
        return {"status": "disabled", "assistant": "Executive Assistant", "answer": "Executive Assistant je vypnutý."}
    if not payload.message or not payload.message.strip():
        return {"status": "error", "assistant": "Executive Assistant", "answer": "Chýba parameter message."}
    message = payload.message.strip()
    route = _route(message)
    orch = _run_orchestrator(OrchestratorRequest(
        message=message,
        limit=payload.limit,
        debug=payload.debug,
        assistant_mode=True,
        write_result=payload.write_result,
        result_title=payload.result_title,
        project_id=payload.project_id,
    ))
    result = {
        "status": "success",
        "assistant": "Executive Assistant",
        "version": VERSION,
        "route": route,
        "answer": orch.get("answer"),
        "next_action": "Potvrdiť ďalší krok alebo doplniť detail zadania.",
    }
    if payload.debug:
        result["debug"] = {"orchestrator": orch.get("debug"), "rollback": "ENABLE_EXECUTIVE_ASSISTANT=false"}
    return result


@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    response.headers["x-ai-os-version"] = VERSION
    response.headers["x-process-time-ms"] = str(int((time.time() - start) * 1000))
    return response


@app.head("/")
def root_head():
    return Response(status_code=200)


@app.get("/")
def root():
    return {
        "service": APP_NAME,
        "status": "running",
        "message": "AI_OS Executive Assistant safe runtime is online.",
        "use": ["/assistant/health", "/assistant?message=test", "/orchestrator/ask?message=test", "/refresh-index"],
        "time_utc": _now_iso(),
    }


@app.get("/health")
def health(request: Request):
    _check_token(request)
    return {"status": "ok", "service": APP_NAME, "version": VERSION, "time_utc": _now_iso()}


@app.get("/orchestrator/health")
def orchestrator_health(request: Request):
    _check_token(request)
    return {
        "status": "ok",
        "service": APP_NAME,
        "orchestrator": "enabled",
        "executive_assistant": "enabled" if ENABLE_EXECUTIVE_ASSISTANT else "disabled",
        "knowledge_evolution_engine": "enabled" if ENABLE_KNOWLEDGE_EVOLUTION_ENGINE else "disabled",
        "knowledge_retrieval": {"enabled": ENABLE_KNOWLEDGE_RETRIEVAL, "mode": "safe_runtime"},
        "external_ai_enabled": ENABLE_EXTERNAL_AI,
        "drive_refresh_enabled": ENABLE_DRIVE_REFRESH,
        "time_utc": _now_iso(),
        "time_local": _now_local_iso(),
    }


@app.get("/assistant/health")
def assistant_health(request: Request):
    _check_token(request)
    return {
        "status": "ok",
        "assistant": "Executive Assistant",
        "version": VERSION,
        "enabled": ENABLE_EXECUTIVE_ASSISTANT,
        "uses": ["AI_OS Orchestrator", "SRV-001 Knowledge Evolution Engine", "Safe Runtime"],
        "rollback": "ENABLE_EXECUTIVE_ASSISTANT=false",
        "time_utc": _now_iso(),
    }


@app.get("/orchestrator/ask")
def orchestrator_ask_get(request: Request, message: str, limit: int = 5, debug: bool = False, assistant_mode: Optional[str] = None, write_result: bool = False, result_title: Optional[str] = None, project_id: str = "AI_OS"):
    _check_token(request)
    return _run_orchestrator(OrchestratorRequest(message=message, limit=limit, debug=debug, assistant_mode=_bool_query(assistant_mode, True), write_result=write_result, result_title=result_title, project_id=project_id))


@app.post("/orchestrator/ask")
def orchestrator_ask_post(request: Request, payload: OrchestratorRequest):
    _check_token(request)
    return _run_orchestrator(payload)


@app.get("/assistant")
def assistant_get(request: Request, message: str, limit: int = 5, debug: bool = False, write_result: bool = False, result_title: Optional[str] = None, project_id: str = "AI_OS"):
    _check_token(request)
    return _run_assistant(ExecutiveAssistantRequest(message=message, limit=limit, debug=debug, write_result=write_result, result_title=result_title, project_id=project_id))


@app.post("/assistant")
def assistant_post(request: Request, payload: ExecutiveAssistantRequest):
    _check_token(request)
    return _run_assistant(payload)


@app.get("/orchestrator/knowledge-evolution")
def knowledge_evolution(request: Request, message: str, limit: int = 5):
    _check_token(request)
    safe_limit = max(1, min(int(limit or 5), 10))
    return {
        "status": "success",
        "service": "SRV-001 Knowledge Evolution Engine",
        "version": VERSION,
        "knowledge_evolution": _knowledge_decision(message, safe_limit),
        "knowledge_retrieval": {"enabled": ENABLE_KNOWLEDGE_RETRIEVAL, "mode": "safe_runtime_no_heavy_drive_reads"},
        "time_utc": _now_iso(),
    }


@app.get("/refresh-index")
def refresh_index(request: Request, limit: int = 20):
    _check_token(request)
    if not ENABLE_DRIVE_REFRESH:
        AI_OS_INDEX["status"] = "ready_safe_noop"
        AI_OS_INDEX["created_utc"] = _now_iso()
        return {
            "status": "success",
            "action": "REFRESH_INDEX",
            "index_status": "ready_safe_noop",
            "document_count": AI_OS_INDEX.get("document_count", 0),
            "note": "Drive refresh is disabled by default in v1.4.2 to prevent Render 502/503. Set ENABLE_DRIVE_REFRESH=true later.",
            "time_utc": _now_iso(),
        }
    # Placeholder for future safe paginated Drive refresh.
    AI_OS_INDEX["status"] = "ready"
    AI_OS_INDEX["created_utc"] = _now_iso()
    return {"status": "success", "action": "REFRESH_INDEX", "index_status": "ready", "document_count": 0, "time_utc": _now_iso()}
