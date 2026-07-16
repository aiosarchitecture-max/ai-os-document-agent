# AI_OS Document Agent — Sprostredkovateľ (Orchestrator)

Aktuálna verzia: **v2.11.0-cap017-github-direct-write**

## Čo tento repozitár obsahuje

FastAPI server (`main.py`), ktorý slúži ako **Sprostredkovateľ (Orchestrator)** medzi Claude
a Google Drive projektu AI_OS. Beží na Render: https://ai-os-document-agent.onrender.com

## Architektúra (podľa AI_OS_GLOSSARY_v2.0)

- **Zapisovateľ (Writer)** — Claude v konverzácii s Danielom. Jediný, kto skutočne vytvára,
  presúva, premenováva alebo maže dokumenty v Google Drive.
- **Sprostredkovateľ (Orchestrator)** — tento server. Spája Zapisovateľa, Kontrolóra a Drive.
- **Kontrolór (Reviewer)** — nezávislý Claude Haiku model, ktorý na požiadanie kontroluje
  dokumenty oproti AI_OS_DOCUMENTATION_STANDARD. Nemá žiadne oprávnenie na zápis.
- **Zápisová vrstva (Apps Script)** — Google Apps Script projekt, ktorý ako jediný fyzicky
  mení obsah Google Drive.
- **Protokol kontrol (Quality Log)** — AI_OS_QUALITY_LOG, kde sa zaznamenáva každá kontrola.

## Kľúčové schopnosti (Capabilities)

- **CAP-014 — MCP Bridge & File Operations**: priame MCP pripojenie pre Claude (`/mcp`),
  nástroje na presun/premenovanie/trash súborov, s povinným `confirm_id`.
- **CAP-015/016 — Quality Workflow**: `aios_review_document` nezávisle skontroluje dokument
  (súlad so štandardom + správne umiestnenie), vráti `workflow_status`, zapíše do Quality Logu.
- **CAP-017 — GitHub Direct Write Bridge**: `aios_github_write_file` zapisuje priamo do tohto
  repozitára cez vlastný Personal Access Token, nezávisle od cudzej OAuth appky.

## Premenné prostredia (Render)

`API_TOKEN`, `APPS_SCRIPT_WEBAPP_URL`, `APPS_SCRIPT_SECRET`, `AI_OS_ROOT_FOLDER_ID`,
`ANTHROPIC_API_KEY`, `REVIEWER_MODEL` (voliteľné), `GITHUB_PAT`, `GITHUB_OWNER`, `GITHUB_REPO`

## Poznámka k histórii

Staršie README opisovalo samostatný, nikdy nenasadený návrh ("v0.9.0 Knowledge Layer").
Nahradené, aby presne zodpovedalo tomu, čo skutočne beží na Render. Tento zápis bol vykonaný
priamo cez CAP-017 GitHub Direct Write Bridge, 16.7.2026.
