# Apps Script bridge: bezpečné staging nasadenie

Tento postup pripája AI_OS Core staging ku Google Drive bez zmeny produkčného `main` a bez vyradenia starého mosta.

## Bezpečnostné hranice

- Most prijíma iba pevný zoznam operácií; ľubovoľný príkaz nie je možný.
- Každý príkaz vyžaduje tajomstvo uložené v Script Properties a v Render Environment.
- Všetky súbory a cieľové priečinky musia byť pod koreňom `AI_OS_ROOT_FOLDER_ID`.
- Zápisové príkazy vyžadujú `requestId`; opakovaná požiadavka sa nevykoná druhýkrát.
- Mazanie, presun a premenovanie vyžadujú aj jednorazové schválenie vo FastAPI.
- Vstupy majú veľkostné limity a text pre Sheets je chránený pred vložením vzorca.

## Script Properties

V Apps Script projekte nastavte v **Project Settings → Script properties**:

| Property | Hodnota |
|---|---|
| `AI_OS_BRIDGE_SECRET` | Nové náhodné tajomstvo; nezverejňovať v kóde ani na screenshote |
| `AI_OS_ROOT_FOLDER_ID` | ID koreňového priečinka AI_OS |

## Web app

Nasadiť ako novú verziu cez **Deploy → Manage deployments → Edit → New version**:

- Execute as: **Me**
- Who has access: **Anyone**

Verejná dostupnosť URL sama osebe nedáva prístup: každý POST navyše prechádza kontrolou tajomstva a koreňového priečinka.

## Render staging premenné

V službe `ai-os-core-staging` nastavte:

| Key | Hodnota |
|---|---|
| `APPS_SCRIPT_WEBAPP_URL` | URL nového Apps Script deploymentu končiaca `/exec` |
| `APPS_SCRIPT_SECRET` | Presne rovnaké tajomstvo ako `AI_OS_BRIDGE_SECRET` |
| `AI_OS_ROOT_FOLDER_ID` | Rovnaké ID koreňového priečinka |

Po uložení premenných vykoná Render nový deploy.

## Overenie v správnom poradí

1. `GET /health` musí vrátiť `200` a `database: ok`.
2. Autorizovaný `GET /integrations/apps-script/health` musí vrátiť `status: success`, `pong: true` a správne `rootFolderId`.
3. Nesprávny Apps Script secret musí byť odmietnutý.
4. Pokus o prácu so súborom mimo AI_OS koreňa musí byť odmietnutý.
5. Až potom vytvoriť jeden testovací dokument v samostatnom staging podpriečinku.
6. Rovnaký zápis s rovnakým `requestId` musí vrátiť `duplicate: true` a nesmie vytvoriť druhý dokument.

## Návrat späť

Ak kontrola zlyhá, v Renderi odstráňte alebo vráťte tri Apps Script premenné. Starý most a produkčný `main` zostávajú nedotknuté. Apps Script deployment možno archivovať bez mazania zdrojového projektu.
