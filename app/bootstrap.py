import asyncio

from app.settings import get_settings
from app.storage.database import init_db


async def bootstrap() -> None:
    settings = get_settings()
    await init_db(settings.database_path)


def main() -> None:
    asyncio.run(bootstrap())


if __name__ == "__main__":
    main()
