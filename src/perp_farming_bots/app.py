from __future__ import annotations

import fcntl
import logging
import os
from pathlib import Path

from nicegui import app, ui

from .api import register_routes
from .markets import Markets
from .notifications import Notifications
from .runtime import Runtime
from .security import Secrets
from .store import Store
from .trading import Accounts
from .ui import install_ui


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    # HTTPX logs outbound URLs at INFO, including Telegram's token-bearing path.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    directory = Path(os.environ.get("PFB_DATA_DIR", "data")).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    handle = (directory / "instance.lock").open("a+")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        handle.close()
        raise RuntimeError("已有实例使用此数据目录，请先停止旧实例") from exc
    secrets = Secrets(directory)
    store = Store(directory / "app.live.db")
    markets = Markets()
    accounts = Accounts(store, markets, secrets)
    runtime = Runtime(store, markets, accounts)
    notifications = Notifications(store, secrets)
    register_routes(app, store, runtime, notifications)
    install_ui(store, runtime, notifications)

    async def startup():
        await runtime.start()
        await notifications.start()

    async def shutdown():
        await runtime.stop()
        await notifications.stop()
        store.close()
        handle.close()

    app.on_startup(startup)
    app.on_shutdown(shutdown)
    logging.getLogger(__name__).info("Native trading application. Authentication design is pending.")
    ui.run(
        host=os.environ.get("PFB_HOST", "127.0.0.1"),
        port=int(os.environ.get("PFB_PORT", "8080")),
        title="Perp Farming Bots",
        show=False,
        reload=False,
    )


if __name__ == "__main__":
    main()
