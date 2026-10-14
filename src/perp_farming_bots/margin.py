"""Confirm native margin configuration before a new grid, with one journaled submission."""

from __future__ import annotations

import asyncio
import json
import time
from typing import TYPE_CHECKING

from .markets import VenueRequestError
from .models import Bot, BotState, GridMarginCapital, GridParameters, MarginSnapshot, Provider

if TYPE_CHECKING:
    from .runtime import Runtime

CONFIRM_TIMEOUT_SECONDS = 15


def matches(snapshot: MarginSnapshot, capital: GridMarginCapital) -> bool:
    return (
        snapshot.leverage == capital.leverage
        and snapshot.margin_mode == capital.margin_mode
        and 0 <= time.time() - snapshot.received_at <= 15
    )


class Margin:
    def __init__(self, runtime: Runtime):
        self.runtime = runtime

    async def read(self, connection_id: str, symbol: str) -> MarginSnapshot:
        return await self.runtime.accounts.adapter(connection_id).margin(symbol)

    def validate(self, p: GridParameters, snapshot: MarginSnapshot) -> None:
        capital = p.capital
        if capital.leverage > snapshot.max_leverage:
            raise ValueError(f"该市场最高可设置 {snapshot.max_leverage.normalize():f} 倍杠杆")
        provider = self.runtime.store.connection(p.connection_id).provider
        if provider == Provider.ONDO and capital.margin_mode != "cross":
            raise ValueError("Ondo Perps 仅支持全仓保证金，请选择全仓")
        if provider in {Provider.LIGHTER, Provider.LIGHTER_RH} and 10000 % capital.leverage:
            raise ValueError("此杠杆无法按交易所精度精确表示，请选择 1、2、4、5、8、10、20、25 等倍数")

    async def verify(self, p: GridParameters) -> MarginSnapshot:
        snapshot = await self.read(p.connection_id, p.symbol)
        self.validate(p, snapshot)
        if not matches(snapshot, p.capital):
            raise ValueError("交易所杠杆或保证金模式与 Bot 参数不一致；已停止新动作，请核实设置后恢复")
        return snapshot

    async def configure(self, bot: Bot) -> None:
        p = bot.parameters
        assert isinstance(p, GridParameters)
        capital = p.capital
        r = self.runtime
        snapshot = await self.read(p.connection_id, p.symbol)
        self.validate(p, snapshot)
        if matches(snapshot, capital):
            return
        await r._check_inventory(p.connection_id, p.symbol)
        if r.store.positions(bot.id) or r.store.bot_pending(bot.id):
            raise ValueError("有仓位或未确认操作，不能修改保证金设置")
        adapter = r.accounts.adapter(p.connection_id)
        prepared = await adapter.prepare_margin(p.symbol, capital)
        op_id = r.store.begin_margin_change(
            bot.id,
            p.connection_id,
            p.symbol,
            capital.model_dump_json(),
            r.accounts.secrets.encrypt(json.dumps(prepared)),
        )
        try:
            await adapter.send_margin(prepared)
        except VenueRequestError as exc:
            if exc.status_code in {400, 401, 403, 422}:
                r.store.finish_margin_change(op_id, "rejected", str(exc))
                r.store.set_state(bot.id, BotState.ATTENTION, str(exc))
                raise
        except Exception:
            pass  # A lost ACK is resolved by reads, never by resending.
        try:
            async with asyncio.timeout(CONFIRM_TIMEOUT_SECONDS):
                for attempt in range(6):
                    try:
                        snapshot = await self.read(p.connection_id, p.symbol)
                        if matches(snapshot, capital):
                            r.store.finish_margin_change(
                                op_id,
                                "confirmed",
                                "原生杠杆和保证金模式已读回确认",
                                snapshot.model_dump_json(),
                            )
                            return
                    except ValueError:
                        pass
                    if attempt < 5:
                        await asyncio.sleep(0.5)
        except TimeoutError:
            pass
        message = "杠杆/保证金模式设置尚未确认，未启用策略；请同步设置，不会重复发送"
        r.store.finish_margin_change(op_id, "unknown", message)
        r.store.set_state(bot.id, BotState.ATTENTION, message)
        raise ValueError(message)

    async def reconcile(self, bot_id: str) -> bool:
        """Original unknown settings are read only; confirmation requires explicit resume."""
        r = self.runtime
        pending = [c for c in r.store.bot_margin_changes(bot_id) if c["status"] in {"pending", "unknown"}]
        if not pending:
            return False
        for change in pending:
            try:
                snapshot = await self.read(change["connection_id"], change["symbol"])
            except ValueError:
                return True
            target = GridMarginCapital.model_validate(change["target"])
            if not matches(snapshot, target):
                return True
            r.store.finish_margin_change(
                change["operation_id"], "confirmed", "原设置已核实，请手动运行", snapshot.model_dump_json()
            )
        r.store.set_state(bot_id, BotState.PAUSED, "杠杆与保证金模式已确认，点击运行继续；没有自动下单")
        return True
