from fastapi import Depends
from sqlalchemy.orm import Session

from .db import get_db
from .drive_workspace import sync_drive_workspace
from .main import app
from .security import require_api_token


@app.post(
    "/integrations/drive-workspace/sync",
    dependencies=[Depends(require_api_token)],
)
async def drive_workspace_sync(db: Session = Depends(get_db)) -> dict:
    """Import human-authored Drive rows, then project current task versions back to Drive."""
    return (await sync_drive_workspace(db)).as_dict()
