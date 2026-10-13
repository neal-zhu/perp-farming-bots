import pytest
from nicegui import ui
from pydantic import ValidationError
from test_account_form import page as page
from test_bot_management import bot_page as bot_page
from test_bot_management import configured_bot as configured_bot
from test_runtime import make_bot, open_bot

from perp_farming_bots.api import Command
from perp_farming_bots.models import BotState


async def test_run_pauses_and_resumes_without_repeating_entry(env):
    store, runtime, a, b = env
    bot = make_bot(store, a, b)
    await runtime.command(bot.id, "run")
    await runtime.command(bot.id, "pause")
    assert not await runtime.try_open(bot.id)
    assert runtime.accounts.adapter(a.id).sent == []
    await runtime.command(bot.id, "run")
    assert await runtime.try_open(bot.id)
    inventory = store.positions(bot.id)
    await runtime.command(bot.id, "pause")
    await runtime.command(bot.id, "run")
    assert store.bot(bot.id).state == BotState.HOLDING
    assert store.positions(bot.id) == inventory
    assert len(runtime.accounts.adapter(a.id).sent) == len(runtime.accounts.adapter(b.id).sent) == 1
    await runtime.command(bot.id, "close")
    assert store.bot(bot.id).state == BotState.CLOSED
    history = store.bot_orders(bot.id)
    await runtime.command(bot.id, "run")
    assert store.bot(bot.id).state == BotState.WAITING
    assert store.cycle(bot.id)["number"] == 2 and store.cycle(bot.id)["open_operation_id"] is None
    assert store.bot_orders(bot.id) == history
    await runtime.sync(bot.id)
    assert store.bot(bot.id).state == BotState.WAITING
    assert await runtime.try_open(bot.id)
    assert store.bot_orders(bot.id)[0]["operation_id"] != history[0]["operation_id"]


async def test_closed_hedge_failed_preflight_preserves_cycle_and_journals(env):
    store, runtime, a, b = env
    bot = await open_bot(store, runtime, a, b)
    await runtime.command(bot.id, "close")
    before = store.bot(bot.id), store.cycle(bot.id), store.bot_orders(bot.id)
    runtime.markets.stale = True
    with pytest.raises(ValueError):
        await runtime.command(bot.id, "run")
    assert before == (store.bot(bot.id), store.cycle(bot.id), store.bot_orders(bot.id))


async def test_close_without_inventory_does_not_change_waiting_state(env):
    store, runtime, a, b = env
    bot = make_bot(store, a, b)
    await runtime.command(bot.id, "run")
    with pytest.raises(ValueError, match="无需平仓"):
        await runtime.command(bot.id, "close")
    assert store.bot(bot.id).state == BotState.WAITING
    assert runtime.accounts.adapter(a.id).sent == []


@pytest.mark.parametrize("old_action", ["start", "resume", "stop"])
def test_old_lifecycle_commands_are_rejected_instead_of_silently_aliased(old_action):
    with pytest.raises(ValidationError):
        Command(action=old_action)


def test_bot_has_three_primary_trading_buttons(bot_page):
    buttons = {e.text: e for e in bot_page.elements.values() if isinstance(e, ui.button)}
    assert all(name in buttons for name in ["运行", "暂停", "平仓"])
    assert not any(name in buttons for name in ["启动", "恢复", "停止", "停止并平仓"])
    assert buttons["运行"].enabled
    assert not buttons["暂停"].enabled
    assert not buttons["平仓"].enabled
    assert buttons["运行"].parent_slot.parent == buttons["平仓"].parent_slot.parent
    assert buttons["修改参数"].parent_slot.parent != buttons["运行"].parent_slot.parent
