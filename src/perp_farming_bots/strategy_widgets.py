"""Read-only strategy monitors. Grid lines are conditional plans, never resting orders."""

from __future__ import annotations

import time
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from nicegui import ui

from .formatting import grid_capital_text, money, rate, stamp
from .grid import target_quantity
from .markets import require_fresh_book
from .models import Book, Bot, BotState, GridParameters, HedgeParameters, MarginSnapshot, Preview
from .store import Store, fills

if TYPE_CHECKING:
    from .runtime import Runtime


@dataclass(frozen=True)
class GridMarket:
    book: Book | None
    error: str | None
    last_tick: float | None
    margin: MarginSnapshot | None
    margin_error: str | None


@dataclass(frozen=True)
class HedgeMarket:
    preview: Preview | None
    error: str | None
    last_tick: float | None


async def observe_strategy(runtime: Runtime, bot: Bot) -> GridMarket | HedgeMarket:
    """Use native public reads and existing sizing logic; never enable execution."""
    if isinstance(bot.parameters, GridParameters):
        book, error = None, None
        try:
            book = await runtime.markets.book(
                runtime.store.connection(bot.parameters.connection_id).provider, bot.parameters.symbol
            )
            require_fresh_book(book)
        except ValueError as exc:
            book, error = None, str(exc)
        margin, margin_error = None, None
        try:
            margin = await runtime.margin.read(bot.parameters.connection_id, bot.parameters.symbol)
        except ValueError as exc:
            margin_error = str(exc)
        return GridMarket(book, error, runtime.last_tick, margin, margin_error)
    try:
        preview = await runtime.preview(bot)
        assert isinstance(preview, Preview)
        return HedgeMarket(preview, None, runtime.last_tick)
    except ValueError as exc:
        return HedgeMarket(None, str(exc), runtime.last_tick)


def duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, seconds = divmod(rest, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}"


def loop_alive(last_tick: float | None) -> bool:
    return last_tick is not None and 0 <= time.time() - last_tick < 60


class StrategyMonitor:
    def __init__(self, title: str, caption: str, headings: tuple[str, str, str]):
        self.root = ui.element("section").classes("pfb-strategy-monitor")
        with self.root:
            with ui.element("div").classes("pfb-monitor-heading"):
                ui.label(title).classes("pfb-monitor-title")
                self.health = ui.label().classes("pfb-monitor-health")
            self.caption = ui.label(caption).classes("pfb-monitor-caption")
            with ui.element("div").classes("pfb-monitor-stats"):
                self.values: list[ui.label] = []
                self.hints: list[ui.label] = []
                for heading in headings:
                    with ui.element("div").classes("pfb-monitor-stat"):
                        ui.label(heading).classes("pfb-monitor-stat-title")
                        self.values.append(ui.label().classes("pfb-monitor-stat-value"))
                        self.hints.append(ui.label().classes("pfb-monitor-stat-hint"))
            self.status = ui.label().classes("pfb-monitor-status")
            self.explanation = ui.label().classes("pfb-monitor-explanation")

    def set_health(self, bot: Bot, last_tick: float | None):
        active = bot.state in {BotState.HOLDING, BotState.WAITING}
        alive = loop_alive(last_tick)
        self.health.set_text(
            "正常监测"
            if active and alive
            else "监测状态待确认"
            if active
            else "已暂停"
            if bot.state == BotState.PAUSED
            else "已结束"
            if bot.state == BotState.CLOSED
            else "待处理"
            if bot.state == BotState.ATTENTION
            else "尚未运行"
        )
        self.health.classes(
            replace="pfb-monitor-health" + (" pfb-monitor-health--live" if active and alive else "")
        )


class GridLine:
    def __init__(self, parent: ui.element):
        with parent:
            self.root = ui.element("div").classes("pfb-grid-line")
            with self.root:
                self.price = ui.label().classes("pfb-grid-line-price")
                self.action = ui.label().classes("pfb-grid-line-action")
                self.quantity = ui.label().classes("pfb-grid-line-quantity")
                self.status = ui.label().classes("pfb-grid-line-status")


class GridMonitor(StrategyMonitor):
    def __init__(self):
        super().__init__(
            "网格触发计划", "程序内等待价格触发 · 交易所未提前挂单", ("当前价格", "下一格买入", "下一格卖出")
        )
        self.values[0].tooltip("盘口中价仅用于定位；买入按可成交卖价、卖出按可成交买价检查触发。")
        self.root.classes("pfb-grid-monitor")
        self.rows: dict[int, GridLine] = {}
        with self.root:
            self.inventory = ui.label().classes("pfb-grid-inventory")
            self.native_margin = ui.label().classes("pfb-monitor-caption")
            self.empty = ui.label("运行后显示实际格线和每格数量").classes("pfb-monitor-empty")
            self.wall = ui.element("div").classes("pfb-grid-wall")
            with self.wall:
                with ui.element("div").classes("pfb-grid-wall-head"):
                    for text in ("触发价格", "策略动作", "每次数量", "状态"):
                        ui.label(text)
                self.lines = ui.element("div").classes("pfb-grid-lines")
                with self.lines:
                    self.ticker = ui.element("div").classes("pfb-grid-ticker")
                    with self.ticker:
                        ui.icon("my_location", size="16px")
                        self.ticker_price = ui.label()
                        self.ticker_hint = ui.label().classes("pfb-grid-ticker-hint")
            ui.label(
                "突出显示的是下一格；其他格线需逐格成交后才会启用。基准格线表示策略位置，不代表成交记录。"
            ).classes("pfb-monitor-footnote")

    def update(self, bot: Bot, store: Store, market: GridMarket | HedgeMarket):
        assert isinstance(market, GridMarket) and isinstance(bot.parameters, GridParameters)
        p = bot.parameters
        self.set_health(bot, market.last_tick)
        self.caption.set_text(
            "上次运行的格线 · 重新运行会重新初始化"
            if bot.state == BotState.CLOSED
            else "程序内等待价格触发 · 交易所未提前挂单"
        )
        state = store.grid_state(bot.id)
        pending = store.bot_pending(bot.id)
        positions = store.positions(bot.id)
        history = store.rows(fills, bot.id)
        inventory = "；".join(
            f"{'多仓' if pos.role == 'long' else '空仓'} {pos.quantity} {p.symbol}" for pos in positions
        ) or ("尚未确认" if pending else "空仓")
        self.inventory.set_text(
            f"已确认仓位：{inventory} · 已确认成交 {len(history)} 笔 · {grid_capital_text(p)}"
            + (" · 未确认订单尚未计入" if pending else "")
        )
        margin = market.margin
        if margin is not None and 0 <= time.time() - margin.received_at <= 15:
            native = (
                f"{margin.leverage.normalize():f} 倍 / {'全仓' if margin.margin_mode == 'cross' else '逐仓'}"
                if margin.leverage is not None
                else "当前设置未返回"
            )
            self.native_margin.set_text(
                f"交易所当前：{native} · 最高 {margin.max_leverage.normalize():f} 倍"
                + (f" · 逐仓余额 {money(margin.position_margin)}" if margin.margin_mode == "isolated" else "")
            )
        else:
            self.native_margin.set_text(f"交易所保证金设置暂不可用：{market.margin_error or '数据已过期'}")
        book = market.book if market.book is not None and market.book.fresh() else None
        mid = (book.bids[0].price + book.asks[0].price) / 2 if book else None
        self.values[0].set_text(money(mid) if mid is not None else "暂不可用")
        self.hints[0].set_text(
            f"盘口中价 · {stamp(book.received_at)}" if book else market.error or "行情已过期"
        )
        self.wall.set_visibility(state is not None)
        self.empty.set_visibility(state is None)
        if state is None:
            for i in (1, 2):
                self.values[i].set_text("等待初始化")
                self.hints[i].set_text("运行后按实际格线确定")
            self.status.set_text(
                "网格已结束"
                if bot.state == BotState.CLOSED
                else "已暂停"
                if bot.state == BotState.PAUSED
                else "订单或仓位待确认"
                if pending or bot.state == BotState.ATTENTION
                else "等待价格进入区间"
                if bot.state == BotState.WAITING
                else "网格尚未初始化"
            )
            self.explanation.set_text(
                f"价格区间 {money(p.lower_price)} – {money(p.upper_price)} · {p.grid_count} 格。{bot.reason}"
                + (
                    " 点击“重新运行”会检查账户并按当前价格重新初始化网格。"
                    if bot.state == BotState.CLOSED
                    else ""
                )
            )
            return
        levels = [Decimal(v) for v in state["levels"]]
        cursor, quantity = state["cursor"], Decimal(state["quantity_per_grid"])
        for slot, index, side in ((1, cursor - 1, "buy"), (2, cursor + 1, "sell")):
            valid = 0 <= index < len(levels)
            self.values[slot].set_text(money(levels[index]) if valid else "已到区间边界")
            reference = book.asks[0].price if book and side == "buy" else book.bids[0].price if book else None
            distance = (
                ((reference - levels[index]) if side == "buy" else (levels[index] - reference))
                / reference
                * 100
                if valid and reference
                else None
            )
            self.hints[slot].set_text(
                (
                    "价格已到触发线"
                    if distance <= 0
                    else f"还需{'下跌' if side == 'buy' else '上涨'} {distance:.2f}%"
                )
                if distance is not None
                else "行情不可用，距离待确认"
                if valid
                else "此方向没有下一格"
            )
        outside = mid is not None and not levels[0] <= mid <= levels[-1]
        enabled = (
            bot.state == BotState.HOLDING
            and state["initialized"]
            and not pending
            and loop_alive(market.last_tick)
            and book is not None
            and not outside
        )
        if pending or not state["initialized"]:
            status, explanation = "订单或仓位待确认", bot.reason
        elif bot.state == BotState.ATTENTION:
            status = "策略已停止，等待处理"
            explanation = f"上次停止原因：{bot.reason}（记录更新 {stamp(bot.updated_at)}）。" + (
                "当前行情可用，核实后点击运行会重新检查账户与原格线。"
                if book is not None
                else "当前行情仍不可用，请等待有效行情。"
            )
        elif bot.state == BotState.PAUSED:
            status, explanation = "已暂停，格线不会触发交易", "保留原仓位和基准格线，点击运行后继续。"
        elif bot.state == BotState.CLOSED:
            status, explanation = (
                "网格已平仓，可以重新运行",
                "点击“重新运行”会检查账户并按当前价格重新初始化网格；历史成交和累计金额保留。以下格线为上次运行记录。",
            )
        elif not loop_alive(market.last_tick):
            status, explanation = "后台监测状态待确认", "暂时不能确认程序是否持续检查，请查看服务状态。"
        elif book is None:
            status, explanation = "等待有效行情，自动重试", "本次不提交交易；行情恢复后继续检查原格线。"
        elif outside:
            status, explanation = "价格在区间外", "保留仓位，等待回到区间；不在区间外新增策略订单。"
        else:
            status = "等待价格触发"
            explanation = (
                "当前为空仓：中性网格在中间格的目标仓位为 0，下一次交易需触发相邻格线。"
                if not positions and p.direction == "neutral" and cursor == p.grid_count // 2
                else "到达下一格后提交订单；按实际成交推进格线，不补造成交。"
            )
        self.status.set_text(status)
        self.explanation.set_text(explanation)
        for index in list(self.rows):
            if index >= len(levels):
                self.rows.pop(index).root.delete()
        for index, price in enumerate(levels):
            if index not in self.rows:
                self.rows[index] = GridLine(self.lines)
            row = self.rows[index]
            side = "sell" if index > cursor else "buy" if index < cursor else "cursor"
            nearest = abs(index - cursor) == 1
            row.root.classes(
                replace=f"pfb-grid-line pfb-grid-line--{side}" + (" pfb-grid-line--next" if nearest else "")
            )
            row.root.style(f"order: {(len(levels) - 1 - index) * 2}")
            row.price.set_text(money(price))
            if side == "cursor":
                row.action.set_text("当前基准")
                row.quantity.set_text("—")
                row.status.set_text("基准格线")
            else:
                origin = index + 1 if side == "buy" else index - 1
                before = target_quantity(p, origin, quantity)
                after = target_quantity(p, index, quantity)
                reducing = abs(after) < abs(before)
                effect = (
                    "平仓"
                    if reducing and after == 0
                    else "减仓"
                    if reducing
                    else "开仓"
                    if before == 0
                    else "加仓"
                )
                row.action.set_text(("买入" if side == "buy" else "卖出") + f" · {effect}")
                row.quantity.set_text(f"{quantity} {p.symbol}")
                row.status.set_text(
                    "下一格 · 等待触发"
                    if nearest and enabled
                    else "下一格 · 已暂停"
                    if nearest and bot.state == BotState.PAUSED
                    else "下一格 · 暂不执行"
                    if nearest
                    else "后续格线"
                )
        ticker_order = sum(price > mid for price in levels) * 2 - 1 if mid is not None else len(levels)
        self.ticker.style(f"order: {ticker_order}")
        self.ticker_price.set_text(f"当前价格 {money(mid)}" if mid is not None else "当前价格暂不可用")
        self.ticker_hint.set_text("盘口中价" if book else "不会用旧价计算距离")


class HedgeMonitor(StrategyMonitor):
    def __init__(self):
        super().__init__(
            "对冲执行状态",
            "按两侧可成交报价检查价差，双腿独立确认成交",
            ("当前建仓价差", "建仓条件", "单侧目标金额"),
        )

    def update(self, bot: Bot, store: Store, market: GridMarket | HedgeMarket):
        assert isinstance(market, HedgeMarket) and isinstance(bot.parameters, HedgeParameters)
        p = bot.parameters
        self.set_health(bot, market.last_tick)
        preview = (
            market.preview
            if market.preview is not None and 0 <= time.time() - market.preview.received_at <= 15
            else None
        )
        self.values[0].set_text(f"{preview.spread_pct:+.4f}%" if preview else "暂不可用")
        self.hints[0].set_text(
            f"报价更新 {stamp(preview.received_at)}" if preview else market.error or "报价已过期"
        )
        self.values[1].set_text(f"≥ {rate(p.threshold_pct)}")
        self.hints[1].set_text("下一次建仓仍需满足此条件")
        self.values[2].set_text(money(p.target_usd))
        self.hints[2].set_text(
            f"参考数量 {preview.quantity} {p.symbol}" if preview else "实际数量按原生精度确定"
        )
        cycle = store.cycle(bot.id)
        positions = store.positions(bot.id)
        if store.bot_pending(bot.id) or bot.state == BotState.ATTENTION:
            status, explanation = "原订单待确认", bot.reason
        elif bot.state == BotState.PAUSED:
            status, explanation = "已暂停", "保留双腿仓位，自动重开不计时。"
        elif bot.state == BotState.CLOSED:
            status, explanation = (
                "已平仓，可以重新运行",
                "点击“重新运行”后检查账户，继续等待原价差条件；历史成交和累计金额保留。",
            )
        elif bot.state == BotState.READY:
            status, explanation = "尚未运行", "点击运行后等待价差条件。"
        elif not loop_alive(market.last_tick):
            status, explanation = "后台监测状态待确认", "请查看程序运行状态。"
        elif positions:
            due = cycle["next_reopen_at"]
            status = (
                f"距离定期平仓 {duration(due - time.time())}" if due is not None else "双腿持仓，等待手动平仓"
            )
            explanation = (
                "持仓期间不自动追加；定期平仓确认后随机等待，再按原价差条件重开。"
                if due is not None
                else "持仓期间不自动追加，价差仅供查看。"
            )
        elif cycle["entry_not_before"] is not None and cycle["entry_not_before"] > time.time():
            status, explanation = (
                f"随机等待剩余 {duration(cycle['entry_not_before'] - time.time())}",
                "等待结束后再次检查价差，不立即无条件建仓。",
            )
        elif preview is None:
            status, explanation = "报价暂不可用", "无法确认是否满足建仓条件。"
        else:
            status = (
                "价差满足，等待执行检查" if preview.spread_pct >= p.threshold_pct else "等待价差达到建仓条件"
            )
            explanation = f"做多报价 {money(preview.long_price)} · 做空报价 {money(preview.short_price)}；数量、余额和仓位在下单前再次核对。"
        self.status.set_text(status)
        self.explanation.set_text(explanation)
