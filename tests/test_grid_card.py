"""Grid summaries keep money scope explicit and presentation free of trading actions."""

import time
from decimal import Decimal

import pytest
from nicegui import ui
from test_account_form import page as page
from test_grid import grid_bot, grid_market

from perp_farming_bots.grid_widgets import GridBotCard, short_rate


async def test_grid_overview_has_clear_money_capital_and_native_position(page, env, monkeypatch):
    store, runtime, account, _ = env
    _, adapter = await grid_market(runtime, account, monkeypatch)
    bot = grid_bot(store, account, "long")
    await runtime.command(bot.id, "run")
    assert await runtime.grid.tick(bot.id)
    bot = store.bot(bot.id)
    with page:
        card = GridBotCard(bot.id, *([lambda *args: None] * 5))
    pnl = await runtime.pnl(bot.id)
    pnl.update(net="12.4", realized="8.5", unrealized="3.92", fees="0.02")
    before = list(adapter.sent)
    card.update(bot, store, pnl, await runtime.funding(bot.id))
    assert card.name.text == "BTC" and card.direction.text == "做多 2×"
    assert card.capital.text == "$1,240.00" and "$2,480.00" in card.capital_limit.text
    assert card.pnl["net"].text == "+$12.40" and "+1.00%" in card.profit_ratio.text
    assert card.pnl["realized"].text == "+$8.50" and card.pnl["unrealized"].text == "+$3.92"
    assert card.pnl["fees"].text == "$0.02"
    assert card.count.value.text == "4" and card.size.value.text == "0.01"
    assert card.position.value.text == "多 0.02" and card.entry.value.text == "$60,000.50"
    assert card.volume.hint.text == "1 笔已确认成交"
    assert card.funding_rate.text == "+0.0012% / 小时" and card.funding_hint.text == "预计支付"
    assert card.edit.visible and card.remove.visible and card.close.visible
    assert not any(isinstance(e, ui.button) and e.text == "更多" for e in page.elements.values())
    assert adapter.sent == before


async def test_missing_money_stays_unknown_and_uninitialized_size_is_not_invented(page, env):
    store, runtime, account, _ = env
    bot = grid_bot(store, account)
    with page:
        card = GridBotCard(bot.id, *([lambda *args: None] * 5))
    pnl = await runtime.pnl(bot.id)
    pnl.update(net=None, fees=None, unrealized=None, unavailable_reason="等待确认")
    funding = await runtime.funding(bot.id)
    funding["position"].update(status="unavailable", unavailable_reason="官方数据暂不可用")
    card.update(bot, store, pnl, funding)
    assert card.pnl["net"].text == card.pnl["fees"].text == card.pnl["unrealized"].text == "待确认"
    assert "待确认" in card.profit_ratio.text and "0.00%" not in card.profit_ratio.text
    assert card.size.value.text == "尚未生成" and card.entry.value.text == "—"
    assert card.funding_rate.text == "暂不可用" and card.funding_hint.text == "等待交易所数据"
    assert runtime.accounts.adapter(account.id).sent == []


async def test_grid_plan_is_collapsed_and_expansion_survives_polling(page, env, monkeypatch):
    from perp_farming_bots.strategy_widgets import observe_strategy

    store, runtime, account, _ = env
    _, adapter = await grid_market(runtime, account, monkeypatch)
    bot = grid_bot(store, account)
    await runtime.command(bot.id, "run")
    assert await runtime.grid.tick(bot.id)
    bot = store.bot(bot.id)
    runtime.last_tick = time.time()
    with page:
        card = GridBotCard(bot.id, *([lambda *args: None] * 5))
    market = await observe_strategy(runtime, bot)
    card.update(bot, store, await runtime.pnl(bot.id), await runtime.funding(bot.id))
    card.monitor.update(bot, store, market)
    assert card.monitor.plan.value is False
    card.monitor.plan.set_value(True)
    card.monitor.show_all.set_value(True)
    elements = set(page.elements)
    card.update(bot, store, await runtime.pnl(bot.id), await runtime.funding(bot.id))
    card.monitor.update(bot, store, market)
    assert card.monitor.plan.value is True and card.monitor.show_all.value is True
    assert set(page.elements) == elements and adapter.sent == []


@pytest.mark.parametrize(
    "value,expected", [("0.000106819477549997", "+0.000107%"), ("0", "0%"), ("-0.00000001", "−<0.000001%")]
)
def test_funding_display_is_brief_without_rounding_tiny_rates_to_zero(value, expected):
    assert short_rate(Decimal(value)) == expected
