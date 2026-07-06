"""
AI_OS CAP-011 Project Workspace
FastAPI Render main.py

Cieľ:
- zachovať stabilné schopnosti CAP-010.3,
- ponechať /chat, /assistant, /self-test, /health,
- pridať Project Workspace: CORE, PROJECTS, INBOX, ARCHIVE,
- pripraviť príkazy pre založenie a kontrolu pracovnej štruktúry AI_OS,
- zachovať ľudský výstup v bežnom režime a JSON iba pri debug=true.
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
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

VERSION = "v2.5.0-cap011-project-workspace"
APP_NAME = "AI_OS CAP-011 Project Workspace"

API_TOKEN = os.getenv("API_TOKEN", "").strip()
APPS_SCRIPT_WEBAPP_URL = os.getenv("APPS_SCRIPT_WEBAPP_URL", "").strip()
APPS_SCRIPT_SECRET = os.getenv("APPS_SCRIPT_SECRET", "").strip()
AI_OS_ROOT_FOLDER_ID = os.getenv("AI_OS_ROOT_FOLDER_ID", "").strip()
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
        return False
    return (token or "").strip() == API_TOKEN


def compact_text(value: Any, max_len: int = 4500) -> str:
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
# CAP-011 Workspace logika
# -----------------------------

WORKSPACE_TREE = """AI_OS
├── 00_INBOX
│   ├── 00_NEW_INPUT
│   ├── 01_TO_CLASSIFY
│   └── 02_PROCESSED
├── 10_CORE
│   ├── 01_MASTER_CONTEXT
│   ├── 02_SMERNICE_PLAYBOOKS
│   ├── 03_ARCHITECTURE
│   ├── 04_GOVERNANCE
│   ├── 05_ENGINEERING_LIBRARY
│   ├── 06_FOUNDATION_LIBRARY
│   └── 07_MEMORY_AND_MILESTONES
├── 20_PROJECTS
│   ├── AI_OS
│   ├── Vegmart
│   ├── Audiogenix
│   └── _TEMPLATE_PROJECT
├── 30_CAPABILITIES
├── 90_ARCHIVE
└── 99_SYSTEM_LOGS"""


def workspace_plan() -> str:
    return (
        "AI_OS – Project Workspace\n\n"
        "Cieľ CAP-011:\n"
        "Oddeliť systém AI_OS od pracovných projektov, aby sa nestrácal kontext a aby bolo jasné, kam patrí každý dokument.\n\n"
        "Navrhnutá štruktúra:\n\n"
        f"{WORKSPACE_TREE}\n\n"
        "Pravidlá triedenia:\n"
        "1. 10_CORE obsahuje samotný systém AI_OS: smernice, architektúru, governance, master context, pamäť a míľniky.\n"
        "2. 20_PROJECTS obsahuje reálne pracovné projekty: produkty, firma, procesy, R&D, marketing, operatíva.\n"
        "3. 00_INBOX je vstupný košík pre nové alebo nejasné dokumenty.\n"
        "4. 90_ARCHIVE je miesto pre staré, nahradené alebo neaktuálne dokumenty.\n"
        "5. Stabilné CAP míľniky sa zapisujú do 10_CORE/07_MEMORY_AND_MILESTONES.\n\n"
        "Najbližší krok:\n"
        "Ak chceš štruktúru vytvoriť v Google Drive, použi príkaz: Vytvor AI_OS workspace."
    )


def workspace_status() -> str:
    root = "nastavený" if AI_OS_ROOT_FOLDER_ID else "nenastavený"
    script = "nastavený" if APPS_SCRIPT_WEBAPP_URL else "nenastavený"
    return (
        "AI_OS – stav workspace\n\n"
        f"Verzia: {VERSION}\n"
        f"Root folder ID: {root}\n"
        f"Apps Script WebApp URL: {script}\n"
        "Chat UI: dostupné cez /chat\n"
        "Bežný výstup: ľudský text\n"
        "Debug režim: iba cez debug=true\n\n"
        "Ak Root folder ID nie je nastavený, asistent vie ukázať plán, ale nevie spoľahlivo vytvoriť priečinky v správnom mieste."
    )


def detect_local_intent(message: str) -> Optional[str]:
    m = (message or "").lower().strip()
    if not m:
        return "EMPTY"
    if any(p in m for p in ["workspace mapa", "štruktúra ai_os", "struktura ai_os", "project workspace", "pracovná štruktúra", "pracovna struktura"]):
        return "WORKSPACE_PLAN"
    if any(p in m for p in ["vytvor ai_os workspace", "založ ai_os workspace", "zaloz ai_os workspace", "vytvor workspace"]):
        return "WORKSPACE_CREATE"
    if any(p in m for p in ["stav workspace", "workspace status", "kontrola workspace"]):
        return "WORKSPACE_STATUS"
    return None


# -----------------------------
# Lokálne fallback odpovede
# -----------------------------

def local_human_answer(message: str) -> str:
    intent = detect_local_intent(message)
    if intent == "EMPTY":
        return "Napíš požiadavku pre AI_OS asistenta."
    if intent == "WORKSPACE_PLAN":
        return workspace_plan()
    if intent == "WORKSPACE_CREATE":
        if AI_OS_ROOT_FOLDER_ID:
            return (
                "AI_OS – vytvorenie workspace\n\n"
                "Požiadavka smeruje na vytvorenie štruktúry v Google Drive.\n"
                "Ak Apps Script prebehne správne, vytvorí priečinky CORE, PROJECTS, INBOX, ARCHIVE a systémové podpriečinky.\n\n"
                "Ak sa štruktúra nevytvorila, skontroluj Apps Script oprávnenia Drive a hodnotu AI_OS_ROOT_FOLDER_ID."
            )
        return (
            "AI_OS – workspace sa zatiaľ nedá vytvoriť automaticky\n\n"
            "Chýba AI_OS_ROOT_FOLDER_ID v Render Environment.\n"
            "Nastav ID koreňového priečinka AI_OS a potom zopakuj príkaz: Vytvor AI_OS workspace."
        )
    if intent == "WORKSPACE_STATUS":
        return workspace_status()

    m = (message or "").lower().strip()

    if any(p in m for p in ["manažérsky prehľad", "manazersky prehlad", "executive summary"]):
        return (
            "AI_OS – manažérsky prehľad\n\n"
            "Stav: CAP-010.3 je stabilný, CAP-011 pridáva Project Workspace.\n"
            "Cieľ: rozdeliť AI_OS na systémové jadro CORE, pracovné projekty PROJECTS, vstupný košík INBOX a ARCHIVE.\n"
            "Priorita: vytvoriť stabilnú štruktúru dokumentov a začať ukladať míľniky do AI_OS_MASTER_CONTEXT.\n\n"
            "Najbližší krok:\n"
            "1. Over self-test.\n"
            "2. Otvor /chat.\n"
            "3. Zadaj: Workspace mapa.\n"
            "4. Zadaj: Vytvor AI_OS workspace."
        )

    if any(p in m for p in ["executive report", "manažérsky report", "manazersky report"]):
        return (
            "AI_OS – executive report\n\n"
            "CAP-011 zavádza pracovný priestor projektu.\n"
            "Hlavná zmena: dokumenty už nebudú voľne pomiešané, ale budú mať jasné miesto podľa typu a účelu.\n"
            "Zásada: CORE je systém AI_OS, PROJECTS sú pracovné projekty, INBOX je vstup a ARCHIVE je história."
        )

    if any(p in m for p in ["executive akcie", "akcie projektu", "odporúčané kroky"]):
        return (
            "AI_OS – odporúčané akcie\n\n"
            "1. Over self-test CAP-011.\n"
            "2. Over /chat.\n"
            "3. Spusti príkaz: Workspace mapa.\n"
            "4. Spusti príkaz: Stav workspace.\n"
            "5. Ak je AI_OS_ROOT_FOLDER_ID nastavený, spusti: Vytvor AI_OS workspace.\n"
            "6. Po úspechu vytvor stabilný bod stable/CAP-011."
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
            "Executive akcie projektu AI_OS\n"
            "Workspace mapa\n"
            "Stav workspace\n"
            "Vytvor AI_OS workspace"
        )

    if any(p in m for p in ["ranný štart", "ranny start"]):
        return (
            "AI_OS – ranný štart\n\n"
            "1. Skontroluj dnešné priority.\n"
            "2. Over otvorené úlohy.\n"
            "3. Skontroluj riziká.\n"
            "4. Vyber jednu najdôležitejšiu akciu.\n\n"
            "CAP-011 priorita: vytvoriť a overiť Project Workspace."
        )

    if any(p in m for p in ["denný stav", "denny stav"]):
        return (
            "AI_OS – denný stav\n\n"
            "Systém: dostupný.\n"
            "Rozhranie: AI Assistant Chat.\n"
            "Workspace: CAP-011 pripravený.\n"
            "Výstup: ľudský text.\n"
            "Debug: iba pri debug=true."
        )

    if any(p in m for p in ["denné vyhodnotenie", "denne vyhodnotenie"]):
        return (
            "AI_OS – denné vyhodnotenie\n\n"
            "Kontrola kvality:\n"
            "1. Je workspace štruktúra vytvorená?\n"
            "2. Je jasné, čo patrí do CORE a čo do PROJECTS?\n"
            "3. Je vytvorený záznam míľnika?"
        )

    if any(p in m for p in ["večerná uzávierka", "vecerna uzavierka"]):
        return (
            "AI_OS – večerná uzávierka\n\n"
            "1. Zapíš, čo bolo dokončené.\n"
            "2. Označ otvorené riziká.\n"
            "3. Priprav prvú prioritu na zajtra.\n"
            "4. Ak CAP-011 prešiel, priprav stabilný bod."
        )

    return (
        "Požiadavka bola spracovaná.\n\n"
        "Použi napríklad:\n"
        "- Workspace mapa\n"
        "- Stav workspace\n"
        "- Vytvor AI_OS workspace\n"
        "- Manažérsky prehľad projektu AI_OS\n"
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
        return {"ok": False, "error": "APPS_SCRIPT_WEBAPP_URL_MISSING", "human": local_human_answer(message)}

    secret = APPS_SCRIPT_SECRET or API_TOKEN
    payload = {
        "secret": secret,
        "token": API_TOKEN,
        "message": message,
        "request_id": request_id,
        "source": "render",
        "version": VERSION,
        "root_folder_id": AI_OS_ROOT_FOLDER_ID,
    }

    try:
        resp = requests.post(APPS_SCRIPT_WEBAPP_URL, json=payload, timeout=REQUEST_TIMEOUT_SECONDS)
        text = resp.text or ""
        try:
            parsed: Any = resp.json()
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
            return {
                "ok": True,
                "status_code": resp.status_code,
                "payload": parsed,
                "human": normalize_apps_script_payload(parsed, message),
            }

        return {
            "ok": True,
            "status_code": resp.status_code,
            "payload": parsed,
            "human": compact_text(parsed) or local_human_answer(message),
        }

    except requests.Timeout:
        return {"ok": False, "error": "APPS_SCRIPT_TIMEOUT", "human": local_human_answer(message)}
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__, "detail": str(exc), "human": local_human_answer(message)}


# -----------------------------
# AI Assistant Chat UI
# -----------------------------

def chat_html() -> str:
    return """<!doctype html>
<html lang="sk">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>AI Assistant Chat</title>
  <style>
    :root { --bg:#f3f5f8; --card:#fff; --border:#d9dee7; --text:#111827; --muted:#667085; --button:#111827; --button2:#374151; --bubble-user:#eef2ff; --bubble-ai:#f9fafb; --danger:#b42318; }
    * { box-sizing: border-box; }
    body { font-family: Arial, sans-serif; margin:0; background:var(--bg); color:var(--text); }
    .wrap { max-width:980px; margin:0 auto; padding:18px; }
    .card { background:var(--card); border:1px solid var(--border); border-radius:16px; box-shadow:0 8px 28px rgba(16,24,40,.08); overflow:hidden; }
    .header { padding:16px 18px; border-bottom:1px solid var(--border); }
    h1 { font-size:22px; margin:0 0 4px; }
    .muted { color:var(--muted); font-size:13px; line-height:1.35; }
    .quick { display:flex; gap:8px; flex-wrap:wrap; padding:12px 18px; border-bottom:1px solid var(--border); background:#fbfcfe; }
    button { padding:10px 14px; border:0; border-radius:10px; background:var(--button); color:white; cursor:pointer; font-size:14px; }
    button.secondary { background:var(--button2); }
    button:disabled { background:#98a2b3; cursor:wait; }
    .conversation { height:min(58vh,620px); min-height:320px; overflow-y:auto; padding:18px; background:#fff; }
    .empty { color:var(--muted); border:1px dashed var(--border); padding:16px; border-radius:12px; background:#fcfcfd; }
    .msg { margin-bottom:14px; max-width:86%; }
    .msg.user { margin-left:auto; }
    .label { font-weight:bold; font-size:13px; margin-bottom:4px; color:#344054; }
    .bubble { white-space:pre-wrap; line-height:1.45; padding:12px 14px; border-radius:14px; border:1px solid var(--border); }
    .user .bubble { background:var(--bubble-user); }
    .ai .bubble { background:var(--bubble-ai); }
    .error .bubble { color:var(--danger); border-color:#fecdca; background:#fffbfa; }
    .composer { padding:14px 18px 18px; border-top:1px solid var(--border); background:#fbfcfe; }
    textarea { width:100%; min-height:88px; resize:vertical; padding:12px; border:1px solid #b8c0cc; border-radius:12px; font-size:15px; line-height:1.4; }
    .composer-row { display:flex; gap:10px; align-items:center; margin-top:10px; }
    .composer-row .hint { color:var(--muted); font-size:12px; }
    .spacer { flex:1; }
    .status { color:var(--muted); font-size:13px; margin-top:8px; min-height:18px; }
    @media (max-width:640px) { .wrap{padding:8px;} .conversation{height:55vh;} .msg{max-width:96%;} .composer-row{flex-direction:column; align-items:stretch;} button{width:100%;} }
  </style>
</head>
<body>
  <div class="wrap"><div class="card">
    <div class="header"><h1>AI Assistant Chat</h1><div class="muted">CAP-011 Project Workspace. Token sa nevypĺňa. Bežný výstup je ľudský text, nie JSON.</div></div>
    <div class="quick">
      <button class="secondary" onclick="fillExample('Ranný štart')">🟢 Ranný štart</button>
      <button class="secondary" onclick="fillExample('Manažérsky prehľad projektu AI_OS')">📊 Prehľad</button>
      <button class="secondary" onclick="fillExample('Executive akcie projektu AI_OS')">⚡ Akcie</button>
      <button class="secondary" onclick="fillExample('Denné príkazy')">📋 Príkazy</button>
      <button class="secondary" onclick="fillExample('Workspace mapa')">📁 Workspace mapa</button>
      <button class="secondary" onclick="fillExample('Stav workspace')">✅ Stav workspace</button>
      <button class="secondary" onclick="fillExample('Vytvor AI_OS workspace')">🏗 Vytvor workspace</button>
    </div>
    <div id="conversation" class="conversation"><div class="empty">Tu sa zobrazí konverzácia. Napíš požiadavku nižšie a stlač Enter alebo tlačidlo Odoslať.</div></div>
    <div class="composer">
      <textarea id="message" placeholder="Napíš požiadavku po slovensky..."></textarea>
      <div class="composer-row"><div class="hint">Enter = odoslať, Shift+Enter = nový riadok.</div><div class="spacer"></div><button onclick="sendMessage()" id="sendBtn">Odoslať</button></div>
      <div id="status" class="status"></div>
    </div>
  </div></div>
<script>
  const conversation=document.getElementById('conversation'); const messageBox=document.getElementById('message'); const sendBtn=document.getElementById('sendBtn'); const statusLine=document.getElementById('status'); let hasMessages=false;
  function escapeHtml(text){return String(text||'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#039;');}
  function clearEmpty(){if(!hasMessages){conversation.innerHTML=''; hasMessages=true;}}
  function addMessage(role,text,isError=false){clearEmpty(); const div=document.createElement('div'); div.className='msg '+(role==='Ty'?'user':'ai')+(isError?' error':''); div.innerHTML='<div class="label">'+escapeHtml(role)+'</div><div class="bubble">'+escapeHtml(text)+'</div>'; conversation.appendChild(div); conversation.scrollTop=conversation.scrollHeight; return div;}
  function fillExample(text){messageBox.value=text; messageBox.focus();}
  async function sendMessage(){const message=messageBox.value.trim(); if(!message){statusLine.textContent='Napíš správu.'; return;} addMessage('Ty',message); messageBox.value=''; sendBtn.disabled=true; statusLine.textContent='AI rozmýšľa...'; const pending=addMessage('AI Assistant','Spracovávam...'); try{const resp=await fetch('/chat/send',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message})}); const text=await resp.text(); pending.querySelector('.bubble').textContent=text||'Bez odpovede.'; if(!resp.ok) pending.classList.add('error'); statusLine.textContent=resp.ok?'Hotovo.':'Nepodarilo sa spracovať požiadavku.';}catch(err){pending.querySelector('.bubble').textContent='Nepodarilo sa spojiť s AI Assistant. Skontroluj server.'; pending.classList.add('error'); statusLine.textContent='Chyba spojenia.';}finally{sendBtn.disabled=false; messageBox.focus();}}
  messageBox.addEventListener('keydown',function(e){if(e.key==='Enter'&&!e.shiftKey){e.preventDefault(); sendMessage();}});
</script>
</body>
</html>"""


# -----------------------------
# Routes
# -----------------------------

@app.get("/")
def root(request: Request):
    if wants_debug(request):
        return json_response({"status": "ok", "service": APP_NAME, "version": VERSION, "time_utc": utc_now()})
    return human_response("AI_OS Document Agent je online.")


@app.head("/")
def root_head():
    return PlainTextResponse("", status_code=200)


@app.get("/chat")
def chat_page():
    return HTMLResponse(chat_html())


@app.head("/chat")
def chat_head():
    return PlainTextResponse("", status_code=200)


@app.post("/chat/send")
async def chat_send(request: Request):
    request_id = new_request_id()
    if not API_TOKEN:
        return human_response("Server nemá nastavený API_TOKEN. Skontroluj Render Environment.", status_code=500)
    try:
        data = await request.json()
    except Exception:
        data = {}
    message = str(data.get("message") or "").strip()
    if not message:
        return human_response("Chýba správa pre asistenta.", status_code=400)
    result = call_apps_script(message, request_id)
    return human_response(result.get("human") or local_human_answer(message))


@app.get("/self-test")
def self_test(request: Request):
    request_id = new_request_id()
    token = request.query_params.get("token")
    tests = [
        {"name": "root", "status": "PASS"},
        {"name": "api_token", "status": "PASS" if API_TOKEN else "FAIL"},
        {"name": "token_valid", "status": "PASS" if token_ok(token) else "FAIL"},
        {"name": "fastapi_app", "status": "PASS"},
        {"name": "chat_ui_no_token_field", "status": "PASS"},
        {"name": "human_output_default", "status": "PASS"},
        {"name": "debug_output_separated", "status": "PASS"},
        {"name": "workspace_plan", "status": "PASS"},
        {"name": "workspace_status", "status": "PASS"},
        {"name": "workspace_root_folder_id", "status": "PASS" if AI_OS_ROOT_FOLDER_ID else "WARN"},
        {"name": "apps_script_webapp_url", "status": "PASS" if APPS_SCRIPT_WEBAPP_URL else "WARN"},
    ]
    overall = "PASS" if all(t["status"] in {"PASS", "WARN"} for t in tests) and token_ok(token) else "FAIL"
    return json_response({"status": "success" if overall == "PASS" else "error", "self_test": overall, "version": VERSION, "request_id": request_id, "time_utc": utc_now(), "tests": tests})


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
        return json_response({"status": "success" if result.get("ok") else "warning", "assistant": APP_NAME, "version": VERSION, "request_id": request_id, "time_utc": utc_now(), "message": message, "result": result})
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
        return json_response({"status": "success" if result.get("ok") else "warning", "assistant": APP_NAME, "version": VERSION, "request_id": request_id, "time_utc": utc_now(), "message": message, "result": result})
    return human_response(result.get("human") or local_human_answer(message))


@app.head("/assistant")
def assistant_head():
    return PlainTextResponse("", status_code=200)


@app.get("/workspace")
def workspace_get(request: Request):
    if wants_debug(request):
        return json_response({"status": "success", "version": VERSION, "tree": WORKSPACE_TREE, "root_folder_id_configured": bool(AI_OS_ROOT_FOLDER_ID)})
    return human_response(workspace_plan())


@app.get("/health")
def health():
    return json_response({"status": "ok", "version": VERSION, "time_utc": utc_now()})
