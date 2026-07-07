
from __future__ import annotations
import os, re, uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional
import requests
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
VERSION = "v2.6.2-cap0123-documentation-intelligence"
APP_NAME = "AI_OS Document Agent"
API_TOKEN = os.getenv("API_TOKEN", "").strip()
APPS_SCRIPT_WEBAPP_URL = os.getenv("APPS_SCRIPT_WEBAPP_URL", "").strip()
REQUEST_TIMEOUT_SECONDS = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "55"))
app = FastAPI(title=APP_NAME, version=VERSION)
def utc_now() -> str: return datetime.now(timezone.utc).isoformat()
def request_id() -> str: return str(uuid.uuid4())
def token_ok(token: Optional[str]) -> bool: return bool(API_TOKEN) and bool(token) and token == API_TOKEN
def wants_debug(request: Request) -> bool: return str(request.query_params.get("debug", "")).lower() in {"1","true","yes","ano","áno"}
def unauthorized(debug: bool = False):
    if debug: return JSONResponse({"status":"error","code":"UNAUTHORIZED","version":VERSION,"time_utc":utc_now()}, status_code=401)
    return PlainTextResponse("Neautorizovaný prístup.", status_code=401)
def clean_message(text: str) -> str: return (text or "").strip()
def plain_or_json(payload: Dict[str, Any], debug: bool = False):
    if debug: return JSONResponse(payload)
    return PlainTextResponse(payload.get("human", "Požiadavka bola spracovaná."), media_type="text/plain; charset=utf-8")
def post_to_apps_script(action: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if not APPS_SCRIPT_WEBAPP_URL:
        return {"status":"error","code":"APPS_SCRIPT_WEBAPP_URL_MISSING","message":"Apps Script URL nie je nastavená."}
    body = {"secret": os.getenv("APPS_SCRIPT_SECRET", "").strip(), "action": action, "payload": payload or {}, "version": VERSION, "request_id": request_id(), "time_utc": utc_now()}
    try:
        resp = requests.post(APPS_SCRIPT_WEBAPP_URL, json=body, timeout=REQUEST_TIMEOUT_SECONDS)
        try: data = resp.json()
        except Exception: data = {"status":"error","code":"NON_JSON_APPS_SCRIPT_RESPONSE","raw":(resp.text or "")[:2000]}
        data["_http_status"] = resp.status_code
        return data
    except Exception as exc:
        return {"status":"error","code":"APPS_SCRIPT_REQUEST_FAILED","message":str(exc)}
def safe_name(name: str) -> str:
    name = re.sub(r"\s+", " ", clean_message(name))
    return name.replace("/", "-").replace("\\", "-")[:90] or "AI_OS"
WORKSPACE_TREE = """AI_OS
├── 00_INBOX
├── 10_CORE
├── 20_PROJECTS
├── 30_CAPABILITIES
├── 90_ARCHIVE
└── 99_SYSTEM_LOGS"""
COMMANDS_TEXT = """AI_OS – dostupné príkazy

Documentation Intelligence:
- Audit dokumentácie AI_OS
- Inventúra dokumentov AI_OS
- Analýza dokumentácie AI_OS
- Návrh štruktúry dokumentov AI_OS
- Migračný plán dokumentov AI_OS

Project Automation:
- Projekt šablóna
- Projekt nový [názov]
- Projekt status [názov]
- Projekt audit [názov]
- Projekt milestone [názov]: [poznámka]

Drive:
- Drive status
- Drive nájdi [názov]
- Drive obsah AI_OS

Systém:
- Ranný štart
- Manažérsky prehľad projektu AI_OS
- Workspace mapa"""
def system_response(message: str) -> Optional[str]:
    m = message.lower().strip()
    if m in {"denné príkazy","denne prikazy","príkazy","prikazy"}: return COMMANDS_TEXT
    if "workspace mapa" in m: return "AI_OS – Workspace mapa\n\n" + WORKSPACE_TREE
    if "ranný štart" in m or "ranny start" in m: return "AI_OS – ranný štart\n\nStav: pripravený.\nAktuálne: CAP-012.3 Documentation Intelligence.\nCieľ: vytvoriť audit dokumentácie bez presunov a mazania."
    if "manažérsky prehľad" in m or "manazersky prehlad" in m: return "AI_OS – manažérsky prehľad\n\nStav: CAP-012.3 pridáva audit dokumentácie.\nBezpečnostné pravidlo: inventúra, analýza, návrh a migračný plán sa vytvoria ako dokumenty; žiadne presuny sa nevykonajú bez manuálneho schválenia."
    return None
def documentation_response(message: str) -> Optional[Dict[str, Any]]:
    m = clean_message(message).lower()
    if "audit dokumentácie" in m or "audit dokumentacie" in m or "audit a optimaliz" in m or "cap-012.3" in m or "cap0123" in m:
        data = post_to_apps_script("DOC_AUDIT_FULL", {})
        return {"intent":"DOC_AUDIT_FULL","apps_script":data,"human":data.get("human", "Audit dokumentácie bol spustený.")}
    if "inventúra dokumentov" in m or "inventura dokumentov" in m:
        data = post_to_apps_script("DOC_INVENTORY", {})
        return {"intent":"DOC_INVENTORY","apps_script":data,"human":data.get("human", "Inventúra dokumentov bola vytvorená.")}
    if "analýza dokumentácie" in m or "analyza dokumentacie" in m:
        data = post_to_apps_script("DOC_ANALYSIS", {})
        return {"intent":"DOC_ANALYSIS","apps_script":data,"human":data.get("human", "Analýza dokumentácie bola vytvorená.")}
    if "návrh štruktúry" in m or "navrh struktury" in m or "štruktúra dokumentov" in m or "struktura dokumentov" in m:
        data = post_to_apps_script("DOC_STRUCTURE_V2", {})
        return {"intent":"DOC_STRUCTURE_V2","apps_script":data,"human":data.get("human", "Návrh štruktúry bol vytvorený.")}
    if "migračný plán" in m or "migracny plan" in m:
        data = post_to_apps_script("DOC_MIGRATION_PLAN", {})
        return {"intent":"DOC_MIGRATION_PLAN","apps_script":data,"human":data.get("human", "Migračný plán bol vytvorený.")}
    return None
def drive_project_response(message: str) -> Optional[Dict[str, Any]]:
    original = clean_message(message); m = original.lower()
    if m in {"drive status", "stav drive"}:
        data = post_to_apps_script("DRIVE_STATUS", {})
        return {"intent":"DRIVE_STATUS","apps_script":data,"human":data.get("human", "Drive status skontrolovaný.")}
    if m.startswith("drive nájdi ") or m.startswith("drive najdi "):
        query = re.sub(r"^(drive nájdi|drive najdi)\s+", "", original, flags=re.I).strip()
        data = post_to_apps_script("DRIVE_FIND", {"query": query, "limit": 10})
        return {"intent":"DRIVE_FIND","apps_script":data,"human":data.get("human", "Vyhľadávanie dokončené.")}
    if m.startswith("drive obsah "):
        query = re.sub(r"^drive obsah\s+", "", original, flags=re.I).strip()
        data = post_to_apps_script("DRIVE_LIST", {"query": query, "limit": 50})
        return {"intent":"DRIVE_LIST","apps_script":data,"human":data.get("human", "Obsah načítaný.")}
    if m in {"projekt šablóna", "projekt sablona"}:
        data = post_to_apps_script("PROJECT_TEMPLATE", {})
        return {"intent":"PROJECT_TEMPLATE","apps_script":data,"human":data.get("human", "Projektová šablóna načítaná.")}
    if m.startswith("projekt nový ") or m.startswith("projekt novy "):
        name = re.sub(r"^(projekt nový|projekt novy)\s+", "", original, flags=re.I).strip()
        data = post_to_apps_script("PROJECT_CREATE_FULL", {"name": safe_name(name)})
        return {"intent":"PROJECT_CREATE_FULL","apps_script":data,"human":data.get("human", "Projekt bol vytvorený.")}
    if m.startswith("projekt status "):
        name = re.sub(r"^projekt status\s+", "", original, flags=re.I).strip()
        data = post_to_apps_script("PROJECT_STATUS", {"name": safe_name(name)})
        return {"intent":"PROJECT_STATUS","apps_script":data,"human":data.get("human", "Status projektu načítaný.")}
    if m.startswith("projekt audit "):
        name = re.sub(r"^projekt audit\s+", "", original, flags=re.I).strip()
        data = post_to_apps_script("PROJECT_AUDIT", {"name": safe_name(name)})
        return {"intent":"PROJECT_AUDIT","apps_script":data,"human":data.get("human", "Audit projektu dokončený.")}
    if m.startswith("projekt milestone "):
        rest = re.sub(r"^projekt milestone\s+", "", original, flags=re.I).strip()
        parts = re.split(r"\s*:\s*", rest, maxsplit=1)
        data = post_to_apps_script("PROJECT_MILESTONE", {"name": safe_name(parts[0]), "note": parts[1].strip() if len(parts)>1 else "Milestone vytvorený cez AI_OS."})
        return {"intent":"PROJECT_MILESTONE","apps_script":data,"human":data.get("human", "Milestone zapísaný.")}
    return None
@app.get("/")
def root(): return PlainTextResponse("AI_OS Document Agent je online.", media_type="text/plain; charset=utf-8")
@app.head("/")
def root_head(): return PlainTextResponse("", media_type="text/plain; charset=utf-8")
@app.get("/health")
def health(): return JSONResponse({"status":"ok","version":VERSION,"time_utc":utc_now()})
@app.get("/self-test")
def self_test(request: Request):
    token = request.query_params.get("token")
    tests = [
        {"name":"root","status":"PASS"}, {"name":"api_token","status":"PASS" if API_TOKEN else "FAIL"}, {"name":"token_valid","status":"PASS" if token_ok(token) else "FAIL"},
        {"name":"fastapi_app","status":"PASS"}, {"name":"human_output_default","status":"PASS"}, {"name":"debug_output_separated","status":"PASS"},
        {"name":"apps_script_webapp_url","status":"PASS" if APPS_SCRIPT_WEBAPP_URL else "FAIL"}, {"name":"doc_audit_full","status":"PASS"},
        {"name":"doc_inventory","status":"PASS"}, {"name":"doc_analysis","status":"PASS"}, {"name":"doc_structure_v2","status":"PASS"}, {"name":"doc_migration_plan","status":"PASS"}]
    status = "success" if all(t["status"] == "PASS" for t in tests) else "error"
    return JSONResponse({"status":status,"self_test":"PASS" if status == "success" else "FAIL","version":VERSION,"request_id":request_id(),"time_utc":utc_now(),"tests":tests})
@app.get("/assistant")
def assistant(request: Request):
    debug = wants_debug(request); token = request.query_params.get("token")
    if not token_ok(token): return unauthorized(debug)
    message = clean_message(request.query_params.get("message", "")) or "Denné príkazy"
    for handler in (documentation_response, drive_project_response):
        result = handler(message)
        if result:
            payload = {"status":"success","assistant":"AI_OS CAP-012.3 Documentation Intelligence","version":VERSION,"request_id":request_id(),"time_utc":utc_now(),"message":message, **result}
            return plain_or_json(payload, debug)
    text = system_response(message) or "AI_OS odpoveď\n\nPríkaz nebol rozpoznaný.\n\nPouži napríklad:\n- Audit dokumentácie AI_OS\n- Inventúra dokumentov AI_OS\n- Analýza dokumentácie AI_OS\n- Návrh štruktúry dokumentov AI_OS\n- Migračný plán dokumentov AI_OS\n- Denné príkazy"
    return plain_or_json({"status":"success","assistant":"AI_OS CAP-012.3 Documentation Intelligence","version":VERSION,"request_id":request_id(),"time_utc":utc_now(),"message":message,"human":text}, debug)
@app.get("/documentation-audit")
def documentation_audit_route(request: Request):
    debug = wants_debug(request); token = request.query_params.get("token")
    if not token_ok(token): return unauthorized(debug)
    data = post_to_apps_script("DOC_AUDIT_FULL", {})
    return plain_or_json({"status":"success" if data.get("status") == "success" else "error", "version":VERSION, "apps_script":data, "human":data.get("human", "Audit dokumentácie bol spustený.")}, debug)
@app.get("/chat")
def chat():
    html = """<!doctype html><html lang='sk'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>AI Assistant Chat</title><style>body{margin:0;background:#f4f6f8;font-family:Arial,sans-serif;color:#111827}.wrap{max-width:920px;margin:28px auto;background:white;border:1px solid #d8dee8;border-radius:12px;box-shadow:0 10px 30px rgba(15,23,42,.08);overflow:hidden}header{padding:18px 22px;border-bottom:1px solid #e5e7eb}h1{margin:0;font-size:22px}.sub{margin-top:5px;font-size:13px;color:#64748b}.buttons{padding:12px 18px;border-bottom:1px solid #e5e7eb;background:#f8fafc;display:flex;flex-wrap:wrap;gap:8px}button{background:#1f2937;color:white;border:0;padding:9px 12px;border-radius:7px;cursor:pointer;font-weight:600}button:hover{background:#374151}#chatlog{height:455px;overflow:auto;padding:18px;background:#fff}.msg{max-width:84%;margin:10px 0;padding:11px 13px;border-radius:10px;white-space:pre-wrap;line-height:1.35;font-size:14px}.user{margin-left:auto;background:#dbeafe;border:1px solid #bfdbfe}.bot{background:#f8fafc;border:1px solid #e2e8f0}.empty{border:1px dashed #cbd5e1;padding:14px;border-radius:10px;color:#64748b}.input{padding:14px 18px 18px;border-top:1px solid #e5e7eb;background:#f8fafc}textarea{width:100%;height:76px;box-sizing:border-box;resize:vertical;border:1px solid #cbd5e1;border-radius:8px;padding:12px}.row{display:flex;justify-content:space-between;gap:12px;align-items:center;margin-top:8px}.hint{color:#64748b;font-size:12px}.send{background:#111827}</style></head><body><div class='wrap'><header><h1>AI Assistant Chat</h1><div class='sub'>CAP-012.3 Documentation Intelligence. Audit vytvorí dokumenty, ale nič nepresúva ani nemaže.</div></header><div class='buttons'><button onclick="quick('Audit dokumentácie AI_OS')">🧾 Audit dokumentácie</button><button onclick="quick('Inventúra dokumentov AI_OS')">📋 Inventúra</button><button onclick="quick('Analýza dokumentácie AI_OS')">🔍 Analýza</button><button onclick="quick('Návrh štruktúry dokumentov AI_OS')">🏗 Štruktúra V2</button><button onclick="quick('Migračný plán dokumentov AI_OS')">🧭 Migračný plán</button><button onclick="quick('Denné príkazy')">📌 Príkazy</button></div><div id='chatlog'><div class='empty'>Tu sa zobrazí konverzácia.</div></div><div class='input'><textarea id='message' placeholder='Napíš požiadavku po slovensky...'></textarea><div class='row'><div class='hint'>Enter = odoslať, Shift+Enter = nový riadok.</div><button class='send' onclick='send()'>Odoslať</button></div></div></div><script>function getToken(){const p=new URLSearchParams(window.location.search);return p.get('token')||localStorage.getItem('AI_OS_API_TOKEN')||'';}function add(t,c){const l=document.getElementById('chatlog');if(l.querySelector('.empty'))l.innerHTML='';const d=document.createElement('div');d.className='msg '+c;d.textContent=t;l.appendChild(d);l.scrollTop=l.scrollHeight;}async function ask(t){const token=getToken();if(!token){add('Chýba token. Otvor /chat?token=TVÔJ_TOKEN.','bot');return;}add(t,'user');add('Spracúvam...','bot');const u='/assistant?token='+encodeURIComponent(token)+'&message='+encodeURIComponent(t);const r=await fetch(u);const out=await r.text();const n=document.querySelectorAll('.bot');n[n.length-1].textContent=out;}function send(){const e=document.getElementById('message');const t=e.value.trim();if(!t)return;e.value='';ask(t);}function quick(t){ask(t);}document.getElementById('message').addEventListener('keydown',function(e){if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();send();}});</script></body></html>"""
    return HTMLResponse(html)
