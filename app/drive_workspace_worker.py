import asyncio

from .db import SessionLocal, create_schema
from .drive_workspace import sync_drive_workspace


async def main() -> None:
    create_schema()
    with SessionLocal() as db:
        result = await sync_drive_workspace(db)
        print(result.as_dict())


if __name__ == "__main__":
    asyncio.run(main())
