from __future__ import annotations

import asyncio
import logging
import time
import uuid
from decimal import ROUND_DOWN, Decimal
from typing import Any

from sqlalchemy import delete, insert

from .markets import Markets
from .models import Bot, BotCreate, BotState, Preview, Provider
from .store import Store, fills, operations, positions

logger = logging.getLogger(__name__)


class Runtime:
    """Pragmatic paper runtime. It has no real-order submission capability."""

    def __init__(self, store: Store, markets: Markets):
        self.store, self.markets = store, markets
        self.guard = asyncio.Lock()
        self.task: asyncio.Task[None] | None = None
        self.last_tick: float | None = None

    async def start(self) -> None:
        # Paper fills + both inventories are atomic; an interrupted pending operation had no partial commit.
        for op in self.store.rows(operations):
            if op["status"] == "pending":
                self.store.finish_operation(
                    op["id"], "interrupted", "模拟成交事务未提交；按当前 Bot 状态继续运行"
                )
                self.store.alert(
                    "上次模拟操作未成交；等待中的 Bot 继续监测，持仓中的 Bot 保留持仓",
                    op["bot_id"],
                    "warning",
                )
        self.task = asyncio.create_task(self.run())

    async def stop(self) -> None:
        if self.task is not None:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        await self.markets.close()

    async def run(self) -> None:
        while True:
            try:
                for bot in self.store.bots():
                    if bot.state == BotState.WAITING:
                        try:
                            await self.try_open(bot.id)
                        except Exception:
                            logger.exception("paper strategy cycle failed")
                self.last_tick = time.time()
            except Exception:
                logger.exception("runtime cycle failed")
            await asyncio.sleep(3)

    async def preview(self, value: BotCreate | Bot) -> Preview:
        p = value.parameters
        long = self.store.connection(p.long_connection_id)
        short = self.store.connection(p.short_connection_id)
        if long.provider == Provider.ARCUS or short.provider == Provider.ARCUS:
            raise ValueError("Arcus 行情尚未接入；可保存配置，但不能启动模拟执行")
        long_book, short_book = await asyncio.gather(
            self.markets.book(long.provider, p.symbol), self.markets.book(short.provider, p.symbol)
        )
        if not long_book.fresh() or not short_book.fresh():
            raise ValueError("行情已过期，暂不执行")
        quantity = (p.target_usd / long_book.asks[0].price).quantize(
            Decimal("0.00000001"), rounding=ROUND_DOWN
        )
        if quantity <= 0:
            raise ValueError("金额不足以生成模拟数量")
        long_price, short_price = long_book.vwap("buy", quantity), short_book.vwap("sell", quantity)
        fee = quantity * (long_price * long.paper_fee_bps + short_price * short.paper_fee_bps) / 10000
        source = f"多腿：{long_book.source} / 空腿：{short_book.source}"
        return Preview(
            quantity=quantity,
            long_price=long_price,
            short_price=short_price,
            spread_pct=(short_price / long_price - 1) * 100,
            estimated_fees=fee,
            source=source,
        )

    def _direction_conflict(self, bot: Bot) -> None:
        desired = {bot.parameters.long_connection_id: "long", bot.parameters.short_connection_id: "short"}
        for pos in self.store.positions():
            if pos.symbol == bot.parameters.symbol and pos.connection_id in desired:
                if pos.role != desired[pos.connection_id]:
                    raise ValueError("该账户合约已被其他 Bot 持有相反方向；请选择另一个账户实例")

    async def command(self, bot_id: str, action: str) -> None:
        async with self.guard:
            bot = self.store.bot(bot_id)
            if action == "start":
                if self.store.positions(bot_id):
                    raise ValueError("该 Bot 已有持仓，请关闭后创建新的 Bot")
                if bot.state == BotState.CLOSED:
                    raise ValueError("已平仓的 Bot 保留历史，请创建新的 Bot")
                self._direction_conflict(bot)
                await self.preview(bot)
                self.store.set_state(bot_id, BotState.WAITING, "等待价差达到条件 · 模拟模式")
            elif action == "pause":
                if bot.state == BotState.CLOSED:
                    raise ValueError("已平仓的 Bot 无需暂停")
                self.store.set_state(bot_id, BotState.PAUSED, "不再执行新建仓；已持有数量保留")
            elif action == "resume":
                if bot.state != BotState.PAUSED:
                    raise ValueError("只有已暂停的 Bot 可以恢复")
                state = BotState.HOLDING if self.store.positions(bot_id) else BotState.WAITING
                self._direction_conflict(bot)
                self.store.set_state(bot_id, state, "模拟策略已恢复")
            elif action == "stop":
                if bot.state == BotState.CLOSED:
                    raise ValueError("已平仓的 Bot 无需停止")
                self.store.set_state(bot_id, BotState.STOPPED, "策略已停止；此操作不平仓")
            elif action == "close":
                await self._close(bot)
            else:
                raise ValueError("未知 Bot 操作")

    async def try_open(self, bot_id: str) -> bool:
        async with self.guard:
            bot = self.store.bot(bot_id)
            if bot.state != BotState.WAITING:
                return False
            try:
                preview = await self.preview(bot)
                self._direction_conflict(bot)
                if preview.spread_pct < bot.parameters.threshold_pct:
                    self.store.set_state(
                        bot_id,
                        BotState.WAITING,
                        f"当前价差 {preview.spread_pct:.4f}% / 条件 {bot.parameters.threshold_pct}%",
                    )
                    return False
                long = self.store.connection(bot.parameters.long_connection_id)
                short = self.store.connection(bot.parameters.short_connection_id)
                for account, price in [(long, preview.long_price), (short, preview.short_price)]:
                    needed = preview.quantity * price * (1 + account.paper_fee_bps / 10000)
                    if self.store.account_available(account) < needed:
                        raise ValueError(f"{account.name} 模拟可用资金不足（按 1× 名义敞口预留）")
            except ValueError as exc:
                self.store.set_state(bot_id, BotState.WAITING, str(exc))
                self.store.alert(str(exc), bot_id, "warning")
                return False
            op_id = self.store.operation(bot_id, "paper_open")
            with self.store.transaction() as db:
                for account, role, side, price in [
                    (long, "long", "buy", preview.long_price),
                    (short, "short", "sell", preview.short_price),
                ]:
                    fee = preview.quantity * price * account.paper_fee_bps / 10000
                    db.execute(
                        insert(positions).values(
                            bot_id=bot.id,
                            role=role,
                            connection_id=account.id,
                            symbol=bot.parameters.symbol,
                            quantity=str(preview.quantity),
                            entry_price=str(price),
                            opening_fee=str(fee),
                        )
                    )
                    db.execute(
                        insert(fills).values(
                            id=uuid.uuid4().hex,
                            operation_id=op_id,
                            bot_id=bot.id,
                            connection_id=account.id,
                            role=role,
                            side=side,
                            quantity=str(preview.quantity),
                            price=str(price),
                            fee=str(fee),
                            realized_pnl="0",
                            created_at=time.time(),
                        )
                    )
                self.store.set_state(bot.id, BotState.HOLDING, "两腿模拟建仓完成；等待用户平仓", db)
                self.store.finish_operation(op_id, "completed", "模拟双腿成交在同一事务记录", db)
            self.store.alert(
                f"{bot.name} 模拟建仓完成，数量 {preview.quantity} {bot.parameters.symbol}", bot.id
            )
            return True

    async def _close(self, bot: Bot) -> None:
        allocated = self.store.positions(bot.id)
        if not allocated:
            if bot.state == BotState.CLOSED:
                return
            self.store.set_state(bot.id, BotState.STOPPED, "没有持仓；已取消等待并停止")
            return
        quotes = []
        for position in allocated:
            account = self.store.connection(position.connection_id)
            book = await self.markets.book(account.provider, position.symbol, refresh=True)
            if not book.fresh():
                raise ValueError("平仓报价已过期")
            side = "sell" if position.role == "long" else "buy"
            quotes.append((position, account, side, book.vwap(side, position.quantity)))
        op_id = self.store.operation(bot.id, "paper_close")
        with self.store.transaction() as db:
            for position, account, side, price in quotes:
                sign = Decimal(1) if position.role == "long" else Decimal(-1)
                realized = (price - position.entry_price) * position.quantity * sign
                fee = position.quantity * price * account.paper_fee_bps / 10000
                db.execute(
                    insert(fills).values(
                        id=uuid.uuid4().hex,
                        operation_id=op_id,
                        bot_id=bot.id,
                        connection_id=account.id,
                        role=position.role,
                        side=side,
                        quantity=str(position.quantity),
                        price=str(price),
                        fee=str(fee),
                        realized_pnl=str(realized),
                        created_at=time.time(),
                    )
                )
            db.execute(delete(positions).where(positions.c.bot_id == bot.id))
            self.store.set_state(
                bot.id, BotState.CLOSED, "此 Bot 的分配数量已模拟平仓；其他 Bot 不受影响", db
            )
            self.store.finish_operation(op_id, "completed", "模拟平仓完成", db)
        self.store.alert(f"{bot.name} 模拟平仓完成", bot.id)

    async def pnl(self, bot_id: str) -> dict[str, Any]:
        bot_fills = self.store.rows(fills, bot_id)
        fees = sum((Decimal(f["fee"]) for f in bot_fills), Decimal(0))
        realized = sum((Decimal(f["realized_pnl"]) for f in bot_fills), Decimal(0))
        unrealized = Decimal(0)
        error: str | None = None
        for pos in self.store.positions(bot_id):
            try:
                account = self.store.connection(pos.connection_id)
                book = await self.markets.book(account.provider, pos.symbol)
                if not book.fresh():
                    raise ValueError("行情已过期")
                price = book.vwap("sell" if pos.role == "long" else "buy", pos.quantity)
                sign = Decimal(1) if pos.role == "long" else Decimal(-1)
                unrealized += (price - pos.entry_price) * pos.quantity * sign
            except ValueError as exc:
                error = str(exc)
        return {
            "realized": str(realized),
            "fees": str(fees),
            "unrealized": str(unrealized) if error is None else None,
            "net": str(realized + unrealized - fees) if error is None else None,
            "unavailable_reason": error,
            "funding": None,
            "funding_status": "模拟模式未模拟资金费",
            "valuation": "模拟 USD；跨报价币种按面值假设，仅供体验",
        }
