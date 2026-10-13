from decimal import Decimal

from nicegui import ui

from .formatting import stamp
from .models import PROVIDER_NAMES
from .points import MAX_AGE_SECONDS, ConnectionPoints, Points


def chart_data(rows: list[dict]) -> list[list]:
    data: list[list] = []
    previous: float | None = None
    for row in rows:
        timestamp = row["sampled_at"] * 1000
        if previous is not None and timestamp - previous > MAX_AGE_SECONDS * 1000:
            # A visual gap marks an unobserved interval, not a stored observation.
            data.append([previous + 1, None])
        data.append([timestamp, float(Decimal(row["value"])) if row["status"] == "available" else None])
        previous = timestamp
    return data


class PointsCard:
    def __init__(self, snapshot: ConnectionPoints, points: Points):
        self.points = points
        self.snapshot = snapshot
        self.chart: ui.echart | None = None
        self.chart_data: list | None = None
        self.root = ui.card().classes("w-full p-5 gap-4 border border-slate-200 shadow-none items-stretch")
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
            if snapshot.provider.value == "lighter_robinhood":
                with ui.row().classes("w-full items-center justify-between"):
                    ui.label("积分历史").classes("text-sm font-medium text-slate-700")
                    self.period = (
                        ui.toggle(
                            {"24h": "24 小时", "7d": "7 天", "30d": "30 天"},
                            value="24h",
                            on_change=lambda: self.update_history(),
                        )
                        .props("dense no-caps unelevated")
                        .classes("text-xs")
                    )
                self.history_status = ui.label().classes("text-xs text-slate-500")
                self.chart = ui.echart(
                    {
                        "animation": False,
                        "color": ["#059669"],
                        "grid": {"left": 54, "right": 20, "top": 22, "bottom": 34},
                        "tooltip": {"trigger": "axis"},
                        "xAxis": {
                            "type": "time",
                            "axisLine": {"lineStyle": {"color": "#cbd5e1"}},
                            "axisLabel": {"color": "#64748b"},
                        },
                        "yAxis": {
                            "type": "value",
                            "scale": True,
                            "name": "积分",
                            "axisLabel": {"color": "#64748b"},
                            "splitLine": {"lineStyle": {"color": "#f1f5f9"}},
                        },
                        "series": [
                            {
                                "name": "我的积分",
                                "type": "line",
                                "smooth": False,
                                "connectNulls": False,
                                "showSymbol": True,
                                "symbolSize": 4,
                                "data": [],
                            }
                        ],
                    }
                ).classes("w-full h-64")
                ui.label("每 2 分钟采集；失败或长时间未采集处断开。历史从开启采集时记录。").classes(
                    "text-xs text-slate-500"
                )
        self.update(snapshot)

    def update(self, snapshot: ConnectionPoints) -> None:
        self.snapshot = snapshot
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
        self.update_history()

    def update_history(self) -> None:
        if self.chart is None:
            return
        history = self.points.history(self.snapshot.connection_ids[0], self.period.value)
        rows = history["samples"]
        # Preserve missing samples as gaps, never as zero-valued points.
        data = chart_data(rows)
        valid = sum(row["status"] == "available" for row in rows)
        self.chart.set_visibility(valid > 0)
        self.history_status.set_text(
            "尚无历史采样，后台会自动开始记录。"
            if not rows
            else "暂未采集到有效积分，等待下一次读取。"
            if not valid
            else f"已记录 {valid} 次有效采样 · {len(rows) - valid} 次读取失败"
            + (" · 再采集一次后形成曲线" if valid == 1 else "")
        )
        if self.chart_data != data:
            self.chart.options["series"][0]["data"] = data
            self.chart.update()
            self.chart_data = data


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
                    self.cards[snapshot.scope_id] = PointsCard(snapshot, self.points)
            else:
                self.cards[snapshot.scope_id].update(snapshot)
