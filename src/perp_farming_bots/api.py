from __future__ import annotations

import time

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, ValidationError

from .models import PROVIDER_NAMES, STRATEGIES, TRADING_PROVIDERS, BotCreate, ConnectionCreate, Provider
from .notifications import Notifications
from .runtime import Runtime
from .store import Store, alerts, fills, operations


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: str


def register_routes(app: FastAPI, store: Store, runtime: Runtime, notifications: Notifications) -> None:
    @app.exception_handler(RequestValidationError)
    async def request_validation_handler(_request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={"detail": [{"loc": error["loc"], "msg": error["msg"]} for error in exc.errors()]},
        )

    @app.exception_handler(ValueError)
    async def value_error_handler(_request, exc: ValueError):
        message = (
            "; ".join(error["msg"] for error in exc.errors())
            if isinstance(exc, ValidationError)
            else str(exc)
        )
        return JSONResponse(status_code=400, content={"detail": message})

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "execution": "native",
            "last_tick": runtime.last_tick,
            "loop_alive": runtime.last_tick is not None and time.time() - runtime.last_tick < 60,
        }

    @app.get("/api/catalog")
    def catalog():
        return {
            "strategies": STRATEGIES,
            "execution": "native",
            "live_trading": True,
            "providers": [
                {
                    "id": provider.value,
                    "name": PROVIDER_NAMES[provider],
                    "account_implemented": provider in TRADING_PROVIDERS,
                }
                for provider in Provider
            ],
        }

    @app.get("/api/connections")
    def list_connections():
        return [
            {
                **c.model_dump(mode="json"),
                **runtime.accounts.view(c.id),
            }
            for c in store.connections()
        ]

    @app.post("/api/connections", status_code=201)
    async def create_connection(value: ConnectionCreate):
        async with runtime.guard:
            return (await runtime.accounts.add(value)).model_dump(mode="json")

    @app.post("/api/connections/{connection_id}/refresh")
    async def refresh_connection(connection_id: str):
        await runtime.accounts.refresh(connection_id)
        return runtime.accounts.view(connection_id)

    @app.delete("/api/connections/{connection_id}")
    async def remove_connection(connection_id: str):
        async with runtime.guard:
            store.delete_connection(connection_id)
        return {"deleted": True}

    @app.get("/api/connections/{connection_id}/markets")
    async def markets(connection_id: str):
        connection = store.connection(connection_id)
        return {"symbols": await runtime.markets.catalog(connection.provider)}

    @app.post("/api/bots/preview")
    async def preview(value: BotCreate):
        return (await runtime.preview(value)).model_dump(mode="json")

    @app.post("/api/bots", status_code=201)
    async def create_bot(value: BotCreate):
        async with runtime.guard:
            return store.add_bot(value).model_dump(mode="json")

    @app.get("/api/bots")
    async def list_bots():
        result = []
        for bot in store.bots():
            result.append(
                {
                    **bot.model_dump(mode="json"),
                    "pnl": await runtime.pnl(bot.id),
                    "positions": [p.model_dump(mode="json") for p in store.positions(bot.id)],
                }
            )
        return result

    @app.get("/api/bots/{bot_id}")
    async def get_bot(bot_id: str):
        return {
            **store.bot(bot_id).model_dump(mode="json"),
            "pnl": await runtime.pnl(bot_id),
            "positions": [p.model_dump(mode="json") for p in store.positions(bot_id)],
            "fills": store.rows(fills, bot_id),
            "orders": store.bot_orders(bot_id),
            "operations": store.rows(operations, bot_id),
        }

    @app.post("/api/bots/{bot_id}/commands")
    async def command(bot_id: str, value: Command):
        await runtime.command(bot_id, value.action)
        return store.bot(bot_id).model_dump(mode="json")

    @app.delete("/api/bots/{bot_id}")
    async def delete_bot(bot_id: str):
        async with runtime.guard:
            store.delete_bot(bot_id)
        return {"deleted": True}

    @app.get("/api/alerts")
    def list_alerts():
        return store.rows(alerts)[:100]

    @app.post("/api/alerts/{alert_id}/acknowledge")
    def acknowledge(alert_id: str):
        store.acknowledge_alert(alert_id)
        return {"acknowledged": True}

    @app.get("/api/points")
    def points():
        return [
            {
                "connection_id": c.id,
                "name": c.name,
                "value": None,
                "status": "unavailable",
                "reason": "尚未接入官方积分读取",
            }
            for c in store.connections()
        ]

    @app.get("/api/notifications")
    def notification_status():
        configured = notifications.config() is not None
        return {"telegram_configured": configured, "station_alerts": True}

    @app.get("/api/operations/{op_id}")
    def operation(op_id: str):
        for op in store.rows(operations):
            if op["id"] == op_id:
                return op
        raise HTTPException(status_code=404, detail="操作不存在")
