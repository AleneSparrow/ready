import asyncio

import uvicorn

from . import bootstrap, config
from .api import app
from .telegram_bot import run_bot


async def _main() -> None:
    bootstrap.run()

    uvicorn_config = uvicorn.Config(app, host="0.0.0.0", port=config.PORT, log_level="info")
    server = uvicorn.Server(uvicorn_config)

    await asyncio.gather(server.serve(), run_bot())


if __name__ == "__main__":
    asyncio.run(_main())
