
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.responses import JSONResponse


APP_NAME = "AI_OS_ORCHESTRATOR_V1_4_3_1_ROOT_ENDPOINT_FIX"
VERSION = "1.4.3.1-root-endpoint-fix"

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
    if not API_TOKEN:
        raise HTTPException(status_code=503, detail="API_TOKEN is not configured")

    header_token = request.headers.get("x-api-token", "").strip()
    query_token = request.query_params.get("token", "").strip()
    auth = request.headers.get("authorization", "").strip()
    bearer_token = auth.replace("Bearer ", "", 1).strip() if auth.lower().startswith("bearer ") else ""

    supplied = header_token or query_token or bearer_token
    if supplied != API_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")


def _safe_limit(limit: Optional[int], default: int = 5, min_value: int = 1, max_value: int = 20) -> int:
    try:
        value = int(limit if limit is not None else default)
    except Exception:
        value = default
    return max(min_value, min(value, max_value))


def _safe_response(payload: Dict[str, Any], status_code: int = 200) -> JSONResponse:
    payload.setdefault("time_utc", utc_now())
    return JSONResponse(status_code=status_code, content=payload)


def _safe_error(e: Exception, request_id: Optional[str] = None) -> JSONResponse:
    if isinstance(e, HTTPException):
        return _safe_response(
            {
                "status": "error",
                "error_type": "http",
                "detail": e.detail,
                "request_id": request_id or str(uuid.uuid4()),
            },
            status_code=e.status_code,
        )
    return _safe_response(
        {
            "status": "safe_error",
            "error_type": e.__class__.__name__,
            "detail": str(e),
            "request_id": request_id or str(uuid.uuid4()),
        },
        status_code=200,
    )


CAPABILITIES: Dict[str, Dict[str, Any]] = {
    "CAP-001": {
        "id": "CAP-001",
        "name": "Working Context",
        "type": "Capability",
        "status": "ACTIVE",
        "priority": "P0",
        "enabled": True,
        "purpose": "Zostavenie pracovného kontextu z dostupných znalostí.",
    },
    "CAP-002": {
        "id": "CAP-002",
        "name": "Executive Assistant",
        "type": "Capability",
        "status": "ACTIVE",
        "priority": "P0",
        "enabled": ENABLE_EXECUTIVE_ASSISTANT,
        "purpose": "Jednotný konverzačný vstup používateľa do AI_OS.",
        "endpoint": "/assistant",
    },
    "CAP-003": {
        "id": "CAP-003",
        "name": "Capability Runtime",
        "type": "Capability",
        "status": "ACTIVE",
        "priority": "P0",
        "enabled": ENABLE_CAPABILITY_RUNTIME,
        "purpose": "Výber, spustenie a bezpečné vykonanie Capability.",
        "endpoint": "/capability/run",
    },
    "CAP-DOC": {
        "id": "CAP-DOC",
        "name": "Document Agent",
        "type": "Capability",
        "status": "SAFE_STUB",
        "priority": "P1",
        "enabled": True,
        "purpose": "Príprava dokumentovej úlohy. Reálny zápis do Drive je vypnutý, kým sa nepripojí adapter.",
    },
    "CAP-KNOW": {
        "id": "CAP-KNOW",
        "name": "Knowledge Evolution",
        "type": "Shared Service Consumer",
        "status": "ACTIVE",
        "priority": "P0",
        "enabled": ENABLE_KNOWLEDGE_EVOLUTION,
        "purpose": "Vyhodnotenie, či sa znalosť použije, zlúči, aktualizuje alebo vytvorí nová.",
    },
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
        return {
            "service": "SRV-001 Knowledge Evolution Engine",
            "decision": "CREATE NEW",
            "confidence": 0.8,
            "reason": "Požiadavka smeruje k vytvoreniu nového artefaktu.",
            "allowed_actions": ["REUSE", "MERGE", "UPDATE", "ARCHIVE", "REMOVE", "CREATE NEW"],
        }
    if any(w in m for w in ["aktualizuj", "uprav", "merge", "zlúč"]):
        return {
            "service": "SRV-001 Knowledge Evolution Engine",
            "decision": "MERGE",
            "confidence": 0.8,
            "reason": "Požiadavka smeruje k úprave alebo zlúčeniu existujúcej znalosti.",
            "allowed_actions": ["REUSE", "MERGE", "UPDATE", "ARCHIVE", "REMOVE", "CREATE NEW"],
        }
    return {
        "service": "SRV-001 Knowledge Evolution Engine",
        "decision": "REUSE",
        "confidence": 0.75,
        "reason": "Bezpečný predvolený režim: najprv použiť existujúce znalosti.",
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

    if not cap.get("enabled", True):
        return {
            "status": "disabled",
            "capability_id": cap["id"],
            "capability_name": cap["name"],
            "answer": "Capability je vypnutá.",
            "next_action": "Zapni feature flag alebo vyber inú Capability.",
        }

    kd = _knowledge_decision(message)

    if cap["id"] == "CAP-DOC":
        if ENABLE_DOCUMENT_AGENT:
            action = "DOCUMENT_AGENT_EXECUTION_PLACEHOLDER"
            answer = "Document Agent je povolený. V tejto verzii je pripravený bezpečný vstup na vykonanie dokumentovej úlohy."
            next_action = "Doplniť napojenie na reálny Google Docs create/update endpoint."
        else:
            action = "SAFE_DOCUMENT_PLAN"
            answer = "Pripravil som bezpečný plán dokumentovej úlohy. Reálny zápis do Google Docs je vypnutý, aby sa predišlo chybám v produkčnom requeste."
            next_action = "Ak chceš reálny zápis, nastav ENABLE_DOCUMENT_AGENT=true a nasadíme Document Agent adapter."
    elif cap["id"] == "CAP-KNOW":
        action = "KNOWLEDGE_DECISION"
        answer = f"Knowledge Evolution rozhodnutie: {kd['decision']}. Dôvod: {kd['reason']}"
        next_action = "Použiť rozhodnutie pri zostavení Working Context."
    elif cap["id"] == "CAP-003":
        action = "RUNTIME_STATUS"
        answer = "Capability Runtime je aktívny a vie klasifikovať požiadavku, vybrať Capability a bezpečne vrátiť výsledok."
        next_action = "Ďalší krok: pripojiť Document Agent adapter."
    else:
        action = "GENERAL_ASSISTANT_WORKFLOW"
        answer = "Požiadavka bola prijatá Executive Assistantom a zaradená do všeobecného workflow."
        next_action = "Potvrdiť ďalšiu akciu alebo doplniť detail zadania."

    result = {
        "status": "success",
        "capability_id": cap["id"],
        "capability_name": cap["name"],
        "action": action,
        "answer": answer,
        "next_action": next_action,
        "knowledge_decision": kd,
    }
    if debug:
        result["debug"] = {
            "capability": cap,
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
    return JSONResponse(status_code=200, content={})


@app.get("/")
def root():
    return _safe_response({
        "service": APP_NAME,
        "status": "running",
        "message": "AI_OS Capability Runtime is online. Root endpoint fixed.",
        "version": VERSION,
        "use": [
            "/assistant/health?token=...",
            "/assistant?message=test&token=...",
            "/capability/registry?token=...",
            "/capability/run?message=test&token=...",
            "/orchestrator/ask?message=test&token=...",
        ],
    })


@app.get("/health")
def global_health(request: Request):
    request_id = str(uuid.uuid4())
    try:
        _check_token(request)
        return _safe_response({
            "status": "ok",
            "service": APP_NAME,
            "version": VERSION,
            "capability_runtime": ENABLE_CAPABILITY_RUNTIME,
            "request_id": request_id,
        })
    except Exception as e:
        return _safe_error(e, request_id)


@app.get("/assistant/health")
def assistant_health(request: Request):
    request_id = str(uuid.uuid4())
    try:
        _check_token(request)
        return _safe_response({
            "status": "ok",
            "assistant": "Executive Assistant",
            "version": VERSION,
            "enabled": ENABLE_EXECUTIVE_ASSISTANT,
            "uses": ["Capability Runtime", "AI_OS Orchestrator", "SRV-001 Knowledge Evolution Engine", "Safe Runtime"],
            "rollback": "ENABLE_EXECUTIVE_ASSISTANT=false",
            "request_id": request_id,
        })
    except Exception as e:
        return _safe_error(e, request_id)


@app.get("/orchestrator/health")
def orchestrator_health(request: Request):
    request_id = str(uuid.uuid4())
    try:
        _check_token(request)
        return _safe_response({
            "status": "ok",
            "service": APP_NAME,
            "orchestrator": "enabled",
            "executive_assistant": "enabled" if ENABLE_EXECUTIVE_ASSISTANT else "disabled",
            "capability_runtime": "enabled" if ENABLE_CAPABILITY_RUNTIME else "disabled",
            "knowledge_evolution_engine": "enabled" if ENABLE_KNOWLEDGE_EVOLUTION else "disabled",
            "knowledge_retrieval": "safe_stub",
            "request_id": request_id,
        })
    except Exception as e:
        return _safe_error(e, request_id)


@app.get("/capability/registry")
def capability_registry(request: Request):
    request_id = str(uuid.uuid4())
    try:
        _check_token(request)
        return _safe_response({
            "status": "success",
            "registry": list(CAPABILITIES.values()),
            "count": len(CAPABILITIES),
            "request_id": request_id,
        })
    except Exception as e:
        return _safe_error(e, request_id)


@app.get("/capability/run")
def capability_run(
    request: Request,
    message: str = Query("", description="Používateľská požiadavka"),
    capability_id: Optional[str] = Query(None),
    debug: bool = Query(False),
):
    request_id = str(uuid.uuid4())
    try:
        _check_token(request)
        if not ENABLE_CAPABILITY_RUNTIME:
            return _safe_response({"status": "disabled", "answer": "Capability Runtime je vypnutý.", "request_id": request_id})
        selected = capability_id or _classify_intent(message)["capability_id"]
        result = _run_capability(selected, message, debug=debug)
        result["router"] = _classify_intent(message)
        result["request_id"] = request_id
        return _safe_response(result)
    except Exception as e:
        return _safe_error(e, request_id)


@app.get("/assistant")
def assistant(
    request: Request,
    message: str = Query("", description="Správa pre Executive Assistanta"),
    debug: bool = Query(False),
):
    request_id = str(uuid.uuid4())
    try:
        _check_token(request)
        if not ENABLE_EXECUTIVE_ASSISTANT:
            return _safe_response({"status": "disabled", "assistant": "Executive Assistant", "answer": "Executive Assistant je vypnutý.", "request_id": request_id})
        router = _classify_intent(message)
        result = _run_capability(router["capability_id"], message, debug=debug)
        return _safe_response({
            "status": result.get("status", "success"),
            "assistant": "Executive Assistant",
            "version": VERSION,
            "route": router,
            "answer": result.get("answer"),
            "next_action": result.get("next_action"),
            "capability_result": result,
            "request_id": request_id,
        })
    except Exception as e:
        return _safe_error(e, request_id)


@app.get("/orchestrator/ask")
def orchestrator_ask(
    request: Request,
    message: str = Query("", description="Správa pre Orchestrator"),
    limit: int = Query(5),
    debug: bool = Query(False),
):
    request_id = str(uuid.uuid4())
    try:
        _check_token(request)
        safe_limit = _safe_limit(limit)
        router = _classify_intent(message)
        result = _run_capability(router["capability_id"], message, debug=debug)
        return _safe_response({
            "status": "success",
            "answer": result.get("answer"),
            "next_action": result.get("next_action"),
            "router": router,
            "limit": safe_limit,
            "capability_result": result,
            "request_id": request_id,
        })
    except Exception as e:
        return _safe_error(e, request_id)


@app.get("/orchestrator/knowledge-evolution")
def knowledge_evolution(request: Request, message: str = Query(""), limit: int = Query(5), debug: bool = Query(False)):
    request_id = str(uuid.uuid4())
    try:
        _check_token(request)
        return _safe_response({
            "status": "success",
            "service": "SRV-001 Knowledge Evolution Engine",
            "version": VERSION,
            "message": message,
            "limit": _safe_limit(limit),
            "knowledge_evolution": _knowledge_decision(message),
            "debug": {"safe_runtime": True} if debug else None,
            "request_id": request_id,
        })
    except Exception as e:
        return _safe_error(e, request_id)


@app.get("/refresh-index")
def refresh_index(request: Request):
    request_id = str(uuid.uuid4())
    try:
        _check_token(request)
        if not ENABLE_DRIVE_REFRESH:
            return _safe_response({
                "status": "success",
                "action": "REFRESH_INDEX",
                "index_status": "ready_safe_noop",
                "document_count": 0,
                "note": "Drive refresh je vypnutý v safe runtime režime. Nastav ENABLE_DRIVE_REFRESH=true až po stabilizácii.",
                "request_id": request_id,
            })
        return _safe_response({
            "status": "success",
            "action": "REFRESH_INDEX",
            "index_status": "refresh_requested",
            "document_count": 0,
            "note": "Placeholder pre reálny Drive refresh adapter.",
            "request_id": request_id,
        })
    except Exception as e:
        return _safe_error(e, request_id)
