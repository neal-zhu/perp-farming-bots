import time
from collections.abc import Callable
from decimal import Decimal
from typing import Any

from nicegui import ui

from .formatting import money, pnl_money, rate, stamp
from .models import (
    PROVIDER_NAMES,
    STATE_NAMES,
    Bot,
    BotState,
    Connection,
    HedgeParameters,
    Position,
)
from .store import Store, alerts
from .strategy_widgets import GridMonitor, HedgeMonitor


class BotLeg:
    def __init__(self, role: str):
        self.role = role
        self.root = ui.element("div").classes("pfb-leg")
        with self.root:
            with ui.element("div").classes("pfb-leg-info"):
                with ui.element("div").classes("pfb-leg-head"):
                    self.role_label = ui.label("做多" if role == "long" else "做空").classes(
                        f"pfb-leg-role pfb-leg-role--{role}"
                    )
                    self.account = ui.label().classes("pfb-leg-account")
                self.provider = ui.label().classes("pfb-leg-provider")
            self.quantity = ui.label().classes("pfb-leg-quantity")
            with ui.element("div").classes("pfb-leg-entry-cell"):
                ui.label("入场价").classes("pfb-mobile-label")
                self.entry = ui.label().classes("pfb-leg-entry")
            with ui.element("div").classes("pfb-leg-funding"):
                self.funding = ui.label().classes("pfb-leg-rate")
                self.funding_title = ui.label().classes("pfb-leg-label")

    def update(self, connection: Connection, position: Position | None, data: dict[str, Any]):
        self.account.set_text(connection.name)
        self.provider.set_text(f"{PROVIDER_NAMES[connection.provider]} · {data['symbol']}")
        self.quantity.set_text(f"{position.quantity} {position.symbol}" if position else "尚无确认仓位")
        self.quantity.classes(
            replace="pfb-leg-quantity" + (" pfb-leg-quantity--empty" if position is None else "")
        )
        self.entry.set_text(money(position.entry_price) if position else "—")
        if data["status"] == "available":
            period = "小时" if data["interval_seconds"] == 3600 else f"{data['interval_seconds']}秒"
            self.funding_title.set_text(f"每{period}")
            forecast = Decimal(data["predicted_rate_pct"])
            direction = "预计支付" if (forecast > 0) == (self.role == "long") else "预计收取"
            self.funding.set_text("无需支付" if forecast == 0 else f"{direction} {rate(abs(forecast))}")
        else:
            self.funding_title.set_text("预估资金费")
            self.funding.set_text("暂不可用")


class BotCard:
    """Persistent elements: polling changes text/visibility, never replaces the card."""

    def __init__(
        self,
        bot_id: str,
        action: Callable,
        edit: Callable,
        remove: Callable,
        close: Callable,
        details: Callable,
    ):
        self.root = ui.card().classes("w-full pfb-bot-card")
        with self.root:
            with ui.element("div").classes("pfb-bot-header"):
                with ui.element("div").classes("pfb-bot-identity"):
                    self.name = ui.label().classes("pfb-bot-name")
                    self.symbol = ui.label().classes("pfb-bot-caption")
                with ui.element("div").classes("pfb-header-actions"):
                    self.state = ui.badge(color=None).classes("pfb-state")
            self.parameters = ui.label().classes("pfb-parameters")
            with ui.element("div").classes("pfb-metrics"):
                self.pnl: dict[str, ui.label] = {}
                for key, title in [("net", "交易盈亏"), ("fees", "手续费")]:
                    with ui.element("div").classes("pfb-metric"):
                        ui.label(title).classes("pfb-metric-label").tooltip(
                            "价格盈亏扣除手续费；不含实际资金费。"
                            if key == "net"
                            else "此 Bot 已确认成交的实际手续费。"
                        )
                        self.pnl[key] = ui.label().classes(
                            "pfb-metric-value" + (" pfb-metric-value--main" if key == "net" else "")
                        )
                with ui.element("div").classes("pfb-metric"):
                    ui.label("累计成交额").classes("pfb-metric-label").tooltip(
                        "此 Bot 的已确认成交，按实际数量 × 成交均价累加；不含未确认订单。"
                    )
                    self.turnover = ui.label().classes("pfb-metric-value")
            self.notice = ui.element("div").classes("pfb-notice")
            with self.notice:
                ui.icon("error_outline", size="17px")
                self.exposure = ui.label()
            self.pnl_error = ui.label().classes("pfb-data-warning")
            self.reopen_status = ui.label().classes("text-xs text-slate-500 mt-3")
            self.monitor = self.build_monitor()
            with ui.element("div").classes("pfb-position-heading"):
                ui.label("持仓明细").classes("pfb-section-title")
                self.match = ui.badge(color=None).classes("pfb-match")
            with ui.element("div").classes("pfb-leg-table"):
                with ui.element("div").classes("pfb-leg-table-head"):
                    for heading in ["账户", "仓位", "入场价", "预估资金费"]:
                        ui.label(heading)
                self.legs = {role: BotLeg(role) for role in ("long", "short")}
            self.funding_summary = ui.element("div").classes("pfb-funding-summary")
            with self.funding_summary:
                label = ui.label("预估净资金费率").classes("pfb-leg-label")
                label.tooltip("按两侧等额名义金额计算。费率会随市场变化，不是实际到账收益。")
                self.net_funding = ui.label().classes("pfb-funding-value")
            self.build_controls(bot_id, action, edit, remove, close, details)

    def build_controls(
        self,
        bot_id: str,
        action: Callable,
        edit: Callable,
        remove: Callable,
        close: Callable,
        details: Callable,
    ) -> None:
        with ui.element("div").classes("pfb-trading-toolbar"):
            with ui.element("div").classes("pfb-primary-actions"):
                self.buttons: dict[str, ui.button] = {}
                for command, title, icon in [("run", "运行", "play_arrow"), ("pause", "暂停", "pause")]:
                    self.buttons[command] = (
                        ui.button(title, icon=icon, on_click=lambda cmd=command: action(bot_id, cmd))
                        .classes("pfb-action" + (" pfb-run" if command == "run" else ""))
                        .props("unelevated" if command == "run" else "outline")
                    )
                self.close = (
                    ui.button("平仓", icon="close", on_click=lambda: close(bot_id))
                    .props("outline")
                    .classes("pfb-action pfb-close")
                )
            with ui.element("div").classes("pfb-card-links"):
                self.buttons["sync"] = (
                    ui.button("同步订单", icon="sync", on_click=lambda: action(bot_id, "sync"))
                    .props("flat dense")
                    .classes("pfb-secondary-button")
                )
                ui.button("成交记录", icon="receipt_long", on_click=lambda: details(bot_id)).props(
                    "flat dense"
                ).classes("pfb-secondary-button")
                self.edit = (
                    ui.button("修改参数", icon="tune", on_click=lambda: edit(bot_id))
                    .props("flat dense")
                    .classes("pfb-secondary-button")
                )
                self.remove = (
                    ui.button(
                        "删除", icon="delete_outline", on_click=lambda: remove(bot_id), color="negative"
                    )
                    .props("flat dense")
                    .classes("pfb-delete-button")
                )
                self.remove.tooltip("无持仓、无未确认订单时可删除")

    def build_monitor(self) -> HedgeMonitor | GridMonitor:
        return HedgeMonitor()

    def update(self, bot: Bot, store: Store, pnl: dict[str, Any], funding: dict[str, Any]):
        assert isinstance(bot.parameters, HedgeParameters)
        positions = store.positions(bot.id)
        editable = store.bot_editability(bot.id)
        pending = store.bot_pending(bot.id)
        cycle = store.cycle(bot.id)
        self.name.set_text(bot.name)
        self.symbol.set_text(
            f"{bot.parameters.long_symbol} / {bot.parameters.short_symbol} · 价差对冲 · 第 {cycle['number']} 轮"
        )
        volume = store.turnover(bot.id)
        self.turnover.set_text(
            "待确认" if volume["has_unconfirmed_orders"] else money(volume["confirmed_usd"])
        )
        interval = bot.parameters.reopen_interval_seconds
        if interval is None:
            schedule = "单次建仓 · 定期重开未开启"
        elif bot.state == BotState.PAUSED:
            schedule = "定期重开已暂停；恢复运行后重新计时" if positions else "定期重开已暂停；运行后继续等待"
        elif bot.state in {BotState.CLOSED, BotState.ATTENTION}:
            schedule = "定期重开已结束" if bot.state == BotState.CLOSED else "定期重开已停止，等待处理"
        elif cycle["next_reopen_at"] is not None:
            schedule = f"下次定期平仓 {stamp(cycle['next_reopen_at'])} · 随机等待上限 {bot.parameters.reopen_random_wait_seconds / 60:g} 分钟"
        elif cycle["entry_not_before"] is not None:
            schedule = (
                f"随机等待至 {stamp(cycle['entry_not_before'])}，随后按价差建仓"
                if time.time() < cycle["entry_not_before"]
                else "随机等待已结束，等待价差条件"
            )
        else:
            schedule = f"建仓后每 {interval / 60:g} 分钟重开 · 随机等待上限 {bot.parameters.reopen_random_wait_seconds / 60:g} 分钟"
        self.reopen_status.set_text(schedule)
        self.reopen_status.set_visibility(interval is not None)
        self.state.set_text(STATE_NAMES[bot.state])
        self.state.classes(replace=f"pfb-state pfb-state--{bot.state.value}")
        self.parameters.set_text(
            f"建仓价差 ≥ {rate(bot.parameters.threshold_pct)} · 单侧目标 {money(bot.parameters.target_usd)}"
        )
        for role, connection_id in [
            ("long", bot.parameters.long_connection_id),
            ("short", bot.parameters.short_connection_id),
        ]:
            connection = store.connection(connection_id)
            position = next((p for p in positions if p.role == role), None)
            data = funding[role]
            self.legs[role].update(connection, position, data)
        net = funding["net_receipt_rate_pct"]
        period = (
            "小时"
            if funding["long"]["interval_seconds"] == 3600
            else f"{funding['long']['interval_seconds']}秒"
        )
        self.net_funding.set_text(
            "暂不可用"
            if net is None
            else "无需支付"
            if Decimal(net) == 0
            else f"预计净{'收取' if Decimal(net) > 0 else '支付'} {rate(abs(Decimal(net)))} / {period}"
        )
        self.update_pnl(pnl)
        mismatched = bool(positions) and (
            len(positions) != 2 or positions[0].quantity != positions[1].quantity
        )
        self.notice.set_visibility(mismatched or bot.state == BotState.ATTENTION or pending)
        self.exposure.set_text(
            "当前只有一条腿有已确认持仓，请先核实订单。"
            if len(positions) == 1
            else "两腿持仓数量不一致，请先核实订单。"
            if mismatched
            else bot.reason
            if bot.state == BotState.ATTENTION
            else "订单正在确认，仓位和盈亏待更新。"
        )
        matched = len(positions) == 2 and not mismatched and not pending
        match_text = (
            "单腿持仓"
            if len(positions) == 1
            else "数量不匹配"
            if mismatched
            else "等待确认"
            if pending or pnl["unavailable_reason"]
            else "双腿等量"
            if matched
            else "已平仓"
            if bot.state == BotState.CLOSED
            else "未建仓"
        )
        self.match.set_text(match_text)
        self.match.classes(
            replace="pfb-match pfb-match--"
            + ("bad" if mismatched else "good" if matched and not pnl["unavailable_reason"] else "unknown")
        )
        can_restart = bot.state == BotState.CLOSED and not positions and not pending
        can_run = can_restart or (
            bot.state in {BotState.READY, BotState.PAUSED}
            and not pending
            and (
                (not positions and cycle["open_operation_id"] is None)
                or (bot.state == BotState.PAUSED and matched)
            )
        )
        can_pause = not pending and (
            bot.state in {BotState.WAITING, BotState.HOLDING}
            or bot.state == BotState.ATTENTION
            and not positions
        )
        self.buttons["run"].set_enabled(can_run)
        self.buttons["run"].set_text("重新运行" if bot.state == BotState.CLOSED else "运行")
        self.buttons["pause"].set_enabled(can_pause)
        self.buttons["sync"].set_visibility(bot.state == BotState.ATTENTION)
        self.close.set_enabled(
            not pending
            and (bool(positions) or cycle["number"] > 1 and bot.state in {BotState.WAITING, BotState.PAUSED})
        )
        self.remove.set_enabled(editable["delete"])

    def update_pnl(self, pnl: dict[str, Any]) -> None:
        for key, element in self.pnl.items():
            value = pnl[key]
            element.set_text(money(value) if key == "fees" else pnl_money(value))
            rounded = Decimal(value).quantize(Decimal("0.01")) if value is not None else None
            tone = (
                "unknown"
                if rounded is None
                else "neutral"
                if rounded == 0 or key == "fees"
                else "positive"
                if rounded > 0
                else "negative"
            )
            element.classes(
                replace=f"pfb-metric-value pfb-value-{tone}"
                + (" pfb-metric-value--main" if key == "net" else "")
            )
        self.pnl_error.set_visibility(bool(pnl["unavailable_reason"]))
        self.pnl_error.set_text(pnl["unavailable_reason"] or "")


class AlertFeed:
    def __init__(self, store: Store):
        self.store = store
        self.root = ui.column().classes("w-full")
        self.cards: dict[str, tuple[ui.card, ui.button]] = {}

    def update(self):
        rows = self.store.rows(alerts)[:50]
        keep = {r["id"] for r in rows}
        for alert_id in list(self.cards):
            if alert_id not in keep:
                self.cards.pop(alert_id)[0].delete()
        for alert in reversed(rows):
            aid = alert["id"]
            if aid not in self.cards:
                with self.root, ui.card().classes("w-full p-4") as card:
                    ui.label(alert["message"])
                    ui.label(stamp(alert["created_at"])).classes("text-xs text-slate-500")

                    def acknowledge(alert_id=aid):
                        self.store.acknowledge_alert(alert_id)
                        self.update()

                    button = ui.button("已读", on_click=acknowledge).props("flat dense")
                card.move(target_index=0)
                self.cards[aid] = card, button
            self.cards[aid][1].set_visibility(not alert["acknowledged"])
