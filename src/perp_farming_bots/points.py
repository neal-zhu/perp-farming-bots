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


class PointMetric(StrictModel):
    key: Literal["live_total", "reported_total", "last_week"]
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
        else f"{connection.provider}:{connection.account_index}"
    )


def definitions(provider: Provider) -> list[tuple[str, str, str, str]]:
    if provider in {Provider.LIGHTER, Provider.LIGHTER_RH}:
        allocated = [
            ("reported_total", "官方累计积分", "unknown", HOSTS[provider] + "/api/v1/referral/points"),
            ("last_week", "官方上周积分", "unknown", HOSTS[provider] + "/api/v1/referral/points"),
        ]
        if provider == Provider.LIGHTER_RH:
            return [
                ("live_total", "实时总积分", "account", HOSTS[provider] + "/api/v1/livePoints/total"),
                *allocated,
            ]
        return allocated
    return [
        (
            "reported_total",
            "积分",
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
        if connection.provider not in {Provider.LIGHTER, Provider.LIGHTER_RH}:
            return self.base(
                connection,
                "unsupported",
                "Arcus 积分暂未接入，请到官网查看。"
                if connection.provider == Provider.ARCUS
                else "该平台的官方积分尚未接入",
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
        response = await self.markets.http.get(
            HOSTS[provider] + path,
            params={"account_index": account_index},
            headers={"authorization": token},
        )
        if response.status_code != 200:
            raise VenueRequestError("官方积分读取失败", response.status_code)
        # referral/points has no code field in its documented successful schema;
        # livePoints/total requires code=200. Do not change the trading API parser.
        payload = json.loads(response.text, parse_float=Decimal)
        if not isinstance(payload, dict):
            raise ValueError("官方积分响应不是对象")
        if ("code" in payload and payload["code"] != 200) or (
            path == "/api/v1/livePoints/total" and payload.get("code") != 200
        ):
            raise ValueError("官方积分返回非成功状态")
        return payload

    async def refresh(self, connection_id: str) -> ConnectionPoints:
        key = scope_id(self.store.connection(connection_id))
        async with self.locks.setdefault(key, asyncio.Lock()):
            connection = self.store.connection(connection_id)
            if connection.provider not in {Provider.LIGHTER, Provider.LIGHTER_RH}:
                return self.view(connection_id)
            # Coalesce refresh clicks and background polling without replaying reads.
            if time.time() - self.checked.get(key, 0) < 10:
                return self.view(connection_id)
            snapshot = self.base(connection, "unavailable", "官方积分读取失败，请稍后刷新")
            try:
                adapter = self.accounts.adapter(connection_id)
                if not isinstance(adapter, Lighter):
                    raise ValueError("原生账户适配器不匹配")
                token = await adapter.auth()
                paths = tuple(
                    dict.fromkeys(m.source.removeprefix(HOSTS[connection.provider]) for m in snapshot.metrics)
                )
                results = dict(
                    zip(
                        paths,
                        await asyncio.gather(
                            *(
                                self.request(connection.provider, path, connection.account_index, token)
                                for path in paths
                            ),
                            return_exceptions=True,
                        ),
                        strict=True,
                    )
                )
                for index, metric in enumerate(snapshot.metrics):
                    result = results[metric.source.removeprefix(HOSTS[connection.provider])]
                    if isinstance(result, BaseException):
                        metric.reason = self.failure(result)
                        continue
                    field = {
                        "live_total": "total_live_points",
                        "reported_total": "user_total_points",
                        "last_week": "user_last_week_points",
                    }[metric.key]
                    try:
                        value = number(result, field)
                    except Exception:
                        metric.reason = "官方积分数据缺失或格式异常，请稍后刷新"
                        continue
                    snapshot.metrics[index] = PointMetric(
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
            self.checked[key] = time.time()
            return self.view(connection_id)

    @staticmethod
    def failure(exc: BaseException) -> str:
        if isinstance(exc, VenueRequestError) and exc.status_code in {401, 403}:
            return "积分授权失败，请检查账户 API key 后刷新"
        if isinstance(exc, VenueRequestError) and exc.status_code == 429:
            return "官方积分接口限流，请稍后刷新"
        return "官方积分读取失败，请稍后刷新"
