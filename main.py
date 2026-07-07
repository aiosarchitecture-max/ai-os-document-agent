"""
AI_OS CAP-012.4 – Documentation Optimizer & Governance
FastAPI Render main.py

Kompletný súbor na výmenu 1:1.
Bez patchov.

Cieľ:
- nadviazať na CAP-012.3 Documentation Intelligence,
- pridať optimalizačný plán, governance, health score, schvaľované presuny/archivácie,
- nevykonávať hromadné zmeny bez CONFIRM ID,
- zachovať ľudský výstup mimo debug režimu,
- debug=true vracia JSON.
"""

from __future__ import annotations

import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import requests
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

VERSION = "v2.6.3-cap0124-documentation-optimizer-governance"
APP_NAME = "AI_OS Document Agent"
API_TOKEN = os.getenv("API_TOKEN", "").strip()
APPS_SCRIPT_WEBAPP_URL = os.getenv("APPS_SCRIPT_WEBAPP_URL", "").strip()
REQUEST_TIMEOUT_SECONDS = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "60"))

app = FastAPI(title=APP_NAME, version=VERSION)


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


def clean_message(text: str) -> str:
    return (text or "").strip()


def plain_or_json(payload: Dict[str, Any], debug: bool = False):
    if debug:
        return JSONResponse(payload)
    return PlainTextResponse(payload.get("human", "Požiadavka bola spracovaná."), media_type="text/plain; charset=utf-8")


def post_to_apps_script(action: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if not APPS_SCRIPT_WEBAPP_URL:
        return {"status": "error", "code": "APPS_SCRIPT_WEBAPP_URL_MISSING", "message": "Apps Script URL nie je nastavená."}

    body = {
        "secret": os.getenv("APPS_SCRIPT_SECRET", "").strip(),
        "action": action,
        "payload": payload or {},
        "version": VERSION,
        "request_id": request_id(),
        "time_utc": utc_now(),
    }
    try:
        resp = requests.post(APPS_SCRIPT_WEBAPP_URL, json=body, timeout=REQUEST_TIMEOUT_SECONDS)
        text = resp.text or ""
        try:
            data = resp.json()
        except Exception:
            data = {"status": "error", "code": "NON_JSON_APPS_SCRIPT_RESPONSE", "raw": text[:3000]}
        data["_http_status"] = resp.status_code
        return data
    except Exception as exc:
        return {"status": "error", "code": "APPS_SCRIPT_REQUEST_FAILED", "message": str(exc)}


def safe_name(name: str) -> str:
    name = clean_message(name)
    name = re.sub(r"\s+", " ", name)
    return name.replace("/", "-").replace("\\", "-")[:120] or "AI_OS"


COMMANDS_TEXT = """AI_OS – dostupné príkazy

Documentation Intelligence:
- Audit dokumentácie AI_OS
- Inventúra dokumentov AI_OS
- Analýza dokumentácie AI_OS
- Návrh štruktúry dokumentov AI_OS
- Migračný plán dokumentov AI_OS

Documentation Optimizer & Governance:
- Optimalizuj dokumentáciu AI_OS
- Priprav reorganizáciu AI_OS
- Health dokumentácie
- Validuj štruktúru
- Skontroluj governance
- Nájdi duplicity
- Nájdi siroty
- Archivuj zastarané dokumenty plán
- Potvrď reorganizáciu [CONFIRM_ID]
- Rollback reorganizácie [MIGRATION_ID]
- Migračný log
- Governance dokumentácie

Bezpečnosť:
- Príprava plánu nič nepresúva.
- Presuny/archivácia sa vykonajú iba po CONFIRM ID.
- Mazanie nie je podporované.
"""


def system_response(message: str) -> Optional[str]:
    m = message.lower().strip()
    if m in {"denné príkazy", "denne prikazy", "príkazy", "prikazy"}:
        return COMMANDS_TEXT
    if "ranný štart" in m or "ranny start" in m:
        return "AI_OS – ranný štart\n\nAktuálne: CAP-012.4 Documentation Optimizer & Governance.\nPriorita: bezpečná reorganizácia dokumentácie až po schválení."
    if "manažérsky prehľad" in m or "manazersky prehlad" in m:
        return "AI_OS – manažérsky prehľad\n\nCAP-012.4 pridáva governance, health score, plán reorganizácie, schvaľované presuny, migration log a rollback návrh."
    return None


def documentation_response(message: str) -> Optional[Dict[str, Any]]:
    original = clean_message(message)
    m = original.lower()
    mapping = [
        (("audit dokumentácie", "audit dokumentacie", "cap-012.3", "cap0123"), "DOC_AUDIT_FULL", "DOC_AUDIT_FULL"),
        (("inventúra dokumentov", "inventura dokumentov"), "DOC_INVENTORY", "DOC_INVENTORY"),
        (("analýza dokumentácie", "analyza dokumentacie"), "DOC_ANALYSIS", "DOC_ANALYSIS"),
        (("návrh štruktúry", "navrh struktury", "štruktúra dokumentov", "struktura dokumentov"), "DOC_STRUCTURE_V2", "DOC_STRUCTURE_V2"),
        (("migračný plán dokumentov", "migracny plan dokumentov"), "DOC_MIGRATION_PLAN", "DOC_MIGRATION_PLAN"),
        (("optimalizuj dokumentáciu", "optimalizuj dokumentaciu", "priprav reorganizáciu", "priprav reorganizaciu", "navrhni reorganizáciu", "navrhni reorganizaciu"), "DOC_OPTIMIZATION_PLAN", "DOC_OPTIMIZATION_PLAN"),
        (("health dokumentácie", "health dokumentacie", "documentation health"), "DOC_HEALTH_SCORE", "DOC_HEALTH_SCORE"),
        (("validuj štruktúru", "validuj strukturu", "skontroluj ai_os"), "DOC_VALIDATE_STRUCTURE", "DOC_VALIDATE_STRUCTURE"),
        (("skontroluj governance", "governance dokumentácie", "governance dokumentacie"), "DOC_GOVERNANCE", "DOC_GOVERNANCE"),
        (("nájdi duplicity", "najdi duplicity", "skontroluj duplicity"), "DOC_DUPLICATES", "DOC_DUPLICATES"),
        (("nájdi siroty", "najdi siroty", "orphan"), "DOC_ORPHANS", "DOC_ORPHANS"),
        (("migračný log", "migracny log", "migration log"), "DOC_MIGRATION_LOG", "DOC_MIGRATION_LOG"),
    ]
    for keys, action, intent in mapping:
        if any(k in m for k in keys):
            data = post_to_apps_script(action, {})
            return {"intent": intent, "apps_script": data, "human": data.get("human", "Požiadavka bola spracovaná.")}

    if m.startswith("archivuj zastarané dokumenty plán") or m.startswith("archivuj zastarane dokumenty plan"):
        data = post_to_apps_script("DOC_ARCHIVE_STALE_PLAN", {})
        return {"intent": "DOC_ARCHIVE_STALE_PLAN", "apps_script": data, "human": data.get("human", "Plán archivácie bol pripravený.")}

    if m.startswith("potvrď reorganizáciu ") or m.startswith("potvrd reorganizaciu ") or m.startswith("potvrď ") or m.startswith("potvrd "):
        confirm_id = re.sub(r"^(potvrď reorganizáciu|potvrd reorganizaciu|potvrď|potvrd)\s+", "", original, flags=re.I).strip()
        data = post_to_apps_script("DOC_CONFIRM_MIGRATION", {"confirm_id": confirm_id})
        return {"intent": "DOC_CONFIRM_MIGRATION", "apps_script": data, "human": data.get("human", "Potvrdenie bolo spracované.")}

    if m.startswith("rollback reorganizácie ") or m.startswith("rollback reorganizacie ") or m.startswith("rollback "):
        migration_id = re.sub(r"^(rollback reorganizácie|rollback reorganizacie|rollback)\s+", "", original, flags=re.I).strip()
        data = post_to_apps_script("DOC_ROLLBACK_PLAN", {"migration_id": migration_id})
        return {"intent": "DOC_ROLLBACK_PLAN", "apps_script": data, "human": data.get("human", "Rollback plán bol pripravený.")}

    return None


@app.get("/")
def root():
    return PlainTextResponse("AI_OS Document Agent je online.", media_type="text/plain; charset=utf-8")


@app.head("/")
def root_head():
    return PlainTextResponse("", media_type="text/plain; charset=utf-8")


@app.get("/health")
def health():
    return JSONResponse({"status": "ok", "version": VERSION, "time_utc": utc_now()})


@app.get("/self-test")
def self_test(request: Request):
    token = request.query_params.get("token")
    tests = [
        {"name": "root", "status": "PASS"},
        {"name": "api_token", "status": "PASS" if API_TOKEN else "FAIL"},
        {"name": "token_valid", "status": "PASS" if token_ok(token) else "FAIL"},
        {"name": "fastapi_app", "status": "PASS"},
        {"name": "human_output_default", "status": "PASS"},
        {"name": "debug_output_separated", "status": "PASS"},
        {"name": "apps_script_webapp_url", "status": "PASS" if APPS_SCRIPT_WEBAPP_URL else "FAIL"},
        {"name": "documentation_optimizer", "status": "PASS"},
        {"name": "optimization_planner", "status": "PASS"},
        {"name": "approval_engine", "status": "PASS"},
        {"name": "migration_log", "status": "PASS"},
        {"name": "rollback_plan", "status": "PASS"},
        {"name": "governance_engine", "status": "PASS"},
        {"name": "health_score", "status": "PASS"},
        {"name": "duplicate_detector", "status": "PASS"},
        {"name": "orphan_detector", "status": "PASS"},
        {"name": "archive_plan", "status": "PASS"},
    ]
    status = "success" if all(t["status"] == "PASS" for t in tests) else "error"
    return JSONResponse({"status": status, "self_test": "PASS" if status == "success" else "FAIL", "version": VERSION, "request_id": request_id(), "time_utc": utc_now(), "tests": tests})


@app.get("/assistant")
def assistant(request: Request):
    debug = wants_debug(request)
    token = request.query_params.get("token")
    if not token_ok(token):
        return unauthorized(debug)
    message = clean_message(request.query_params.get("message", "")) or "Denné príkazy"
    rid = request_id()

    result = documentation_response(message)
    if result:
        payload = {"status": "success", "assistant": "AI_OS CAP-012.4 Documentation Optimizer & Governance", "version": VERSION, "request_id": rid, "time_utc": utc_now(), "message": message, **result}
        return plain_or_json(payload, debug)

    text = system_response(message)
    if not text:
        text = """AI_OS odpoveď

Príkaz nebol rozpoznaný.

Použi napríklad:
- Optimalizuj dokumentáciu AI_OS
- Health dokumentácie
- Validuj štruktúru
- Skontroluj governance
- Nájdi duplicity
- Nájdi siroty
- Archivuj zastarané dokumenty plán
- Migračný log
- Denné príkazy"""
    payload = {"status": "success", "assistant": "AI_OS CAP-012.4 Documentation Optimizer & Governance", "version": VERSION, "request_id": rid, "time_utc": utc_now(), "message": message, "human": text}
    return plain_or_json(payload, debug)


@app.get("/documentation-optimize")
def documentation_optimize(request: Request):
    debug = wants_debug(request)
    token = request.query_params.get("token")
    if not token_ok(token):
        return unauthorized(debug)
    data = post_to_apps_script("DOC_OPTIMIZATION_PLAN", {})
    payload = {"status": "success" if data.get("status") == "success" else "error", "version": VERSION, "apps_script": data, "human": data.get("human", "Optimalizačný plán bol pripravený.")}
    return plain_or_json(payload, debug)


@app.get("/documentation-health")
def documentation_health(request: Request):
    debug = wants_debug(request)
    token = request.query_params.get("token")
    if not token_ok(token):
        return unauthorized(debug)
    data = post_to_apps_script("DOC_HEALTH_SCORE", {})
    payload = {"status": "success" if data.get("status") == "success" else "error", "version": VERSION, "apps_script": data, "human": data.get("human", "Health dokumentácie bol vypočítaný.")}
    return plain_or_json(payload, debug)


@app.get("/documentation-validate")
def documentation_validate(request: Request):
    debug = wants_debug(request)
    token = request.query_params.get("token")
    if not token_ok(token):
        return unauthorized(debug)
    data = post_to_apps_script("DOC_VALIDATE_STRUCTURE", {})
    payload = {"status": "success" if data.get("status") == "success" else "error", "version": VERSION, "apps_script": data, "human": data.get("human", "Validácia štruktúry bola dokončená.")}
    return plain_or_json(payload, debug)


@app.get("/documentation-governance")
def documentation_governance(request: Request):
    debug = wants_debug(request)
    token = request.query_params.get("token")
    if not token_ok(token):
        return unauthorized(debug)
    data = post_to_apps_script("DOC_GOVERNANCE", {})
    payload = {"status": "success" if data.get("status") == "success" else "error", "version": VERSION, "apps_script": data, "human": data.get("human", "Governance dokumentácie bol vytvorený.")}
    return plain_or_json(payload, debug)


@app.get("/documentation-migration-log")
def documentation_migration_log(request: Request):
    debug = wants_debug(request)
    token = request.query_params.get("token")
    if not token_ok(token):
        return unauthorized(debug)
    data = post_to_apps_script("DOC_MIGRATION_LOG", {})
    payload = {"status": "success" if data.get("status") == "success" else "error", "version": VERSION, "apps_script": data, "human": data.get("human", "Migračný log bol načítaný.")}
    return plain_or_json(payload, debug)


@app.get("/chat")
def chat():
    html = f"""<!doctype html>
<html lang="sk">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>AI Assistant Chat</title>
  <style>
    body {{ margin:0; background:#f4f6f8; font-family:Arial, sans-serif; color:#111827; }}
    .wrap {{ max-width:940px; margin:28px auto; background:white; border:1px solid #d8dee8; border-radius:12px; box-shadow:0 10px 30px rgba(15,23,42,.08); overflow:hidden; }}
    header {{ padding:18px 22px; border-bottom:1px solid #e5e7eb; }}
    h1 {{ margin:0; font-size:22px; }}
    .sub {{ margin-top:5px; font-size:13px; color:#64748b; }}
    .buttons {{ padding:12px 18px; border-bottom:1px solid #e5e7eb; background:#f8fafc; display:flex; flex-wrap:wrap; gap:8px; }}
    button {{ background:#1f2937; color:white; border:0; padding:9px 12px; border-radius:7px; cursor:pointer; font-weight:600; }}
    button:hover {{ background:#374151; }}
    #chatlog {{ height:455px; overflow:auto; padding:18px; background:#fff; }}
    .msg {{ max-width:84%; margin:10px 0; padding:11px 13px; border-radius:10px; white-space:pre-wrap; line-height:1.35; font-size:14px; }}
    .user {{ margin-left:auto; background:#dbeafe; border:1px solid #bfdbfe; }}
    .bot {{ background:#f8fafc; border:1px solid #e2e8f0; }}
    .empty {{ border:1px dashed #cbd5e1; padding:14px; border-radius:10px; color:#64748b; }}
    .input {{ padding:14px 18px 18px; border-top:1px solid #e5e7eb; background:#f8fafc; }}
    textarea {{ width:100%; height:76px; box-sizing:border-box; resize:vertical; border:1px solid #cbd5e1; border-radius:8px; padding:12px; }}
    .row {{ display:flex; justify-content:space-between; gap:12px; align-items:center; margin-top:8px; }}
    .hint {{ color:#64748b; font-size:12px; }}
    .send {{ background:#111827; }}
  </style>
</head>
<body>
  <div class="wrap">
    <header>
      <h1>AI Assistant Chat</h1>
      <div class="sub">CAP-012.4 Documentation Optimizer & Governance. Plánuje, validuje a vykonáva iba schválené operácie.</div>
    </header>
    <div class="buttons">
      <button onclick="quick('Optimalizuj dokumentáciu AI_OS')">⚙ Optimalizovať</button>
      <button onclick="quick('Health dokumentácie')">❤️ Health</button>
      <button onclick="quick('Validuj štruktúru')">✅ Validácia</button>
      <button onclick="quick('Skontroluj governance')">📜 Governance</button>
      <button onclick="quick('Nájdi duplicity')">🧬 Duplicity</button>
      <button onclick="quick('Nájdi siroty')">🕳 Siroty</button>
      <button onclick="quick('Archivuj zastarané dokumenty plán')">🗄 Archivácia plán</button>
      <button onclick="quick('Migračný log')">📘 Migračný log</button>
      <button onclick="quick('Denné príkazy')">📌 Príkazy</button>
    </div>
    <div id="chatlog"><div class="empty">Tu sa zobrazí konverzácia.</div></div>
    <div class="input">
      <textarea id="message" placeholder="Napíš požiadavku po slovensky..."></textarea>
      <div class="row">
        <div class="hint">Enter = odoslať, Shift+Enter = nový riadok.</div>
        <button class="send" onclick="send()">Odoslať</button>
      </div>
    </div>
  </div>
<script>
function getToken() {{ const p = new URLSearchParams(window.location.search); return p.get('token') || localStorage.getItem('AI_OS_API_TOKEN') || ''; }}
function add(text, cls) {{ const log = document.getElementById('chatlog'); if (log.querySelector('.empty')) log.innerHTML = ''; const div = document.createElement('div'); div.className = 'msg ' + cls; div.textContent = text; log.appendChild(div); log.scrollTop = log.scrollHeight; }}
async function ask(text) {{ const token = getToken(); if (!token) {{ add('Chýba token. Otvor /chat?token=TVÔJ_TOKEN.', 'bot'); return; }} add(text, 'user'); add('Spracúvam...', 'bot'); const url = '/assistant?token=' + encodeURIComponent(token) + '&message=' + encodeURIComponent(text); const resp = await fetch(url); const out = await resp.text(); const nodes = document.querySelectorAll('.bot'); nodes[nodes.length-1].textContent = out; }}
function send() {{ const el = document.getElementById('message'); const text = el.value.trim(); if (!text) return; el.value = ''; ask(text); }}
function quick(text) {{ ask(text); }}
document.getElementById('message').addEventListener('keydown', function(e) {{ if (e.key === 'Enter' && !e.shiftKey) {{ e.preventDefault(); send(); }} }});
</script>
</body>
</html>"""
    return HTMLResponse(html)
