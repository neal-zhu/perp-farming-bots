from __future__ import annotations

import asyncio
import json
import time
from decimal import Decimal
from typing import Any, Literal

from pydantic import Field, model_validator

from .markets import HOSTS, Markets, VenueRequestError
from .models import Connection, Provider, StrictModel
from .store import Store
from .trading import Accounts, Lighter

REFRESH_SECONDS = 120
MAX_AGE_SECONDS = 300
ARCUS_POINTS_URL = "https://app.arcus.xyz/rewards"
LIGHTER_POINTS_URL = "https://app.lighter.xyz/referrals"
RH_POINTS_URL = "https://robinhoodchain.lighter.xyz/leaderboard"
HISTORY_RANGES = {"24h": 86400, "7d": 604800, "30d": 2592000}


class PointMetric(StrictModel):
    key: Literal["live_total"]
    label: str
    scope: Literal["account", "wallet", "unknown"]
    status: Literal["available", "unavailable", "unsupported"]
    value: Decimal | None = Field(ge=0, allow_inf_nan=False)
    received_at: float | None
    reason: str | None
    source: str

    @model_validator(mode="after")
    def explicit_value(self) -> PointMetric:
        if self.status == "available":
            if self.value is None or self.received_at is None or self.reason is not None:
                raise ValueError("可用积分必须有官方数值、读取时间且没有失败原因")
        elif self.value is not None or self.received_at is not None or not self.reason:
            raise ValueError("不可用积分必须保留空值并说明原因")
        return self


class ConnectionPoints(StrictModel):
    scope_id: str
    connection_ids: list[str]
    name: str
    provider: Provider
    official_url: str | None
    metrics: list[PointMetric]


def scope_id(connection: Connection) -> str:
    return (
        f"arcus:{connection.address}"
        if connection.provider == Provider.ARCUS
        else f"entropy:{connection.address}"
        if connection.provider == Provider.ENTROPY
        else f"ondo:{connection.account_ref}"
        if connection.provider == Provider.ONDO
        else f"{connection.provider}:{connection.account_index}"
    )


def definitions(provider: Provider) -> list[tuple[str, str, str, str]]:
    if provider == Provider.LIGHTER_RH:
        return [("live_total", "我的积分", "account", HOSTS[provider] + "/api/v1/livePoints/total")]
    return [
        (
            "live_total",
            "我的积分",
            "wallet" if provider == Provider.ARCUS else "unknown",
            "Arcus 官网（暂未接入）" if provider == Provider.ARCUS else "尚未接入",
        )
    ]


def blank(connection: Connection, status: str, reason: str) -> ConnectionPoints:
    return ConnectionPoints.model_validate(
        {
            "scope_id": scope_id(connection),
            "connection_ids": [connection.id],
            "name": connection.name,
            "provider": connection.provider,
            "official_url": {
                Provider.ARCUS: ARCUS_POINTS_URL,
                Provider.LIGHTER: LIGHTER_POINTS_URL,
                Provider.LIGHTER_RH: RH_POINTS_URL,
            }.get(connection.provider),
            "metrics": [
                {
                    "key": key,
                    "label": label,
                    "scope": scope,
                    "source": source,
                    "status": status,
                    "value": None,
                    "received_at": None,
                    "reason": reason,
                }
                for key, label, scope, source in definitions(connection.provider)
            ],
        }
    )


def number(payload: dict[str, Any], field: str) -> Decimal:
    raw = payload[field]
    # The documented fields are JSON numbers. Missing/null/boolean/string values
    # are schema errors, not a new account with zero points.
    if isinstance(raw, bool) or not isinstance(raw, (int, float, Decimal)):
        raise ValueError("官方积分字段不是数字")
    result = Decimal(str(raw))
    if not result.is_finite() or result < 0:
        raise ValueError("官方积分字段不是有效非负数字")
    return result


class Points:
    """Read-only points polling, independent of the strategy execution task."""

    def __init__(self, store: Store, markets: Markets, accounts: Accounts):
        self.store, self.markets, self.accounts = store, markets, accounts
        self.snapshots: dict[str, ConnectionPoints] = {}
        self.checked: dict[str, float] = {}
        self.locks: dict[str, asyncio.Lock] = {}
        self.task: asyncio.Task[None] | None = None

    def base(self, connection: Connection, status: str, reason: str) -> ConnectionPoints:
        snapshot = blank(connection, status, reason)
        members = [c for c in self.store.connections() if scope_id(c) == snapshot.scope_id]
        snapshot.connection_ids = [c.id for c in members]
        snapshot.name = " / ".join(c.name for c in members)
        return snapshot

    def view(self, connection_id: str) -> ConnectionPoints:
        connection = self.store.connection(connection_id)
        if connection.provider != Provider.LIGHTER_RH:
            return self.base(
                connection,
                "unsupported",
                "Arcus 积分暂未接入，请到官网查看。"
                if connection.provider == Provider.ARCUS
                else "该平台的账户实时积分暂未接入，请到官网查看。",
            )
        snapshot = self.snapshots.get(scope_id(connection))
        if snapshot is None:
            snapshot = self.base(connection, "unavailable", "等待读取官方积分")
        metrics = []
        for metric in snapshot.metrics:
            if (
                metric.received_at is not None
                and not 0 <= time.time() - metric.received_at <= MAX_AGE_SECONDS
            ):
                metric = metric.model_copy(
                    update={
                        "status": "unavailable",
                        "value": None,
                        "received_at": None,
                        "reason": "积分数据已过期，等待重新读取",
                    }
                )
            metrics.append(metric)
        group = self.base(connection, "unavailable", "等待读取官方积分")
        return snapshot.model_copy(
            update={
                "name": group.name,
                "connection_ids": group.connection_ids,
                "metrics": metrics,
            }
        )

    def views(self) -> list[ConnectionPoints]:
        result: dict[str, ConnectionPoints] = {}
        for c in self.store.connections():
            key = scope_id(c)
            if key not in result:
                result[key] = self.view(c.id)
        return list(result.values())

    def listing(self) -> list[dict[str, Any]]:
        return [snapshot.model_dump(mode="json") for snapshot in self.views()]

    def history(self, connection_id: str, period: str = "24h") -> dict[str, Any]:
        if period not in HISTORY_RANGES:
            raise ValueError("积分历史范围仅支持 24h、7d、30d")
        connection = self.store.connection(connection_id)
        since = time.time() - HISTORY_RANGES[period]
        return {
            "scope_id": scope_id(connection),
            "period": period,
            "since": since,
            "samples": self.store.points_history(scope_id(connection), since),
        }

    async def start(self) -> None:
        self.task = asyncio.create_task(self.run())

    async def stop(self) -> None:
        if self.task is not None:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

    async def run(self) -> None:
        while True:
            await self.refresh_all()
            await asyncio.sleep(REFRESH_SECONDS)

    async def refresh_all(self) -> list[dict[str, Any]]:
        # A connection may be removed while its read is in flight. One account
        # must not prevent the other accounts' refresh or terminate the poller.
        await asyncio.gather(
            *(self.refresh(s.connection_ids[0]) for s in self.views()), return_exceptions=True
        )
        return self.listing()

    async def request(self, provider: Provider, path: str, account_index: int, token: str) -> dict[str, Any]:
        if provider != Provider.LIGHTER_RH or path != "/api/v1/livePoints/total":
            raise ValueError("该平台的账户实时积分尚未接入")
        response = await self.markets.request_response(
            provider,
            "GET",
            path,
            params={"account_index": account_index},
            headers={"authorization": token},
        )
        if response.status_code != 200:
            raise VenueRequestError("官方积分读取失败", response.status_code)
        payload = json.loads(response.text, parse_float=Decimal)
        if not isinstance(payload, dict):
            raise ValueError("官方积分响应不是对象")
        if payload.get("code") != 200:
            raise ValueError("官方积分返回非成功状态")
        return payload

    async def refresh(self, connection_id: str) -> ConnectionPoints:
        key = scope_id(self.store.connection(connection_id))
        async with self.locks.setdefault(key, asyncio.Lock()):
            connection = self.store.connection(connection_id)
            if connection.provider != Provider.LIGHTER_RH:
                return self.view(connection_id)
            # Coalesce refresh clicks and background polling without replaying reads.
            if time.time() - self.checked.get(key, 0) < 10:
                return self.view(connection_id)
            snapshot = self.base(connection, "unavailable", "官方积分读取失败，请稍后刷新")
            try:
                adapter = self.accounts.adapter(connection_id)
                if not isinstance(adapter, Lighter):
                    raise ValueError("原生账户适配器不匹配")
                if connection.account_index is None:
                    raise ValueError("缺少 Lighter 原生账户编号")
                token = await adapter.auth()
                result = await self.request(
                    connection.provider, "/api/v1/livePoints/total", connection.account_index, token
                )
                try:
                    value = number(result, "total_live_points")
                except Exception:
                    snapshot.metrics[0].reason = "官方积分数据缺失或格式异常，请稍后刷新"
                else:
                    metric = snapshot.metrics[0]
                    snapshot.metrics[0] = PointMetric(
                        key=metric.key,
                        label=metric.label,
                        scope=metric.scope,
                        source=metric.source,
                        status="available",
                        value=value,
                        received_at=time.time(),
                        reason=None,
                    )
            except Exception as exc:
                for metric in snapshot.metrics:
                    metric.reason = self.failure(exc)
            self.snapshots[key] = snapshot
            sampled_at = time.time()
            for metric in snapshot.metrics:
                self.store.save_point_sample(
                    key, metric.key, sampled_at, metric.status, metric.value, metric.reason, metric.source
                )
            self.checked[key] = sampled_at
            return self.view(connection_id)

    @staticmethod
    def failure(exc: BaseException) -> str:
        if isinstance(exc, VenueRequestError) and exc.status_code in {401, 403}:
            return "积分授权失败，请检查账户 API key 后刷新"
        if isinstance(exc, VenueRequestError) and exc.status_code == 429:
            return "官方积分接口限流，请稍后刷新"
        return "官方积分读取失败，请稍后刷新"
