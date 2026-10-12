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

from .models import (
    AccountSnapshot,
    Bot,
    BotCreate,
    BotState,
    BotUpdate,
    Connection,
    ConnectionCreate,
    OrderIntent,
    OrderResult,
    Position,
)

metadata = MetaData()
connections = Table(
    "connections",
    metadata,
    Column("id", String, primary_key=True),
    Column("name", String, nullable=False, unique=True),
    Column("provider", String, nullable=False),
    Column("account_ref", String, nullable=False),
    Column("account_index", Integer, nullable=False),
    Column("address", String, nullable=True),
    Column("api_key_index", Integer, nullable=True),
    Column("credentials", Text, nullable=False),
    Column("verified_at", Float, nullable=False),
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
    Column("opening_fee", String, nullable=True),
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
    Column("fee", String, nullable=True),
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

orders = Table(
    "orders",
    metadata,
    Column("id", String, primary_key=True),
    Column("operation_id", String, nullable=False),
    Column("bot_id", String, nullable=False),
    Column("role", String, nullable=False),
    Column("connection_id", String, nullable=False),
    Column("intent", Text, nullable=False),
    Column("payload", Text, nullable=False),
    Column("native_id", String, nullable=True),
    Column("status", String, nullable=False),
    Column("result", Text, nullable=True),
    Column("applied", Integer, nullable=False),
    Column("created_at", Float, nullable=False),
    Column("updated_at", Float, nullable=False),
    UniqueConstraint("operation_id", "role"),
)


class Store:
    """Account identities and durable native-order journals in a single-process SQLite store."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
        with self.engine.begin() as db:
            version = db.exec_driver_sql("PRAGMA user_version").scalar_one()
            if version not in {0, 2}:
                raise ValueError(f"Unsupported database schema version {version}")
        metadata.create_all(self.engine)
        with self.engine.begin() as db:
            db.exec_driver_sql("PRAGMA user_version=2")

    @contextmanager
    def transaction(self) -> Iterator[DBConnection]:
        with self.engine.begin() as db:
            yield db

    def close(self) -> None:
        self.engine.dispose()

    def add_connection(
        self, value: ConnectionCreate, snapshot: AccountSnapshot, encrypted: str
    ) -> Connection:
        account_ref = (
            f"{value.address}:{value.account_index}"
            if value.provider.value == "arcus"
            else str(value.account_index)
        )
        item = Connection(
            **value.model_dump(exclude={"api_private_key"}),
            account_ref=account_ref,
            id=uuid.uuid4().hex,
            created_at=time.time(),
            verified_at=snapshot.received_at,
        )
        try:
            with self.transaction() as db:
                db.execute(insert(connections).values(**item.model_dump(mode="json"), credentials=encrypted))
        except IntegrityError as exc:
            raise ValueError("账户名称已存在，或同一交易所的原生账户已经添加") from exc
        return item

    @staticmethod
    def _connection(row) -> Connection:
        data = dict(row)
        data.pop("credentials")
        return Connection.model_validate(data)

    def credentials(self, connection_id: str) -> str:
        with self.engine.connect() as db:
            result = db.execute(
                select(connections.c.credentials).where(connections.c.id == connection_id)
            ).scalar_one_or_none()
        if result is None:
            raise ValueError("账户凭据不存在")
        return result

    def connections(self) -> list[Connection]:
        with self.engine.connect() as db:
            return [
                self._connection(row)
                for row in db.execute(select(connections).order_by(connections.c.created_at)).mappings()
            ]

    def connection(self, connection_id: str) -> Connection:
        with self.engine.connect() as db:
            row = db.execute(select(connections).where(connections.c.id == connection_id)).mappings().first()
        if row is None:
            raise ValueError("账户实例不存在")
        return self._connection(row)

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
            reason="尚未启动",
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
        if self.bot_pending(bot_id):
            raise ValueError("有未确认订单或操作，不能删除；请先同步并处理")
        with self.transaction() as db:
            db.execute(delete(bots).where(bots.c.id == bot_id))

    def bot_pending(self, bot_id: str) -> bool:
        return any(
            not order["applied"] or order["status"] in {"prepared", "submitting", "submitted", "unknown"}
            for order in self.bot_orders(bot_id)
        ) or any(op["status"] in {"pending", "unknown"} for op in self.rows(operations, bot_id))

    def bot_editability(self, bot_id: str) -> dict[str, bool]:
        bot = self.bot(bot_id)
        pending = self.bot_pending(bot_id)
        return {
            "entry_parameters": not pending
            and not self.positions(bot_id)
            and not self.bot_orders(bot_id)
            and bot.state in {BotState.READY, BotState.WAITING, BotState.PAUSED, BotState.STOPPED},
            "slippage": not pending and bot.state != BotState.ATTENTION,
            "delete": not pending
            and not self.positions(bot_id)
            and bot.state in {BotState.READY, BotState.STOPPED, BotState.CLOSED},
        }

    def update_bot(self, bot_id: str, value: BotUpdate) -> Bot:
        bot = self.bot(bot_id)
        editable = self.bot_editability(bot_id)
        entry_fields = set(type(value.parameters).model_fields) - {"slippage_bps"}
        if value.parameters.model_dump(include=entry_fields) != bot.parameters.model_dump(
            include=entry_fields
        ):
            if not editable["entry_parameters"]:
                raise ValueError("已有订单或持仓，不能修改账户、币种、建仓金额或价差条件；请新建 Bot")
        if value.parameters.slippage_bps != bot.parameters.slippage_bps and not editable["slippage"]:
            raise ValueError("有未确认订单或需要处理的状态，不能修改滑点；请先同步并处理")
        self.connection(value.parameters.long_connection_id)
        self.connection(value.parameters.short_connection_id)
        values: dict[str, Any] = {
            "name": value.name,
            "parameters": value.parameters.model_dump_json(),
            "updated_at": time.time(),
        }
        if value.parameters != bot.parameters and bot.state in {BotState.WAITING, BotState.PAUSED}:
            if editable["entry_parameters"]:
                values.update(state=BotState.READY.value, reason="参数已修改，请重新启动")
        with self.transaction() as db:
            db.execute(update(bots).where(bots.c.id == bot_id).values(**values))
        return self.bot(bot_id)

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

    def add_order(self, op_id: str, bot_id: str, role: str, intent: OrderIntent, payload: str) -> str:
        order_id = uuid.uuid4().hex
        with self.transaction() as db:
            db.execute(
                insert(orders).values(
                    id=order_id,
                    operation_id=op_id,
                    bot_id=bot_id,
                    role=role,
                    connection_id=intent.connection_id,
                    intent=intent.model_dump_json(),
                    payload=payload,
                    native_id=None,
                    status="prepared",
                    result=None,
                    applied=0,
                    created_at=time.time(),
                    updated_at=time.time(),
                )
            )
        return order_id

    def update_order(self, order_id: str, status: str, native_id: str | None = None) -> None:
        values: dict[str, Any] = {"status": status, "updated_at": time.time()}
        if native_id is not None:
            values["native_id"] = native_id
        with self.transaction() as db:
            db.execute(update(orders).where(orders.c.id == order_id).values(**values))

    def order(self, order_id: str) -> dict[str, Any]:
        with self.engine.connect() as db:
            row = db.execute(select(orders).where(orders.c.id == order_id)).mappings().one()
        return dict(row)

    def bot_orders(self, bot_id: str, *, public: bool = True) -> list[dict[str, Any]]:
        result = self.rows(orders, bot_id)
        for row in result:
            row["intent"] = json.loads(row["intent"])
            row["result"] = json.loads(row["result"]) if row["result"] is not None else None
            if public:
                row.pop("payload")
        return result

    def apply_order_result(self, order_id: str, result: OrderResult) -> None:
        if result.status == "unknown":
            self.update_order(order_id, "unknown", result.native_id)
            return
        with self.transaction() as db:
            row = dict(db.execute(select(orders).where(orders.c.id == order_id)).mappings().one())
            if row["applied"]:
                previous = OrderResult.model_validate_json(row["result"])
                if previous.model_dump(exclude={"fee"}) != result.model_dump(exclude={"fee"}):
                    raise ValueError("订单终态证据发生变化，需要人工核实")
                if previous.fee is None and result.fee is not None:
                    db.execute(
                        update(orders)
                        .where(orders.c.id == order_id)
                        .values(result=result.model_dump_json(), updated_at=time.time())
                    )
                    db.execute(update(fills).where(fills.c.id == order_id).values(fee=str(result.fee)))
                    intent = OrderIntent.model_validate_json(row["intent"])
                    if not intent.reduce_only:
                        db.execute(
                            update(positions)
                            .where((positions.c.bot_id == row["bot_id"]) & (positions.c.role == row["role"]))
                            .values(opening_fee=str(result.fee))
                        )
                elif previous.fee is not None and result.fee != previous.fee:
                    raise ValueError("已确认手续费证据发生变化，需要人工核实")
                return
            intent = OrderIntent.model_validate_json(row["intent"])
            quantity, price = result.quantity, result.average_price
            if quantity is None or quantity > intent.quantity:
                raise ValueError("场馆成交数量超出已提交数量")
            if quantity > 0:
                if price is None:
                    raise ValueError("成交价格未知")
                key = (positions.c.bot_id == row["bot_id"]) & (positions.c.role == row["role"])
                position = db.execute(select(positions).where(key)).mappings().first()
                realized = Decimal(0)
                if intent.reduce_only:
                    if position is None or quantity > Decimal(position["quantity"]):
                        raise ValueError("平仓成交超出 Bot 分配数量")
                    owned = Decimal(position["quantity"])
                    realized = (
                        (price - Decimal(position["entry_price"]))
                        * quantity
                        * (1 if row["role"] == "long" else -1)
                    )
                    if quantity == owned:
                        db.execute(delete(positions).where(key))
                    else:
                        db.execute(update(positions).where(key).values(quantity=str(owned - quantity)))
                else:
                    if position is not None:
                        raise ValueError("此 Bot 已有该腿库存，禁止重复开仓")
                    db.execute(
                        insert(positions).values(
                            bot_id=row["bot_id"],
                            role=row["role"],
                            connection_id=row["connection_id"],
                            symbol=intent.symbol,
                            quantity=str(quantity),
                            entry_price=str(price),
                            opening_fee=str(result.fee) if result.fee is not None else None,
                        )
                    )
                db.execute(
                    insert(fills).values(
                        id=order_id,
                        operation_id=row["operation_id"],
                        bot_id=row["bot_id"],
                        connection_id=row["connection_id"],
                        role=row["role"],
                        side=intent.side,
                        quantity=str(quantity),
                        price=str(price),
                        fee=str(result.fee) if result.fee is not None else None,
                        realized_pnl=str(realized),
                        created_at=time.time(),
                    )
                )
            db.execute(
                update(orders)
                .where(orders.c.id == order_id)
                .values(
                    status=result.status,
                    result=result.model_dump_json(),
                    native_id=result.native_id,
                    applied=1,
                    updated_at=time.time(),
                )
            )
