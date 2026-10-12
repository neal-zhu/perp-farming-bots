from decimal import Decimal

import httpx
import pytest
from conftest import connection_value
from pydantic import ValidationError

from perp_farming_bots.models import BotCreate, BotState, HedgeParameters, Provider
from perp_farming_bots.runtime import Runtime, bounded_price, common_step
from perp_farming_bots.store import fills


def make_bot(store, a, b, *, name="bot", request="request-0001", amount="1000"):
    return store.add_bot(
        BotCreate(
            request_id=request,
            name=name,
            parameters=HedgeParameters(
                long_connection_id=a.id,
                short_connection_id=b.id,
                symbol="BTC",
                threshold_pct=Decimal("-0.1"),
                target_usd=Decimal(amount),
            ),
        )
    )


async def open_bot(store, runtime, a, b, **kwargs):
    bot = make_bot(store, a, b, **kwargs)
    await runtime.command(bot.id, "start")
    assert await runtime.try_open(bot.id)
    return store.bot(bot.id)


async def test_same_venue_accounts_and_independent_bot_close(env):
    store, runtime, a, b = env
    assert a.provider == b.provider == Provider.ARCUS
    assert a.account_ref != b.account_ref
    one = await open_bot(store, runtime, a, b)
    two = await open_bot(store, runtime, a, b, request="request-0002", name="second")
    owned_two = store.positions(two.id)
    await runtime.command(one.id, "close")
    assert store.bot(one.id).state == BotState.CLOSED
    assert store.positions(one.id) == []
    assert store.positions(two.id) == owned_two
    assert runtime.accounts.adapter(a.id).net == owned_two[0].quantity
    assert all(order.reduce_only for order in runtime.accounts.adapter(a.id).sent[2:])


async def test_partial_first_leg_sizes_peer_from_actual_fill(env):
    store, runtime, a, b = env
    runtime.accounts.adapter(a.id).fraction = Decimal("0.5")
    bot = await open_bot(store, runtime, a, b, amount="120.002")
    assert store.positions(bot.id)[0].quantity == Decimal("0.001")
    assert runtime.accounts.adapter(b.id).sent[0].quantity == Decimal("0.001")
    assert "目标 0.002" in bot.reason


async def test_peer_partial_fill_retains_actual_exposure_without_risk_trade(env):
    store, runtime, a, b = env
    runtime.accounts.adapter(b.id).fraction = Decimal("0.5")
    bot = make_bot(store, a, b, amount="120.002")
    await runtime.command(bot.id, "start")
    assert not await runtime.try_open(bot.id)
    assert store.bot(bot.id).state == BotState.ATTENTION
    assert len(runtime.accounts.adapter(a.id).sent) == len(runtime.accounts.adapter(b.id).sent) == 1
    assert sorted(p.quantity for p in store.positions(bot.id)) == [Decimal("0.001"), Decimal("0.002")]


async def test_unknown_first_order_does_not_send_peer_or_retry(env):
    store, runtime, a, b = env
    runtime.accounts.adapter(a.id).unknown = True
    bot = make_bot(store, a, b)
    await runtime.command(bot.id, "start")
    assert not await runtime.try_open(bot.id)
    assert len(runtime.accounts.adapter(a.id).sent) == 1
    assert runtime.accounts.adapter(b.id).sent == []
    assert (await runtime.pnl(bot.id))["net"] is None
    assert not await runtime.try_open(bot.id)
    with pytest.raises(ValueError):
        await runtime.command(bot.id, "start")
    runtime.accounts.adapter(a.id).unknown = False
    await runtime.sync(bot.id)
    await runtime.sync(bot.id)
    assert len(store.positions(bot.id)) == 1
    assert len(store.rows(fills, bot.id)) == 1
    assert runtime.accounts.adapter(b.id).sent == []


async def test_transient_order_lookup_error_does_not_abandon_confirmed_first_leg(env, monkeypatch):
    store, runtime, a, b = env
    adapter = runtime.accounts.adapter(a.id)
    original_lookup = adapter.lookup
    lookups = 0
    await runtime.markets.http.aclose()
    runtime.markets.http = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(404, json={"error": "not indexed yet"}))
    )

    async def lookup(intent, native_id):
        nonlocal lookups
        lookups += 1
        if lookups == 1:
            await runtime.markets.request(a.provider, "GET", "/v1/order/test-order")
        return await original_lookup(intent, native_id)

    monkeypatch.setattr(adapter, "lookup", lookup)
    bot = make_bot(store, a, b)
    await runtime.command(bot.id, "start")
    assert await runtime.try_open(bot.id), "temporary first-leg lookup error must not create a single-leg bot"
    assert len(store.positions(bot.id)) == 2
    assert len(adapter.sent) == len(runtime.accounts.adapter(b.id).sent) == 1


async def test_incomplete_first_read_can_be_confirmed_without_another_send(env, monkeypatch):
    store, runtime, a, b = env
    adapter = runtime.accounts.adapter(a.id)
    original_lookup = adapter.lookup
    count = 0

    async def lookup(intent, native_id):
        nonlocal count
        count += 1
        if count == 1:
            raise KeyError("remainingSize")
        return await original_lookup(intent, native_id)

    monkeypatch.setattr(adapter, "lookup", lookup)
    bot = await open_bot(store, runtime, a, b)
    assert bot.state == BotState.HOLDING
    assert count == 2 and len(adapter.sent) == 1


async def test_invalid_native_identity_stays_unknown_and_preserves_diagnostic_after_sync(env, monkeypatch):
    store, runtime, a, b = env
    adapter = runtime.accounts.adapter(a.id)
    original_lookup = adapter.lookup
    count = 0

    async def lookup(intent, native_id):
        nonlocal count
        count += 1
        raise ValueError("Arcus 订单身份与本地提交不符")

    monkeypatch.setattr(adapter, "lookup", lookup)
    bot = make_bot(store, a, b)
    await runtime.command(bot.id, "start")
    assert not await runtime.try_open(bot.id)
    assert count == 1 and len(adapter.sent) == 1
    assert runtime.accounts.adapter(b.id).sent == []
    assert "订单身份" in store.bot(bot.id).reason
    from perp_farming_bots.store import operations

    message = store.rows(operations, bot.id)[0]["message"]
    monkeypatch.setattr(adapter, "lookup", original_lookup)
    await runtime.sync(bot.id)
    await runtime.sync(bot.id)
    assert store.rows(operations, bot.id)[0]["message"] == message
    assert "单腿持仓" in store.bot(bot.id).reason
    assert runtime.accounts.adapter(b.id).sent == []


async def test_lost_send_ack_queries_original_without_duplicate_submission(env):
    store, runtime, a, b = env
    runtime.accounts.adapter(a.id).raise_after_send = True
    bot = await open_bot(store, runtime, a, b)
    assert len(runtime.accounts.adapter(a.id).sent) == 1
    assert len(store.positions(bot.id)) == 2


async def test_partial_close_retains_remaining_allocation_and_retry_closes_only_that(env):
    store, runtime, a, b = env
    bot = await open_bot(store, runtime, a, b, amount="120.002")
    runtime.accounts.adapter(a.id).fraction = Decimal("0.5")
    await runtime.command(bot.id, "close")
    assert store.bot(bot.id).state == BotState.ATTENTION
    remaining = store.positions(bot.id)
    assert len(remaining) == 1 and remaining[0].quantity == Decimal("0.001")
    runtime.accounts.adapter(a.id).fraction = Decimal(1)
    await runtime.command(bot.id, "close")
    assert store.bot(bot.id).state == BotState.CLOSED
    assert runtime.accounts.adapter(a.id).sent[-1].quantity == Decimal("0.001")
    assert runtime.accounts.adapter(a.id).sent[-1].reduce_only is True


async def test_pause_stop_preserve_positions_and_direction_conflict(env):
    store, runtime, a, b = env
    bot = await open_bot(store, runtime, a, b)
    owned = store.positions(bot.id)
    await runtime.command(bot.id, "pause")
    await runtime.command(bot.id, "resume")
    await runtime.command(bot.id, "stop")
    assert store.positions(bot.id) == owned
    opposing = make_bot(store, b, a, request="other-request")
    with pytest.raises(ValueError, match="相反方向"):
        await runtime.command(opposing.id, "start")


async def test_external_inventory_and_orders_block_submission(env):
    store, runtime, a, b = env
    bot = make_bot(store, a, b)
    runtime.accounts.adapter(a.id).net = Decimal("0.1")
    with pytest.raises(ValueError, match="实际持仓"):
        await runtime.command(bot.id, "start")
    runtime.accounts.adapter(a.id).net = Decimal(0)
    runtime.accounts.adapter(a.id).external_orders = [{"id": "external"}]
    with pytest.raises(ValueError, match="其他未成交委托"):
        await runtime.command(bot.id, "start")
    assert runtime.accounts.adapter(a.id).sent == []


async def test_stale_quotes_and_unknown_fee_remain_explicit(env):
    store, runtime, a, b = env
    bot = await open_bot(store, runtime, a, b)
    runtime.markets.stale = True
    assert (await runtime.pnl(bot.id))["unrealized"] is None
    assert (await runtime.pnl(bot.id))["net"] is None
    assert (await runtime.pnl(bot.id))["funding"] is None


async def test_request_id_and_native_account_identity_are_unique(env):
    store, runtime, a, b = env
    bot = make_bot(store, a, b)
    assert make_bot(store, a, b).id == bot.id
    with pytest.raises(ValueError, match="请求 ID"):
        make_bot(store, a, b, amount="2000")
    with pytest.raises(ValueError, match="原生账户"):
        await runtime.accounts.add(connection_value(0, "new key same account"))
    with pytest.raises(ValidationError):
        HedgeParameters(
            long_connection_id=a.id, short_connection_id=a.id, symbol="BTC", threshold_pct=0, target_usd=100
        )
    with pytest.raises(ValidationError):
        BotCreate(request_id="future-request", name="grid", strategy="grid", parameters=bot.parameters)


async def test_restart_does_not_repeat_completed_entry(env):
    store, runtime, a, b = env
    bot = await open_bot(store, runtime, a, b)
    again = Runtime(store, runtime.markets, runtime.accounts)
    await again.start()
    assert not await again.try_open(bot.id)
    await again.stop()
    assert len(runtime.accounts.adapter(a.id).sent) == 1


async def test_rounding_is_shared_and_price_tiers_are_applied(env):
    _, runtime, a, _ = env
    assert common_step(Decimal("0.003"), Decimal("0.002")) == Decimal("0.006")
    spec = await runtime.markets.spec(a.provider, "BTC")
    spec.tick_tiers = [{"upToPrice": "100", "tick": "0.1"}, {"tick": "0.5"}]
    assert bounded_price(Decimal("99.99"), spec, "buy") == Decimal("100.0")
    assert bounded_price(Decimal("100.01"), spec, "buy") == Decimal("100.5")


async def test_signed_request_is_durable_before_send_and_private_payload_is_not_exported(env, monkeypatch):
    store, runtime, a, b = env
    bot = make_bot(store, a, b)
    adapter = runtime.accounts.adapter(a.id)
    original = adapter.send

    async def check_journal(prepared):
        records = store.bot_orders(bot.id)
        assert len(records) == 1
        assert records[0]["status"] == "submitting"
        assert "payload" not in records[0]
        raw = store.order(records[0]["id"])
        assert "client_id" not in raw["payload"]
        assert runtime.accounts.secrets.decrypt(raw["payload"])
        return await original(prepared)

    monkeypatch.setattr(adapter, "send", check_journal)
    await runtime.command(bot.id, "start")
    assert await runtime.try_open(bot.id)
