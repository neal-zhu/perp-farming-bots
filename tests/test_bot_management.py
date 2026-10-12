from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from nicegui import ui
from test_account_form import click
from test_account_form import page as page
from test_runtime import make_bot, open_bot

from perp_farming_bots.api import register_routes
from perp_farming_bots.models import BotState, BotUpdate, HedgeParameters
from perp_farming_bots.notifications import Notifications
from perp_farming_bots.store import fills


def edit(bot, **changes):
    parameters = HedgeParameters.model_validate({**bot.parameters.model_dump(), **changes})
    return BotUpdate(name="修改后的 Bot", parameters=parameters)


async def test_edit_waiting_bot_requires_explicit_restart_and_sends_no_orders(env):
    store, runtime, a, b = env
    bot = make_bot(store, a, b)
    await runtime.command(bot.id, "start")
    updated = store.update_bot(bot.id, edit(bot, symbol="ETH", target_usd="250", threshold_pct="0.2"))
    assert updated.state == BotState.READY
    assert updated.parameters.symbol == "ETH"
    assert updated.parameters.target_usd == Decimal("250")
    assert updated.id == bot.id and updated.request_id == bot.request_id
    assert not await runtime.try_open(bot.id)
    assert runtime.accounts.adapter(a.id).sent == runtime.accounts.adapter(b.id).sent == []


async def test_rename_waiting_bot_preserves_waiting_state(env):
    store, runtime, a, b = env
    bot = make_bot(store, a, b)
    await runtime.command(bot.id, "start")
    assert store.update_bot(bot.id, edit(bot)).state == BotState.WAITING


@pytest.mark.parametrize("change", [{"symbol": "ETH"}, {"target_usd": "250"}, {"threshold_pct": "0.2"}])
async def test_executed_bot_cannot_rebind_entry_parameters(env, change):
    store, runtime, a, b = env
    bot = await open_bot(store, runtime, a, b)
    original_positions = store.positions(bot.id)
    with pytest.raises(ValueError, match="已有订单或持仓"):
        store.update_bot(bot.id, edit(bot, **change))
    assert store.bot(bot.id).parameters == bot.parameters
    assert store.positions(bot.id) == original_positions


async def test_holding_bot_can_change_close_slippage_and_delete_only_after_close(env):
    store, runtime, a, b = env
    bot = await open_bot(store, runtime, a, b)
    updated = store.update_bot(bot.id, edit(bot, slippage_bps="35"))
    assert updated.state == BotState.HOLDING
    with pytest.raises(ValueError):
        store.delete_bot(bot.id)
    await runtime.command(bot.id, "close")
    history = store.rows(fills, bot.id)
    store.delete_bot(bot.id)
    assert store.bots() == []
    assert store.rows(fills, bot.id) == history
    assert len(store.bot_orders(bot.id)) == 4
    assert all(i.symbol == "BTC" for i in runtime.accounts.adapter(a.id).sent)


async def test_pending_operation_blocks_delete_and_parameter_edits_even_if_state_stopped(env):
    store, _, a, b = env
    bot = make_bot(store, a, b)
    store.operation(bot.id, "open")
    store.set_state(bot.id, BotState.STOPPED, "interrupted")
    assert not any(store.bot_editability(bot.id).values())
    with pytest.raises(ValueError, match="未确认"):
        store.delete_bot(bot.id)
    with pytest.raises(ValueError):
        store.update_bot(bot.id, edit(bot, target_usd="250"))
    with pytest.raises(ValueError, match="未确认"):
        store.update_bot(bot.id, edit(bot, slippage_bps="35"))
    assert store.update_bot(bot.id, edit(bot)).name == "修改后的 Bot"


async def test_bot_update_and_delete_api(env):
    store, runtime, a, b = env
    bot = make_bot(store, a, b)
    app = FastAPI()
    register_routes(app, store, runtime, Notifications(store, runtime.accounts.secrets))
    with TestClient(app) as client:
        value = edit(bot, target_usd="200").model_dump(mode="json")
        result = client.put(f"/api/bots/{bot.id}", json=value)
        assert result.status_code == 200
        assert result.json()["parameters"]["target_usd"] == "200"
        bad = client.put(f"/api/bots/{bot.id}", json={**value, "name": ""})
        assert bad.status_code == 422
        assert client.get(f"/api/bots/{bot.id}/funding").json()["long"]["status"] == "available"
        assert client.delete(f"/api/bots/{bot.id}").status_code == 200
        assert client.get("/api/bots").json() == []


@pytest.fixture
def configured_bot(env):
    store, _, a, b = env
    return make_bot(store, a, b)


@pytest.fixture
def bot_page(configured_bot, page):
    return page


async def test_edit_form_prefills_parameters_and_survives_reopening(bot_page, configured_bot, env):
    import asyncio

    store, _, _, _ = env
    click(bot_page, "修改参数")
    name = next(e for e in bot_page.elements.values() if isinstance(e, ui.input) and e.label == "Bot 名称 *")
    amount = next(
        e for e in bot_page.elements.values() if isinstance(e, ui.number) and e.label.startswith("单侧目标")
    )
    assert amount.value == 1000
    name.set_value("新名称")
    amount.set_value(250)
    click(bot_page, "修改参数")
    assert sum(isinstance(e, ui.input) and e.label == "Bot 名称 *" for e in bot_page.elements.values()) == 1
    await asyncio.gather(*click(bot_page, "保存 Bot"))
    assert store.bot(configured_bot.id).name == "新名称"
    assert store.bot(configured_bot.id).parameters.target_usd == Decimal("250")


async def test_bot_empty_name_is_inline_and_delete_requires_confirmation(bot_page, configured_bot, env):
    import asyncio

    store, _, _, _ = env
    click(bot_page, "修改参数")
    name = next(e for e in bot_page.elements.values() if isinstance(e, ui.input) and e.label == "Bot 名称 *")
    name.set_value("")
    await asyncio.gather(*click(bot_page, "保存 Bot"))
    assert name.error == "请输入 Bot 名称"
    assert store.bot(configured_bot.id).name == configured_bot.name
    click(bot_page, "取消")
    click(bot_page, "删除")
    assert len(store.bots()) == 1
    await asyncio.gather(*click(bot_page, "确认删除"))
    assert store.bots() == []


def test_bot_card_explains_funding_payment_directions(bot_page):
    labels = [e.text for e in bot_page.elements.values() if isinstance(e, ui.label)]
    assert "+0.001200% / 1小时 · 预计支付" in labels
    assert "+0.001200% / 1小时 · 预计收取" in labels
    assert any("实际资金费尚未计入 Bot 盈亏" in s for s in labels)


async def test_periodic_updates_preserve_bot_card_nodes_and_unsaved_form(bot_page):
    button = next(e for e in bot_page.elements.values() if isinstance(e, ui.button) and e.text == "修改参数")
    click(bot_page, "修改参数")
    name = next(e for e in bot_page.elements.values() if isinstance(e, ui.input) and e.label == "Bot 名称 *")
    name.set_value("尚未保存的名称")
    with bot_page:
        await bot_page.test_refresh()
        await bot_page.test_refresh()
    assert button.id in bot_page.elements, "periodic polling must update values without replacing the card"
    assert name.id in bot_page.elements and name.value == "尚未保存的名称"


async def test_periodic_updates_change_status_values_in_place(bot_page, configured_bot, env):
    store, _, _, _ = env
    old_ids = set(bot_page.elements)
    badge = next(e for e in bot_page.elements.values() if isinstance(e, ui.badge) and e.text == "待启动")
    store.set_state(configured_bot.id, BotState.WAITING, "正在等条件")
    with bot_page:
        await bot_page.test_refresh()
    assert set(bot_page.elements) == old_ids
    assert badge.text == "等待价差"
    start = next(e for e in bot_page.elements.values() if isinstance(e, ui.button) and e.text == "启动")
    pause = next(e for e in bot_page.elements.values() if isinstance(e, ui.button) and e.text == "暂停")
    assert not start.visible and pause.visible


async def test_alert_polling_keeps_telegram_draft_and_existing_alert_nodes(bot_page, env):
    store, _, _, _ = env
    tabs = next(e for e in bot_page.elements.values() if isinstance(e, ui.tabs))
    alert_tab = next(e for e in bot_page.elements.values() if isinstance(e, ui.tab) and e.label == "通知")
    tabs.set_value(alert_tab)
    token = next(e for e in bot_page.elements.values() if isinstance(e, ui.input) and e.label == "Bot Token")
    token.set_value("unsaved-test-draft")
    store.alert("测试通知")
    with bot_page:
        await bot_page.test_refresh()
    alert_label = next(
        e for e in bot_page.elements.values() if isinstance(e, ui.label) and e.text == "测试通知"
    )
    with bot_page:
        await bot_page.test_refresh()
    assert alert_label.id in bot_page.elements
    assert token.id in bot_page.elements and token.value == "unsaved-test-draft"
