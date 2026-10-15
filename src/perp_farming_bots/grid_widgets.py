"""Grid overview: confirmed money first, execution plan on demand."""

from collections.abc import Callable
from decimal import Decimal
from typing import Any

from nicegui import ui

from .bot_widgets import BotCard
from .formatting import money, rate, stamp
from .grid import target_quantity
from .models import GRID_DIRECTION_NAMES, PROVIDER_NAMES, STATE_NAMES, Bot, BotState, GridParameters
from .store import Store, fills
from .strategy_widgets import GridMonitor


class GridDatum:
    def __init__(self, title: str, *, tooltip: str | None = None):
        self.root = ui.element("div").classes("pfb-grid-datum")
        with self.root:
            self.title = ui.label(title).classes("pfb-grid-datum-title")
            if tooltip is not None:
                self.title.tooltip(tooltip)
            self.value = ui.label().classes("pfb-grid-datum-value")
            self.hint = ui.label().classes("pfb-grid-datum-hint")


def short_rate(value: Decimal) -> str:
    rounded = value.quantize(Decimal("0.000001"))
    if value and not rounded:
        return ("−" if value < 0 else "+") + "<0.000001%"
    return ("+" if rounded > 0 else "") + rate(abs(rounded) if rounded == 0 else rounded)


class GridBotCard(BotCard):
    def __init__(
        self,
        bot_id: str,
        action: Callable,
        edit: Callable,
        remove: Callable,
        close: Callable,
        details: Callable,
    ):
        self.root = ui.card().classes("w-full pfb-bot-card pfb-grid-card")
        with self.root:
            with ui.element("div").classes("pfb-bot-header"):
                self.name = ui.label().classes("pfb-grid-market")
                self.state = ui.badge(color=None).classes("pfb-state")
            with ui.element("div").classes("pfb-grid-tags"):
                ui.label("永续网格").classes("pfb-grid-tag")
                self.mode = ui.label().classes("pfb-grid-tag")
                self.direction = ui.label().classes("pfb-grid-tag")
                self.account = ui.label().classes("pfb-grid-account")
            self.symbol = ui.label().classes("pfb-bot-caption")
            self.notice = ui.element("div").classes("pfb-notice")
            with self.notice:
                ui.icon("error_outline", size="17px")
                self.exposure = ui.label()
            with ui.element("div").classes("pfb-grid-hero"):
                with ui.element("div").classes("pfb-grid-profit"):
                    ui.label("交易盈亏 (USD)").classes("pfb-grid-hero-label").tooltip(
                        "已实现价差 + 持仓浮盈亏 − 已确认手续费；不含实际资金费。"
                    )
                    self.pnl: dict[str, ui.label] = {
                        "net": ui.label().classes("pfb-metric-value pfb-metric-value--main")
                    }
                    self.profit_ratio = ui.label().classes("pfb-grid-profit-ratio")
                    self.profit_ratio.tooltip(
                        "交易盈亏 ÷ 当前配置的保证金额度。额度修改后此比值会变化；不是年化收益率。"
                    )
                    ui.label("已扣手续费 · 未含实际资金费").classes("pfb-grid-profit-note")
                with ui.element("div").classes("pfb-grid-capital"):
                    ui.label("保证金额度 (USD)").classes("pfb-grid-hero-label").tooltip(
                        "此 Bot 配置的资金预算，不等于交易所实际占用或已隔离的保证金。"
                    )
                    self.capital = ui.label().classes("pfb-grid-capital-value")
                    self.capital_limit = ui.label().classes("pfb-grid-capital-hint")
            self.pnl_error = ui.label().classes("pfb-data-warning")
            with ui.element("div").classes("pfb-grid-profit-breakdown"):
                for key, title, explanation in [
                    (
                        "realized",
                        "已实现价差",
                        "按已确认减仓成交计算的价格盈亏，手续费单列；不是逐格配对利润。",
                    ),
                    ("unrealized", "持仓浮盈亏", "按当前可成交盘口估值；账户或行情无法确认时显示待确认。"),
                    ("fees", "手续费", "此 Bot 已确认成交的实际手续费，已从交易盈亏中扣除。"),
                ]:
                    with ui.element("div").classes("pfb-grid-profit-item"):
                        ui.label(title).classes("pfb-grid-datum-title").tooltip(explanation)
                        self.pnl[key] = ui.label().classes("pfb-metric-value")
            with ui.element("div").classes("pfb-grid-facts"):
                self.range = GridDatum("价格区间 (USD)")
                self.range.root.classes("pfb-grid-range")
                self.count = GridDatum("网格数量")
                self.size = GridDatum("每格数量")
                self.position = GridDatum("当前仓位")
                self.entry = GridDatum("持仓均价 (USD)")
                self.volume = GridDatum(
                    "累计成交额 (USD)",
                    tooltip="实际成交数量 × 成交价格累加，含开仓与平仓，不是当前持仓金额。",
                )
                self.turnover = self.volume.value
            with ui.element("div").classes("pfb-grid-funding-strip"):
                ui.label("当前资金费率").classes("pfb-grid-datum-title")
                self.funding_rate = ui.label().classes("pfb-grid-funding-rate")
                self.funding_hint = ui.label().classes("pfb-grid-funding-hint")
                self.funding_source = ui.tooltip("")
            self.monitor = GridMonitor()
            self.build_controls(bot_id, action, edit, remove, close, details)

    def update(self, bot: Bot, store: Store, pnl: dict[str, Any], funding: dict[str, Any]):
        p = bot.parameters
        assert isinstance(p, GridParameters)
        positions, state = store.positions(bot.id), store.grid_state(bot.id)
        pending, volume = store.bot_pending(bot.id), store.turnover(bot.id)
        connection = store.connection(p.connection_id)
        self.name.set_text(p.symbol)
        self.symbol.set_text(f"{bot.name} · 创建于 {stamp(bot.created_at)}")
        self.account.set_text(f"{PROVIDER_NAMES[connection.provider]} / {connection.name}")
        self.mode.set_text("逐仓" if p.capital.margin_mode == "isolated" else "全仓")
        self.direction.set_text(f"{GRID_DIRECTION_NAMES[p.direction]} {p.capital.leverage}×")
        self.direction.classes(replace=f"pfb-grid-tag pfb-grid-tag--{p.direction}")
        self.state.set_text(
            "运行中"
            if bot.state == BotState.HOLDING
            else "等待入场"
            if bot.state == BotState.WAITING
            else STATE_NAMES[bot.state]
        )
        self.state.classes(replace=f"pfb-state pfb-state--{bot.state.value}")
        self.capital.set_text(money(p.capital.investment_usd))
        self.capital_limit.set_text(f"仓位上限 {money(p.notional_limit)}")
        self.update_pnl(pnl)
        ratio = (
            (Decimal(pnl["net"]) / p.capital.investment_usd * 100).quantize(Decimal("0.01"))
            if pnl["net"] is not None
            else None
        )
        self.profit_ratio.set_text(
            "额度盈亏比待确认"
            if ratio is None
            else f"{'+' if ratio > 0 else ''}{abs(ratio) if ratio == 0 else ratio:.2f}% · 按当前额度"
        )
        self.profit_ratio.classes(
            replace="pfb-grid-profit-ratio "
            + (
                "pfb-value-unknown"
                if ratio is None
                else "pfb-value-positive"
                if ratio > 0
                else "pfb-value-negative"
                if ratio < 0
                else "pfb-value-neutral"
            )
        )
        self.range.value.set_text(f"{money(p.lower_price)} – {money(p.upper_price)}")
        self.count.value.set_text(str(p.grid_count))
        self.count.hint.set_text("等差 · 启动建仓" if p.open_position_on_start else "等差 · 启动不建仓")
        self.size.value.set_text(
            f"{Decimal(state['quantity_per_grid']).normalize():f}" if state is not None else "尚未生成"
        )
        self.size.hint.set_text(p.symbol)
        position = positions[0] if len(positions) == 1 else None
        owned = (
            f"{'多' if position.role == 'long' else '空'} {position.quantity}"
            if position
            else "待核实"
            if len(positions) > 1
            else "无仓位"
        )
        self.position.value.set_text("待确认" if pending else "待核实" if len(positions) > 1 else owned)
        self.position.hint.set_text(
            f"已确认 {owned}" if pending else p.symbol if position else "等待价格触发"
        )
        self.entry.value.set_text(
            "待确认"
            if pending
            else "待核实"
            if len(positions) > 1
            else money(position.entry_price)
            if position
            else "—"
        )
        self.entry.hint.set_text("按此 Bot 的持仓计算")
        self.turnover.set_text(
            "待确认" if volume["has_unconfirmed_orders"] else money(volume["confirmed_usd"])
        )
        self.volume.hint.set_text(f"{len(store.rows(fills, bot.id))} 笔已确认成交")
        data = funding["position"]
        if data["status"] == "available":
            forecast = Decimal(data["predicted_rate_pct"])
            period = "小时" if data["interval_seconds"] == 3600 else f"{data['interval_seconds']}秒"
            self.funding_rate.set_text(f"{short_rate(forecast)} / {period}")
            self.funding_hint.set_text(
                "当前无需支付"
                if forecast == 0
                else ("预计支付" if (forecast > 0) == (position.role == "long") else "预计收取")
                if position
                else "当前无仓位"
            )
            self.funding_source.set_text(f"下一次结算费率预估：{rate(forecast)}；实际资金费未计入交易盈亏。")
        else:
            self.funding_rate.set_text("暂不可用")
            self.funding_hint.set_text("等待交易所数据")
            self.funding_source.set_text(data["unavailable_reason"] or "资金费率暂不可用")
        self.notice.set_visibility(bot.state == BotState.ATTENTION or pending)
        self.exposure.set_text(
            bot.reason if bot.state == BotState.ATTENTION else "原订单正在确认，已停止新动作。"
        )
        signed = position.quantity * (1 if position.role == "long" else -1) if position else Decimal(0)
        aligned = (
            state is None
            or state["initialized"]
            and signed
            == target_quantity(
                p, state["cursor"], Decimal(state["quantity_per_grid"]), state["zero_inventory_cursor"]
            )
        )
        can_restart = bot.state == BotState.CLOSED and not positions and not pending
        self.buttons["run"].set_text("重新运行" if bot.state == BotState.CLOSED else "运行")
        self.buttons["run"].set_enabled(
            can_restart
            or bot.state in {BotState.READY, BotState.PAUSED, BotState.ATTENTION}
            and not pending
            and aligned
        )
        self.buttons["pause"].set_enabled(
            bot.state in {BotState.WAITING, BotState.HOLDING, BotState.ATTENTION} and not pending
        )
        self.buttons["sync"].set_visibility(bot.state == BotState.ATTENTION)
        self.close.set_enabled(not pending and bot.state != BotState.CLOSED)
        self.remove.set_enabled(store.bot_editability(bot.id)["delete"])
