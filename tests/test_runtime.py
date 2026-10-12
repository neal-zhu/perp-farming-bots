import time
import uuid
from decimal import Decimal

import pytest

from perp_farming_bots.markets import Markets
from perp_farming_bots.models import BotCreate, BotState, ConnectionCreate, HedgeParameters, Provider
from perp_farming_bots.runtime import Runtime
from perp_farming_bots.store import Store, fills


@pytest.fixture
def system(tmp_path):
    store = Store(tmp_path / "test.db")
    runtime = Runtime(store, Markets())
    yield store, runtime
    store.close()


def accounts(store, same_venue=False, balance="10000"):
    return (
        store.add_connection(
            ConnectionCreate(
                name="账户 A", provider=Provider.DEMO_A, account_ref="A", paper_balance=Decimal(balance)
            )
        ),
        store.add_connection(
            ConnectionCreate(
                name="账户 B",
                provider=Provider.DEMO_A if same_venue else Provider.DEMO_B,
                account_ref="B",
                paper_balance=Decimal(balance),
            )
        ),
    )


def create_bot(store, long, short, amount="1000", threshold="0.1", request_id=None):
    return store.add_bot(
        BotCreate(
            request_id=request_id or uuid.uuid4().hex,
            name="测试 Bot",
            parameters=HedgeParameters(
                long_connection_id=long.id,
                short_connection_id=short.id,
                symbol="BTC",
                target_usd=Decimal(amount),
                threshold_pct=Decimal(threshold),
            ),
        )
    )


async def test_two_bots_close_only_own_allocations(system):
    store, runtime = system
    long, short = accounts(store)
    a, b = create_bot(store, long, short), create_bot(store, long, short, amount="2000")
    await runtime.command(a.id, "start")
    await runtime.command(b.id, "start")
    assert await runtime.try_open(a.id)
    assert await runtime.try_open(b.id)
    before = store.positions(b.id)
    assert len(store.positions()) == 4
    await runtime.command(a.id, "close")
    assert store.bot(a.id).state == BotState.CLOSED
    assert store.positions(b.id) == before
    assert len(store.positions()) == 2
    assert len(store.rows(fills, a.id)) == 4
    await runtime.command(a.id, "close")
    assert len(store.rows(fills, a.id)) == 4


async def test_two_accounts_at_same_venue_can_hedge(system):
    store, runtime = system
    long, short = accounts(store, same_venue=True)
    bot = create_bot(store, long, short, threshold="-0.1")
    await runtime.command(bot.id, "start")
    assert await runtime.try_open(bot.id)
    assert {p.connection_id for p in store.positions(bot.id)} == {long.id, short.id}


def test_one_account_cannot_be_both_legs(system):
    store, _ = system
    long, _ = accounts(store)
    with pytest.raises(ValueError, match="不同账户实例"):
        create_bot(store, long, long)


def test_duplicate_native_identity_is_rejected(system):
    store, _ = system
    accounts(store)
    with pytest.raises(ValueError, match="原生账户身份"):
        store.add_connection(
            ConnectionCreate(name="another API key", provider=Provider.DEMO_A, account_ref="A")
        )


async def test_opposite_inventory_is_rejected(system):
    store, runtime = system
    long, short = accounts(store)
    a = create_bot(store, long, short)
    await runtime.command(a.id, "start")
    await runtime.try_open(a.id)
    reversed_bot = create_bot(store, short, long, threshold="-1")
    with pytest.raises(ValueError, match="相反方向"):
        await runtime.command(reversed_bot.id, "start")
    assert not store.positions(reversed_bot.id)


async def test_pause_and_stop_do_not_flatten(system):
    store, runtime = system
    long, short = accounts(store)
    bot = create_bot(store, long, short)
    await runtime.command(bot.id, "start")
    await runtime.try_open(bot.id)
    original = store.positions(bot.id)
    await runtime.command(bot.id, "pause")
    assert store.positions(bot.id) == original
    await runtime.command(bot.id, "resume")
    assert store.bot(bot.id).state == BotState.HOLDING
    await runtime.command(bot.id, "stop")
    assert store.positions(bot.id) == original
    assert store.bot(bot.id).state == BotState.STOPPED


async def test_funds_admission_is_account_scoped(system):
    store, runtime = system
    long, short = accounts(store, balance="1500")
    a, b = create_bot(store, long, short), create_bot(store, long, short)
    await runtime.command(a.id, "start")
    await runtime.command(b.id, "start")
    assert await runtime.try_open(a.id)
    assert not await runtime.try_open(b.id)
    assert not store.positions(b.id)
    assert "模拟可用资金不足" in store.bot(b.id).reason


def test_create_is_idempotent_and_rejects_changed_payload(system):
    store, _ = system
    long, short = accounts(store)
    a = create_bot(store, long, short, request_id="request-123")
    b = create_bot(store, long, short, request_id="request-123")
    assert a.id == b.id
    with pytest.raises(ValueError, match="不同 Bot 参数"):
        create_bot(store, long, short, amount="2000", request_id="request-123")
    assert len(store.bots()) == 1


async def test_expired_quotes_do_not_produce_zero_pnl(system, monkeypatch):
    store, runtime = system
    long, short = accounts(store)
    bot = create_bot(store, long, short)
    await runtime.command(bot.id, "start")
    await runtime.try_open(bot.id)
    old_fetch = runtime.markets._fetch

    async def expired(provider, symbol):
        book = await old_fetch(provider, symbol)
        return book.model_copy(update={"received_at": time.time() - 100})

    runtime.markets.cache.clear()
    monkeypatch.setattr(runtime.markets, "_fetch", expired)
    pnl = await runtime.pnl(bot.id)
    assert pnl["net"] is None
    assert pnl["unrealized"] is None
    assert pnl["unavailable_reason"] == "行情已过期"


async def test_restart_preserves_positions_and_does_not_reopen(tmp_path):
    path = tmp_path / "persist.db"
    first = Store(path)
    long, short = accounts(first)
    bot = create_bot(first, long, short)
    runtime = Runtime(first, Markets())
    await runtime.command(bot.id, "start")
    await runtime.try_open(bot.id)
    quantities = [p.quantity for p in first.positions(bot.id)]
    first.close()
    second = Store(path)
    recovered = Runtime(second, Markets())
    await recovered.start()
    assert second.bot(bot.id).state == BotState.HOLDING
    assert not await recovered.try_open(bot.id)
    assert [p.quantity for p in second.positions(bot.id)] == quantities
    assert len(second.rows(fills, bot.id)) == 2
    await recovered.stop()
    second.close()


async def test_arcus_is_explicitly_unavailable(system):
    store, runtime = system
    arcus = store.add_connection(ConnectionCreate(name="Arcus A", provider=Provider.ARCUS, account_ref="A"))
    other = store.add_connection(ConnectionCreate(name="Arcus B", provider=Provider.ARCUS, account_ref="B"))
    bot = create_bot(store, arcus, other)
    with pytest.raises(ValueError, match="尚未接入"):
        await runtime.command(bot.id, "start")
    assert not store.rows(fills)


def test_unimplemented_strategy_is_rejected(system):
    store, _ = system
    long, short = accounts(store)
    with pytest.raises(ValueError, match="尚未实现"):
        BotCreate(
            request_id="request-123",
            name="网格",
            strategy="grid",
            parameters=HedgeParameters(
                long_connection_id=long.id,
                short_connection_id=short.id,
                symbol="BTC",
                target_usd=Decimal("1000"),
                threshold_pct=Decimal("0.1"),
            ),
        )
