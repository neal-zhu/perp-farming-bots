from nicegui import ui

from .formatting import stamp
from .models import PROVIDER_NAMES
from .points import ConnectionPoints, Points


class PointsCard:
    def __init__(self, snapshot: ConnectionPoints):
        self.root = ui.card().classes("w-full p-5 gap-4")
        with self.root:
            with ui.row().classes("w-full justify-between items-center"):
                with ui.column().classes("gap-1"):
                    self.name = ui.label().classes("text-lg font-semibold")
                    ui.label(PROVIDER_NAMES[snapshot.provider]).classes("text-sm text-slate-500")
                if snapshot.official_url is not None:
                    ui.link("到官网查看积分", snapshot.official_url, new_tab=True).classes("text-sm")
            self.metrics: dict[str, tuple[ui.label, ui.label, ui.label]] = {}
            with ui.row().classes("w-full gap-4"):
                for metric in snapshot.metrics:
                    with ui.column().classes("flex-1 min-w-48 bg-slate-50 rounded-xl p-4 gap-2"):
                        ui.label(metric.label).classes("text-sm text-slate-500")
                        value = ui.label().classes("text-2xl font-semibold")
                        status = ui.label().classes("text-sm text-slate-600")
                        source = ui.label().classes("text-xs text-slate-500 break-all")
                        self.metrics[metric.key] = value, status, source
            if any(m.scope == "unknown" for m in snapshot.metrics):
                ui.label(
                    "累计和上周积分按账户编号查询；官方未说明子账户是否合并，请以官网口径为准。"
                ).classes("text-xs text-slate-500")
        self.update(snapshot)

    def update(self, snapshot: ConnectionPoints) -> None:
        self.name.set_text(snapshot.name)
        for metric in snapshot.metrics:
            value, status, source = self.metrics[metric.key]
            available = metric.status == "available"
            value.set_text(f"{metric.value:,.4f}" if available else "—")
            scope = {"account": "账户积分", "wallet": "钱包积分", "unknown": "官方统计积分"}[metric.scope]
            status.set_text(
                f"{scope} · 读取于 {stamp(metric.received_at)}"
                if available and metric.received_at is not None
                else metric.reason or "暂不可读取"
            )
            source.set_text(f"来源：{PROVIDER_NAMES[snapshot.provider]} 官方积分")
            source.set_visibility(metric.status != "unsupported")


class PointsFeed:
    """Update numbers in place so polling preserves the user's page and drafts."""

    def __init__(self, points: Points):
        self.points = points
        self.cards: dict[str, PointsCard] = {}
        self.empty = ui.label("尚未连接账户。连接后即可查看官方积分。").classes("text-slate-500")
        self.root = ui.column().classes("w-full gap-4")
        self.update()

    def update(self) -> None:
        snapshots = self.points.views()
        self.empty.set_visibility(not snapshots)
        keep = {s.scope_id for s in snapshots}
        for connection_id in list(self.cards):
            if connection_id not in keep:
                self.cards.pop(connection_id).root.delete()
        for snapshot in snapshots:
            if snapshot.scope_id not in self.cards:
                with self.root:
                    self.cards[snapshot.scope_id] = PointsCard(snapshot)
            else:
                self.cards[snapshot.scope_id].update(snapshot)
