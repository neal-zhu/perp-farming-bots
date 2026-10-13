from __future__ import annotations

import asyncio
import json
import logging
import math
import secrets
import time
import uuid
from decimal import ROUND_CEILING, ROUND_DOWN, Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import ValidationError

from .grid import Grid, GridPreview
from .margin import Margin
from .markets import Markets, VenueRequestError, require_fresh_book
from .models import (
    Bot,
    BotCreate,
    BotState,
    BotUpdate,
    GridParameters,
    HedgeParameters,
    MarketSpec,
    OrderIntent,
    OrderResult,
    Preview,
    Provider,
)
from .points import Points
from .store import Store, fills, operations, orders
from .trading import Accounts

logger = logging.getLogger(__name__)
UNRESOLVED = {"prepared", "submitting", "submitted", "unknown"}


def common_step(a: Decimal, b: Decimal) -> Decimal:
    a_exponent, b_exponent = a.as_tuple().exponent, b.as_tuple().exponent
    if not isinstance(a_exponent, int) or not isinstance(b_exponent, int):
        raise ValueError("数量精度必须是有限数字")
    scale = Decimal(10) ** -min(a_exponent, b_exponent)
    return Decimal(math.lcm(int(a * scale), int(b * scale))) / scale


def quantity_floor(value: Decimal, step: Decimal) -> Decimal:
    return (value / step).to_integral_value(rounding=ROUND_DOWN) * step


def bounded_price(value: Decimal, spec: MarketSpec, side: str) -> Decimal:
    price = value
    for _ in range(10):
        tick = spec.price_tick
        for tier in spec.tick_tiers:
            if "upToPrice" not in tier or price < Decimal(tier["upToPrice"]):
                tick = Decimal(tier["tick"])
                break
        snapped = (value / tick).to_integral_value(
            rounding=ROUND_CEILING if side == "buy" else ROUND_DOWN
        ) * tick
        if snapped == price:
            return snapped
        price = snapped
    raise ValueError("无法确定价格档位精度")


class Runtime:
    """Single-process native execution. Every send is journaled; uncertainty stops new sends."""

    def __init__(self, store: Store, markets: Markets, accounts: Accounts):
        self.store, self.markets, self.accounts = store, markets, accounts
        self.points = Points(store, markets, accounts)
        self.margin = Margin(self)
        self.grid = Grid(self)
        self.guard = asyncio.Lock()
        self.task: asyncio.Task[None] | None = None
        self.last_tick: float | None = None

    async def start(self) -> None:
        # No request is replayed on restart. Query originals; require operator review
        # before any further entry when an interrupted operation exists.
        for op in self.store.rows(operations):
            if op["status"] in {"pending", "unknown"}:
                self.store.set_state(op["bot_id"], BotState.ATTENTION, "上次操作中断，正在查询原订单")
                self.store.finish_operation(op["id"], "unknown", "原订单待核实；不会重复提交")
        self.task = asyncio.create_task(self.run())
        await self.points.start()

    async def stop(self) -> None:
        await self.points.stop()
        if self.task is not None:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        await self.markets.close()

    async def run(self) -> None:
        refreshed = 0.0
        while True:
            try:
                if time.time() - refreshed >= 15:
                    for account in self.store.connections():
                        try:
                            await self.accounts.refresh(account.id)
                        except ValueError as exc:
                            self.store.alert(f"{account.name}：{exc}", severity="warning")
                    for bot in self.store.bots():
                        await self.refresh_fees(bot.id)
                    refreshed = time.time()
                for bot in self.store.bots():
                    try:
                        if bot.state == BotState.ATTENTION:
                            await self.sync(bot.id)
                        elif bot.strategy == "grid" and bot.state in {BotState.WAITING, BotState.HOLDING}:
                            await self.grid.tick(bot.id)
                        elif bot.state == BotState.WAITING:
                            await self.try_open(bot.id)
                        elif bot.state == BotState.HOLDING:
                            await self.try_reopen(bot.id)
                    except Exception as exc:
                        message = str(exc) if isinstance(exc, ValueError) else "策略执行异常，请检查日志"
                        self.store.alert(message, bot.id, "error")
                        logger.error("Strategy cycle failed for bot %s: %s", bot.id, type(exc).__name__)
                self.last_tick = time.time()
            except Exception:
                logger.exception("runtime cycle failed")
            await asyncio.sleep(3)

    async def funding(self, bot_id: str) -> dict[str, Any]:
        bot = self.store.bot(bot_id)
        p = bot.parameters
        if isinstance(p, GridParameters):
            data = await self.markets.funding(self.store.connection(p.connection_id).provider, p.symbol)
            return {"position": data.model_dump(mode="json")}
        assert isinstance(p, HedgeParameters)
        long, short = await asyncio.gather(
            self.markets.funding(self.store.connection(p.long_connection_id).provider, p.symbol),
            self.markets.funding(self.store.connection(p.short_connection_id).provider, p.symbol),
        )
        net = None
        if (
            long.status == short.status == "available"
            and long.interval_seconds == short.interval_seconds
            and long.predicted_rate_pct is not None
            and short.predicted_rate_pct is not None
        ):
            net = str(short.predicted_rate_pct - long.predicted_rate_pct)
        return {
            "long": long.model_dump(mode="json"),
            "short": short.model_dump(mode="json"),
            "net_receipt_rate_pct": net,
        }

    async def refresh_fees(self, bot_id: str) -> None:
        async with self.guard:
            for order in self.store.bot_orders(bot_id):
                result = order["result"]
                if not order["applied"] or result is None or result["fee"] is not None:
                    continue
                if result["quantity"] is None or Decimal(result["quantity"]) <= 0:
                    continue
                try:
                    refreshed = await self.accounts.adapter(order["connection_id"]).lookup(
                        OrderIntent.model_validate(order["intent"]), order["native_id"]
                    )
                except Exception:
                    continue  # A failed fee read never changes the confirmed fill.
                if refreshed.status != "unknown" and refreshed.fee is not None:
                    try:
                        self.store.apply_order_result(order["id"], refreshed)
                    except ValueError as exc:
                        self.store.alert(str(exc), bot_id, "warning")

    async def validate_configuration(
        self, value: BotCreate | BotUpdate, *, bot_id: str | None = None
    ) -> None:
        if not isinstance(value.parameters, GridParameters):
            return
        if bot_id is not None:
            previous = self.store.bot(bot_id)
            self.store.check_grid_update(bot_id, value.parameters)
            entry_fields = set(GridParameters.model_fields) - {"slippage_bps"}
            if self.store.grid_state(bot_id) is not None and value.parameters.model_dump(
                include=entry_fields
            ) == previous.parameters.model_dump(include=entry_fields):
                return  # A name/slippage edit does not request a new inventory allocation.
            assert isinstance(previous.parameters, GridParameters)
            old = previous.parameters
            if self.store.grid_state(bot_id) is not None and (old.connection_id, old.symbol) != (
                value.parameters.connection_id,
                value.parameters.symbol,
            ):
                await self._check_inventory(old.connection_id, old.symbol)
        await self.grid.preview(value, bot_id=bot_id)

    async def preview(
        self, value: BotCreate | BotUpdate | Bot, *, bot_id: str | None = None
    ) -> Preview | GridPreview:
        p = value.parameters
        if isinstance(p, GridParameters):
            return await self.grid.preview(value, bot_id=bot_id)
        assert isinstance(p, HedgeParameters)
        long, short = (
            self.store.connection(p.long_connection_id),
            self.store.connection(p.short_connection_id),
        )
        long_book, short_book, long_spec, short_spec = await asyncio.gather(
            self.markets.book(long.provider, p.symbol),
            self.markets.book(short.provider, p.symbol),
            self.markets.spec(long.provider, p.symbol),
            self.markets.spec(short.provider, p.symbol),
        )
        if not long_book.fresh() or not short_book.fresh():
            raise ValueError("行情已过期，暂不执行")
        quantity = quantity_floor(
            p.target_usd / long_book.asks[0].price,
            common_step(long_spec.quantity_step, short_spec.quantity_step),
        )
        if quantity <= 0:
            raise ValueError("金额不足以生成符合两边精度的数量")
        long_price, short_price = long_book.vwap("buy", quantity), short_book.vwap("sell", quantity)
        for spec, price in [(long_spec, long_price), (short_spec, short_price)]:
            if quantity < spec.min_quantity or quantity * price < spec.min_notional:
                raise ValueError("金额低于交易所最小下单限制")
        return Preview(
            quantity=quantity,
            long_price=long_price,
            short_price=short_price,
            spread_pct=(short_price / long_price - 1) * 100,
            estimated_fees=None,
            source=f"多腿：{long_book.source} / 空腿：{short_book.source}",
            received_at=min(long_book.received_at, short_book.received_at),
        )

    def _direction_conflict(self, bot: Bot) -> None:
        assert isinstance(bot.parameters, HedgeParameters)
        self.store.check_grid_reservation(bot)
        desired = {bot.parameters.long_connection_id: "long", bot.parameters.short_connection_id: "short"}
        for position in self.store.positions():
            if position.symbol == bot.parameters.symbol and position.connection_id in desired:
                if position.role != desired[position.connection_id]:
                    raise ValueError("该账户合约被其他 Bot 持有相反方向，请选择另一个账户实例")

    async def _check_inventory(self, connection_id: str, symbol: str) -> None:
        for order in self.store.rows(orders):
            intent = OrderIntent.model_validate_json(order["intent"])
            if (
                order["connection_id"] == connection_id
                and intent.symbol == symbol
                and order["status"] in UNRESOLVED
            ):
                raise ValueError("该账户合约有未确认的订单，先同步原订单")
        snapshot = await self.accounts.refresh(connection_id)
        expected = sum(
            (
                p.quantity * (1 if p.role == "long" else -1)
                for p in self.store.positions()
                if p.connection_id == connection_id and p.symbol == symbol
            ),
            Decimal(0),
        )
        actual = sum((p.quantity for p in snapshot.positions if p.symbol == symbol), Decimal(0))
        if expected != actual:
            raise ValueError("账户实际持仓与 Bot 分配数量不一致，请先核实外部交易或持仓变化")
        if await self.accounts.adapter(connection_id).open_orders(symbol):
            raise ValueError("该账户合约有其他未成交委托，请先在交易所处理")

    async def command(self, bot_id: str, action: str) -> None:
        if action == "sync":
            await self.sync(bot_id)
            return
        async with self.guard:
            bot = self.store.bot(bot_id)
            if bot.strategy == "grid":
                await self.grid.command(bot, action)
                return
            assert isinstance(bot.parameters, HedgeParameters)
            if action == "run":
                if bot.state == BotState.CLOSED:
                    if self.store.positions(bot_id) or self.store.bot_pending(bot_id):
                        raise ValueError("仍有分配仓位或未确认订单，不能重新运行")
                    self.store.check_strategy_accounts(bot.parameters, bot_id=bot_id)
                    self._direction_conflict(bot)
                    await self.preview(bot)
                    for connection_id in bot.parameters.connection_ids:
                        await self._check_inventory(connection_id, bot.parameters.symbol)
                    self.store.restart_closed_bot(bot_id)
                    return
                if bot.state not in {BotState.READY, BotState.PAUSED}:
                    raise ValueError("当前状态无法运行，请先核实订单和持仓")
                if self.store.bot_pending(bot_id):
                    raise ValueError("有未确认订单或操作，请先同步")
                owned = self.store.positions(bot_id)
                self._direction_conflict(bot)
                if owned:
                    if bot.state != BotState.PAUSED:
                        raise ValueError("待运行状态不应已有持仓，请同步并核实")
                    if len(owned) != 2 or owned[0].quantity != owned[1].quantity:
                        raise ValueError("持仓尚未形成匹配的双腿，请先处理；运行不会补腿")
                    for position in owned:
                        await self._check_inventory(position.connection_id, position.symbol)
                    self.store.set_state(bot_id, BotState.HOLDING, "策略运行中；保留已确认持仓")
                    self.store.arm_reopen(bot_id)
                else:
                    if self.store.cycle(bot_id)["open_operation_id"] is not None:
                        raise ValueError("本轮已执行过建仓且无持仓，请先核实原订单")
                    await self.preview(bot)
                    for connection_id in [
                        bot.parameters.long_connection_id,
                        bot.parameters.short_connection_id,
                    ]:
                        await self._check_inventory(connection_id, bot.parameters.symbol)
                    self.store.set_state(bot_id, BotState.WAITING, "等待价差达到条件后建仓")
            elif action == "pause":
                idle_attention = bot.state == BotState.ATTENTION and not self.store.positions(bot_id)
                if bot.state not in {BotState.WAITING, BotState.HOLDING} and not idle_attention:
                    raise ValueError("当前状态无需暂停")
                if self.store.bot_pending(bot_id):
                    raise ValueError("有未确认订单或操作，请先同步；策略已停止新动作")
                self.store.set_state(bot_id, BotState.PAUSED, "策略已暂停；持仓保留，点击运行可继续")
                self.store.disarm_reopen(bot_id)
            elif action == "close":
                self.store.disarm_reopen(bot_id)
                if (
                    not self.store.positions(bot_id)
                    and self.store.cycle(bot_id)["number"] > 1
                    and bot.state in {BotState.WAITING, BotState.PAUSED}
                ):
                    if self.store.bot_pending(bot_id):
                        raise ValueError("有未确认订单，请先同步订单")
                    self.store.set_state(bot_id, BotState.CLOSED, "无持仓，已结束重开等待")
                else:
                    await self._close(bot)
            else:
                raise ValueError("未知 Bot 操作")

    async def _execute(
        self,
        bot: Bot,
        op_id: str,
        role: str,
        connection_id: str,
        side: Literal["buy", "sell"],
        quantity: Decimal,
        reduce_only: bool,
        reference_price: Decimal,
        *,
        trigger_price: Decimal | None = None,
        grid_bounds: tuple[Decimal, Decimal] | None = None,
    ) -> OrderResult:
        account = self.store.connection(connection_id)
        if isinstance(bot.parameters, GridParameters) and not reduce_only:
            await self.margin.verify(bot.parameters)
        spec = await self.markets.spec(account.provider, bot.parameters.symbol)
        if quantity_floor(quantity, spec.quantity_step) != quantity:
            raise ValueError("实际数量不符合该交易所精度，请在交易所处理残余数量")
        book = await self.markets.book(account.provider, bot.parameters.symbol, refresh=True)
        if grid_bounds is not None:
            require_fresh_book(book)
        elif not book.fresh():
            raise ValueError("盘口已过期")
        if grid_bounds is not None:
            midpoint = (book.bids[0].price + book.asks[0].price) / 2
            if not grid_bounds[0] <= midpoint <= grid_bounds[1]:
                raise ValueError("下单前价格已离开网格区间，未提交订单")
        if trigger_price is not None:
            executable = book.vwap(side, quantity)
            if (side == "buy" and executable > trigger_price) or (
                side == "sell" and executable < trigger_price
            ):
                raise ValueError("价格已离开触发格线，未提交订单；请核实后恢复")
        slippage = bot.parameters.slippage_bps / 10000
        raw = reference_price * (1 + slippage if side == "buy" else 1 - slippage)
        price = bounded_price(raw, spec, side)
        if grid_bounds is not None:
            price = min(price, grid_bounds[1]) if side == "buy" else max(price, grid_bounds[0])
        if trigger_price is not None:
            price = min(price, trigger_price) if side == "buy" else max(price, trigger_price)
        if not reduce_only and (quantity < spec.min_quantity or quantity * price < spec.min_notional):
            raise ValueError("实际成交数量低于下一腿最小下单限制，保留持仓并告警")
        client_id = uuid.uuid4().hex if account.provider == Provider.ARCUS else str(secrets.randbits(47))
        intent = OrderIntent(
            connection_id=connection_id,
            symbol=bot.parameters.symbol,
            side=side,
            quantity=quantity,
            limit_price=price,
            reduce_only=reduce_only,
            client_id=client_id,
        )
        adapter = self.accounts.adapter(connection_id)
        prepared = await adapter.prepare(intent)
        order_id = self.store.add_order(
            op_id, bot.id, role, intent, self.accounts.secrets.encrypt(json.dumps(prepared))
        )
        self.store.update_order(order_id, "submitting")
        native_id = None
        try:
            native_id = await adapter.send(prepared)
            self.store.update_order(order_id, "submitted", native_id)
        except Exception:
            # A send error does not establish rejection. Query the original client identity.
            self.store.update_order(order_id, "unknown")
        last_read_error = "交易所尚未返回可确认的终态成交"
        for attempt in range(8):
            try:
                result = await adapter.lookup(intent, native_id)
                if result.status != "unknown":
                    self.store.apply_order_result(order_id, result)
                    return result
                if result.native_id is not None:
                    native_id = result.native_id
                    self.store.update_order(order_id, "submitted", native_id)
            except VenueRequestError as exc:
                last_read_error = str(exc)
                if not exc.retryable_read:
                    break
            except (KeyError, TypeError, InvalidOperation, ValidationError) as exc:
                # An incomplete native read remains unknown. Query the same
                # identity again; only complete valid evidence permits a peer.
                last_read_error = f"订单回报不完整或格式无效（{type(exc).__name__}）"
            except Exception as exc:
                last_read_error = (
                    str(exc) if isinstance(exc, ValueError) else f"订单回报解析失败（{type(exc).__name__}）"
                )
                break
            if attempt < 7:
                await asyncio.sleep(0.5)
        self.store.update_order(order_id, "unknown", native_id)
        direction = "做多" if role == "long" else "做空"
        raise ValueError(f"{direction}订单尚未确认：{last_read_error}；已停止后续提交，请同步原订单")

    def _unresolved(self, bot_id: str) -> bool:
        return any(o["status"] in UNRESOLVED for o in self.store.bot_orders(bot_id))

    async def try_open(self, bot_id: str) -> bool:
        async with self.guard:
            bot = self.store.bot(bot_id)
            assert isinstance(bot.parameters, HedgeParameters)
            if bot.state != BotState.WAITING:
                return False
            if (
                self.store.cycle(bot_id)["open_operation_id"] is not None
                or self.store.positions(bot_id)
                or self.store.bot_pending(bot_id)
            ):
                self.store.set_state(bot_id, BotState.ATTENTION, "已有执行记录，禁止重复建仓")
                return False
            not_before = self.store.cycle(bot_id)["entry_not_before"]
            if not_before is not None and time.time() < not_before:
                self.store.set_state(
                    bot_id,
                    BotState.WAITING,
                    f"随机等待中，{math.ceil(not_before - time.time())} 秒后开始检查价差",
                )
                return False
            try:
                preview = await self.preview(bot)
                assert isinstance(preview, Preview)
                self._direction_conflict(bot)
                if preview.spread_pct < bot.parameters.threshold_pct:
                    self.store.set_state(
                        bot_id,
                        BotState.WAITING,
                        f"当前价差 {preview.spread_pct:.4f}% / 条件 {bot.parameters.threshold_pct}%",
                    )
                    return False
                for connection_id in [bot.parameters.long_connection_id, bot.parameters.short_connection_id]:
                    await self._check_inventory(connection_id, bot.parameters.symbol)
                    if self.accounts.snapshots[connection_id].available < bot.parameters.target_usd:
                        raise ValueError("账户可用抵押资产不足以覆盖单侧目标金额，请调整金额")
            except ValueError as exc:
                self.store.set_state(bot_id, BotState.WAITING, str(exc))
                self.store.alert(str(exc), bot_id, "warning")
                return False
            op_id = self.store.operation(bot_id, "open")
            try:
                first = await self._execute(
                    bot,
                    op_id,
                    "long",
                    bot.parameters.long_connection_id,
                    "buy",
                    preview.quantity,
                    False,
                    preview.long_price,
                )
                if first.quantity is None or first.quantity == 0:
                    raise ValueError("做多订单未成交，未提交做空订单")
                short_account = self.store.connection(bot.parameters.short_connection_id)
                short_spec = await self.markets.spec(short_account.provider, bot.parameters.symbol)
                short_quantity = quantity_floor(first.quantity, short_spec.quantity_step)
                if short_quantity <= 0:
                    raise ValueError("第一腿成交不足第二腿最小数量，保留实际持仓并告警")
                second = await self._execute(
                    bot, op_id, "short", short_account.id, "sell", short_quantity, False, preview.short_price
                )
                if second.quantity != first.quantity:
                    raise ValueError("两腿实际成交数量不匹配，需要处理；不会自动追加或止损")
            except Exception as exc:
                message = str(exc) if isinstance(exc, ValueError) else "执行失败，请同步原订单和实际持仓"
                self.store.finish_operation(
                    op_id, "unknown" if self._unresolved(bot.id) else "attention", message
                )
                self.store.set_state(bot.id, BotState.ATTENTION, message)
                self.store.alert(message, bot.id, "error")
                return False
            self.store.complete_open(
                bot.id,
                op_id,
                f"两腿已建仓 {first.quantity} {bot.parameters.symbol} / 目标 {preview.quantity}；不自动追加",
            )
            self.store.alert(f"{bot.name} 建仓完成", bot.id)
            return True

    async def try_reopen(self, bot_id: str) -> bool:
        async with self.guard:
            bot = self.store.bot(bot_id)
            assert isinstance(bot.parameters, HedgeParameters)
            due = self.store.cycle(bot_id)["next_reopen_at"]
            if (
                bot.state != BotState.HOLDING
                or bot.parameters.reopen_interval_seconds is None
                or due is None
                or time.time() < due
            ):
                return False
            owned = self.store.positions(bot_id)
            if self.store.bot_pending(bot_id) or len(owned) != 2 or owned[0].quantity != owned[1].quantity:
                self.store.disarm_reopen(bot_id)
                self.store.set_state(
                    bot_id, BotState.ATTENTION, "定期重开前订单或双腿持仓未确认，已停止自动动作"
                )
                self.store.alert("定期重开前订单或双腿持仓未确认，已停止自动动作", bot_id, "error")
                return False
            await self._close(bot, reopen=True)
            return self.store.bot(bot_id).state == BotState.WAITING

    async def _close(self, bot: Bot, *, reopen: bool = False) -> None:
        if self._unresolved(bot.id):
            raise ValueError("有未确认订单，请先同步订单")
        allocated = self.store.positions(bot.id)
        if not allocated:
            raise ValueError("此 Bot 没有已分配持仓，无需平仓")
        op_id = self.store.operation(bot.id, "reopen_close" if reopen else "close")
        try:
            for p in allocated:
                await self._check_inventory(p.connection_id, p.symbol)
            references = {}
            for p in allocated:
                account = self.store.connection(p.connection_id)
                book = await self.markets.book(account.provider, p.symbol, refresh=True)
                if not book.fresh():
                    raise ValueError("平仓报价已过期")
                references[p.role] = book.vwap("sell" if p.role == "long" else "buy", p.quantity)
            for p in allocated:
                await self._execute(
                    bot,
                    op_id,
                    p.role,
                    p.connection_id,
                    "sell" if p.role == "long" else "buy",
                    p.quantity,
                    True,
                    references[p.role],
                )
            if self.store.positions(bot.id):
                raise ValueError("本次平仓未完全成交，保留剩余分配数量，可再次点击平仓")
        except Exception as exc:
            message = str(exc) if isinstance(exc, ValueError) else "平仓执行失败，请同步订单"
            self.store.finish_operation(
                op_id, "unknown" if self._unresolved(bot.id) else "attention", message
            )
            self.store.set_state(bot.id, BotState.ATTENTION, message)
            self.store.disarm_reopen(bot.id)
            self.store.alert(message, bot.id, "error")
            return
        if reopen:
            assert isinstance(bot.parameters, HedgeParameters)
            wait = secrets.randbelow(bot.parameters.reopen_random_wait_seconds + 1)
            self.store.complete_reopen_close(bot.id, op_id, wait)
            self.store.alert(f"{bot.name} 定期平仓完成，等待下一轮价差条件", bot.id)
        else:
            self.store.finish_operation(op_id, "completed", "此 Bot 的分配数量已确认平仓")
            self.store.set_state(bot.id, BotState.CLOSED, "平仓完成")
            self.store.alert(f"{bot.name} 平仓完成", bot.id)

    async def sync(self, bot_id: str) -> None:
        async with self.guard:
            if self.store.bot(bot_id).state != BotState.ATTENTION and not self.store.bot_pending(bot_id):
                return
            if await self.margin.reconcile(bot_id):
                return
            for order in self.store.bot_orders(bot_id):
                if order["status"] not in UNRESOLVED:
                    continue
                intent = OrderIntent.model_validate(order["intent"])
                result = await self.accounts.adapter(order["connection_id"]).lookup(
                    intent, order["native_id"]
                )
                self.store.apply_order_result(order["id"], result)
            if self._unresolved(bot_id):
                self.store.set_state(bot_id, BotState.ATTENTION, "原订单尚未确认，已停止新动作")
                return
            if self.store.bot(bot_id).strategy == "grid":
                self.grid.finish_sync(bot_id)
                return
            # Synchronization records native evidence only. It never starts another leg.
            inventory = self.store.positions(bot_id)
            ops = self.store.rows(operations, bot_id)
            if not ops:
                return
            latest = ops[0]
            if latest["kind"] in {"close", "reopen_close"} and not inventory:
                self.store.set_state(bot_id, BotState.CLOSED, "原平仓订单已确认完成")
                self.store.finish_operation(latest["id"], "completed", "原平仓订单已确认")
                self.store.disarm_reopen(bot_id)
            elif (
                latest["kind"] == "open"
                and len(inventory) == 2
                and inventory[0].quantity == inventory[1].quantity
            ):
                self.store.complete_open(bot_id, latest["id"], "原建仓订单已确认完成")
            else:
                if not inventory:
                    message = "订单已同步，没有已分配持仓；请查看原订单结果"
                elif len(inventory) == 1:
                    p = inventory[0]
                    message = f"单腿持仓：{'多仓' if p.role == 'long' else '空仓'} {p.quantity} {p.symbol}；请自行处理"
                else:
                    message = "两腿持仓数量不匹配，请查看实际成交并自行处理"
                self.store.set_state(bot_id, BotState.ATTENTION, message)
                # Preserve the original failure evidence instead of replacing it
                # with a generic message on every background synchronization.
                if latest["status"] in {"pending", "unknown"}:
                    self.store.finish_operation(latest["id"], "attention", latest["message"])

    async def pnl(self, bot_id: str) -> dict[str, Any]:
        history = self.store.rows(fills, bot_id)
        fees = (
            sum((Decimal(f["fee"]) for f in history), Decimal(0))
            if all(f["fee"] is not None for f in history)
            else None
        )
        realized = sum((Decimal(f["realized_pnl"]) for f in history), Decimal(0))
        unrealized = Decimal(0)
        error: str | None = None
        if self._unresolved(bot_id):
            error = "有未确认订单，持仓和盈亏尚不能完整确认"
        for p in self.store.positions(bot_id):
            snapshot = self.accounts.snapshots.get(p.connection_id)
            if (
                snapshot is None
                or time.time() - snapshot.received_at > 30
                or p.connection_id in self.accounts.errors
            ):
                error = "账户持仓尚未同步，盈亏等待确认"
            else:
                expected = sum(
                    (
                        owned.quantity * (1 if owned.role == "long" else -1)
                        for owned in self.store.positions()
                        if owned.connection_id == p.connection_id and owned.symbol == p.symbol
                    ),
                    Decimal(0),
                )
                native = sum(
                    (owned.quantity for owned in snapshot.positions if owned.symbol == p.symbol), Decimal(0)
                )
                if expected != native:
                    error = "账户实际持仓与分配数量不一致，盈亏等待确认"
            try:
                account = self.store.connection(p.connection_id)
                book = await self.markets.book(account.provider, p.symbol)
                if not book.fresh():
                    raise ValueError("行情已过期")
                unrealized += (
                    (book.vwap("sell" if p.role == "long" else "buy", p.quantity) - p.entry_price)
                    * p.quantity
                    * (1 if p.role == "long" else -1)
                )
            except ValueError as exc:
                error = str(exc)
        return {
            "realized": str(realized),
            "fees": str(fees) if fees is not None else None,
            "unrealized": str(unrealized) if error is None else None,
            "gross": str(realized + unrealized) if error is None else None,
            "net": str(realized + unrealized - fees) if error is None and fees is not None else None,
            "unavailable_reason": error,
            "funding": None,
            "funding_status": "资金费归属尚未接入",
            "valuation": "原生成交价差；费用和资金费缺失时总收益未知",
        }
