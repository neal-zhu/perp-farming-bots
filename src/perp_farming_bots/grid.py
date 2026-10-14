"""Price-triggered perpetual grid; execution and money evidence stay in the shared journal."""

from __future__ import annotations

from decimal import ROUND_CEILING, Decimal
from typing import TYPE_CHECKING, Any, Literal

from .hummingbot_grid import linear
from .markets import QuoteUnavailable, require_fresh_book
from .models import Bot, BotCreate, BotState, BotUpdate, GridParameters, StrictModel
from .store import operations

if TYPE_CHECKING:
    from .runtime import Runtime


class GridPreview(StrictModel):
    source: str
    levels: list[Decimal]
    quantity_per_grid: Decimal
    max_notional: Decimal
    initial_quantity: Decimal  # Signed: positive long, negative short.
    cursor: int
    zero_inventory_cursor: int
    can_initialize: bool
    current_price: Decimal
    inside_range: bool
    minimum_collateral: Decimal
    notional_limit: Decimal
    collateral_budget: Decimal
    minimum_quantity_per_grid: Decimal
    account_available: Decimal
    account_checked_at: float
    execution: str = "price_triggered_ioc"


def target_quantity(p: GridParameters, cursor: int, quantity: Decimal, zero_inventory_cursor: int) -> Decimal:
    if not 0 <= cursor <= p.grid_count or not 0 <= zero_inventory_cursor <= p.grid_count:
        raise ValueError("网格格线编号无效")
    units = zero_inventory_cursor - cursor
    if p.direction == "long":
        units = max(0, units)
    elif p.direction == "short":
        units = min(0, units)
    return units * quantity


def signed_inventory(runtime: Runtime, bot_id: str) -> Decimal:
    owned = runtime.store.positions(bot_id)
    if len(owned) > 1:
        raise ValueError("网格出现多个方向的分配仓位，需要核实")
    return sum((p.quantity * (1 if p.role == "long" else -1) for p in owned), Decimal(0))


class Grid:
    def __init__(self, runtime: Runtime):
        self.runtime = runtime

    async def preview(self, value: BotCreate | BotUpdate | Bot, *, bot_id: str | None = None) -> GridPreview:
        from .runtime import bounded_price, quantity_floor

        p = value.parameters
        assert isinstance(p, GridParameters)
        r = self.runtime
        owner = value.id if isinstance(value, Bot) else bot_id
        r.store.check_strategy_accounts(p, bot_id=owner)
        margin = await r.margin.read(p.connection_id, p.symbol)
        r.margin.validate(p, margin)
        connection = r.store.connection(p.connection_id)
        spec = await r.markets.spec(connection.provider, p.symbol)
        low = bounded_price(p.lower_price, spec, "buy")
        high = bounded_price(p.upper_price, spec, "sell")
        levels = [bounded_price(price, spec, "buy") for price in linear(p.grid_count + 1, low, high)]
        if low >= high or any(a >= b for a, b in zip(levels, levels[1:])) or levels[-1] > p.upper_price:
            raise ValueError("区间过窄，按交易所价格精度无法生成独立格线；请扩大区间或减少格数")
        await r._check_inventory(p.connection_id, p.symbol)
        account = r.accounts.snapshots[p.connection_id]
        book = await r.markets.book(connection.provider, p.symbol, refresh=True)
        require_fresh_book(book)
        midpoint = (book.asks[0].price + book.bids[0].price) / 2
        cursor = min(range(len(levels)), key=lambda i: abs(levels[i] - midpoint))
        anchor = p.grid_count if p.direction == "long" else 0
        if not p.open_position_on_start:
            anchor = cursor
        max_units = max(anchor, p.grid_count - anchor) if p.direction == "neutral" else p.grid_count
        available_units = anchor if p.direction == "long" else p.grid_count - anchor
        if p.direction == "neutral":
            available_units = max_units
        minimum_quantity = (
            max(spec.quantity_step, spec.min_quantity, spec.min_notional / levels[0]) / spec.quantity_step
        ).to_integral_value(rounding=ROUND_CEILING) * spec.quantity_step
        leverage = p.capital.leverage
        minimum_budget = minimum_quantity * levels[-1] * max_units / leverage
        minimum_budget_cents = minimum_budget.quantize(Decimal("0.01"), rounding=ROUND_CEILING)
        quantity = quantity_floor(p.notional_limit / levels[-1] / max_units, spec.quantity_step)
        if quantity <= 0 or quantity < spec.min_quantity or quantity * levels[0] < spec.min_notional:
            raise ValueError(
                f"每格数量 {quantity} {p.symbol} 低于最小订单要求。"
                f"按此区间和 {p.grid_count} 格，保证金额度至少 ${minimum_budget_cents:,.2f}，"
                f"每格至少 {minimum_quantity} {p.symbol}。请先核对币种和价格区间，再调整格数或预算。"
            )
        if account.available < p.collateral_budget:
            raise ValueError(
                f"账户可用余额 ${account.available:,.2f}，低于网格资金预算 ${p.collateral_budget:,.2f}。"
                f"当前格数和区间最低预算 ${minimum_budget_cents:,.2f}；请调整预算或格数。"
            )
        return GridPreview(
            source=book.source,
            levels=levels,
            quantity_per_grid=quantity,
            max_notional=quantity * available_units * levels[-1],
            initial_quantity=target_quantity(p, cursor, quantity, anchor),
            cursor=cursor,
            zero_inventory_cursor=anchor,
            can_initialize=available_units > 0,
            current_price=midpoint,
            inside_range=levels[0] <= midpoint <= levels[-1],
            minimum_collateral=minimum_budget,
            notional_limit=p.notional_limit,
            collateral_budget=p.collateral_budget,
            minimum_quantity_per_grid=minimum_quantity,
            account_available=account.available,
            account_checked_at=account.received_at,
        )

    async def command(self, bot: Bot, action: str) -> None:
        r, p = self.runtime, bot.parameters
        assert isinstance(p, GridParameters)
        if r.store.bot_pending(bot.id):
            raise ValueError("网格有未确认订单或操作，请先同步原订单")
        if action == "run":
            if bot.state == BotState.CLOSED:
                if r.store.positions(bot.id):
                    raise ValueError("仍有分配仓位，不能重新初始化网格，请先核实平仓结果")
                await self.preview(bot)
                await r.margin.configure(bot)
                r.store.restart_closed_bot(bot.id)
                return
            if bot.state not in {BotState.READY, BotState.PAUSED, BotState.ATTENTION}:
                raise ValueError("当前状态无法运行网格，请先核实订单和持仓")
            r.store.check_grid_reservation(bot)
            await r._check_inventory(p.connection_id, p.symbol)
            state = r.store.grid_state(bot.id)
            if state is not None:
                if not state["initialized"] or signed_inventory(r, bot.id) != target_quantity(
                    p, state["cursor"], Decimal(state["quantity_per_grid"]), state["zero_inventory_cursor"]
                ):
                    raise ValueError("网格成交数量未达到原目标；请平仓后新建 Bot，不会补单")
                await r.margin.verify(p)
                require_fresh_book(
                    await r.markets.book(r.store.connection(p.connection_id).provider, p.symbol, refresh=True)
                )
                r.store.set_state(bot.id, BotState.HOLDING, "网格已恢复，继续等待原相邻格线")
            else:
                await self.preview(bot)
                await r.margin.configure(bot)
                r.store.set_state(bot.id, BotState.WAITING, "等待区间内价格，随后初始化网格")
        elif action == "pause":
            if bot.state not in {BotState.WAITING, BotState.HOLDING, BotState.ATTENTION}:
                raise ValueError("当前状态无需暂停")
            r.store.set_state(bot.id, BotState.PAUSED, "网格已暂停；保留仓位和格线，运行后继续")
        elif action == "close":
            if r.store.positions(bot.id):
                await r._close(bot)
            else:
                r.store.set_state(bot.id, BotState.CLOSED, "网格无分配仓位，已结束运行")
        else:
            raise ValueError("未知网格操作")

    async def tick(self, bot_id: str) -> bool:
        async with self.runtime.guard:
            r = self.runtime
            bot = r.store.bot(bot_id)
            if bot.state not in {BotState.WAITING, BotState.HOLDING}:
                return False
            p = bot.parameters
            assert isinstance(p, GridParameters)
            op_id = None
            try:
                if r.store.bot_pending(bot.id):
                    raise ValueError("网格有未确认操作，已停止新动作")
                r.store.check_grid_reservation(bot)
                # A grid exclusively owns this account/symbol. External inventory/orders block it.
                await r._check_inventory(p.connection_id, p.symbol)
                await r.margin.verify(p)
                state = r.store.grid_state(bot.id)
                trigger: Decimal | None = None
                if state is None:
                    preview = await self.preview(bot)
                    if not preview.inside_range:
                        r.store.set_state(bot.id, BotState.WAITING, "当前价格在网格区间外，等待进入区间")
                        return False
                    if not preview.can_initialize:
                        r.store.set_state(
                            bot.id, BotState.WAITING, "当前价附近没有可开仓格线，等待价格进入可交易位置"
                        )
                        return False
                    cursor, target = preview.cursor, preview.initial_quantity
                    levels = preview.levels
                    layout: dict[str, Any] | None = {
                        "levels": preview.levels,
                        "quantity_per_grid": preview.quantity_per_grid,
                        "zero_inventory_cursor": preview.zero_inventory_cursor,
                    }
                    current = signed_inventory(r, bot.id)
                else:
                    if not state["initialized"]:
                        raise ValueError("网格初始化尚未确认，请同步原订单")
                    levels = [Decimal(v) for v in state["levels"]]
                    quantity = Decimal(state["quantity_per_grid"])
                    current = signed_inventory(r, bot.id)
                    if current != target_quantity(
                        p, state["cursor"], quantity, state["zero_inventory_cursor"]
                    ):
                        raise ValueError("网格分配仓位与格线状态不符，已停止新动作")
                    book = await r.markets.book(
                        r.store.connection(p.connection_id).provider, p.symbol, refresh=True
                    )
                    require_fresh_book(book)
                    midpoint = (book.bids[0].price + book.asks[0].price) / 2
                    if not levels[0] <= midpoint <= levels[-1]:
                        r.store.set_state(
                            bot.id, BotState.HOLDING, "价格在网格区间外；保留仓位，等待回到区间"
                        )
                        return False
                    cursor = state["cursor"]
                    # Use executable bid/ask, not midpoint, to prevent spread-only triggers.
                    if cursor > 0 and book.asks[0].price <= levels[cursor - 1]:
                        cursor -= 1
                    elif cursor < p.grid_count and book.bids[0].price >= levels[cursor + 1]:
                        cursor += 1
                    else:
                        r.store.set_state(bot.id, BotState.HOLDING, "网格运行中，等待相邻格线")
                        return False
                    target = target_quantity(p, cursor, quantity, state["zero_inventory_cursor"])
                    if target == current:
                        r.store.set_state(
                            bot.id, BotState.HOLDING, "当前空仓，等待开仓方向的格线；不反向开仓"
                        )
                        return False
                    trigger, layout = levels[cursor], None
                delta = target - current
                if current and target and (current > 0) != (target > 0):
                    raise ValueError("网格必须先确认零仓位，再切换方向")
                reduce = bool(current) and abs(target) < abs(current)
                if (
                    not reduce
                    and r.accounts.snapshots[p.connection_id].available
                    < abs(delta) * p.upper_price / p.capital.leverage
                ):
                    raise ValueError("可用抵押资产不足以覆盖本格订单")
                if delta:
                    side: Literal["buy", "sell"] = "buy" if delta > 0 else "sell"
                    role = "long" if (current > 0 if reduce else delta > 0) else "short"
                    book = await r.markets.book(
                        r.store.connection(p.connection_id).provider, p.symbol, refresh=True
                    )
                    require_fresh_book(book)
                    reference = book.vwap(side, abs(delta))
                op_id = r.store.begin_grid_action(bot.id, cursor, target, layout=layout)
                if delta:
                    result = await r._execute(
                        bot,
                        op_id,
                        role,
                        p.connection_id,
                        side,
                        abs(delta),
                        reduce,
                        reference,
                        trigger_price=trigger,
                        grid_bounds=(levels[0], levels[-1]),
                    )
                    if result.quantity != abs(delta):
                        raise ValueError("本格订单未完全成交；保留实际仓位，停止后续动作，请平仓处理")
                r.store.complete_grid_action(bot.id, op_id)
                return True
            except QuoteUnavailable as exc:
                if op_id is not None:
                    try:
                        r.store.skip_unsent_grid_action(bot.id, op_id, str(exc))
                    except ValueError as guard_error:
                        self._fail(bot.id, op_id, guard_error)
                        return False
                r.store.set_state(bot.id, bot.state, f"行情暂不可用，等待下一次更新：{exc}")
                r.store.alert(
                    f"{bot.name}：行情暂不可用，跳过本次交易；恢复后继续检查原网格", bot.id, "warning"
                )
                return False
            except Exception as exc:
                self._fail(bot.id, op_id, exc)
                return False

    def _fail(self, bot_id: str, op_id: str | None, exc: Exception) -> None:
        r = self.runtime
        message = str(exc) if isinstance(exc, ValueError) else "网格执行失败，请核实原订单"
        if op_id is not None:
            r.store.finish_operation(op_id, "unknown" if r._unresolved(bot_id) else "attention", message)
        r.store.set_state(bot_id, BotState.ATTENTION, message)
        r.store.alert(message, bot_id, "error")

    def finish_sync(self, bot_id: str) -> None:
        r = self.runtime
        history = r.store.rows(operations, bot_id)
        if not history:
            return
        latest = history[0]
        if (
            latest["kind"] == "close"
            and latest["status"] in {"pending", "unknown", "attention"}
            and not r.store.positions(bot_id)
        ):
            r.store.finish_operation(latest["id"], "completed", "网格原平仓订单已确认")
            r.store.set_state(bot_id, BotState.CLOSED, "网格已确认平仓，结束运行")
        elif latest["kind"] in {"grid_initial", "grid_step"} and latest["status"] in {
            "pending",
            "unknown",
            "attention",
        }:
            try:
                r.store.complete_grid_action(bot_id, latest["id"], recovered=True)
            except ValueError as exc:
                r.store.finish_operation(latest["id"], "attention", str(exc))
                r.store.set_state(bot_id, BotState.ATTENTION, str(exc))
