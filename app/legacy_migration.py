from sqlalchemy.orm import Session

from .schemas import LegacyTaskImportRequest
from .services import import_legacy_tasks


LEGACY_TASKS_DOCUMENT_ID = "1PQ-J04TWXASe-Q4GsBg69E1l7TE6aAUG4vj7fyVsDIQ"
LEGACY_TASKS_REVISION_ID = "ALtnJHxo-TYSxy-XChHo-lU8DZfh9ACw-VYF-tgz5qkIdd8X8yJSDs2KoBONZKcxRPPBUx2SL4NP-dKkGGBQTmjgZu4h1wQ0IuF3KhioX-Q"

# Immutable snapshot of the five records reviewed in AI_OS_TASKS on 2026-07-21.
# Importing the snapshot instead of re-reading a mutable document makes the
# migration deterministic and auditable.
LEGACY_TASK_SNAPSHOT = [
    {
        "external_id": "TASK-20260703-233250",
        "status": "DONE",
        "priority": "HIGH",
        "project_key": "AI_OS",
        "owner": "Daniel",
        "title": "AI_OS v2 stabilizačný test",
        "description": "Vytvor úlohu AI_OS v2 stabilizačný test priorita vysoká projekt AI_OS  [Bádateľ spracováva]  [Bádateľ: Na základe poskytnutých výsledkov vyhľadávania neexistujú priame informácie ani špecifické detaily týkajúce sa metodík, výsledkov alebo výziev 'AI_OS v2 stabilizačného testu'. Výsledky sa skôr delia n]",
    },
    {
        "external_id": "TEST-001",
        "status": "DONE",
        "priority": "LOW",
        "project_key": "AI_OS",
        "owner": "Daniel",
        "title": "Testovacia úloha pre CAP-019",
        "description": "Over stav Model Context Protocol v roku 2026  [Bádateľ spracováva]  [Bádateľ: Na základe poskytnutých výsledkov vyhľadávania neboli nájdené žiadne konkrétne informácie, ktoré by priamo definovali alebo popisovali testovaciu úlohu označenú ako \"CAP-019\". Termín \"CAP\" sa v súvisl]",
    },
    {
        "external_id": "ÚLOHA-202607020-001",
        "status": "STAV",
        "priority": "VYSOKÁ",
        "project_key": "AI_OS",
        "owner": "DAMIEL",
        "title": "Kontrola funkčnosti",
        "description": "Bádatel v AI_OS funguje ako?",
    },
    {
        "external_id": "ÚLOHA-202607020-002",
        "status": "STAV",
        "priority": "VYSOKÁ",
        "project_key": "AI_OS",
        "owner": "DAMIEL",
        "title": "Kontrola funkčnosti 2",
        "description": "Bádatel dáva kam odpovede?",
    },
    {
        "external_id": "TASK-20260720-122429",
        "status": "DONE",
        "priority": "LOW",
        "project_key": "AI_OS",
        "owner": "Daniel",
        "title": "Test CAP-020 end-to-end",
        "description": "Testovacia uloha na overenie mobilneho formulara po redeployi Apps Script  [Bádateľ spracováva]  [Bádateľ: Vyhľadávacie výsledky sa primárne zameriavajú na \"End-Cap Test Caps\" (koncové testovacie uzávery) používané na hydrostatické tlakové testovanie potrubí, armatúr a ventilov. Tieto uzávery sú navrhnuté ]",
    },
]


def run_legacy_task_migration(db: Session, *, apply: bool) -> dict:
    base = {
        "source_document_id": LEGACY_TASKS_DOCUMENT_ID,
        "tasks": LEGACY_TASK_SNAPSHOT,
    }
    preview = import_legacy_tasks(
        db,
        LegacyTaskImportRequest(**base, dry_run=True),
    )
    result = {
        "source_document_id": LEGACY_TASKS_DOCUMENT_ID,
        "source_revision_id": LEGACY_TASKS_REVISION_ID,
        "received": preview.received,
        "importable": preview.imported,
        "skipped_existing": preview.skipped_existing,
        "applied": 0,
    }
    if apply and preview.imported:
        applied = import_legacy_tasks(
            db,
            LegacyTaskImportRequest(**base, dry_run=False),
        )
        result["applied"] = applied.imported
        result["skipped_existing"] = applied.skipped_existing
    return result
