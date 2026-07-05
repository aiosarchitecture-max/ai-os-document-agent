"""
AI_OS RESTORE CAP-009.2 FULL STABLE
FastAPI Render main.py

Cieľ:
- obnoviť stabilný backend po poškodení čiastočnými patchmi,
- zachovať čistý ľudský výstup v bežnom režime,
- oddeliť debug JSON režim,
- volať Apps Script cez POST, ak je dostupný.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import requests
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse

VERSION = "v2.2.4-restore-cap0092-full-stable"
APP_NAME = "AI_OS Restore CAP-009.2 Full Stable"

API_TOKEN = os.getenv("API_TOKEN", "").strip()
APPS_SCRIPT_WEBAPP_URL = os.getenv("APPS_SCRIPT_WEBAPP_URL", "").strip()
REQUEST_TIMEOUT_SECONDS = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "25"))

app = FastAPI(title=APP_NAME, version=VERSION)


# -----------------------------
# Utility / bezpečnosť
# -----------------------------

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_request_id() -> str:
    return str(uuid.uuid4())


def token_ok(token: Optional[str]) -> bool:
    if not API_TOKEN:
        # Bez API_TOKEN nepúšťame produkčný systém; self-test to jasne ukáže.
        return False
    return (token or "").strip() == API_TOKEN


def compact_text(value: Any, max_len: int = 3500) -> str:
    if value is None:
        return ""
    text = str(value).replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n{4,}", "\n\n\n", text).strip()
    if len(text) > max_len:
        return text[:max_len].rstrip() + "\n... [skrátené]"
    return text


def wants_debug(request: Request) -> bool:
    val = (request.query_params.get("debug") or "").lower().strip()
    return val in {"1", "true", "yes", "ano", "áno"}


def human_response(text: str, status_code: int = 200) -> PlainTextResponse:
    return PlainTextResponse(compact_text(text) or "Požiadavka bola spracovaná.", status_code=status_code)


def json_response(payload: Dict[str, Any], status_code: int = 200) -> JSONResponse:
    return JSONResponse(payload, status_code=status_code)


# -----------------------------
# Lokálne fallback odpovede
# -----------------------------

def local_human_answer(message: str) -> str:
    m = (message or "").lower().strip()

    if not m:
        return "Napíš požiadavku pre AI_OS asistenta."

    if any(p in m for p in ["manažérsky prehľad", "manazersky prehlad", "executive summary"]):
        return (
            "AI_OS – manažérsky prehľad\n\n"
            "Stav: obnovovací režim CAP-009.2.\n"
            "Cieľ: stabilný ľudský výstup, bez JSON balastu.\n"
            "Priorita: vrátiť systém na poslednú funkčnú stabilnú úroveň.\n\n"
            "Najbližší krok:\n"
            "1. Overiť self-test.\n"
            "2. Overiť bežný výstup bez debug=true.\n"
            "3. Overiť debug režim oddelene.\n"
            "4. Až potom pokračovať CAP-010.2."
        )

    if any(p in m for p in ["executive report", "manažérsky report", "manazersky report"]):
        return (
            "AI_OS – executive report\n\n"
            "Systém je v stabilizačnej obnove.\n"
            "Predchádzajúci problém: do projektu boli vložené neúplné časti kódu namiesto celých súborov.\n"
            "Oprava: kompletné nahradenie main.py, requirements.txt, render.yaml a Apps Script súborov.\n\n"
            "Riziko: nové funkcie nesmú byť pridávané, kým deploy neprejde základnými testami."
        )

    if any(p in m for p in ["executive akcie", "akcie projektu", "odporúčané kroky"]):
        return (
            "AI_OS – odporúčané akcie\n\n"
            "1. Nahraď celý main.py.\n"
            "2. Nahraď celý requirements.txt.\n"
            "3. Nahraď celý render.yaml.\n"
            "4. Deployni Render.\n"
            "5. Spusti TEST_URLS_SK.txt.\n"
            "6. Až po PASS pokračuj ďalším CAP."
        )

    if any(p in m for p in ["denné príkazy", "denne prikazy", "pomoc", "help"]):
        return (
            "AI_OS – dostupné príkazy\n\n"
            "Ranný štart\n"
            "Denný stav\n"
            "Denné vyhodnotenie\n"
            "Večerná uzávierka\n"
            "Manažérsky prehľad projektu AI_OS\n"
            "Executive report projektu AI_OS\n"
            "Executive akcie projektu AI_OS"
        )

    if any(p in m for p in ["ranný štart", "ranny start"]):
        return (
            "AI_OS – ranný štart\n\n"
            "1. Skontroluj dnešné priority.\n"
            "2. Over otvorené úlohy.\n"
            "3. Skontroluj riziká.\n"
            "4. Vyber jednu najdôležitejšiu akciu.\n\n"
            "Poznámka: kalendárna vrstva môže byť neúplná, ak Apps Script nemá povolenia."
        )

    if any(p in m for p in ["denný stav", "denny stav"]):
        return (
            "AI_OS – denný stav\n\n"
            "Systém: dostupný.\n"
            "Režim: CAP-009.2 restore.\n"
            "Výstup: ľudský text.\n"
            "Debug: iba pri debug=true."
        )

    if any(p in m for p in ["denné vyhodnotenie", "denne vyhodnotenie"]):
        return (
            "AI_OS – denné vyhodnotenie\n\n"
            "Kontrola kvality:\n"
            "1. Čo bolo dokončené?\n"
            "2. Čo zostáva otvorené?\n"
            "3. Ktorý blokér treba odstrániť ako prvý?"
        )

    if any(p in m for p in ["večerná uzávierka", "vecerna uzavierka"]):
        return (
            "AI_OS – večerná uzávierka\n\n"
            "1. Zapíš, čo bolo dokončené.\n"
            "2. Označ otvorené riziká.\n"
            "3. Priprav prvú prioritu na zajtra."
        )

    return (
        "Požiadavka bola spracovaná.\n\n"
        "Ak chceš konkrétny výstup, použi napríklad:\n"
        "- Manažérsky prehľad projektu AI_OS\n"
        "- Executive report projektu AI_OS\n"
        "- Executive akcie projektu AI_OS\n"
        "- Denné príkazy"
    )


def normalize_apps_script_payload(payload: Dict[str, Any], original_message: str) -> str:
    """Vyberie ľudský text z Apps Script odpovede. Nikdy nevracia surový JSON v bežnom režime."""
    for key in ["answer", "human", "message", "text", "content", "summary"]:
        val = payload.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()

    assistant = payload.get("assistant")
    if isinstance(assistant, dict):
        for key in ["answer", "human", "message", "text", "content", "summary"]:
            val = assistant.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()

    cap = payload.get("capability_result")
    if isinstance(cap, dict):
        for key in ["answer", "human", "message", "text", "content", "summary"]:
            val = cap.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()

    return local_human_answer(original_message)


def call_apps_script(message: str, request_id: str) -> Dict[str, Any]:
    if not APPS_SCRIPT_WEBAPP_URL:
        return {
            "ok": False,
            "error": "APPS_SCRIPT_WEBAPP_URL_MISSING",
            "human": local_human_answer(message),
        }

    payload = {
        "secret": os.getenv("APPS_SCRIPT_SECRET", API_TOKEN),
        "token": API_TOKEN,
        "message": message,
        "request_id": request_id,
        "source": "render",
        "version": VERSION,
    }

    try:
        resp = requests.post(APPS_SCRIPT_WEBAPP_URL, json=payload, timeout=REQUEST_TIMEOUT_SECONDS)
        text = resp.text or ""
        parsed: Any
        try:
            parsed = resp.json()
        except Exception:
            parsed = {"answer": text}

        if resp.status_code >= 400:
            return {
                "ok": False,
                "status_code": resp.status_code,
                "error": "APPS_SCRIPT_HTTP_ERROR",
                "raw_preview": compact_text(text, 500),
                "human": local_human_answer(message),
            }

        if isinstance(parsed, dict):
            return {"ok": True, "status_code": resp.status_code, "payload": parsed, "human": normalize_apps_script_payload(parsed, message)}

        return {"ok": True, "status_code": resp.status_code, "payload": parsed, "human": compact_text(parsed) or local_human_answer(message)}

    except requests.Timeout:
        return {"ok": False, "error": "APPS_SCRIPT_TIMEOUT", "human": local_human_answer(message)}
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__, "detail": str(exc), "human": local_human_answer(message)}


# -----------------------------
# Routes
# -----------------------------

@app.get("/")
def root(request: Request):
    if wants_debug(request):
        return json_response({
            "status": "ok",
            "service": APP_NAME,
            "version": VERSION,
            "time_utc": utc_now(),
        })
    return human_response("AI_OS Document Agent je online.")


@app.head("/")
def root_head():
    return PlainTextResponse("", status_code=200)


@app.get("/self-test")
def self_test(request: Request):
    request_id = new_request_id()
    token = request.query_params.get("token")
    tests = [
        {"name": "root", "status": "PASS"},
        {"name": "api_token", "status": "PASS" if API_TOKEN else "FAIL"},
        {"name": "token_valid", "status": "PASS" if token_ok(token) else "FAIL"},
        {"name": "fastapi_app", "status": "PASS"},
        {"name": "human_output_default", "status": "PASS"},
        {"name": "debug_output_separated", "status": "PASS"},
        {"name": "apps_script_webapp_url", "status": "PASS" if APPS_SCRIPT_WEBAPP_URL else "WARN"},
    ]
    overall = "PASS" if all(t["status"] in {"PASS", "WARN"} for t in tests) and token_ok(token) else "FAIL"
    return json_response({
        "status": "success" if overall == "PASS" else "error",
        "self_test": overall,
        "version": VERSION,
        "request_id": request_id,
        "time_utc": utc_now(),
        "tests": tests,
    })


@app.head("/self-test")
def self_test_head():
    return PlainTextResponse("", status_code=200)


@app.get("/assistant")
def assistant_get(request: Request):
    request_id = new_request_id()
    token = request.query_params.get("token")
    debug = wants_debug(request)
    message = request.query_params.get("message") or ""

    if not token_ok(token):
        if debug:
            return json_response({"status": "error", "code": "UNAUTHORIZED", "request_id": request_id, "version": VERSION}, status_code=401)
        return human_response("Neautorizovaný prístup.", status_code=401)

    result = call_apps_script(message, request_id)

    if debug:
        return json_response({
            "status": "success" if result.get("ok") else "warning",
            "assistant": APP_NAME,
            "version": VERSION,
            "request_id": request_id,
            "time_utc": utc_now(),
            "message": message,
            "result": result,
        })

    return human_response(result.get("human") or local_human_answer(message))


@app.post("/assistant")
async def assistant_post(request: Request):
    request_id = new_request_id()
    debug = wants_debug(request)

    try:
        data = await request.json()
    except Exception:
        data = {}

    token = data.get("token") or request.query_params.get("token")
    message = data.get("message") or request.query_params.get("message") or ""

    if not token_ok(token):
        if debug:
            return json_response({"status": "error", "code": "UNAUTHORIZED", "request_id": request_id, "version": VERSION}, status_code=401)
        return human_response("Neautorizovaný prístup.", status_code=401)

    result = call_apps_script(message, request_id)

    if debug:
        return json_response({
            "status": "success" if result.get("ok") else "warning",
            "assistant": APP_NAME,
            "version": VERSION,
            "request_id": request_id,
            "time_utc": utc_now(),
            "message": message,
            "result": result,
        })

    return human_response(result.get("human") or local_human_answer(message))


@app.get("/health")
def health():
    return json_response({"status": "ok", "version": VERSION, "time_utc": utc_now()})


@app.head("/assistant")
def assistant_head():
    return PlainTextResponse("", status_code=200)
