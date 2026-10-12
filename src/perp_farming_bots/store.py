from __future__ import annotations

import json
import time
import uuid
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterator

from sqlalchemy import (
    Column,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
    delete,
    insert,
    select,
    update,
)
from sqlalchemy import Connection as DBConnection
from sqlalchemy.exc import IntegrityError

from .models import Bot, BotCreate, BotState, Connection, ConnectionCreate, Position

metadata = MetaData()
connections = Table(
    "connections",
    metadata,
    Column("id", String, primary_key=True),
    Column("name", String, nullable=False, unique=True),
    Column("provider", String, nullable=False),
    Column("account_ref", String, nullable=False),
    Column("paper_balance", String, nullable=False),
    Column("paper_fee_bps", String, nullable=False),
    Column("created_at", Float, nullable=False),
    UniqueConstraint("provider", "account_ref"),
)
bots = Table(
    "bots",
    metadata,
    Column("id", String, primary_key=True),
    Column("name", String, nullable=False),
    Column("request_id", String, nullable=False, unique=True),
    Column("strategy", String, nullable=False),
    Column("parameters", Text, nullable=False),
    Column("state", String, nullable=False),
    Column("reason", Text, nullable=False),
    Column("created_at", Float, nullable=False),
    Column("updated_at", Float, nullable=False),
)
positions = Table(
    "positions",
    metadata,
    Column("bot_id", String, primary_key=True),
    Column("role", String, primary_key=True),
    Column("connection_id", String, nullable=False),
    Column("symbol", String, nullable=False),
    Column("quantity", String, nullable=False),
    Column("entry_price", String, nullable=False),
    Column("opening_fee", String, nullable=False),
)
fills = Table(
    "fills",
    metadata,
    Column("id", String, primary_key=True),
    Column("operation_id", String, nullable=False),
    Column("bot_id", String, nullable=False),
    Column("connection_id", String, nullable=False),
    Column("role", String, nullable=False),
    Column("side", String, nullable=False),
    Column("quantity", String, nullable=False),
    Column("price", String, nullable=False),
    Column("fee", String, nullable=False),
    Column("realized_pnl", String, nullable=False),
    Column("created_at", Float, nullable=False),
    UniqueConstraint("operation_id", "role"),
)
operations = Table(
    "operations",
    metadata,
    Column("id", String, primary_key=True),
    Column("bot_id", String, nullable=False),
    Column("kind", String, nullable=False),
    Column("status", String, nullable=False),
    Column("message", Text, nullable=False),
    Column("created_at", Float, nullable=False),
    Column("updated_at", Float, nullable=False),
)
alerts = Table(
    "alerts",
    metadata,
    Column("id", String, primary_key=True),
    Column("bot_id", String, nullable=True),
    Column("severity", String, nullable=False),
    Column("message", Text, nullable=False),
    Column("created_at", Float, nullable=False),
    Column("acknowledged", Integer, nullable=False),
)
settings = Table(
    "settings", metadata, Column("key", String, primary_key=True), Column("value", Text, nullable=False)
)


class Store:
    """A single-process SQLite store. Paper two-leg fills commit in one transaction."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
        with self.engine.begin() as db:
            version = db.exec_driver_sql("PRAGMA user_version").scalar_one()
            if version not in {0, 1}:
                raise ValueError(f"Unsupported database schema version {version}")
        metadata.create_all(self.engine)
        with self.engine.begin() as db:
            db.exec_driver_sql("PRAGMA user_version=1")

    @contextmanager
    def transaction(self) -> Iterator[DBConnection]:
        with self.engine.begin() as db:
            yield db

    def close(self) -> None:
        self.engine.dispose()

    def add_connection(self, value: ConnectionCreate) -> Connection:
        item = Connection(**value.model_dump(), id=uuid.uuid4().hex, created_at=time.time())
        try:
            with self.transaction() as db:
                db.execute(insert(connections).values(**item.model_dump(mode="json")))
        except IntegrityError as exc:
            raise ValueError("账户名称已存在，或同一场馆的原生账户身份已经添加") from exc
        return item

    def connections(self) -> list[Connection]:
        with self.engine.connect() as db:
            return [
                Connection.model_validate(dict(row))
                for row in db.execute(select(connections).order_by(connections.c.created_at)).mappings()
            ]

    def connection(self, connection_id: str) -> Connection:
        with self.engine.connect() as db:
            row = db.execute(select(connections).where(connections.c.id == connection_id)).mappings().first()
        if row is None:
            raise ValueError("账户实例不存在")
        return Connection.model_validate(dict(row))

    def delete_connection(self, connection_id: str) -> None:
        for bot in self.bots():
            if connection_id in {bot.parameters.long_connection_id, bot.parameters.short_connection_id}:
                raise ValueError("账户仍被 Bot 引用，请保留账户或先删除已结束的 Bot")
        with self.transaction() as db:
            db.execute(delete(connections).where(connections.c.id == connection_id))

    def add_bot(self, value: BotCreate) -> Bot:
        self.connection(value.parameters.long_connection_id)
        self.connection(value.parameters.short_connection_id)
        now = time.time()
        bot = Bot(
            **value.model_dump(),
            id=uuid.uuid4().hex,
            state=BotState.READY,
            reason="模拟交易 · 尚未启动",
            created_at=now,
            updated_at=now,
        )
        record = bot.model_dump(mode="json")
        record["parameters"] = bot.parameters.model_dump_json()
        with self.transaction() as db:
            existing = (
                db.execute(select(bots).where(bots.c.request_id == value.request_id)).mappings().first()
            )
            if existing is not None:
                previous = self._bot(existing)
                if (
                    BotCreate.model_validate(previous.model_dump(include=set(BotCreate.model_fields)))
                    != value
                ):
                    raise ValueError("相同创建请求 ID 不能用于不同 Bot 参数")
                return previous
            db.execute(insert(bots).values(**record))
        return bot

    @staticmethod
    def _bot(row: Any) -> Bot:
        data = dict(row)
        data["parameters"] = json.loads(data["parameters"])
        return Bot.model_validate(data)

    def bots(self) -> list[Bot]:
        with self.engine.connect() as db:
            return [
                self._bot(row)
                for row in db.execute(select(bots).order_by(bots.c.created_at.desc())).mappings()
            ]

    def bot(self, bot_id: str) -> Bot:
        with self.engine.connect() as db:
            row = db.execute(select(bots).where(bots.c.id == bot_id)).mappings().first()
        if row is None:
            raise ValueError("Bot 不存在")
        return self._bot(row)

    def set_state(self, bot_id: str, state: BotState, reason: str, db: DBConnection | None = None) -> None:
        query = (
            update(bots)
            .where(bots.c.id == bot_id)
            .values(state=state.value, reason=reason, updated_at=time.time())
        )
        if db is not None:
            db.execute(query)
        else:
            with self.transaction() as tx:
                tx.execute(query)

    def delete_bot(self, bot_id: str) -> None:
        bot = self.bot(bot_id)
        if bot.state not in {BotState.READY, BotState.STOPPED, BotState.CLOSED} or self.positions(bot_id):
            raise ValueError("只能删除没有持仓、且尚未启动或已停止的 Bot")
        with self.transaction() as db:
            db.execute(delete(bots).where(bots.c.id == bot_id))

    def positions(self, bot_id: str | None = None) -> list[Position]:
        query = select(positions)
        if bot_id is not None:
            query = query.where(positions.c.bot_id == bot_id)
        with self.engine.connect() as db:
            return [Position.model_validate(dict(row)) for row in db.execute(query).mappings()]

    def rows(self, table: Table, bot_id: str | None = None) -> list[dict[str, Any]]:
        query = select(table)
        if bot_id is not None:
            query = query.where(table.c.bot_id == bot_id)
        with self.engine.connect() as db:
            return [dict(row) for row in db.execute(query.order_by(table.c.created_at.desc())).mappings()]

    def account_available(self, account: Connection) -> Decimal:
        used = sum(
            (p.quantity * p.entry_price for p in self.positions() if p.connection_id == account.id),
            Decimal(0),
        )
        costs = sum(
            (
                Decimal(row["realized_pnl"]) - Decimal(row["fee"])
                for row in self.rows(fills)
                if row["connection_id"] == account.id
            ),
            Decimal(0),
        )
        return account.paper_balance + costs - used

    def operation(self, bot_id: str, kind: str) -> str:
        op_id = uuid.uuid4().hex
        now = time.time()
        with self.transaction() as db:
            db.execute(
                insert(operations).values(
                    id=op_id,
                    bot_id=bot_id,
                    kind=kind,
                    status="pending",
                    message="等待后台执行",
                    created_at=now,
                    updated_at=now,
                )
            )
        return op_id

    def finish_operation(self, op_id: str, status: str, message: str, db: DBConnection | None = None) -> None:
        query = (
            update(operations)
            .where(operations.c.id == op_id)
            .values(status=status, message=message, updated_at=time.time())
        )
        if db is not None:
            db.execute(query)
        else:
            with self.transaction() as tx:
                tx.execute(query)

    def alert(self, message: str, bot_id: str | None = None, severity: str = "info") -> None:
        now = time.time()
        with self.transaction() as db:
            latest = db.execute(
                select(alerts).where(
                    alerts.c.bot_id == bot_id, alerts.c.message == message, alerts.c.created_at > now - 300
                )
            ).first()
            if latest is None:
                db.execute(
                    insert(alerts).values(
                        id=uuid.uuid4().hex,
                        bot_id=bot_id,
                        severity=severity,
                        message=message,
                        created_at=now,
                        acknowledged=0,
                    )
                )

    def acknowledge_alert(self, alert_id: str) -> None:
        with self.transaction() as db:
            db.execute(update(alerts).where(alerts.c.id == alert_id).values(acknowledged=1))

    def setting(self, key: str) -> str | None:
        with self.engine.connect() as db:
            return db.execute(select(settings.c.value).where(settings.c.key == key)).scalar_one_or_none()

    def save_setting(self, key: str, value: str) -> None:
        with self.transaction() as db:
            db.execute(delete(settings).where(settings.c.key == key))
            db.execute(insert(settings).values(key=key, value=value))
