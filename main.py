"""
AI_OS v2.3.1 – CAP-010.1 Daily Time Blocks
Patch pre Render main.py.
Nevymieňa celý main.py. Dopĺňa routing a čistý výstup.
"""

VERSION = "v2.3.1-cap0101-daily-time-blocks"

CAP0101_INTENTS = {
    "time_blocks": ["časové bloky", "dnešné bloky", "denné bloky"],
    "daily_plan_blocks": ["denný plán s blokmi", "naplánuj deň", "plán dňa s blokmi"]
}


def cap0101_detect_intent(message: str) -> str | None:
    text = (message or "").lower().strip()
    for intent, phrases in CAP0101_INTENTS.items():
        if any(p in text for p in phrases):
            return intent
    return None


def cap0101_default_blocks() -> list[dict]:
    return [
        {"name": "Ranný štart", "start": "06:30", "end": "07:00", "purpose": "Zorientovať deň a priority."},
        {"name": "Hlboká práca 1", "start": "08:30", "end": "10:30", "purpose": "Najdôležitejšia úloha dňa bez rušenia."},
        {"name": "Operatíva", "start": "10:45", "end": "12:00", "purpose": "E-maily, faktúry, odpovede, rýchle rozhodnutia."},
        {"name": "Hlboká práca 2", "start": "13:00", "end": "14:30", "purpose": "Strategická alebo tvorivá práca."},
        {"name": "Kontrola a blokery", "start": "15:00", "end": "15:30", "purpose": "Riziká, otvorené body a ďalší krok."},
        {"name": "Večerná uzávierka", "start": "17:30", "end": "18:00", "purpose": "Uzavrieť deň a pripraviť zajtrajšok."},
    ]


def cap0101_blocks_text(blocks: list[dict]) -> str:
    lines = ["AI_OS – denné časové bloky", ""]
    for b in blocks:
        lines.append(f"{b['start']}–{b['end']}  {b['name']}")
        lines.append(f"- {b['purpose']}")
    return "\n".join(lines).strip()


def cap0101_daily_plan_text() -> str:
    blocks = cap0101_default_blocks()
    return (
        "AI_OS – denný plán s časovými blokmi\n\n"
        + cap0101_blocks_text(blocks)
        + "\n\nPriorita dňa:\n- Vyber 1 najdôležitejšiu úlohu a vlož ju do Hlboká práca 1.\n\n"
        + "Kontrola kvality:\n- Plán má mať čas, prioritu a ďalší konkrétny krok."
    )


def cap0101_handle(message: str) -> dict:
    intent = cap0101_detect_intent(message)
    if intent == "time_blocks":
        return {"status": "success", "capability_id": "CAP-010.1", "answer": cap0101_blocks_text(cap0101_default_blocks())}
    if intent == "daily_plan_blocks":
        return {"status": "success", "capability_id": "CAP-010.1", "answer": cap0101_daily_plan_text()}
    return {"status": "error", "code": "CAP0101_NO_MATCH"}

# Integrácia do existujúceho /assistant handlera:
# 1. Po načítaní message pridaj:
# cap0101_intent = cap0101_detect_intent(message)
# if cap0101_intent:
#     result = cap0101_handle(message)
#     return clean_or_json_response(result, debug=debug)
#
# 2. Ak nemáš clean_or_json_response, vráť pri debug=false čistý text:
# if not debug:
#     return PlainTextResponse(result.get("answer", "OK"))
# return JSONResponse(result)
#
# 3. Do self-test zoznamu pridaj:
# {"name": "route_daily_time_blocks", "status": "PASS"}
