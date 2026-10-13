import asyncio
import logging

import httpx
import pytest
from test_points import add_lighter

from perp_farming_bots import markets as markets_module
from perp_farming_bots.markets import Markets, VenueRequestError
from perp_farming_bots.models import Provider


@pytest.fixture
async def markets(monkeypatch):
    instance = Markets()
    await instance.http.aclose()
    monkeypatch.setattr(markets_module, "READ_RETRY_DELAY_SECONDS", 0, raising=False)
    yield instance
    await instance.close()


@pytest.mark.parametrize(
    "failure", [httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadError, httpx.ReadTimeout, 502, 503, 504]
)
async def test_transient_read_failure_recovers_once_without_returning_unknown_or_duplicate_data(
    markets, failure
):
    calls = []

    def handle(request):
        calls.append(request)
        if len(calls) == 1:
            if isinstance(failure, int):
                return httpx.Response(failure, text="private-native-response")
            raise failure("private-native-error", request=request)
        return httpx.Response(200, json={"markets": []})

    markets.http = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    assert await markets.request(Provider.ARCUS, "GET", "/v1/markets") == {"markets": []}
    assert len(calls) == 2
    assert calls[0].url == calls[1].url


@pytest.mark.parametrize("status", [401, 403, 429])
async def test_auth_and_rate_limit_failures_are_not_rapidly_retried(markets, status):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(status, text="private-native-response")

    markets.http = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    with pytest.raises(VenueRequestError) as failure:
        await markets.request(Provider.LIGHTER_RH, "GET", "/api/v1/account")
    assert failure.value.status_code == status
    assert len(calls) == 1


@pytest.mark.parametrize("failure", [httpx.ConnectError, 502])
async def test_mutating_requests_are_never_resent_after_transport_or_gateway_failure(markets, failure):
    calls = []

    def handle(request):
        calls.append(request)
        if isinstance(failure, int):
            return httpx.Response(failure)
        raise failure("private-native-error", request=request)

    markets.http = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    with pytest.raises(VenueRequestError):
        await markets.request(Provider.ARCUS, "POST", "/v1/orders", json={"signed": "private-payload"})
    assert len(calls) == 1


async def test_persistent_read_failure_exhausts_two_attempts_and_logs_only_safe_metadata(markets, caplog):
    calls = []

    def handle(request):
        calls.append(request)
        try:
            raise OSError("private-socket-details")
        except OSError as cause:
            raise httpx.ConnectError("private-native-error", request=request) from cause

    markets.http = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    caplog.set_level(logging.INFO, logger=markets_module.__name__)
    with pytest.raises(VenueRequestError, match="ConnectError"):
        await markets.request(
            Provider.ARCUS,
            "GET",
            "/v1/orders/private-order-id",
            params={"token": "private-token"},
            headers={"authorization": "private-token"},
        )
    assert len(calls) == 2
    records = " ".join(record.message for record in caplog.records if record.name == markets_module.__name__)
    assert "ConnectError" in records and "OSError" in records
    assert "attempts=2" in records and "endpoint=/v1/orders" in records
    assert "private" not in records


async def test_read_retry_has_one_total_time_budget_including_both_attempts(markets, monkeypatch):
    monkeypatch.setattr(markets_module, "READ_TOTAL_TIMEOUT_SECONDS", 0.02, raising=False)
    calls = []

    async def handle(request):
        calls.append(request)
        if len(calls) == 1:
            raise httpx.ReadError("temporary read failure", request=request)
        await asyncio.Event().wait()

    markets.http = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    with pytest.raises(VenueRequestError, match="读取超时"):
        await asyncio.wait_for(markets.request(Provider.ARCUS, "GET", "/v1/markets"), timeout=1)
    assert len(calls) == 2


async def test_points_read_reuses_safe_retry_and_keeps_exact_decimal_precision(env, monkeypatch):
    store, runtime, _, _ = env
    connection = add_lighter(env, monkeypatch)
    monkeypatch.setattr(markets_module, "READ_RETRY_DELAY_SECONDS", 0, raising=False)
    calls = []

    def handle(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(502)
        return httpx.Response(200, text='{"code":200,"total_live_points":2.137635570967187}')

    await runtime.markets.http.aclose()
    runtime.markets.http = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    snapshot = await runtime.points.refresh(connection.id)
    assert str(snapshot.metrics[0].value) == "2.137635570967187"
    assert len(calls) == 2
    assert len(runtime.points.history(connection.id)["samples"]) == 1
