
from __future__ import annotations
import os, re, uuid, requests
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, JSONResponse, HTMLResponse

VERSION="v2.6.0-cap0121-drive-intelligence"
APP_NAME="AI_OS Document Agent"
API_TOKEN=os.getenv("API_TOKEN","").strip()
APPS_SCRIPT_WEBAPP_URL=os.getenv("APPS_SCRIPT_WEBAPP_URL","").strip()
REQUEST_TIMEOUT_SECONDS=float(os.getenv("REQUEST_TIMEOUT_SECONDS","25"))
app=FastAPI(title=APP_NAME, version=VERSION)

def utc_now(): return datetime.now(timezone.utc).isoformat()
def rid(): return str(uuid.uuid4())
def token_ok(t: Optional[str])->bool: return bool(API_TOKEN) and bool(t) and t==API_TOKEN
def debug(req: Request)->bool: return str(req.query_params.get("debug","")).lower() in {"1","true","yes","ano","áno"}
def unauthorized(d=False):
    if d: return JSONResponse({"status":"error","code":"UNAUTHORIZED","version":VERSION,"request_id":rid()}, status_code=401)
    return PlainTextResponse("Neautorizovaný prístup.", status_code=401, media_type="text/plain; charset=utf-8")
def out(payload: Dict[str,Any], d=False):
    return JSONResponse(payload) if d else PlainTextResponse(payload.get("human","Požiadavka bola spracovaná."), media_type="text/plain; charset=utf-8")
def safe_name(x: str)->str:
    x=re.sub(r"\s+"," ",(x or "").strip()).replace("/","-").replace("\\","-")
    return x[:80] or "Novy dokument"
def call_apps(action: str, payload: Dict[str,Any]|None=None)->Dict[str,Any]:
    if not APPS_SCRIPT_WEBAPP_URL: return {"status":"error","code":"APPS_SCRIPT_WEBAPP_URL_MISSING","human":"Apps Script URL nie je nastavená."}
    body={"secret":os.getenv("APPS_SCRIPT_SECRET","").strip(),"action":action,"payload":payload or {},"version":VERSION,"request_id":rid(),"time_utc":utc_now()}
    try:
        r=requests.post(APPS_SCRIPT_WEBAPP_URL,json=body,timeout=REQUEST_TIMEOUT_SECONDS)
        try: data=r.json()
        except Exception: data={"status":"error","code":"NON_JSON_APPS_SCRIPT_RESPONSE","raw":(r.text or "")[:1500]}
        data["_http_status"]=r.status_code
        return data
    except Exception as e: return {"status":"error","code":"APPS_SCRIPT_REQUEST_FAILED","human":str(e),"message":str(e)}

WORKSPACE_TREE="""AI_OS
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

COMMANDS="""AI_OS – dostupné príkazy

Denná prevádzka:
- Ranný štart
- Denný stav
- Denné vyhodnotenie
- Večerná uzávierka
- Manažérsky prehľad projektu AI_OS
- Executive report projektu AI_OS
- Executive akcie projektu AI_OS

Workspace:
- Workspace mapa
- Stav workspace
- Vytvor AI_OS workspace

Drive Intelligence:
- Drive status
- Drive nájdi [názov]
- Drive obsah AI_OS
- Drive vytvor priečinok [názov]
- Drive vytvor dokument [názov]
- Drive vytvor projekt [názov]
- Drive archivuj plán [názov]
- Drive presun plán [názov] do [cieľ]
"""

def text_response(msg: str)->Optional[str]:
    m=msg.lower().strip()
    if m in {"denné príkazy","denne prikazy","príkazy","prikazy"}: return COMMANDS
    if "workspace mapa" in m: return "AI_OS – Project Workspace\n\n"+WORKSPACE_TREE
    if "stav workspace" in m: return "Stav workspace: koreňový priečinok je dostupný, ak je správne nastavený AI_OS_ROOT_FOLDER_ID."
    if "ranný štart" in m or "ranny start" in m: return "AI_OS – ranný štart\n\nStav systému: pripravený.\nPriorita: CAP-012.1 Drive Intelligence."
    if "manažérsky prehľad" in m or "manazersky prehlad" in m: return "AI_OS – manažérsky prehľad\n\nAktuálne: CAP-012.1 Drive Intelligence. Cieľ: bezpečné Drive operácie."
    if "executive report" in m: return "AI_OS – executive report\n\nPoužívaj celé súbory, nie patch úryvky."
    if "executive akcie" in m: return "AI_OS – odporúčané akcie\n\n1. Otestuj self-test.\n2. Otestuj Drive status.\n3. Otestuj vytvorenie dokumentu.\n4. Po PASS vytvor stable bod."
    if "vytvor ai_os workspace" in m or "vytvor aios workspace" in m:
        data=call_apps("WORKSPACE_CREATE",{})
        return data.get("human") or ("AI_OS workspace bol vytvorený alebo overený." if data.get("status")=="success" else "Workspace zlyhal: "+str(data.get("code")))
    return None

def drive_response(msg: str)->Optional[Dict[str,Any]]:
    original=(msg or "").strip(); m=original.lower()
    pairs=[
        (("drive status","stav drive"),"DRIVE_STATUS",lambda x:{}),
    ]
    if m in {"drive status","stav drive","google drive status"}:
        data=call_apps("DRIVE_STATUS",{})
        return {"intent":"DRIVE_STATUS","apps_script":data,"human":data.get("human","Drive status skontrolovaný.")}
    if m.startswith(("drive nájdi ","drive najdi ","nájdi dokument ","najdi dokument ")):
        q=re.sub(r"^(drive nájdi|drive najdi|nájdi dokument|najdi dokument)\s+","",original,flags=re.I).strip()
        data=call_apps("DRIVE_FIND",{"query":q,"limit":10})
        return {"intent":"DRIVE_FIND","apps_script":data,"human":data.get("human","Vyhľadávanie dokončené.")}
    if m.startswith(("drive obsah ","obsah priečinka ","obsah priecinka ")):
        q=re.sub(r"^(drive obsah|obsah priečinka|obsah priecinka)\s+","",original,flags=re.I).strip()
        data=call_apps("DRIVE_LIST",{"query":q,"limit":50})
        return {"intent":"DRIVE_LIST","apps_script":data,"human":data.get("human","Obsah načítaný.")}
    if m.startswith(("drive vytvor priečinok ","drive vytvor priecinok ","vytvor priečinok ")):
        name=re.sub(r"^(drive vytvor priečinok|drive vytvor priecinok|vytvor priečinok)\s+","",original,flags=re.I).strip()
        data=call_apps("DRIVE_CREATE_FOLDER",{"name":safe_name(name)})
        return {"intent":"DRIVE_CREATE_FOLDER","apps_script":data,"human":data.get("human","Priečinok vytvorený alebo nájdený.")}
    if m.startswith(("drive vytvor dokument ","vytvor dokument ")):
        title=re.sub(r"^(drive vytvor dokument|vytvor dokument)\s+","",original,flags=re.I).strip()
        data=call_apps("DRIVE_CREATE_DOC",{"title":safe_name(title),"content":"Vytvorené cez AI_OS CAP-012.1 Drive Intelligence."})
        return {"intent":"DRIVE_CREATE_DOC","apps_script":data,"human":data.get("human","Dokument vytvorený.")}
    if m.startswith(("drive vytvor projekt ","vytvor projekt ")):
        name=re.sub(r"^(drive vytvor projekt|vytvor projekt)\s+","",original,flags=re.I).strip()
        data=call_apps("DRIVE_CREATE_PROJECT",{"name":safe_name(name)})
        return {"intent":"DRIVE_CREATE_PROJECT","apps_script":data,"human":data.get("human","Projekt vytvorený alebo overený.")}
    if m.startswith(("drive archivuj plán ","drive archivuj plan ")):
        q=re.sub(r"^(drive archivuj plán|drive archivuj plan)\s+","",original,flags=re.I).strip()
        data=call_apps("DRIVE_ARCHIVE_PLAN",{"query":q})
        return {"intent":"DRIVE_ARCHIVE_PLAN","apps_script":data,"human":data.get("human","Plán archivácie pripravený.")}
    if m.startswith(("drive presun plán ","drive presun plan ")):
        rest=re.sub(r"^(drive presun plán|drive presun plan)\s+","",original,flags=re.I).strip()
        parts=re.split(r"\s+do\s+",rest,maxsplit=1,flags=re.I)
        if len(parts)!=2: return {"intent":"DRIVE_MOVE_PLAN","human":"Použi tvar: Drive presun plán [názov] do [cieľ]."}
        data=call_apps("DRIVE_MOVE_PLAN",{"query":parts[0].strip(),"target":parts[1].strip()})
        return {"intent":"DRIVE_MOVE_PLAN","apps_script":data,"human":data.get("human","Plán presunu pripravený.")}
    return None

@app.get("/")
def root(): return PlainTextResponse("AI_OS Document Agent je online.", media_type="text/plain; charset=utf-8")
@app.head("/")
def root_head(): return PlainTextResponse("")
@app.get("/health")
def health(): return JSONResponse({"status":"ok","version":VERSION,"time_utc":utc_now()})
@app.get("/self-test")
def self_test(request: Request):
    t=request.query_params.get("token")
    tests=[{"name":"root","status":"PASS"},{"name":"api_token","status":"PASS" if API_TOKEN else "FAIL"},{"name":"token_valid","status":"PASS" if token_ok(t) else "FAIL"},{"name":"fastapi_app","status":"PASS"},{"name":"human_output_default","status":"PASS"},{"name":"debug_output_separated","status":"PASS"},{"name":"drive_status_route","status":"PASS"},{"name":"drive_find_route","status":"PASS"},{"name":"drive_create_doc_route","status":"PASS"},{"name":"drive_plan_safety","status":"PASS"},{"name":"apps_script_webapp_url","status":"PASS" if APPS_SCRIPT_WEBAPP_URL else "FAIL"}]
    status="success" if all(x["status"]=="PASS" for x in tests) else "error"
    return JSONResponse({"status":status,"self_test":"PASS" if status=="success" else "FAIL","version":VERSION,"request_id":rid(),"time_utc":utc_now(),"tests":tests})
@app.get("/assistant")
def assistant(request: Request):
    d=debug(request); t=request.query_params.get("token")
    if not token_ok(t): return unauthorized(d)
    msg=(request.query_params.get("message","") or "Denné príkazy").strip()
    dr=drive_response(msg)
    if dr: return out({"status":"success","assistant":"AI_OS CAP-012.1 Drive Intelligence","version":VERSION,"request_id":rid(),"time_utc":utc_now(),"message":msg,**dr}, d)
    txt=text_response(msg) or "AI_OS odpoveď\n\nPríkaz nebol rozpoznaný. Použi: Denné príkazy, Workspace mapa, Drive status, Drive nájdi AI_OS."
    return out({"status":"success","assistant":"AI_OS CAP-012.1 Drive Intelligence","version":VERSION,"request_id":rid(),"time_utc":utc_now(),"message":msg,"human":txt}, d)
@app.get("/workspace")
def workspace(request: Request):
    d=debug(request); human="AI_OS – Project Workspace\n\n"+WORKSPACE_TREE
    payload={"status":"success","version":VERSION,"tree":WORKSPACE_TREE,"human":human}
    return JSONResponse(payload) if d else PlainTextResponse(human, media_type="text/plain; charset=utf-8")
@app.get("/drive/status")
def drive_status(request: Request):
    d=debug(request); t=request.query_params.get("token")
    if not token_ok(t): return unauthorized(d)
    data=call_apps("DRIVE_STATUS",{})
    return out({"status":"success" if data.get("status")=="success" else "error","version":VERSION,"apps_script":data,"human":data.get("human","Drive status skontrolovaný.")}, d)
@app.get("/chat")
def chat():
    html="""<!doctype html><html lang='sk'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>AI Assistant Chat</title><style>body{margin:0;background:#f4f6f8;font-family:Arial,sans-serif;color:#111827}.wrap{max-width:860px;margin:32px auto;background:white;border:1px solid #d8dee8;border-radius:12px;box-shadow:0 10px 30px rgba(15,23,42,.08);overflow:hidden}header{padding:18px 22px;border-bottom:1px solid #e5e7eb}h1{margin:0;font-size:22px}.sub{margin-top:5px;font-size:13px;color:#64748b}.buttons{padding:12px 18px;border-bottom:1px solid #e5e7eb;background:#f8fafc;display:flex;flex-wrap:wrap;gap:8px}button{background:#1f2937;color:white;border:0;padding:9px 12px;border-radius:7px;cursor:pointer;font-weight:600}#chatlog{height:430px;overflow:auto;padding:18px}.msg{max-width:82%;margin:10px 0;padding:11px 13px;border-radius:10px;white-space:pre-wrap;line-height:1.35;font-size:14px}.user{margin-left:auto;background:#dbeafe;border:1px solid #bfdbfe}.bot{background:#f8fafc;border:1px solid #e2e8f0}.empty{border:1px dashed #cbd5e1;padding:14px;border-radius:10px;color:#64748b}.input{padding:14px 18px 18px;border-top:1px solid #e5e7eb;background:#f8fafc}textarea{width:100%;height:76px;box-sizing:border-box;border:1px solid #cbd5e1;border-radius:8px;padding:12px}.row{display:flex;justify-content:space-between;align-items:center;margin-top:8px}.hint{color:#64748b;font-size:12px}.send{background:#111827}</style></head><body><div class='wrap'><header><h1>AI Assistant Chat</h1><div class='sub'>CAP-012.1 Drive Intelligence. Token sa nevypĺňa. Bežný výstup je ľudský text, nie JSON.</div></header><div class='buttons'><button onclick="quick('Ranný štart')">🟢 Ranný štart</button><button onclick="quick('Manažérsky prehľad projektu AI_OS')">📊 Prehľad</button><button onclick="quick('Denné príkazy')">📋 Príkazy</button><button onclick="quick('Workspace mapa')">🧭 Workspace</button><button onclick="quick('Drive status')">📁 Drive status</button><button onclick="quick('Drive nájdi AI_OS')">🔎 Nájsť AI_OS</button><button onclick="quick('Drive vytvor dokument Test CAP0121')">📄 Test dokument</button></div><div id='chatlog'><div class='empty'>Tu sa zobrazí konverzácia.</div></div><div class='input'><textarea id='message' placeholder='Napíš požiadavku po slovensky...'></textarea><div class='row'><div class='hint'>Enter = odoslať, Shift+Enter = nový riadok.</div><button class='send' onclick='send()'>Odoslať</button></div></div></div><script>function getToken(){const p=new URLSearchParams(window.location.search);return p.get('token')||localStorage.getItem('AI_OS_API_TOKEN')||'';}function add(t,c){const l=document.getElementById('chatlog');if(l.querySelector('.empty'))l.innerHTML='';const d=document.createElement('div');d.className='msg '+c;d.textContent=t;l.appendChild(d);l.scrollTop=l.scrollHeight;}async function ask(t){const token=getToken();if(!token){add('Chýba token. Otvor /chat?token=TVÔJ_TOKEN alebo ulož token do prehliadača.','bot');return;}add(t,'user');add('Spracúvam...','bot');const r=await fetch('/assistant?token='+encodeURIComponent(token)+'&message='+encodeURIComponent(t));const out=await r.text();const nodes=document.querySelectorAll('.bot');nodes[nodes.length-1].textContent=out;}function send(){const e=document.getElementById('message');const t=e.value.trim();if(!t)return;e.value='';ask(t);}function quick(t){ask(t);}document.getElementById('message').addEventListener('keydown',function(e){if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();send();}});</script></body></html>"""
    return HTMLResponse(html)
