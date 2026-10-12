from collections.abc import Callable
from decimal import Decimal
from typing import Any

from nicegui import ui

from .formatting import money, stamp
from .models import STATE_NAMES, Bot, BotState
from .store import Store, alerts


class FundingLeg:
    def __init__(self):
        with ui.column().classes("flex-1 min-w-60 bg-slate-50 rounded-xl p-3 gap-1"):
            self.title = ui.label().classes("text-sm text-slate-500")
            self.rate = ui.label().classes("font-semibold")
            self.previous = ui.label().classes("text-xs text-slate-500")
            self.time = ui.label().classes("text-xs text-slate-500")

    def update(self, role: str, name: str, data: dict[str, Any]):
        self.title.set_text(f"{'做多' if role == 'long' else '做空'} {name} · 资金费率")
        available = data["status"] == "available"
        self.previous.set_visibility(available)
        if available:
            rate = Decimal(data["predicted_rate_pct"])
            direction = (
                "无需支付" if rate == 0 else "预计支付" if (rate > 0) == (role == "long") else "预计收取"
            )
            self.rate.set_text(f"{rate:+.6f}% / 1小时 · {direction}")
            self.previous.set_text(f"上次结算 {Decimal(data['last_rate_pct']):+.6f}%")
            self.time.set_text(
                f"下次结算 {stamp(data['next_payment_at'])} · 更新 {stamp(data['received_at'])}"
            )
        else:
            self.rate.set_text("暂不可用")
            self.time.set_text(data["unavailable_reason"])


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
        self.root = ui.card().classes("w-full p-6 gap-4")
        with self.root:
            with ui.row().classes("w-full items-center justify-between"):
                with ui.row().classes("items-center gap-3"):
                    self.name = ui.label().classes("text-xl font-bold")
                    self.symbol = ui.badge(color="blue-grey")
                self.state = ui.badge(color="grey-7")
            self.accounts = ui.label().classes("text-slate-600")
            self.parameters = ui.label()
            with ui.row().classes("w-full gap-4"):
                self.funding_long, self.funding_short = FundingLeg(), FundingLeg()
            self.net_funding = ui.label().classes("text-sm")
            ui.label("当前费率为下次结算预估，会随市场变化；实际资金费尚未计入 Bot 盈亏。").classes(
                "text-xs text-slate-500"
            )
            with ui.row().classes("gap-8"):
                self.pnl: dict[str, ui.label] = {}
                for key, title in [("gross", "价格盈亏"), ("realized", "已实现价差"), ("fees", "手续费")]:
                    with ui.column().classes("gap-1"):
                        ui.label(title).classes("text-xs text-slate-500")
                        self.pnl[key] = ui.label().classes("text-xl font-semibold")
            self.exposure = ui.label().classes("text-red-700 font-semibold")
            self.positions = {role: ui.label().classes("text-sm") for role in ("long", "short")}
            self.reason = ui.label().classes("text-sm text-slate-500")
            self.pnl_error = ui.label().classes("text-amber-800 text-sm")
            with ui.row().classes("gap-2"):
                self.buttons: dict[str, ui.button] = {}
                for command, title, icon in [
                    ("run", "运行", "play_arrow"),
                    ("pause", "暂停", "pause"),
                ]:
                    self.buttons[command] = ui.button(
                        title, icon=icon, on_click=lambda cmd=command: action(bot_id, cmd)
                    )
                    if command != "run":
                        self.buttons[command].props("outline")
                self.close = ui.button("平仓", on_click=lambda: close(bot_id), color="orange").props(
                    "outline"
                )
            with ui.row().classes("gap-2"):
                self.buttons["sync"] = ui.button(
                    "同步订单", icon="sync", on_click=lambda: action(bot_id, "sync")
                ).props("flat")
                ui.button("修改参数", icon="edit", on_click=lambda: edit(bot_id)).props("outline")
                self.remove = ui.button(
                    "删除", icon="delete_outline", on_click=lambda: remove(bot_id), color="negative"
                ).props("flat")
                self.remove.tooltip("无持仓、无未确认订单，且待运行/已暂停/已平仓时可删除")
                ui.button("成交明细", icon="receipt_long", on_click=lambda: details(bot_id)).props("flat")

    def update(self, bot: Bot, store: Store, pnl: dict[str, Any], funding: dict[str, Any]):
        long = store.connection(bot.parameters.long_connection_id)
        short = store.connection(bot.parameters.short_connection_id)
        positions = store.positions(bot.id)
        editable = store.bot_editability(bot.id)
        self.name.set_text(bot.name)
        self.symbol.set_text(bot.parameters.symbol)
        self.state.set_text(STATE_NAMES[bot.state])
        color = (
            "positive"
            if bot.state == BotState.HOLDING
            else "negative"
            if bot.state == BotState.ATTENTION
            else "grey-7"
        )
        self.state.props(f"color={color}")
        self.accounts.set_text(f"做多 {long.name} ↔ 做空 {short.name}")
        self.parameters.set_text(
            f"价差条件 ≥ {bot.parameters.threshold_pct}% · 目标单侧金额 {money(bot.parameters.target_usd)}"
        )
        self.funding_long.update("long", long.name, funding["long"])
        self.funding_short.update("short", short.name, funding["short"])
        net = funding["net_receipt_rate_pct"]
        self.net_funding.set_visibility(net is not None)
        if net is not None:
            self.net_funding.set_text(
                f"等额双腿预估净收取费率 {Decimal(net):+.6f}% / 1小时（正数收取，负数支付）"
            )
        for key, element in self.pnl.items():
            element.set_text(money(pnl[key]))
        mismatched = bool(positions) and (
            len(positions) != 2 or positions[0].quantity != positions[1].quantity
        )
        self.exposure.set_visibility(mismatched)
        self.exposure.set_text(
            "已确认单腿持仓，双腿对冲尚未确认" if len(positions) == 1 else "两腿已确认持仓数量不匹配"
        )
        for role, element in self.positions.items():
            owned = next((p for p in positions if p.role == role), None)
            label = "多仓" if role == "long" else "空仓"
            element.set_text(
                f"{label} {owned.quantity} {owned.symbol} · 均价 {money(owned.entry_price)}"
                if owned
                else f"{label}：尚无已确认持仓"
            )
            element.set_visibility(bool(positions))
        self.reason.set_text(bot.reason)
        self.pnl_error.set_visibility(bool(pnl["unavailable_reason"]))
        self.pnl_error.set_text(pnl["unavailable_reason"] or "")
        pending = store.bot_pending(bot.id)
        can_run = (
            bot.state in {BotState.READY, BotState.PAUSED}
            and not pending
            and (
                (not positions and not store.bot_orders(bot.id))
                or (
                    bot.state == BotState.PAUSED
                    and len(positions) == 2
                    and positions[0].quantity == positions[1].quantity
                )
            )
        )
        can_pause = not pending and (
            bot.state in {BotState.WAITING, BotState.HOLDING}
            or bot.state == BotState.ATTENTION
            and not positions
        )
        self.buttons["run"].set_enabled(can_run)
        self.buttons["pause"].set_enabled(can_pause)
        self.buttons["sync"].set_visibility(bot.state == BotState.ATTENTION)
        self.close.set_enabled(bool(positions) and not pending)
        self.remove.set_enabled(editable["delete"])


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
