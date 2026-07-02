
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx
from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.responses import JSONResponse


APP_NAME = "AI_OS_ORCHESTRATOR_V1_4_4_CAP004_DOCUMENT_AGENT_ADAPTER_FINAL"
VERSION = "1.4.4-cap004-document-agent-adapter-final"

API_TOKEN = os.getenv("API_TOKEN", "").strip()

ENABLE_EXECUTIVE_ASSISTANT = os.getenv("ENABLE_EXECUTIVE_ASSISTANT", "true").lower() == "true"
ENABLE_CAPABILITY_RUNTIME = os.getenv("ENABLE_CAPABILITY_RUNTIME", "true").lower() == "true"
ENABLE_KNOWLEDGE_EVOLUTION = os.getenv("ENABLE_KNOWLEDGE_EVOLUTION", "true").lower() == "true"
ENABLE_DOCUMENT_AGENT = os.getenv("ENABLE_DOCUMENT_AGENT", "true").lower() == "true"
ENABLE_DRIVE_REFRESH = os.getenv("ENABLE_DRIVE_REFRESH", "false").lower() == "true"

# Ak nie je nastavené, adapter beží v safe_local režime.
# Ak je nastavené napr. na https://ai-os-document-agent.onrender.com, adapter volá POST /document/create.
DOCUMENT_AGENT_BASE_URL = os.getenv("DOCUMENT_AGENT_BASE_URL", "").strip().rstrip("/")
DOCUMENT_AGENT_CREATE_PATH = os.getenv("DOCUMENT_AGENT_CREATE_PATH", "/document/create").strip()
DOCUMENT_AGENT_TIMEOUT_SECONDS = float(os.getenv("DOCUMENT_AGENT_TIMEOUT_SECONDS", "20"))

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
    "CAP-004": {
        "id": "CAP-004",
        "name": "Document Agent Adapter",
        "type": "Capability Adapter",
        "status": "ACTIVE",
        "priority": "P0",
        "enabled": ENABLE_DOCUMENT_AGENT,
        "purpose": "Prepojenie Capability Runtime s Document Agentom.",
        "endpoint": "/capability/document",
    },
    "CAP-DOC": {
        "id": "CAP-DOC",
        "name": "Document Agent",
        "type": "Capability",
        "status": "ADAPTER_CONNECTED" if ENABLE_DOCUMENT_AGENT else "DISABLED",
        "priority": "P0",
        "enabled": ENABLE_DOCUMENT_AGENT,
        "purpose": "Vytváranie alebo príprava dokumentových úloh cez Document Agent Adapter.",
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
        return {"intent": "document", "capability_id": "CAP-DOC", "confidence": 0.88}
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


def _extract_document_title(message: str) -> str:
    raw = (message or "").strip()
    if not raw:
        return "AI_OS Document"

    clean = raw
    prefixes = [
        "vytvor nový dokument",
        "vytvor dokument",
        "nový dokument",
        "create document",
        "document",
    ]
    low = clean.lower()
    for p in prefixes:
        if low.startswith(p):
            clean = clean[len(p):].strip(" :-–—")
            break
    return clean[:120] if clean else "AI_OS Document"


def _default_document_content(title: str, message: str, request_id: str) -> str:
    return f"""# {title}

Status: DRAFT
Created by: AI_OS Document Agent Adapter
Request ID: {request_id}
Created at: {utc_now()}

## Zadanie

{message}

## Poznámka

Tento dokument bol pripravený cez CAP-004 Document Agent Adapter.
Ak DOCUMENT_AGENT_BASE_URL nie je nastavený, ide o safe_local režim bez fyzického zápisu do Google Docs.
"""


def _safe_local_document(title: str, content: str, request_id: str, reason: str) -> Dict[str, Any]:
    synthetic_id = f"safe-doc-{request_id[:8]}"
    return {
        "status": "success",
        "mode": "safe_local",
        "message": "Document Agent Adapter pripravil dokument v safe_local režime. Reálny Google Docs zápis nie je zapnutý.",
        "document": {
            "id": synthetic_id,
            "title": title,
            "url": None,
            "content_preview": content[:500],
            "created": False,
            "reason": reason,
        },
    }


async def _document_adapter_create_document(
    title: str,
    content: str,
    request_id: str,
) -> Dict[str, Any]:
    """
    Adapter pre Document Agent.

    Režimy:
    1. safe_local:
       Ak DOCUMENT_AGENT_BASE_URL nie je nastavené.
    2. external_document_agent:
       Ak DOCUMENT_AGENT_BASE_URL je nastavené, zavolá POST {base_url}{path}.
    """
    if not ENABLE_DOCUMENT_AGENT:
        return {
            "status": "disabled",
            "mode": "disabled",
            "message": "Document Agent Adapter je vypnutý.",
            "document": None,
        }

    if not DOCUMENT_AGENT_BASE_URL:
        return _safe_local_document(title, content, request_id, "DOCUMENT_AGENT_BASE_URL is not configured")

    url = f"{DOCUMENT_AGENT_BASE_URL}{DOCUMENT_AGENT_CREATE_PATH}"
    payload = {
        "title": title,
        "content": content,
        "request_id": request_id,
    }
    headers = {"x-api-token": API_TOKEN} if API_TOKEN else {}

    try:
        async with httpx.AsyncClient(timeout=DOCUMENT_AGENT_TIMEOUT_SECONDS, follow_redirects=True) as client:
            response = await client.post(url, json=payload, headers=headers)
    except httpx.TimeoutException:
        return {
            "status": "error",
            "mode": "external_document_agent",
            "error_type": "timeout",
            "message": "Document Agent timeout.",
            "document": None,
        }
    except Exception as e:
        return {
            "status": "error",
            "mode": "external_document_agent",
            "error_type": e.__class__.__name__,
            "message": str(e),
            "document": None,
        }

    try:
        data = response.json()
    except Exception:
        data = {"raw": response.text[:1000]}

    if response.status_code >= 400:
        return {
            "status": "error",
            "mode": "external_document_agent",
            "error_type": "document_agent_http_error",
            "http_status": response.status_code,
            "message": "Document Agent returned error.",
            "response": data,
            "document": None,
        }

    document = data.get("document") if isinstance(data, dict) else None
    return {
        "status": "success",
        "mode": "external_document_agent",
        "message": "Document Agent vykonal požiadavku.",
        "document": document or data,
        "response": data,
    }


async def _run_document_capability(message: str, request_id: str, debug: bool = False) -> Dict[str, Any]:
    title = _extract_document_title(message)
    content = _default_document_content(title, message, request_id)
    adapter_result = await _document_adapter_create_document(title, content, request_id)

    status = adapter_result.get("status", "error")
    document = adapter_result.get("document")

    if status == "success":
        if adapter_result.get("mode") == "safe_local":
            answer = "Dokumentový tok prebehol úspešne v safe_local režime. Reálny zápis do Google Docs ešte nie je zapnutý."
            next_action = "Nastav DOCUMENT_AGENT_BASE_URL alebo doplň interný Google Docs adapter."
        else:
            answer = "Dokument bol úspešne vytvorený cez Document Agent."
            next_action = "Skontrolovať document_url a zapísať výsledok do registra."
    else:
        answer = "Document Agent Adapter nedokončil vytvorenie dokumentu."
        next_action = "Skontrolovať Document Agent konfiguráciu a logy."

    result = {
        "status": status,
        "capability_id": "CAP-DOC",
        "capability_name": "Document Agent",
        "action": "CREATE_DOCUMENT",
        "answer": answer,
        "next_action": next_action,
        "document_adapter": adapter_result,
        "document": document,
        "knowledge_decision": _knowledge_decision(message),
    }

    if debug:
        result["debug"] = {
            "title": title,
            "document_agent_base_url_configured": bool(DOCUMENT_AGENT_BASE_URL),
            "document_agent_create_path": DOCUMENT_AGENT_CREATE_PATH,
            "content_preview": content[:1000],
        }

    return result


async def _run_capability(capability_id: str, message: str, request_id: str, debug: bool = False) -> Dict[str, Any]:
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

    if cap["id"] in ["CAP-DOC", "CAP-004"]:
        return await _run_document_capability(message, request_id, debug=debug)

    kd = _knowledge_decision(message)

    if cap["id"] == "CAP-KNOW":
        action = "KNOWLEDGE_DECISION"
        answer = f"Knowledge Evolution rozhodnutie: {kd['decision']}. Dôvod: {kd['reason']}"
        next_action = "Použiť rozhodnutie pri zostavení Working Context."
    elif cap["id"] == "CAP-003":
        action = "RUNTIME_STATUS"
        answer = "Capability Runtime je aktívny a vie klasifikovať požiadavku, vybrať Capability a bezpečne vrátiť výsledok."
        next_action = "Ďalší krok: pripojiť plnohodnotný Google Docs adapter."
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
                "DOCUMENT_AGENT_BASE_URL_CONFIGURED": bool(DOCUMENT_AGENT_BASE_URL),
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
        "message": "AI_OS Capability Runtime is online. CAP-004 Document Agent Adapter is available.",
        "version": VERSION,
        "use": [
            "/assistant/health?token=...",
            "/assistant?message=test&token=...",
            "/capability/registry?token=...",
            "/capability/run?message=test&token=...",
            "/capability/document?message=Vytvor%20dokument%20AI_OS%20Test&token=...",
            "/document/create [POST]",
            "/orchestrator/ask?message=test&token=...",
            "/self-test?token=...",
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
            "document_adapter": {
                "enabled": ENABLE_DOCUMENT_AGENT,
                "mode": "external_document_agent" if DOCUMENT_AGENT_BASE_URL else "safe_local",
                "base_url_configured": bool(DOCUMENT_AGENT_BASE_URL),
            },
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
            "uses": ["Capability Runtime", "AI_OS Orchestrator", "SRV-001 Knowledge Evolution Engine", "Document Agent Adapter", "Safe Runtime"],
            "document_adapter": {
                "enabled": ENABLE_DOCUMENT_AGENT,
                "mode": "external_document_agent" if DOCUMENT_AGENT_BASE_URL else "safe_local",
                "base_url_configured": bool(DOCUMENT_AGENT_BASE_URL),
                "create_path": DOCUMENT_AGENT_CREATE_PATH,
            },
            "rollback": "ENABLE_DOCUMENT_AGENT=false",
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
            "document_adapter": "enabled" if ENABLE_DOCUMENT_AGENT else "disabled",
            "document_adapter_mode": "external_document_agent" if DOCUMENT_AGENT_BASE_URL else "safe_local",
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
async def capability_run(
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
        result = await _run_capability(selected, message, request_id, debug=debug)
        result["router"] = _classify_intent(message)
        result["request_id"] = request_id
        return _safe_response(result)
    except Exception as e:
        return _safe_error(e, request_id)


@app.get("/capability/document")
async def capability_document(
    request: Request,
    message: str = Query("", description="Dokumentová požiadavka"),
    title: Optional[str] = Query(None),
    content: Optional[str] = Query(None),
    debug: bool = Query(False),
):
    request_id = str(uuid.uuid4())
    try:
        _check_token(request)
        msg = message or f"Vytvor dokument {title or 'AI_OS Document'}"
        doc_title = title or _extract_document_title(msg)
        doc_content = content or _default_document_content(doc_title, msg, request_id)
        adapter_result = await _document_adapter_create_document(doc_title, doc_content, request_id)
        return _safe_response({
            "status": adapter_result.get("status", "error"),
            "capability": "CAP-DOC",
            "adapter": "CAP-004 Document Agent Adapter",
            "action": "CREATE_DOCUMENT",
            "document": adapter_result.get("document"),
            "document_adapter": adapter_result,
            "next_action": "Ak je mode=safe_local, nastav DOCUMENT_AGENT_BASE_URL pre fyzický zápis do Google Docs.",
            "debug": {"title": doc_title, "content_preview": doc_content[:500]} if debug else None,
            "request_id": request_id,
        })
    except Exception as e:
        return _safe_error(e, request_id)


@app.post("/document/create")
async def document_create(request: Request):
    """
    Interný Document Agent endpoint.
    V tejto verzii vytvára safe_local dokumentový výsledok.
    Neskôr sa tu pripojí fyzický Google Docs zápis.
    """
    request_id = str(uuid.uuid4())
    try:
        _check_token(request)
        try:
            payload = await request.json()
            if not isinstance(payload, dict):
                payload = {}
        except Exception:
            payload = {}

        title = str(payload.get("title") or "AI_OS Document")[:120]
        content = str(payload.get("content") or _default_document_content(title, "Internal document/create request", request_id))
        source_request_id = str(payload.get("request_id") or request_id)

        result = _safe_local_document(
            title=title,
            content=content,
            request_id=source_request_id,
            reason="Internal /document/create safe_local endpoint. Google Docs adapter not yet enabled.",
        )
        return _safe_response({
            "status": result["status"],
            "service": "Internal Document Agent",
            "version": VERSION,
            "mode": result["mode"],
            "document": result["document"],
            "message": result["message"],
            "request_id": request_id,
        })
    except Exception as e:
        return _safe_error(e, request_id)


@app.get("/assistant")
async def assistant(
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
        result = await _run_capability(router["capability_id"], message, request_id, debug=debug)
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
async def orchestrator_ask(
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
        result = await _run_capability(router["capability_id"], message, request_id, debug=debug)
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


@app.get("/self-test")
async def self_test(request: Request):
    request_id = str(uuid.uuid4())
    try:
        _check_token(request)
        tests = []
        tests.append({"name": "root", "status": "PASS"})
        tests.append({"name": "capability_registry", "status": "PASS", "count": len(CAPABILITIES)})

        router = _classify_intent("Vytvor dokument AI_OS Test")
        tests.append({"name": "document_intent_router", "status": "PASS" if router["capability_id"] == "CAP-DOC" else "FAIL", "router": router})

        doc_result = await _run_document_capability("Vytvor dokument AI_OS Self Test", request_id, debug=False)
        tests.append({
            "name": "document_adapter",
            "status": "PASS" if doc_result.get("status") == "success" else "FAIL",
            "mode": doc_result.get("document_adapter", {}).get("mode"),
            "created": doc_result.get("document", {}).get("created"),
        })

        overall = "PASS" if all(t["status"] == "PASS" for t in tests) else "FAIL"
        return _safe_response({
            "status": "success",
            "self_test": overall,
            "version": VERSION,
            "tests": tests,
            "request_id": request_id,
        })
    except Exception as e:
        return _safe_error(e, request_id)
