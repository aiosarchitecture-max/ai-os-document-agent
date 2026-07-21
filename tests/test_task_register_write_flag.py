import asyncio
from types import SimpleNamespace

from app import services


def test_configured_register_does_not_enable_dual_write(monkeypatch):
    monkeypatch.setattr(
        services,
        "get_settings",
        lambda: SimpleNamespace(
            task_register_spreadsheet_id="configured-sheet",
            task_register_dual_write_enabled=False,
        ),
    )

    result = asyncio.run(services.sync_task_to_register(None, None))

    assert result == {"status": "disabled"}
