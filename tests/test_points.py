import asyncio
import json
import time
from decimal import Decimal
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from nicegui import ui
from pydantic import SecretStr, ValidationError
from test_account_form import click
from test_account_form import page as page
from test_runtime import make_bot

from perp_farming_bots.api import register_routes
from perp_farming_bots.models import ConnectionCreate, Provider
from perp_farming_bots.notifications import Notifications
from perp_farming_bots.points import MAX_AGE_SECONDS, PointMetric
from perp_farming_bots.trading import Lighter


def add_lighter(env, monkeypatch, provider=Provider.LIGHTER_RH, index=12):
    store, runtime, a, _ = env
    value = ConnectionCreate(
        name=f"{provider.value} {index}",
        provider=provider,
        account_index=index,
        api_key_index=4,
        api_private_key=SecretStr("22" * 32),
    )
    c = store.add_connection(value, runtime.accounts.snapshots[a.id], "test-only")
    adapter = Lighter(value, runtime.markets)
    monkeypatch.setattr(adapter, "auth", AsyncMock(return_value=f"test-token-{provider.value}-{index}"))
    monkeypatch.setattr(adapter, "send", AsyncMock(side_effect=AssertionError("points must never trade")))
    runtime.accounts.adapters[c.id] = adapter
    return c


def metrics(snapshot):
    return {m.key: m for m in snapshot.metrics}


async def test_native_points_contract_and_zero_are_read_without_trading(env, monkeypatch):
    store, runtime, a, b = env
    bot = make_bot(store, a, b)
    rh = add_lighter(env, monkeypatch)
    core = add_lighter(env, monkeypatch, Provider.LIGHTER)
    reads = []

    def handle(request):
        reads.append(request)
        assert request.method == "GET"
        assert request.url.params["account_index"] == "12"
        provider = Provider.LIGHTER_RH if request.url.host == "api.rh.lighter.xyz" else Provider.LIGHTER
        assert request.headers["authorization"] == f"test-token-{provider.value}-12"
        if request.url.path == "/api/v1/livePoints/total":
            assert provider == Provider.LIGHTER_RH
            return httpx.Response(200, text='{"code":200,"total_live_points":2.137635570967187}')
        assert request.url.path == "/api/v1/referral/points"
        return httpx.Response(
            200,
            json={
                "user_total_points": 0,
                "user_last_week_points": 0,
                "user_total_referral_reward_points": 500,
                "referrals": [{"total_points": 1000}],
            },
        )

    await runtime.markets.http.aclose()
    monkeypatch.setattr(runtime.markets, "http", httpx.AsyncClient(transport=httpx.MockTransport(handle)))
    await runtime.points.refresh_all()
    rh_metrics = metrics(runtime.points.view(rh.id))
    assert rh_metrics["live_total"].value == Decimal("2.137635570967187")
    assert rh_metrics["live_total"].scope == "account"
    assert rh_metrics["reported_total"].value == rh_metrics["last_week"].value == Decimal(0)
    assert rh_metrics["reported_total"].scope == "unknown"
    assert all(m.status == "available" for m in rh_metrics.values())
    assert set(metrics(runtime.points.view(core.id))) == {"reported_total", "last_week"}
    assert len(reads) == 3
    assert {r.url.host for r in reads} == {"api.rh.lighter.xyz", "mainnet.zklighter.elliot.ai"}
    assert store.bot(bot.id) == bot and store.bot_orders(bot.id) == []
    for c in [rh, core]:
        runtime.accounts.adapter(c.id).send.assert_not_awaited()
    await runtime.points.refresh_all()
    assert len(reads) == 3, "rapid clicks must coalesce with polling"


@pytest.mark.parametrize("raw", [None, True, "0", -1, float("nan"), float("inf")])
async def test_invalid_value_never_becomes_zero_or_erases_other_valid_metrics(env, monkeypatch, raw):
    _, runtime, _, _ = env
    rh = add_lighter(env, monkeypatch)

    async def request(provider, path, index, token):
        if path.endswith("/total"):
            return {"total_live_points": raw}
        return {"user_total_points": 0, "user_last_week_points": 0}

    monkeypatch.setattr(runtime.points, "request", request)
    result = metrics(await runtime.points.refresh(rh.id))
    assert result["live_total"].status == "unavailable"
    assert result["live_total"].value is result["live_total"].received_at is None
    assert result["reported_total"].status == "available" and result["reported_total"].value == 0


@pytest.mark.parametrize("status", [401, 429, 500])
async def test_failed_refresh_discards_cached_success_and_sanitizes_native_response(env, monkeypatch, status):
    _, runtime, _, _ = env
    rh = add_lighter(env, monkeypatch)
    code = 200

    def handle(request):
        if code != 200:
            return httpx.Response(code, text="sensitive-native-token-and-body")
        return httpx.Response(
            200,
            json={
                "code": 200,
                "total_live_points": 10,
                "user_total_points": 8,
                "user_last_week_points": 2,
            },
        )

    await runtime.markets.http.aclose()
    monkeypatch.setattr(runtime.markets, "http", httpx.AsyncClient(transport=httpx.MockTransport(handle)))
    assert metrics(await runtime.points.refresh(rh.id))["live_total"].value == 10
    code = status
    runtime.points.checked.clear()
    failed = await runtime.points.refresh(rh.id)
    assert all(m.status == "unavailable" and m.value is None for m in failed.metrics)
    assert "sensitive" not in failed.model_dump_json() and "test-token" not in failed.model_dump_json()
    if status == 401:
        assert all("授权失败" in m.reason for m in failed.metrics)
    if status == 429:
        assert all("限流" in m.reason for m in failed.metrics)


async def test_missing_weekly_field_and_stale_live_data_are_explicit(env, monkeypatch):
    _, runtime, _, _ = env
    rh = add_lighter(env, monkeypatch)
    monkeypatch.setattr(
        runtime.points,
        "request",
        AsyncMock(
            return_value={
                "total_live_points": 3,
                "user_total_points": 1,
            }
        ),
    )
    result = metrics(await runtime.points.refresh(rh.id))
    assert result["last_week"].status == "unavailable" and result["last_week"].value is None
    result["live_total"].received_at = time.time() - MAX_AGE_SECONDS - 1
    view = metrics(runtime.points.view(rh.id))
    assert view["live_total"].status == "unavailable" and view["live_total"].value is None
    assert "过期" in view["live_total"].reason
    assert view["reported_total"].value == 1


async def test_arcus_is_deferred_and_does_not_make_points_requests(env, monkeypatch):
    _, runtime, a, _ = env
    request = AsyncMock(side_effect=AssertionError("no unsupported auth request"))
    monkeypatch.setattr(runtime.points, "request", request)
    result = await runtime.points.refresh(a.id)
    assert result.metrics[0].status == "unsupported"
    assert result.metrics[0].value is None and result.metrics[0].scope == "wallet"
    assert "暂未接入" in result.metrics[0].reason
    assert result.official_url == "https://app.arcus.xyz/rewards"
    request.assert_not_awaited()


async def test_one_failed_account_does_not_break_another_or_block_strategy_task(env, monkeypatch):
    _, runtime, _, _ = env
    good = add_lighter(env, monkeypatch, index=12)
    bad = add_lighter(env, monkeypatch, index=13)
    monkeypatch.setattr(runtime.accounts.adapter(bad.id), "auth", AsyncMock(side_effect=ValueError("secret")))
    started, release = asyncio.Event(), asyncio.Event()

    async def request(*args):
        started.set()
        await release.wait()
        return {"total_live_points": 2, "user_total_points": 1, "user_last_week_points": 0}

    monkeypatch.setattr(runtime.points, "request", request)
    await runtime.points.start()
    await asyncio.wait_for(started.wait(), timeout=1)
    assert runtime.task is None and runtime.points.task is not None
    assert "secret" not in runtime.points.view(bad.id).model_dump_json()
    release.set()
    for _ in range(20):
        if runtime.points.view(good.id).metrics[0].status == "available":
            break
        await asyncio.sleep(0.01)
    assert runtime.points.view(good.id).metrics[0].value == 2


def test_metric_model_rejects_unknown_with_value_or_available_without_value():
    base = dict(key="live_total", label="实时总积分", scope="account", source="official")
    for data in [
        dict(status="available", value=None, received_at=time.time(), reason=None),
        dict(status="unavailable", value=0, received_at=None, reason="missing"),
        dict(status="unavailable", value=None, received_at=None, reason=None),
    ]:
        with pytest.raises(ValidationError):
            PointMetric(**base, **data)


@pytest.fixture
def configured_points(env, monkeypatch):
    _, runtime, _, _ = env
    rh = add_lighter(env, monkeypatch)
    monkeypatch.setattr(
        runtime.points,
        "request",
        AsyncMock(
            return_value={
                "total_live_points": 2.137635570967187,
                "user_total_points": 0,
                "user_last_week_points": 0,
            }
        ),
    )
    return rh


@pytest.fixture
def points_page(configured_points, page):
    return page


async def test_page_refresh_changes_only_numbers_and_preserves_unsaved_account_form(points_page, env):
    _, runtime, _, _ = env
    click(points_page, "连接账户")
    name = next(
        e for e in points_page.elements.values() if isinstance(e, ui.input) and e.label.startswith("账户昵称")
    )
    name.set_value("尚未保存的账户")
    original_ids = set(points_page.elements)
    await asyncio.gather(*click(points_page, "刷新积分"))
    with points_page:
        await points_page.test_refresh()
    assert set(points_page.elements) == original_ids
    assert name.value == "尚未保存的账户"
    assert any(isinstance(e, ui.label) and e.text == "2.1376" for e in points_page.elements.values())
    assert sum(isinstance(e, ui.label) and e.text == "0.0000" for e in points_page.elements.values()) == 2
    assert runtime.accounts.adapters


async def test_points_api_reports_scopes_and_missing_values_without_secrets(env, configured_points):
    store, runtime, _, _ = env
    await runtime.points.refresh(configured_points.id)
    app = FastAPI()
    register_routes(app, store, runtime, Notifications(store, runtime.accounts.secrets))
    with TestClient(app) as client:
        result = client.get("/api/points").json()
        assert result[0]["metrics"][0]["status"] == "unsupported"
        assert result[0]["metrics"][0]["value"] is None
        assert result[-1]["metrics"][0]["value"] == "2.137635570967187"
        assert "test-token" not in json.dumps(result) and "api_private_key" not in json.dumps(result)
        assert client.post("/api/points/refresh").status_code == 200
