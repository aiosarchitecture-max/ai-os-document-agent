# AI_OS Document Agent v0.1

## Účel
Prvá funkčná verzia Dokumentačného agenta AI OS.

Vie:
- overiť prístup k AI_OS priečinku,
- vytvoriť testovací Google Docs dokument v AI_OS,
- automaticky vytvoriť alebo použiť Google Sheet `AI_OS_CHANGE_LOG`,
- zapísať záznam o zmene do Change Logu.

## Súbory
- `main.py` – aplikácia agenta
- `requirements.txt` – Python závislosti
- `render.yaml` – Render konfigurácia
- `.env.example` – vzor premenných prostredia

## Render premenné
- `API_TOKEN`
- `AI_OS_ROOT_FOLDER_ID`
- `GOOGLE_SERVICE_ACCOUNT_JSON_B64`

## Test po nasadení
1. `/health`
2. `/root-check?token=TV0J_TOKEN`
3. `/test-write?token=TV0J_TOKEN`

## Bezpečnosť
JSON kľúč nikdy neukladať do GitHub repozitára.
JSON kľúč nikdy neposielať do chatu.
Na Render vložiť iba base64 obsah ako environment variable.