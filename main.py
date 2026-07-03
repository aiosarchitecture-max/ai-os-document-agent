import os
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import requests
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

APP_NAME = "AI_OS_ORCHESTRATOR_V1_4_7_1_APPS_SCRIPT_POST_FIX"
VERSION = "1.4.7.1-apps-script-post-fix"

API_TOKEN = os.getenv("API_TOKEN", "").strip()
AI_OS_ROOT_FOLDER_ID = os.getenv("AI_OS_ROOT_FOLDER_ID", "").strip()
APPS_SCRIPT_WEBAPP_URL = os.getenv("APPS_SCRIPT_WEBAPP_URL", "").strip()
APPS_SCRIPT_SECRET = os.getenv("APPS_SCRIPT_SECRET", "").strip()
REQUEST_TIMEOUT_SECONDS = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "30"))

app = FastAPI(title=APP_NAME, version=VERSION)


class DocumentCreateRequest(BaseModel):
    title: str = "AI_OS Document"
    content: str = ""
    folder_id: Optional[str] = None
    debug: bool = False


class AssistantRequest(BaseModel):
    message: str
    debug: bool = False


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def rid() -> str:
    return str(uuid.uuid4())


def ok(data: Dict[str, Any]) -> Dict[str, Any]:
    base = {"status": "success", "version": VERSION, "request_id": rid(), "time_utc": now_utc()}
    base.update(data)
    return base


def err(code: str, detail: str, **extra: Any) -> Dict[str, Any]:
    data = {"status": "error", "version": VERSION, "code": code, "detail": detail, "request_id": rid(), "time_utc": now_utc()}
    data.update(extra)
    return data


def check_token(request: Request) -> None:
    if not API_TOKEN:
        raise HTTPException(status_code=500, detail="API_TOKEN is not configured on Render.")
    token = request.query_params.get("token") or request.headers.get("x-api-token") or ""
    if token.strip() != API_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")


def config_status() -> Dict[str, Any]:
    return {
        "api_token_configured": bool(API_TOKEN),
        "root_folder_id_configured": bool(AI_OS_ROOT_FOLDER_ID),
        "apps_script_webapp_url_configured": bool(APPS_SCRIPT_WEBAPP_URL),
        "apps_script_secret_configured": bool(APPS_SCRIPT_SECRET),
        "write_mode": "APPS_SCRIPT_OWNER_CONTEXT",
    }


def safe_json_from_text(text: str) -> Optional[Dict[str, Any]]:
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {"status": "success", "data": data}
    except Exception:
        return None


def call_apps_script(title: str, content: str, folder_id: Optional[str], debug: bool = False) -> Dict[str, Any]:
    if not APPS_SCRIPT_WEBAPP_URL:
        return err("APPS_SCRIPT_WEBAPP_URL_MISSING", "Render variable APPS_SCRIPT_WEBAPP_URL is missing.")
    if not APPS_SCRIPT_SECRET:
        return err("APPS_SCRIPT_SECRET_MISSING", "Render variable APPS_SCRIPT_SECRET is missing.")
    target_folder_id = (folder_id or AI_OS_ROOT_FOLDER_ID).strip()
    if not target_folder_id:
        return err("AI_OS_ROOT_FOLDER_ID_MISSING", "Render variable AI_OS_ROOT_FOLDER_ID is missing.")

    payload = {
        "secret": APPS_SCRIPT_SECRET,
        "action": "CREATE_DOC",
        "title": title[:120],
        "content": content or "",
        "folder_id": target_folder_id,
        "request_id": rid(),
    }

    try:
        response = requests.post(
            APPS_SCRIPT_WEBAPP_URL,
            json=payload,
            headers={"Accept": "application/json"},
            timeout=REQUEST_TIMEOUT_SECONDS,
            allow_redirects=True,
        )
    except requests.Timeout:
        return err("APPS_SCRIPT_TIMEOUT", f"Apps Script did not answer within {REQUEST_TIMEOUT_SECONDS} seconds.")
    except Exception as exc:
        return err("APPS_SCRIPT_REQUEST_FAILED", str(exc)[:1000])

    raw = response.text or ""
    parsed = None
    try:
        parsed = response.json()
    except Exception:
        parsed = safe_json_from_text(raw.strip())

    debug_block = {
        "http_status": response.status_code,
        "content_type": response.headers.get("Content-Type", ""),
        "final_url_prefix": response.url[:120],
        "raw_prefix": raw[:1200],
    }

    print("===== APPS SCRIPT DEBUG =====")
    print("STATUS:", response.status_code)
    print("CONTENT-TYPE:", response.headers.get("Content-Type"))
    print("FINAL URL:", response.url[:300])
    print("BODY:")
    print(raw[:3000])
    print("=============================")

    if response.status_code >= 400:
        return err("APPS_SCRIPT_HTTP_ERROR", "Apps Script returned HTTP error.", apps_script_debug=debug_block)

    if not isinstance(parsed, dict):
        return err(
            "NON_JSON_APPS_SCRIPT_RESPONSE",
            "Apps Script returned non-JSON response. This usually means Google login/consent HTML or wrong Web App URL.",
            apps_script_debug=debug_block,
        )

    if parsed.get("status") != "success":
        result = err("APPS_SCRIPT_ERROR", "Apps Script returned error status.", apps_script_response=parsed)
        if debug:
            result["apps_script_debug"] = debug_block
        return result

    result = {"status": "success", "apps_script_response": parsed}
    if debug:
        result["apps_script_debug"] = debug_block
    return result


def classify_intent(message: str) -> Dict[str, Any]:
    text = (message or "").lower()
    if any(word in text for word in ["vytvor", "create", "dokument", "document", "zapíš", "zapis"]):
        return {"intent": "document", "capability_id": "CAP-004.3", "confidence": 0.90, "decision": "CREATE NEW"}
    return {"intent": "status", "capability_id": "CAP-003", "confidence": 0.75, "decision": "REUSE"}


def document_content_from_message(message: str) -> str:
    return (
        "AI_OS DOCUMENT\n"
        f"Created by: {APP_NAME}\n"
        f"Created UTC: {now_utc()}\n"
        "\n"
        "User request:\n"
        f"{message}\n"
    )


@app.head("/")
def root_head():
    return JSONResponse(status_code=200, content={})


@app.get("/")
def root_get():
    return ok({
        "service": APP_NAME,
        "message": "AI_OS runtime is online. Apps Script physical write adapter is enabled.",
        "config": config_status(),
        "use": [
            "/self-test?token=...",
            "/debug/config?token=...",
            "/assistant?token=...&debug=true&message=Vytvor%20dokument%20AI_OS%20Test",
            "/document/create?token=...&title=Test&content=Hello",
        ],
    })


@app.get("/debug/config")
def debug_config(request: Request):
    check_token(request)
    return ok({"config": config_status()})


@app.get("/self-test")
def self_test(request: Request):
    check_token(request)
    tests = [
        {"name": "root", "status": "PASS"},
        {"name": "api_token", "status": "PASS" if API_TOKEN else "FAIL"},
        {"name": "root_folder_id", "status": "PASS" if AI_OS_ROOT_FOLDER_ID else "FAIL"},
        {"name": "apps_script_webapp_url", "status": "PASS" if APPS_SCRIPT_WEBAPP_URL else "FAIL"},
        {"name": "apps_script_secret", "status": "PASS" if APPS_SCRIPT_SECRET else "FAIL"},
        {"name": "router_document", "status": "PASS" if classify_intent("Vytvor dokument")["intent"] == "document" else "FAIL"},
    ]
    overall = "PASS" if all(t["status"] == "PASS" for t in tests) else "FAIL"
    return ok({"self_test": overall, "tests": tests})


@app.get("/assistant/health")
def assistant_health(request: Request):
    check_token(request)
    return ok({"assistant": "Executive Assistant", "enabled": True, "uses": ["CAP-003", "CAP-004.3"]})


@app.get("/orchestrator/health")
def orchestrator_health(request: Request):
    check_token(request)
    return ok({"orchestrator": "enabled", "capability_runtime": "enabled", "document_adapter": "enabled"})


@app.get("/capability/registry")
def capability_registry(request: Request):
    check_token(request)
    return ok({
        "registry": [
            {"id": "CAP-003", "name": "Capability Runtime", "status": "ACTIVE", "purpose": "Classify requests and choose safe capability."},
            {"id": "CAP-004.3", "name": "Apps Script Physical Write", "status": "ACTIVE", "purpose": "Create Google Docs through Apps Script owner context."},
        ]
    })


@app.get("/capability/run")
def capability_run(request: Request, message: str = "test"):
    check_token(request)
    route = classify_intent(message)
    return ok({"capability_result": route, "next_action": "Use /assistant for normal execution."})


@app.get("/orchestrator/ask")
def orchestrator_ask(request: Request, message: str = "test", limit: int = 5, debug: bool = False):
    check_token(request)
    route = classify_intent(message)
    return ok({
        "answer": "Požiadavka bola prijatá orchestrace vrstvou.",
        "route": route,
        "limit": limit,
        "next_action": "Použi /assistant na vykonanie akcie." if route["intent"] == "document" else "Zadaj konkrétnu požiadavku.",
    })


@app.get("/orchestrator/knowledge-evolution")
def knowledge_evolution(request: Request, message: str = ""):
    check_token(request)
    route = classify_intent(message)
    return ok({"service": "SRV-001 Knowledge Evolution Engine", "message": message, "decision": route["decision"], "allowed_actions": ["REUSE", "MERGE", "UPDATE", "ARCHIVE", "REMOVE", "CREATE NEW"]})


@app.get("/assistant")
def assistant_get(request: Request, message: str = "", debug: bool = False):
    check_token(request)
    route = classify_intent(message)
    if route["intent"] != "document":
        return ok({
            "assistant": "Executive Assistant",
            "route": route,
            "answer": "Runtime je aktívny. Na vytvorenie dokumentu použi požiadavku typu: Vytvor dokument ...",
            "next_action": "Zadaj požiadavku na dokument.",
        })

    title = "AI_OS Test" if "test" in message.lower() else "AI_OS Document"
    write_result = call_apps_script(title=title, content=document_content_from_message(message), folder_id=None, debug=debug)
    if write_result.get("status") == "success":
        return ok({
            "assistant": "Executive Assistant",
            "route": route,
            "answer": "Dokument bol fyzicky vytvorený cez Apps Script.",
            "document": write_result.get("apps_script_response", {}).get("document"),
            "write_result": write_result if debug else {"status": "success"},
        })
    return ok({
        "assistant": "Executive Assistant",
        "route": route,
        "answer": "Dokument sa nepodarilo vytvoriť. Pozri write_result.",
        "write_result": write_result,
    })


@app.post("/assistant")
async def assistant_post(request: Request, payload: AssistantRequest):
    check_token(request)
    return assistant_get(request=request, message=payload.message, debug=payload.debug)


@app.get("/document/create")
def document_create_get(request: Request, title: str = "AI_OS Document", content: str = "", folder_id: Optional[str] = None, debug: bool = False):
    check_token(request)
    result = call_apps_script(title=title, content=content, folder_id=folder_id, debug=debug)
    return ok({"document_create": result})


@app.post("/document/create")
async def document_create_post(request: Request, payload: DocumentCreateRequest):
    check_token(request)
    result = call_apps_script(title=payload.title, content=payload.content, folder_id=payload.folder_id, debug=payload.debug)
    return ok({"document_create": result})


@app.get("/refresh-index")
def refresh_index(request: Request):
    check_token(request)
    return ok({"action": "REFRESH_INDEX", "index_status": "safe_stub", "document_count": 0, "note": "Drive index refresh is disabled in this package. Physical write uses Apps Script."})
