import time
from collections.abc import Callable
from decimal import Decimal
from typing import Any

from nicegui import ui

from .formatting import grid_capital_text, money, pnl_money, rate, stamp
from .grid import target_quantity
from .models import (
    GRID_DIRECTION_NAMES,
    PROVIDER_NAMES,
    STATE_NAMES,
    Bot,
    BotState,
    Connection,
    GridParameters,
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
        self.provider.set_text(PROVIDER_NAMES[connection.provider])
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
                    with (
                        ui.button("更多", icon="more_horiz")
                        .props("flat dense")
                        .classes("pfb-secondary-button")
                    ):
                        with ui.menu().props("auto-close").classes("pfb-bot-menu"):
                            ui.button("修改参数", icon="tune", on_click=lambda: edit(bot_id)).props(
                                "flat align=left"
                            ).classes("pfb-menu-item")
                            self.remove = (
                                ui.button(
                                    "删除",
                                    icon="delete_outline",
                                    on_click=lambda: remove(bot_id),
                                    color="negative",
                                )
                                .props("flat align=left")
                                .classes("pfb-menu-item")
                            )
                            self.remove.tooltip("无持仓、无未确认订单时可删除")
            with ui.element("div").classes("pfb-metrics"):
                self.pnl: dict[str, ui.label] = {}
                for key, title in [("net", "交易盈亏"), ("gross", "价格盈亏"), ("fees", "手续费")]:
                    with ui.element("div").classes("pfb-metric"):
                        ui.label(title).classes("pfb-metric-label")
                        self.pnl[key] = ui.label().classes(
                            "pfb-metric-value" + (" pfb-metric-value--main" if key == "net" else "")
                        )
                with ui.element("div").classes("pfb-metric"):
                    ui.label("累计成交额").classes("pfb-metric-label").tooltip(
                        "此 Bot 的已确认成交，按实际数量 × 成交均价累加；不含未确认订单。"
                    )
                    self.turnover = ui.label().classes("pfb-metric-value")
            with ui.element("div").classes("pfb-trading-toolbar"):
                ui.label("已扣手续费 · 未计实际资金费").classes("pfb-pnl-note")
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
            with ui.element("div").classes("pfb-card-links"):
                self.buttons["sync"] = (
                    ui.button("同步订单", icon="sync", on_click=lambda: action(bot_id, "sync"))
                    .props("flat dense")
                    .classes("pfb-secondary-button")
                )
                ui.button("成交记录", icon="receipt_long", on_click=lambda: details(bot_id)).props(
                    "flat dense"
                ).classes("pfb-secondary-button")
            self.details = ui.expansion("策略与数据详情", icon="tune").props("dense").classes("pfb-details")
            with self.details, ui.element("div").classes("pfb-details-body"):
                self.parameters = ui.label()
                self.realized = ui.label()
                self.confirmed_turnover = ui.label()
                self.reason = ui.label()
                ui.label("资金费率为下次结算预估，实际资金费尚未计入 Bot 盈亏。")
                with ui.element("div").classes("pfb-detail-funding"):
                    self.funding_details: dict[str, tuple[ui.label, ui.label, ui.label, ui.label]] = {}
                    self.funding_detail_roots: dict[str, ui.element] = {}
                    for role in ("long", "short"):
                        self.funding_detail_roots[role] = ui.element("div")
                        with self.funding_detail_roots[role]:
                            funding_title = ui.label().classes("pfb-detail-title")
                            previous, settlement, received = ui.label(), ui.label(), ui.label()
                            self.funding_details[role] = funding_title, previous, settlement, received

    def build_monitor(self) -> HedgeMonitor | GridMonitor:
        return HedgeMonitor()

    def update(self, bot: Bot, store: Store, pnl: dict[str, Any], funding: dict[str, Any]):
        assert isinstance(bot.parameters, HedgeParameters)
        positions = store.positions(bot.id)
        editable = store.bot_editability(bot.id)
        pending = store.bot_pending(bot.id)
        cycle = store.cycle(bot.id)
        self.name.set_text(bot.name)
        self.symbol.set_text(f"{bot.parameters.symbol} 永续 · 价差对冲 · 第 {cycle['number']} 轮")
        volume = store.turnover(bot.id)
        self.turnover.set_text(
            "待确认" if volume["has_unconfirmed_orders"] else money(volume["confirmed_usd"])
        )
        self.confirmed_turnover.set_text(
            f"累计已确认成交额 {money(volume['confirmed_usd'])} · 双腿建仓和平仓"
            + ("；未确认订单尚未计入" if volume["has_unconfirmed_orders"] else "")
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
        self.state.set_text(STATE_NAMES[bot.state])
        self.state.classes(replace=f"pfb-state pfb-state--{bot.state.value}")
        self.parameters.set_text(
            f"建仓价差 ≥ {rate(bot.parameters.threshold_pct)} · 单侧目标 {money(bot.parameters.target_usd)} · 滑点上限 {rate(bot.parameters.slippage_bps / 100)}"
        )
        self.realized.set_text(f"已实现价格盈亏 {pnl_money(pnl['realized'])}")
        self.reason.set_text(f"状态说明：{bot.reason}")
        for role, connection_id in [
            ("long", bot.parameters.long_connection_id),
            ("short", bot.parameters.short_connection_id),
        ]:
            connection = store.connection(connection_id)
            position = next((p for p in positions if p.role == role), None)
            data = funding[role]
            self.legs[role].update(connection, position, data)
            title, previous, settlement, received = self.funding_details[role]
            title.set_text(f"{'做多' if role == 'long' else '做空'} {connection.name} · 资金费数据")
            if data["status"] == "available":
                previous.set_text(f"上次结算 {rate(data['last_rate_pct'])}")
                settlement.set_text(f"下次结算 {stamp(data['next_payment_at'])}")
                received.set_text(f"更新于 {stamp(data['received_at'])}")
            else:
                previous.set_text(data["unavailable_reason"])
            settlement.set_visibility(data["status"] == "available")
            received.set_visibility(data["status"] == "available")
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
                if rounded == 0 or key != "net"
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


class GridBotCard(BotCard):
    def build_monitor(self) -> GridMonitor:
        self.reopen_status.set_visibility(False)
        return GridMonitor()

    def update(self, bot: Bot, store: Store, pnl: dict[str, Any], funding: dict[str, Any]):
        p = bot.parameters
        assert isinstance(p, GridParameters)
        positions, state = store.positions(bot.id), store.grid_state(bot.id)
        pending, volume = store.bot_pending(bot.id), store.turnover(bot.id)
        self.name.set_text(bot.name)
        self.symbol.set_text(f"{p.symbol} 永续 · {GRID_DIRECTION_NAMES[p.direction]}网格 · {p.grid_count} 格")
        state_name = (
            "网格运行中"
            if bot.state == BotState.HOLDING
            else "等待进入区间"
            if bot.state == BotState.WAITING
            else STATE_NAMES[bot.state]
        )
        self.state.set_text(state_name)
        self.state.classes(replace=f"pfb-state pfb-state--{bot.state.value}")
        self.turnover.set_text(
            "待确认" if volume["has_unconfirmed_orders"] else money(volume["confirmed_usd"])
        )
        self.confirmed_turnover.set_text(
            f"累计已确认成交额 {money(volume['confirmed_usd'])} · 包含初始建仓、每格成交和平仓"
        )
        self.parameters.set_text(
            f"区间 {money(p.lower_price)}–{money(p.upper_price)} · {p.grid_count} 格 · {grid_capital_text(p)} · {'启动时建仓' if p.open_position_on_start else '启动不建仓'} · 滑点上限 {rate(p.slippage_bps / 100)}"
        )
        self.realized.set_text(f"已实现价格盈亏 {pnl_money(pnl['realized'])}")
        self.reason.set_text(
            f"上次停止原因：{bot.reason} · 记录更新 {stamp(bot.updated_at)}"
            if bot.state == BotState.ATTENTION
            else f"状态说明：{bot.reason}"
        )
        schedule = "价格触发 · 需程序在线 · " + (
            "启动时建立底仓" if p.open_position_on_start else "启动不建仓，等待格线触发"
        )
        if state is not None:
            levels, cursor = state["levels"], state["cursor"]
            q = Decimal(state["quantity_per_grid"])
            anchor = state["zero_inventory_cursor"]
            current = target_quantity(p, cursor, q, anchor)
            buys = (
                money(levels[cursor - 1])
                if cursor > 0 and target_quantity(p, cursor - 1, q, anchor) != current
                else "暂无买入"
            )
            sells = (
                money(levels[cursor + 1])
                if cursor < p.grid_count and target_quantity(p, cursor + 1, q, anchor) != current
                else "暂无卖出"
            )
            schedule = f"每格 {state['quantity_per_grid']} {p.symbol} · 下格买入 {buys} · 上格卖出 {sells}"
        self.reopen_status.set_text(schedule)
        position = positions[0] if len(positions) == 1 else None
        role = position.role if position else "long"
        for key, leg in self.legs.items():
            leg.root.set_visibility(key == role)
        data = funding["position"]
        leg = self.legs[role]
        leg.update(store.connection(p.connection_id), position, data)
        leg.role_label.set_text("多仓" if position and role == "long" else "空仓" if position else "空仓位")
        if position is None and data["status"] == "available":
            leg.funding.set_text(rate(data["predicted_rate_pct"]))
            leg.funding_title.set_text("当前费率 · 无仓位")
        self.funding_summary.set_visibility(False)
        for key, root in self.funding_detail_roots.items():
            root.set_visibility(key == role)
        title, previous, settlement, received = self.funding_details[role]
        title.set_text("账户资金费数据")
        previous.set_text(
            f"上次结算 {rate(data['last_rate_pct'])}"
            if data["status"] == "available"
            else data["unavailable_reason"]
        )
        settlement.set_text(f"下次结算 {stamp(data['next_payment_at'])}")
        received.set_text(f"更新于 {stamp(data['received_at'])}")
        settlement.set_visibility(data["status"] == "available")
        received.set_visibility(data["status"] == "available")
        self.notice.set_visibility(bot.state == BotState.ATTENTION or pending)
        self.exposure.set_text(
            f"上次停止原因：{bot.reason} · 记录更新 {stamp(bot.updated_at)}"
            if bot.state == BotState.ATTENTION
            else "原订单正在确认，已停止新动作。"
        )
        self.match.set_text(
            "待确认"
            if pending
            else "多仓"
            if position and role == "long"
            else "空仓"
            if position
            else "无仓位"
        )
        self.match.classes(replace="pfb-match pfb-match--unknown" if pending else "pfb-match pfb-match--good")
        self.update_pnl(pnl)
        signed = position.quantity * (1 if role == "long" else -1) if position else Decimal(0)
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
