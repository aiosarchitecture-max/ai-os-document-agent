
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel


APP_NAME = "AI_OS_ORCHESTRATOR_V1_4_3_CAPABILITY_RUNTIME"
VERSION = "1.4.3-capability-runtime"

API_TOKEN = os.getenv("API_TOKEN", "").strip()

ENABLE_EXECUTIVE_ASSISTANT = os.getenv("ENABLE_EXECUTIVE_ASSISTANT", "true").lower() == "true"
ENABLE_CAPABILITY_RUNTIME = os.getenv("ENABLE_CAPABILITY_RUNTIME", "true").lower() == "true"
ENABLE_KNOWLEDGE_EVOLUTION = os.getenv("ENABLE_KNOWLEDGE_EVOLUTION", "true").lower() == "true"
ENABLE_DOCUMENT_AGENT = os.getenv("ENABLE_DOCUMENT_AGENT", "false").lower() == "true"
ENABLE_DRIVE_REFRESH = os.getenv("ENABLE_DRIVE_REFRESH", "false").lower() == "true"

app = FastAPI(title=APP_NAME, version=VERSION)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _check_token(request: Request) -> None:
    """
    Accepts token from:
    - ?token=<API_TOKEN>
    - x-api-token header
    - Authorization: Bearer <API_TOKEN>

    If API_TOKEN is empty, protected endpoints are disabled by default.
    """
    if not API_TOKEN:
        raise HTTPException(status_code=503, detail="API_TOKEN is not configured")

    header_token = request.headers.get("x-api-token", "").strip()
    query_token = request.query_params.get("token", "").strip()
    auth = request.headers.get("authorization", "").strip()
    bearer_token = auth.replace("Bearer ", "", 1).strip() if auth.lower().startswith("bearer ") else ""

    supplied = header_token or query_token or bearer_token
    if supplied != API_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")


def _safe_limit(limit: int | None, default: int = 5, min_value: int = 1, max_value: int = 20) -> int:
    try:
        value = int(limit if limit is not None else default)
    except Exception:
        value = default
    return max(min_value, min(value, max_value))


def safe_endpoint(fn):
    async def wrapper(*args, **kwargs):
        start = time.time()
        request_id = str(uuid.uuid4())
        try:
            result = fn(*args, **kwargs)
            if hasattr(result, "__await__"):
                result = await result
            if isinstance(result, JSONResponse):
                return result
            if isinstance(result, dict):
                result.setdefault("request_id", request_id)
                result.setdefault("duration_ms", round((time.time() - start) * 1000, 2))
                return JSONResponse(result)
            return result
        except HTTPException as e:
            return JSONResponse(
                status_code=e.status_code,
                content={
                    "status": "error",
                    "error_type": "http",
                    "detail": e.detail,
                    "request_id": request_id,
                    "duration_ms": round((time.time() - start) * 1000, 2),
                },
            )
        except Exception as e:
            return JSONResponse(
                status_code=200,
                content={
                    "status": "safe_error",
                    "error_type": e.__class__.__name__,
                    "detail": str(e),
                    "request_id": request_id,
                    "duration_ms": round((time.time() - start) * 1000, 2),
                },
            )
    return wrapper


class Capability(BaseModel):
    id: str
    name: str
    type: str = "Capability"
    status: str = "ACTIVE"
    priority: str = "P1"
    enabled: bool = True
    purpose: str = ""
    endpoint: Optional[str] = None


class CapabilityResult(BaseModel):
    status: str
    capability_id: str
    capability_name: str
    action: str
    answer: str
    next_action: str
    data: Dict[str, Any] = {}


CAPABILITIES: Dict[str, Capability] = {
    "CAP-001": Capability(
        id="CAP-001",
        name="Working Context",
        status="ACTIVE",
        priority="P0",
        purpose="Zostavenie pracovného kontextu z dostupných znalostí.",
    ),
    "CAP-002": Capability(
        id="CAP-002",
        name="Executive Assistant",
        status="ACTIVE",
        priority="P0",
        purpose="Jednotný konverzačný vstup používateľa do AI_OS.",
        endpoint="/assistant",
    ),
    "CAP-003": Capability(
        id="CAP-003",
        name="Capability Runtime",
        status="ACTIVE",
        priority="P0",
        purpose="Výber, spustenie a bezpečné vykonanie Capability.",
        endpoint="/capability/run",
    ),
    "CAP-DOC": Capability(
        id="CAP-DOC",
        name="Document Agent",
        status="SAFE_STUB",
        priority="P1",
        enabled=True,
        purpose="Príprava alebo vytvorenie dokumentu. V safe runtime režime vytvára návrh, nie zápis do Drive.",
    ),
    "CAP-KNOW": Capability(
        id="CAP-KNOW",
        name="Knowledge Evolution",
        status="ACTIVE",
        priority="P0",
        purpose="Vyhodnotenie, či sa má znalosť použiť, zlúčiť, aktualizovať alebo vytvoriť nová.",
    ),
}


def _classify_intent(message: str) -> Dict[str, Any]:
    m = (message or "").lower().strip()
    if not m:
        return {"intent": "empty", "capability_id": "CAP-002", "confidence": 0.2}

    doc_words = ["vytvor dokument", "nový dokument", "dokument", "doc", "docs", "zapíš", "ulož"]
    knowledge_words = ["knowledge", "znalosť", "reuse", "merge", "aktualizuj znalosti", "vyhodnoť"]
    status_words = ["stav", "health", "status", "funguje", "test"]

    if any(w in m for w in doc_words):
        return {"intent": "document", "capability_id": "CAP-DOC", "confidence": 0.85}
    if any(w in m for w in knowledge_words):
        return {"intent": "knowledge", "capability_id": "CAP-KNOW", "confidence": 0.8}
    if any(w in m for w in status_words):
        return {"intent": "status", "capability_id": "CAP-003", "confidence": 0.75}
    return {"intent": "general", "capability_id": "CAP-002", "confidence": 0.65}


def _knowledge_decision(message: str) -> Dict[str, Any]:
    m = (message or "").lower()
    if any(w in m for w in ["vytvor", "nový", "new"]):
        decision = "CREATE NEW"
        reason = "Požiadavka smeruje k vytvoreniu nového artefaktu."
    elif any(w in m for w in ["aktualizuj", "uprav", "merge", "zlúč"]):
        decision = "MERGE"
        reason = "Požiadavka smeruje k úprave alebo zlúčeniu existujúcej znalosti."
    elif any(w in m for w in ["čo je", "aký je", "stav", "nájdi"]):
        decision = "REUSE"
        reason = "Požiadavka smeruje k použitiu existujúcej znalosti."
    else:
        decision = "REUSE"
        reason = "Bezpečný predvolený režim: najprv použiť existujúce znalosti."
    return {
        "service": "SRV-001 Knowledge Evolution Engine",
        "decision": decision,
        "confidence": 0.8,
        "reason": reason,
        "allowed_actions": ["REUSE", "MERGE", "UPDATE", "ARCHIVE", "REMOVE", "CREATE NEW"],
    }


def _run_capability(capability_id: str, message: str, debug: bool = False) -> Dict[str, Any]:
    cap = CAPABILITIES.get(capability_id)
    if not cap:
        return {
            "status": "error",
            "error": "unknown_capability",
            "capability_id": capability_id,
            "answer": "Neznáma Capability.",
            "next_action": "Over Capability Registry.",
        }

    if not cap.enabled:
        return {
            "status": "disabled",
            "capability_id": cap.id,
            "capability_name": cap.name,
            "answer": "Capability je vypnutá.",
            "next_action": "Zapni feature flag alebo vyber inú Capability.",
        }

    kd = _knowledge_decision(message)

    if cap.id == "CAP-DOC":
        if ENABLE_DOCUMENT_AGENT:
            action = "DOCUMENT_AGENT_EXECUTION_PLACEHOLDER"
            answer = "Document Agent je povolený. V tejto verzii je pripravený bezpečný vstup na vykonanie dokumentovej úlohy."
            next_action = "Doplniť napojenie na reálny Google Docs create/update endpoint."
        else:
            action = "SAFE_DOCUMENT_PLAN"
            answer = "Pripravil som bezpečný plán dokumentovej úlohy. Reálny zápis do Google Docs je vypnutý, aby sa predišlo chybám v produkčnom requeste."
            next_action = "Ak chceš reálny zápis, nastav ENABLE_DOCUMENT_AGENT=true a nasadíme Document Agent adapter."
    elif cap.id == "CAP-KNOW":
        action = "KNOWLEDGE_DECISION"
        answer = f"Knowledge Evolution rozhodnutie: {kd['decision']}. Dôvod: {kd['reason']}"
        next_action = "Použiť rozhodnutie pri zostavení Working Context."
    elif cap.id == "CAP-003":
        action = "RUNTIME_STATUS"
        answer = "Capability Runtime je aktívny a vie klasifikovať požiadavku, vybrať Capability a bezpečne vrátiť výsledok."
        next_action = "Ďalší krok: pripojiť Document Agent adapter."
    else:
        action = "GENERAL_ASSISTANT_WORKFLOW"
        answer = "Požiadavka bola prijatá Executive Assistantom a zaradená do všeobecného workflow."
        next_action = "Potvrdiť ďalšiu akciu alebo doplniť detail zadania."

    result = {
        "status": "success",
        "capability_id": cap.id,
        "capability_name": cap.name,
        "action": action,
        "answer": answer,
        "next_action": next_action,
        "knowledge_decision": kd,
    }
    if debug:
        result["debug"] = {
            "capability": cap.model_dump(),
            "message_preview": (message or "")[:300],
            "feature_flags": {
                "ENABLE_EXECUTIVE_ASSISTANT": ENABLE_EXECUTIVE_ASSISTANT,
                "ENABLE_CAPABILITY_RUNTIME": ENABLE_CAPABILITY_RUNTIME,
                "ENABLE_KNOWLEDGE_EVOLUTION": ENABLE_KNOWLEDGE_EVOLUTION,
                "ENABLE_DOCUMENT_AGENT": ENABLE_DOCUMENT_AGENT,
                "ENABLE_DRIVE_REFRESH": ENABLE_DRIVE_REFRESH,
            },
        }
    return result


@app.head("/")
def root_head():
    return JSONResponse({"status": "ok"})


@app.get("/")
@safe_endpoint
def root():
    return {
        "service": APP_NAME,
        "status": "running",
        "message": "AI_OS Capability Runtime is online.",
        "use": [
            "/assistant/health?token=...",
            "/assistant?message=test&token=...",
            "/capability/registry?token=...",
            "/capability/run?message=test&token=...",
            "/orchestrator/ask?message=test&token=...",
        ],
        "time_utc": utc_now(),
    }


@app.get("/health")
@safe_endpoint
def global_health(request: Request):
    _check_token(request)
    return {
        "status": "ok",
        "service": APP_NAME,
        "version": VERSION,
        "capability_runtime": ENABLE_CAPABILITY_RUNTIME,
        "time_utc": utc_now(),
    }


@app.get("/assistant/health")
@safe_endpoint
def assistant_health(request: Request):
    _check_token(request)
    return {
        "status": "ok",
        "assistant": "Executive Assistant",
        "version": VERSION,
        "enabled": ENABLE_EXECUTIVE_ASSISTANT,
        "uses": ["Capability Runtime", "AI_OS Orchestrator", "SRV-001 Knowledge Evolution Engine", "Safe Runtime"],
        "rollback": "ENABLE_EXECUTIVE_ASSISTANT=false",
        "time_utc": utc_now(),
    }


@app.get("/orchestrator/health")
@safe_endpoint
def orchestrator_health(request: Request):
    _check_token(request)
    return {
        "status": "ok",
        "service": APP_NAME,
        "orchestrator": "enabled",
        "executive_assistant": "enabled" if ENABLE_EXECUTIVE_ASSISTANT else "disabled",
        "capability_runtime": "enabled" if ENABLE_CAPABILITY_RUNTIME else "disabled",
        "knowledge_evolution_engine": "enabled" if ENABLE_KNOWLEDGE_EVOLUTION else "disabled",
        "knowledge_retrieval": "safe_stub",
        "time_utc": utc_now(),
    }


@app.get("/capability/registry")
@safe_endpoint
def capability_registry(request: Request):
    _check_token(request)
    return {
        "status": "success",
        "registry": [cap.model_dump() for cap in CAPABILITIES.values()],
        "count": len(CAPABILITIES),
        "time_utc": utc_now(),
    }


@app.get("/capability/run")
@safe_endpoint
def capability_run(
    request: Request,
    message: str = Query("", description="Používateľská požiadavka"),
    capability_id: Optional[str] = Query(None),
    debug: bool = Query(False),
):
    _check_token(request)
    if not ENABLE_CAPABILITY_RUNTIME:
        return {"status": "disabled", "answer": "Capability Runtime je vypnutý."}
    selected = capability_id or _classify_intent(message)["capability_id"]
    result = _run_capability(selected, message, debug=debug)
    result["router"] = _classify_intent(message)
    return result


@app.get("/assistant")
@safe_endpoint
def assistant(
    request: Request,
    message: str = Query("", description="Správa pre Executive Assistanta"),
    debug: bool = Query(False),
):
    _check_token(request)
    if not ENABLE_EXECUTIVE_ASSISTANT:
        return {"status": "disabled", "assistant": "Executive Assistant", "answer": "Executive Assistant je vypnutý."}
    router = _classify_intent(message)
    result = _run_capability(router["capability_id"], message, debug=debug)
    return {
        "status": result.get("status", "success"),
        "assistant": "Executive Assistant",
        "version": VERSION,
        "route": router,
        "answer": result.get("answer"),
        "next_action": result.get("next_action"),
        "capability_result": result,
        "time_utc": utc_now(),
    }


@app.get("/orchestrator/ask")
@safe_endpoint
def orchestrator_ask(
    request: Request,
    message: str = Query("", description="Správa pre Orchestrator"),
    limit: int = Query(5),
    debug: bool = Query(False),
):
    _check_token(request)
    safe_limit = _safe_limit(limit)
    router = _classify_intent(message)
    result = _run_capability(router["capability_id"], message, debug=debug)
    return {
        "status": "success",
        "answer": result.get("answer"),
        "next_action": result.get("next_action"),
        "router": router,
        "limit": safe_limit,
        "capability_result": result,
        "time_utc": utc_now(),
    }


@app.get("/orchestrator/knowledge-evolution")
@safe_endpoint
def knowledge_evolution(request: Request, message: str = Query(""), limit: int = Query(5), debug: bool = Query(False)):
    _check_token(request)
    decision = _knowledge_decision(message)
    return {
        "status": "success",
        "service": "SRV-001 Knowledge Evolution Engine",
        "version": VERSION,
        "message": message,
        "limit": _safe_limit(limit),
        "knowledge_evolution": decision,
        "debug": {"safe_runtime": True} if debug else None,
        "time_utc": utc_now(),
    }


@app.get("/refresh-index")
@safe_endpoint
def refresh_index(request: Request):
    _check_token(request)
    if not ENABLE_DRIVE_REFRESH:
        return {
            "status": "success",
            "action": "REFRESH_INDEX",
            "index_status": "ready_safe_noop",
            "document_count": 0,
            "note": "Drive refresh je vypnutý v safe runtime režime. Nastav ENABLE_DRIVE_REFRESH=true až po stabilizácii.",
            "time_utc": utc_now(),
        }
    return {
        "status": "success",
        "action": "REFRESH_INDEX",
        "index_status": "refresh_requested",
        "document_count": 0,
        "note": "Placeholder pre reálny Drive refresh adapter.",
        "time_utc": utc_now(),
    }
