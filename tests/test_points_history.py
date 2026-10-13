import time
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from nicegui import ui
from test_account_form import page as page
from test_points import add_lighter
from test_points import configured_points as configured_points
from test_points import points_page as points_page

from perp_farming_bots.api import register_routes
from perp_farming_bots.notifications import Notifications
from perp_farming_bots.points import scope_id
from perp_farming_bots.points_widgets import PointsCard, chart_data
from perp_farming_bots.store import Store


async def test_samples_preserve_precision_zero_failures_and_account_isolation_after_restart(env, monkeypatch):
    store, runtime, _, _ = env
    one = add_lighter(env, monkeypatch, index=12)
    two = add_lighter(env, monkeypatch, index=13)
    request = AsyncMock(return_value={"total_live_points": Decimal("2.137635570967187")})
    monkeypatch.setattr(runtime.points, "request", request)
    await runtime.points.refresh(one.id)
    await runtime.points.refresh(one.id)
    assert len(runtime.points.history(one.id)["samples"]) == 1, (
        "coalesced reads must not duplicate observations"
    )
    runtime.points.checked.clear()
    request.return_value = {"total_live_points": 0}
    await runtime.points.refresh(one.id)
    runtime.points.checked.clear()
    request.side_effect = ValueError("secret-native-token")
    await runtime.points.refresh(one.id)
    request.side_effect = None
    request.return_value = {"total_live_points": 99}
    await runtime.points.refresh(two.id)
    samples = runtime.points.history(one.id)["samples"]
    assert [row["value"] for row in samples] == ["2.137635570967187", "0", None]
    assert [row["status"] for row in samples] == ["available", "available", "unavailable"]
    assert "secret" not in str(samples)
    assert [row["value"] for row in runtime.points.history(two.id)["samples"]] == ["99"]
    another = Store(Path(store.engine.url.database))
    try:
        assert another.points_history(scope_id(one), 0) == samples
    finally:
        another.close()


async def test_history_api_filters_time_ranges_and_rejects_invalid_period(env, monkeypatch):
    store, runtime, a, _ = env
    rh = add_lighter(env, monkeypatch)
    now = time.time()
    for age, value in [(31 * 86400, "1"), (8 * 86400, "2"), (2 * 86400, "3"), (120, "4")]:
        store.save_point_sample(
            scope_id(rh), "live_total", now - age, "available", Decimal(value), None, "official"
        )
    app = FastAPI()
    register_routes(app, store, runtime, Notifications(store, runtime.accounts.secrets))
    with TestClient(app) as client:
        endpoint = f"/api/connections/{rh.id}/points/history"
        assert [s["value"] for s in client.get(endpoint).json()["samples"]] == ["4"]
        assert [s["value"] for s in client.get(endpoint, params={"period": "7d"}).json()["samples"]] == [
            "3",
            "4",
        ]
        assert [s["value"] for s in client.get(endpoint, params={"period": "30d"}).json()["samples"]] == [
            "2",
            "3",
            "4",
        ]
        assert client.get(endpoint, params={"period": "all"}).status_code == 422
        assert client.get(f"/api/connections/{a.id}/points/history").json()["samples"] == []


def test_chart_keeps_read_failures_and_program_outages_as_gaps_without_zero_or_interpolation():
    rows = [
        {"sampled_at": 1000, "status": "available", "value": "2"},
        {"sampled_at": 1120, "status": "unavailable", "value": None},
        {"sampled_at": 1240, "status": "available", "value": "0"},
        {"sampled_at": 5000, "status": "available", "value": "3"},
    ]
    assert chart_data(rows) == [
        [1000000, 2.0],
        [1120000, None],
        [1240000, 0.0],
        [1240001, None],
        [5000000, 3.0],
    ]


async def test_curve_and_selected_range_update_in_place(points_page, configured_points, env):
    store, runtime, _, _ = env
    with points_page:
        card = PointsCard(runtime.points.view(configured_points.id), runtime.points)
    now = time.time()
    for age, value in [(2 * 86400, 1), (240, 2), (120, 3)]:
        store.save_point_sample(
            scope_id(configured_points),
            "live_total",
            now - age,
            "available",
            Decimal(value),
            None,
            "official",
        )
    card.update(runtime.points.view(configured_points.id))
    assert len(card.chart.options["series"][0]["data"]) == 2
    assert card.chart.options["series"][0]["connectNulls"] is False
    old_id = card.chart.id
    card.period.set_value("7d")
    card.update_history()
    card.update(runtime.points.view(configured_points.id))
    assert card.period.value == "7d"
    assert card.chart.id == old_id
    assert len(card.chart.options["series"][0]["data"]) == 4, "long unobserved span must add a visual gap"
    labels = [e.text for e in points_page.elements.values() if isinstance(e, ui.label)]
    assert "积分历史" in labels
