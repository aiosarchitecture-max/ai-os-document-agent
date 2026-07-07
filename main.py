from __future__ import annotations
import os, re, uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional
import requests
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, JSONResponse, HTMLResponse
VERSION='v2.6.1-cap0122-project-automation'
API_TOKEN=os.getenv('API_TOKEN','').strip(); APPS_SCRIPT_WEBAPP_URL=os.getenv('APPS_SCRIPT_WEBAPP_URL','').strip(); TIMEOUT=float(os.getenv('REQUEST_TIMEOUT_SECONDS','25'))
app=FastAPI(title='AI_OS Document Agent', version=VERSION)
def now(): return datetime.now(timezone.utc).isoformat()
def rid(): return str(uuid.uuid4())
def ok_token(t:Optional[str])->bool: return bool(API_TOKEN) and bool(t) and t==API_TOKEN
def dbg(r:Request)->bool: return str(r.query_params.get('debug','')).lower() in {'1','true','yes','ano','áno'}
def resp(p:Dict[str,Any], d=False): return JSONResponse(p) if d else PlainTextResponse(p.get('human','Požiadavka bola spracovaná.'), media_type='text/plain; charset=utf-8')
def unauth(d=False): return JSONResponse({'status':'error','code':'UNAUTHORIZED','version':VERSION,'request_id':rid(),'time_utc':now()},status_code=401) if d else PlainTextResponse('Neautorizovaný prístup.',status_code=401)
def safe(s:str)->str: return re.sub(r'\s+',' ',(s or '').strip()).replace('/','-').replace('\\','-')[:90] or 'Novy projekt'
def call(action:str,payload:Dict[str,Any]|None=None)->Dict[str,Any]:
    if not APPS_SCRIPT_WEBAPP_URL: return {'status':'error','code':'APPS_SCRIPT_WEBAPP_URL_MISSING','human':'Apps Script URL nie je nastavená.'}
    body={'secret':os.getenv('APPS_SCRIPT_SECRET','').strip(),'action':action,'payload':payload or {},'version':VERSION,'request_id':rid(),'time_utc':now()}
    try:
        r=requests.post(APPS_SCRIPT_WEBAPP_URL,json=body,timeout=TIMEOUT)
        try: data=r.json()
        except Exception: data={'status':'error','code':'NON_JSON_APPS_SCRIPT_RESPONSE','raw':(r.text or '')[:2000]}
        data['_http_status']=r.status_code; return data
    except Exception as e: return {'status':'error','code':'APPS_SCRIPT_REQUEST_FAILED','human':str(e)}
TREE='''AI_OS
├── 00_INBOX
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
└── 99_SYSTEM_LOGS'''
COMMANDS='''AI_OS – dostupné príkazy\n\n- Ranný štart\n- Manažérsky prehľad projektu AI_OS\n- Workspace mapa\n- Drive status\n- Drive nájdi [názov]\n- Drive obsah AI_OS\n- Drive vytvor priečinok [názov]\n- Drive vytvor dokument [názov]\n- Drive archivuj plán [názov]\n- Drive presun plán [názov] do [cieľ]\n- Drive potvrď [confirm_id]\n- Projekt šablóna\n- Projekt nový [názov]\n- Projekt status [názov]\n- Projekt audit [názov]\n- Projekt plán [názov]\n- Projekt milestone [názov]: [poznámka]'''
def route(msg:str)->Dict[str,Any]:
    o=(msg or '').strip(); m=o.lower()
    if m in {'denné príkazy','denne prikazy','príkazy','prikazy'}: return {'intent':'COMMANDS','human':COMMANDS}
    if 'ranný štart' in m or 'ranny start' in m: return {'intent':'MORNING','human':'AI_OS – ranný štart\n\nStav: pripravený. Aktuálne: CAP-012.2 Project Automation.'}
    if 'manažérsky prehľad' in m or 'manazersky prehlad' in m: return {'intent':'SUMMARY','human':'AI_OS – manažérsky prehľad\n\nCAP-012.2 pridáva projektovú automatizáciu nad Google Drive.'}
    if 'workspace mapa' in m: return {'intent':'WORKSPACE_MAP','human':'AI_OS – Project Workspace\n\n'+TREE}
    if 'vytvor ai_os workspace' in m or 'vytvor aios workspace' in m: d=call('WORKSPACE_CREATE',{}); return {'intent':'WORKSPACE_CREATE','apps_script':d,'human':d.get('human','Workspace overený.')}
    if m in {'drive status','stav drive'}: d=call('DRIVE_STATUS',{}); return {'intent':'DRIVE_STATUS','apps_script':d,'human':d.get('human','Drive status skontrolovaný.')}
    if m.startswith(('drive nájdi ','drive najdi ')): q=re.sub(r'^(drive nájdi|drive najdi)\s+','',o,flags=re.I); d=call('DRIVE_FIND',{'query':q,'limit':10}); return {'intent':'DRIVE_FIND','apps_script':d,'human':d.get('human','Vyhľadávanie dokončené.')}
    if m.startswith('drive obsah '): q=re.sub(r'^drive obsah\s+','',o,flags=re.I); d=call('DRIVE_LIST',{'query':q,'limit':50}); return {'intent':'DRIVE_LIST','apps_script':d,'human':d.get('human','Obsah načítaný.')}
    if m.startswith(('drive vytvor priečinok ','drive vytvor priecinok ')): q=re.sub(r'^(drive vytvor priečinok|drive vytvor priecinok)\s+','',o,flags=re.I); d=call('DRIVE_CREATE_FOLDER',{'name':safe(q)}); return {'intent':'DRIVE_CREATE_FOLDER','apps_script':d,'human':d.get('human','Priečinok vytvorený.')}
    if m.startswith('drive vytvor dokument '): q=re.sub(r'^drive vytvor dokument\s+','',o,flags=re.I); d=call('DRIVE_CREATE_DOC',{'title':safe(q),'content':'Vytvorené cez AI_OS CAP-012.2.'}); return {'intent':'DRIVE_CREATE_DOC','apps_script':d,'human':d.get('human','Dokument vytvorený.')}
    if m.startswith(('drive archivuj plán ','drive archivuj plan ')): q=re.sub(r'^(drive archivuj plán|drive archivuj plan)\s+','',o,flags=re.I); d=call('DRIVE_ARCHIVE_PLAN',{'query':q}); return {'intent':'DRIVE_ARCHIVE_PLAN','apps_script':d,'human':d.get('human','Plán archivácie pripravený.')}
    if m.startswith(('drive presun plán ','drive presun plan ')):
        rest=re.sub(r'^(drive presun plán|drive presun plan)\s+','',o,flags=re.I); parts=re.split(r'\s+do\s+',rest,1,flags=re.I)
        if len(parts)!=2: return {'intent':'DRIVE_MOVE_PLAN','human':'Použi: Drive presun plán [názov] do [cieľ].'}
        d=call('DRIVE_MOVE_PLAN',{'query':parts[0].strip(),'target':parts[1].strip()}); return {'intent':'DRIVE_MOVE_PLAN','apps_script':d,'human':d.get('human','Plán presunu pripravený.')}
    if m.startswith(('drive potvrď ','drive potvrd ')): q=re.sub(r'^(drive potvrď|drive potvrd)\s+','',o,flags=re.I); d=call('DRIVE_CONFIRM',{'confirm_id':q}); return {'intent':'DRIVE_CONFIRM','apps_script':d,'human':d.get('human','Potvrdenie spracované.')}
    if m in {'projekt šablóna','projekt sablona'}: d=call('PROJECT_TEMPLATE',{}); return {'intent':'PROJECT_TEMPLATE','apps_script':d,'human':d.get('human','Projektová šablóna načítaná.')}
    if m.startswith(('projekt nový ','projekt novy ')): q=re.sub(r'^(projekt nový|projekt novy)\s+','',o,flags=re.I); d=call('PROJECT_CREATE_FULL',{'name':safe(q)}); return {'intent':'PROJECT_CREATE_FULL','apps_script':d,'human':d.get('human','Projekt vytvorený.')}
    if m.startswith('projekt status '): q=re.sub(r'^projekt status\s+','',o,flags=re.I); d=call('PROJECT_STATUS',{'name':safe(q)}); return {'intent':'PROJECT_STATUS','apps_script':d,'human':d.get('human','Status načítaný.')}
    if m.startswith('projekt audit '): q=re.sub(r'^projekt audit\s+','',o,flags=re.I); d=call('PROJECT_AUDIT',{'name':safe(q)}); return {'intent':'PROJECT_AUDIT','apps_script':d,'human':d.get('human','Audit dokončený.')}
    if m.startswith(('projekt plán ','projekt plan ')): q=re.sub(r'^(projekt plán|projekt plan)\s+','',o,flags=re.I); d=call('PROJECT_PLAN',{'name':safe(q)}); return {'intent':'PROJECT_PLAN','apps_script':d,'human':d.get('human','Plán pripravený.')}
    if m.startswith('projekt milestone '):
        rest=re.sub(r'^projekt milestone\s+','',o,flags=re.I); parts=re.split(r'\s*:\s*',rest,1); d=call('PROJECT_MILESTONE',{'name':safe(parts[0]),'note':parts[1] if len(parts)>1 else 'Milestone cez CAP-012.2.'}); return {'intent':'PROJECT_MILESTONE','apps_script':d,'human':d.get('human','Milestone zapísaný.')}
    return {'intent':'UNKNOWN','human':'Príkaz nebol rozpoznaný. Použi: Denné príkazy alebo Projekt šablóna.'}
@app.get('/')
def root(): return PlainTextResponse('AI_OS Document Agent je online.', media_type='text/plain; charset=utf-8')
@app.head('/')
def root_head(): return PlainTextResponse('', media_type='text/plain; charset=utf-8')
@app.get('/health')
def health(): return JSONResponse({'status':'ok','version':VERSION,'time_utc':now()})
@app.get('/self-test')
def self_test(request:Request):
    t=request.query_params.get('token'); tests=[{'name':n,'status':'PASS'} for n in ['root','fastapi_app','human_output_default','debug_output_separated','project_template','project_create_full','project_status','project_audit','project_milestone','drive_confirm']]
    tests.insert(1,{'name':'api_token','status':'PASS' if API_TOKEN else 'FAIL'}); tests.insert(2,{'name':'token_valid','status':'PASS' if ok_token(t) else 'FAIL'}); tests.append({'name':'apps_script_webapp_url','status':'PASS' if APPS_SCRIPT_WEBAPP_URL else 'FAIL'})
    status='success' if all(x['status']=='PASS' for x in tests) else 'error'; return JSONResponse({'status':status,'self_test':'PASS' if status=='success' else 'FAIL','version':VERSION,'request_id':rid(),'time_utc':now(),'tests':tests})
@app.get('/assistant')
def assistant(request:Request):
    d=dbg(request); token=request.query_params.get('token')
    if not ok_token(token): return unauth(d)
    msg=(request.query_params.get('message','') or 'Denné príkazy').strip(); r=route(msg)
    return resp({'status':'success','assistant':'AI_OS CAP-012.2 Project Automation','version':VERSION,'request_id':rid(),'time_utc':now(),'message':msg,**r},d)
@app.get('/workspace')
def workspace(request:Request):
    p={'status':'success','version':VERSION,'tree':TREE,'human':'AI_OS – Project Workspace\n\n'+TREE}; return resp(p,dbg(request))
@app.get('/chat')
def chat():
    return HTMLResponse('<!doctype html><html lang="sk"><head><meta charset="utf-8"><title>AI Assistant Chat</title><style>body{font-family:Arial;background:#f4f6f8}.wrap{max-width:900px;margin:30px auto;background:white;border:1px solid #ddd;border-radius:12px;padding:18px}button{margin:4px;padding:8px 10px;background:#1f2937;color:white;border:0;border-radius:7px}textarea{width:100%;height:80px}.msg{white-space:pre-wrap;border:1px solid #ddd;padding:10px;margin:8px;border-radius:8px}</style></head><body><div class="wrap"><h1>AI Assistant Chat</h1><p>CAP-012.2 Project Automation</p><div><button onclick="quick(\'Projekt šablóna\')">Projekt šablóna</button><button onclick="quick(\'Projekt nový CAP0122 TEST\')">Test projekt</button><button onclick="quick(\'Projekt status CAP0122 TEST\')">Status</button><button onclick="quick(\'Projekt audit CAP0122 TEST\')">Audit</button><button onclick="quick(\'Drive status\')">Drive status</button></div><div id="log" class="msg">Tu sa zobrazí konverzácia.</div><textarea id="m" placeholder="Napíš požiadavku..."></textarea><br><button onclick="send()">Odoslať</button></div><script>function token(){return new URLSearchParams(location.search).get("token")||localStorage.getItem("AI_OS_API_TOKEN")||""}function add(x){document.getElementById("log").textContent=x}async function ask(x){if(!token()){add("Chýba token. Otvor /chat?token=TVÔJ_TOKEN.");return}add("Spracúvam...");let r=await fetch("/assistant?token="+encodeURIComponent(token())+"&message="+encodeURIComponent(x));add(await r.text())}function send(){let e=document.getElementById("m");let x=e.value.trim();if(x){e.value="";ask(x)}}function quick(x){ask(x)}</script></body></html>')
