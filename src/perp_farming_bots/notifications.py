from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx

from .security import Secrets
from .store import Store, alerts

logger = logging.getLogger(__name__)


class Notifications:
    def __init__(self, store: Store, secrets: Secrets):
        self.store, self.secrets = store, secrets
        self.task: asyncio.Task[None] | None = None
        self.client = httpx.AsyncClient(timeout=8)

    def config(self) -> dict[str, Any] | None:
        value = self.store.setting("telegram")
        return json.loads(self.secrets.decrypt(value)) if value else None

    def save(self, token: str, chat_id: str) -> None:
        if not token or not chat_id or ":" not in token:
            raise ValueError("请填写 Bot Token 和 Chat ID")
        self.store.save_setting(
            "telegram", self.secrets.encrypt(json.dumps({"token": token, "chat_id": chat_id}))
        )

    def disable(self) -> None:
        self.store.save_setting("telegram", "")

    async def send(self, message: str) -> None:
        config = self.config()
        if config is None:
            raise ValueError("尚未配置 Telegram")
        try:
            response = await self.client.post(
                f"https://api.telegram.org/bot{config['token']}/sendMessage",
                json={"chat_id": config["chat_id"], "text": f"Perp Farming Bots\n{message}"},
            )
            if response.status_code != 200 or response.json().get("ok") is not True:
                raise ValueError("Telegram 拒绝投递；请检查 Token 和 Chat ID")
        except httpx.HTTPError as exc:
            # Never log the request URL: it contains the token.
            raise ValueError("Telegram 网络请求未确认，请在站内查看通知") from exc

    async def start(self) -> None:
        self.task = asyncio.create_task(self.run())

    async def stop(self) -> None:
        if self.task is not None:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        await self.client.aclose()

    async def run(self) -> None:
        while True:
            try:
                if self.config() is not None:
                    for alert in reversed(self.store.rows(alerts)[:30]):
                        marker = f"telegram-delivery:{alert['id']}"
                        if self.store.setting(marker) is not None:
                            continue
                        # A timeout could mean delivered; no blind duplicate retry after a crash.
                        self.store.save_setting(marker, "unconfirmed")
                        try:
                            await self.send(alert["message"])
                            self.store.save_setting(marker, "sent")
                        except ValueError:
                            self.store.save_setting(marker, "failed_or_unconfirmed")
            except Exception:
                logger.error("notification cycle failed; trading remains independent")
            await asyncio.sleep(10)
