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
    literal_column,
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
    GridParameters,
    HedgeParameters,
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
    Column("account_index", Integer, nullable=True),
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

bot_cycles = Table(
    "bot_cycles",
    metadata,
    Column("bot_id", String, primary_key=True),
    Column("number", Integer, nullable=False),
    Column("open_operation_id", String, nullable=True),
    Column("opened_at", Float, nullable=True),
    Column("next_reopen_at", Float, nullable=True),
    Column("entry_not_before", Float, nullable=True),
)
point_samples = Table(
    "point_samples",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("scope_id", String, nullable=False, index=True),
    Column("metric", String, nullable=False),
    Column("sampled_at", Float, nullable=False),
    Column("status", String, nullable=False),
    Column("value", String, nullable=True),
    Column("reason", Text, nullable=True),
    Column("source", String, nullable=False),
    UniqueConstraint("scope_id", "metric", "sampled_at"),
)

grid_states = Table(
    "grid_states",
    metadata,
    Column("bot_id", String, primary_key=True),
    Column("cursor", Integer, nullable=False),
    Column("zero_inventory_cursor", Integer, nullable=False),
    Column("quantity_per_grid", String, nullable=False),
    Column("levels", Text, nullable=False),
    Column("initialized", Integer, nullable=False),
)
grid_actions = Table(
    "grid_actions",
    metadata,
    Column("operation_id", String, primary_key=True),
    Column("bot_id", String, nullable=False),
    Column("cursor_after", Integer, nullable=False),
    Column("target_quantity", String, nullable=False),
)
margin_changes = Table(
    "margin_changes",
    metadata,
    Column("operation_id", String, primary_key=True),
    Column("bot_id", String, nullable=False),
    Column("connection_id", String, nullable=False),
    Column("symbol", String, nullable=False),
    Column("target", Text, nullable=False),
    Column("payload", Text, nullable=False),
    Column("status", String, nullable=False),
    Column("result", Text, nullable=True),
    Column("created_at", Float, nullable=False),
    Column("updated_at", Float, nullable=False),
)


class Store:
    """Account identities and durable native-order journals in a single-process SQLite store."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
        with self.engine.begin() as db:
            version = db.exec_driver_sql("PRAGMA user_version").scalar_one()
            if version not in {0, 9}:
                raise ValueError(f"Unsupported database schema version {version}; expected 9")
            if (
                version == 0
                and db.exec_driver_sql(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                ).first()
                is not None
            ):
                raise ValueError("Database has no schema version; use a new database")
        metadata.create_all(self.engine)
        with self.engine.begin() as db:
            db.exec_driver_sql("PRAGMA user_version=9")

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
            else value.address
            if value.provider.value == "entropy"
            else str(value.account_index)
        )
        if account_ref is None:
            raise ValueError("缺少原生账户身份")
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
            if connection_id in bot.parameters.connection_ids:
                raise ValueError("账户仍被 Bot 引用，请保留账户或先删除已结束的 Bot")
        with self.transaction() as db:
            db.execute(delete(connections).where(connections.c.id == connection_id))

    def add_bot(self, value: BotCreate) -> Bot:
        for connection_id in value.parameters.connection_ids:
            self.connection(connection_id)
        now = time.time()
        bot = Bot(
            **value.model_dump(),
            id=uuid.uuid4().hex,
            state=BotState.READY,
            reason="尚未运行",
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
            self.check_grid_reservation(bot)
            db.execute(insert(bots).values(**record))
            db.execute(
                insert(bot_cycles).values(
                    bot_id=bot.id,
                    number=1,
                    open_operation_id=None,
                    opened_at=None,
                    next_reopen_at=None,
                    entry_not_before=None,
                )
            )
        return bot

    def check_grid_reservation(self, bot: Bot) -> None:
        if bot.state == BotState.CLOSED:
            return
        self.check_strategy_accounts(bot.parameters, bot_id=bot.id)

    def check_strategy_accounts(
        self, parameters: HedgeParameters | GridParameters, *, bot_id: str | None = None
    ) -> None:
        for other in self.bots():
            if other.id == bot_id or other.state == BotState.CLOSED:
                continue
            if (
                (isinstance(parameters, GridParameters) or other.strategy == "grid")
                and parameters.symbol == other.parameters.symbol
                and set(parameters.connection_ids) & set(other.parameters.connection_ids)
            ):
                raise ValueError(
                    f"网格需要独占账户的该币种，已被 Bot「{other.name}」使用；请选择其他账户或币种"
                )

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
        if bot.state not in {BotState.READY, BotState.PAUSED, BotState.CLOSED} or self.positions(bot_id):
            raise ValueError("只能删除没有持仓、且待运行/已暂停/已平仓的 Bot")
        if self.bot_pending(bot_id):
            raise ValueError("有未确认订单或操作，不能删除；请先同步并处理")
        with self.transaction() as db:
            db.execute(delete(grid_states).where(grid_states.c.bot_id == bot_id))
            db.execute(delete(bots).where(bots.c.id == bot_id))

    def bot_pending(self, bot_id: str) -> bool:
        return any(
            not order["applied"] or order["status"] in {"prepared", "submitting", "submitted", "unknown"}
            for order in self.bot_orders(bot_id)
        ) or any(op["status"] in {"pending", "unknown"} for op in self.rows(operations, bot_id))

    def bot_editability(self, bot_id: str) -> dict[str, bool]:
        bot = self.bot(bot_id)
        pending = self.bot_pending(bot_id)
        empty = not self.positions(bot_id)
        untouched = not self.bot_orders(bot_id) and self.grid_state(bot_id) is None
        entry = (
            not pending
            and empty
            and untouched
            and bot.state in {BotState.READY, BotState.WAITING, BotState.PAUSED}
        )
        if isinstance(bot.parameters, GridParameters):
            entry = (
                not pending
                and empty
                and (
                    bot.state in {BotState.READY, BotState.PAUSED, BotState.CLOSED}
                    or untouched
                    and bot.state == BotState.WAITING
                )
            )
        return {
            "capital": entry
            if isinstance(bot.parameters, GridParameters)
            else not pending
            and empty
            and (
                bot.state == BotState.CLOSED
                or not self.bot_orders(bot_id)
                and self.grid_state(bot_id) is None
                and bot.state in {BotState.READY, BotState.WAITING, BotState.PAUSED}
            ),
            "entry_parameters": entry,
            "binding_parameters": entry
            and (not isinstance(bot.parameters, GridParameters) or not self.bot_orders(bot_id)),
            "slippage": not pending and bot.state != BotState.ATTENTION,
            "reopen": not pending and bot.state != BotState.ATTENTION,
            "delete": not pending
            and not self.positions(bot_id)
            and bot.state in {BotState.READY, BotState.PAUSED, BotState.CLOSED},
        }

    def check_grid_update(self, bot_id: str, parameters: GridParameters) -> None:
        old = self.bot(bot_id).parameters
        if not isinstance(old, GridParameters):
            raise ValueError("不能修改 Bot 的策略类型，请新建 Bot")
        editable = self.bot_editability(bot_id)
        if parameters.model_dump(exclude={"slippage_bps"}) != old.model_dump(exclude={"slippage_bps"}):
            if not editable["entry_parameters"]:
                raise ValueError("请先暂停网格；仍有仓位需先平仓，未确认订单或操作需先处理")
            if (parameters.connection_id, parameters.symbol) != (
                old.connection_id,
                old.symbol,
            ) and not editable["binding_parameters"]:
                raise ValueError("已有订单记录，账户和币种固定；更换账户或币种请新建 Bot")

    def update_bot(self, bot_id: str, value: BotUpdate) -> Bot:
        bot = self.bot(bot_id)
        if type(value.parameters) is not type(bot.parameters):
            raise ValueError("不能修改 Bot 的策略类型，请新建 Bot")
        editable = self.bot_editability(bot_id)
        entry_fields = set(type(value.parameters).model_fields) - {
            "slippage_bps",
            "reopen_interval_seconds",
            "reopen_random_wait_seconds",
        }
        if value.parameters.model_dump(include=entry_fields) != bot.parameters.model_dump(
            include=entry_fields
        ):
            if isinstance(value.parameters, GridParameters):
                self.check_grid_update(bot_id, value.parameters)
            elif not editable["entry_parameters"]:
                raise ValueError("已有订单或持仓，不能修改账户、币种、建仓金额或价差条件；请新建 Bot")
        if value.parameters.slippage_bps != bot.parameters.slippage_bps and not editable["slippage"]:
            raise ValueError("有未确认订单或需要处理的状态，不能修改滑点；请先同步并处理")
        interval_changed = False
        if isinstance(value.parameters, HedgeParameters) and isinstance(bot.parameters, HedgeParameters):
            interval_changed = (
                value.parameters.reopen_interval_seconds != bot.parameters.reopen_interval_seconds
            )
            if (
                interval_changed
                or value.parameters.reopen_random_wait_seconds != bot.parameters.reopen_random_wait_seconds
            ) and not editable["reopen"]:
                raise ValueError("有未确认订单或需要处理的状态，不能修改定期重开；请先同步并处理")
        for connection_id in value.parameters.connection_ids:
            self.connection(connection_id)
        self.check_grid_reservation(bot.model_copy(update={"parameters": value.parameters}))
        values: dict[str, Any] = {
            "name": value.name,
            "parameters": value.parameters.model_dump_json(),
            "updated_at": time.time(),
        }
        grid_changed = (
            isinstance(value.parameters, GridParameters)
            and isinstance(bot.parameters, GridParameters)
            and value.parameters.model_dump(exclude={"slippage_bps"})
            != bot.parameters.model_dump(exclude={"slippage_bps"})
        )
        if grid_changed:
            values.update(
                state=BotState.CLOSED.value if bot.state == BotState.CLOSED else BotState.READY.value,
                reason="参数已保存，点击运行启动网格",
            )
        elif value.parameters != bot.parameters and bot.state in {BotState.WAITING, BotState.PAUSED}:
            if editable["entry_parameters"]:
                values.update(state=BotState.READY.value, reason="参数已修改，请重新点击运行")
        with self.transaction() as db:
            if grid_changed:
                db.execute(delete(grid_states).where(grid_states.c.bot_id == bot_id))
            db.execute(update(bots).where(bots.c.id == bot_id).values(**values))
            if interval_changed:
                assert isinstance(value.parameters, HedgeParameters)
                interval = value.parameters.reopen_interval_seconds
                db.execute(
                    update(bot_cycles)
                    .where(bot_cycles.c.bot_id == bot_id)
                    .values(
                        next_reopen_at=time.time() + interval
                        if interval is not None and bot.state == BotState.HOLDING
                        else None
                    )
                )
        return self.bot(bot_id)

    def positions(self, bot_id: str | None = None) -> list[Position]:
        query = select(positions)
        if bot_id is not None:
            query = query.where(positions.c.bot_id == bot_id)
        with self.engine.connect() as db:
            return [Position.model_validate(dict(row)) for row in db.execute(query).mappings()]

    def grid_state(self, bot_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as db:
            row = db.execute(select(grid_states).where(grid_states.c.bot_id == bot_id)).mappings().first()
        if row is None:
            return None
        state = dict(row)
        state["levels"] = json.loads(state["levels"])
        state["initialized"] = bool(state["initialized"])
        return state

    def restart_closed_bot(self, bot_id: str) -> None:
        bot = self.bot(bot_id)
        if bot.state != BotState.CLOSED:
            raise ValueError("仅已平仓的 Bot 可以重新运行")
        if self.positions(bot_id) or self.bot_pending(bot_id):
            raise ValueError("仍有分配仓位或未确认订单，不能重新运行")
        with self.transaction() as db:
            if isinstance(bot.parameters, GridParameters):
                # Remove only the active layout; original orders, fills and action journals remain.
                db.execute(delete(grid_states).where(grid_states.c.bot_id == bot_id))
                reason = "等待区间内价格后初始化网格"
            else:
                assert isinstance(bot.parameters, HedgeParameters)
                cycle = db.execute(select(bot_cycles).where(bot_cycles.c.bot_id == bot_id)).mappings().one()
                db.execute(
                    update(bot_cycles)
                    .where(bot_cycles.c.bot_id == bot_id)
                    .values(
                        number=cycle["number"] + (1 if cycle["open_operation_id"] is not None else 0),
                        open_operation_id=None,
                        opened_at=None,
                        next_reopen_at=None,
                        entry_not_before=None,
                    )
                )
                reason = "等待价差条件开始下一轮"
            self.set_state(bot_id, BotState.WAITING, reason, db)

    def begin_margin_change(
        self, bot_id: str, connection_id: str, symbol: str, target: str, payload: str
    ) -> str:
        if self.bot_pending(bot_id) or self.positions(bot_id):
            raise ValueError("有未确认操作或分配仓位，不能修改保证金设置")
        op_id, now = uuid.uuid4().hex, time.time()
        with self.transaction() as db:
            db.execute(
                insert(operations).values(
                    id=op_id,
                    bot_id=bot_id,
                    kind="margin_config",
                    status="pending",
                    message="正在确认杠杆与保证金模式",
                    created_at=now,
                    updated_at=now,
                )
            )
            db.execute(
                insert(margin_changes).values(
                    operation_id=op_id,
                    bot_id=bot_id,
                    connection_id=connection_id,
                    symbol=symbol,
                    target=target,
                    payload=payload,
                    status="pending",
                    result=None,
                    created_at=now,
                    updated_at=now,
                )
            )
        return op_id

    def finish_margin_change(self, op_id: str, status: str, message: str, result: str | None = None) -> None:
        if status not in {"confirmed", "unknown", "rejected"}:
            raise ValueError("保证金设置操作状态无效")
        with self.transaction() as db:
            db.execute(
                update(margin_changes)
                .where(margin_changes.c.operation_id == op_id)
                .values(status=status, result=result, updated_at=time.time())
            )
            self.finish_operation(
                op_id,
                "completed" if status == "confirmed" else "unknown" if status == "unknown" else "attention",
                message,
                db,
            )

    def bot_margin_changes(self, bot_id: str, *, public: bool = True) -> list[dict[str, Any]]:
        rows = self.rows(margin_changes, bot_id)
        for row in rows:
            if public:
                row.pop("payload")
            row["target"] = json.loads(row["target"])
            row["result"] = json.loads(row["result"]) if row["result"] is not None else None
        return rows

    def begin_grid_action(
        self, bot_id: str, cursor: int, target: Decimal, *, layout: dict[str, Any] | None = None
    ) -> str:
        if self.bot_pending(bot_id):
            raise ValueError("网格有未确认操作，禁止提交新订单")
        if not isinstance(self.bot(bot_id).parameters, GridParameters):
            raise ValueError("此 Bot 不是网格")
        op_id, now = uuid.uuid4().hex, time.time()
        with self.transaction() as db:
            if layout is not None:
                db.execute(
                    insert(grid_states).values(
                        bot_id=bot_id,
                        cursor=cursor,
                        zero_inventory_cursor=layout["zero_inventory_cursor"],
                        quantity_per_grid=str(layout["quantity_per_grid"]),
                        levels=json.dumps([str(p) for p in layout["levels"]]),
                        initialized=0,
                    )
                )
            db.execute(
                insert(operations).values(
                    id=op_id,
                    bot_id=bot_id,
                    kind="grid_initial" if layout else "grid_step",
                    status="pending",
                    message="",
                    created_at=now,
                    updated_at=now,
                )
            )
            db.execute(
                insert(grid_actions).values(
                    operation_id=op_id,
                    bot_id=bot_id,
                    cursor_after=cursor,
                    target_quantity=str(target),
                )
            )
        return op_id

    def skip_unsent_grid_action(self, bot_id: str, op_id: str, reason: str) -> None:
        """Only a pending action with no order journal can be skipped and retried."""
        with self.transaction() as db:
            op = db.execute(select(operations).where(operations.c.id == op_id)).mappings().one()
            action = (
                db.execute(select(grid_actions).where(grid_actions.c.operation_id == op_id)).mappings().one()
            )
            if (
                op["bot_id"] != bot_id
                or action["bot_id"] != bot_id
                or op["status"] != "pending"
                or op["kind"] not in {"grid_initial", "grid_step"}
                or db.execute(select(orders.c.id).where(orders.c.operation_id == op_id)).first() is not None
            ):
                raise ValueError("本次操作已有订单日志或状态不符，请核实原订单，不能自动重试")
            state = db.execute(select(grid_states).where(grid_states.c.bot_id == bot_id)).mappings().one()
            if op["kind"] == "grid_initial":
                if (
                    state["initialized"]
                    or db.execute(select(positions).where(positions.c.bot_id == bot_id)).first()
                ):
                    raise ValueError("初始化已有确认状态或仓位，不能自动重试")
                db.execute(delete(grid_states).where(grid_states.c.bot_id == bot_id))
            elif not state["initialized"]:
                raise ValueError("原网格尚未确认，不能自动重试")
            self.finish_operation(op_id, "skipped", f"未创建订单，跳过本次操作：{reason}", db)

    def complete_grid_action(self, bot_id: str, op_id: str, *, recovered: bool = False) -> None:
        with self.transaction() as db:
            kind = db.execute(select(operations.c.kind).where(operations.c.id == op_id)).scalar_one()
            action = (
                db.execute(select(grid_actions).where(grid_actions.c.operation_id == op_id)).mappings().one()
            )
            if action["bot_id"] != bot_id:
                raise ValueError("网格操作归属不符")
            owned = list(db.execute(select(positions).where(positions.c.bot_id == bot_id)).mappings())
            quantity = sum(
                (Decimal(p["quantity"]) * (1 if p["role"] == "long" else -1) for p in owned), Decimal(0)
            )
            if (
                len(owned) > 1
                or quantity != Decimal(action["target_quantity"])
                or any(
                    not order["applied"]
                    for order in db.execute(select(orders).where(orders.c.operation_id == op_id)).mappings()
                )
            ):
                raise ValueError("网格实际成交未达到本格目标；保留实际仓位，停止后续动作，请平仓处理")
            db.execute(
                update(grid_states)
                .where(grid_states.c.bot_id == bot_id)
                .values(
                    cursor=action["cursor_after"],
                    initialized=1,
                )
            )
            self.finish_operation(
                op_id,
                "completed",
                "原订单已确认；等待手动恢复"
                if recovered
                else "网格初始化完成"
                if kind == "grid_initial"
                else "本格实际成交已确认",
                db,
            )
            self.set_state(
                bot_id,
                BotState.PAUSED if recovered else BotState.HOLDING,
                "网格原订单已确认，点击运行继续" if recovered else "网格运行中，等待相邻格线",
                db,
            )

    def rows(self, table: Table, bot_id: str | None = None) -> list[dict[str, Any]]:
        query = select(table)
        if bot_id is not None:
            query = query.where(table.c.bot_id == bot_id)
        with self.engine.connect() as db:
            return [
                dict(row)
                for row in db.execute(
                    query.order_by(table.c.created_at.desc(), literal_column("rowid").desc())
                ).mappings()
            ]

    def cycle(self, bot_id: str) -> dict[str, Any]:
        with self.engine.connect() as db:
            return dict(db.execute(select(bot_cycles).where(bot_cycles.c.bot_id == bot_id)).mappings().one())

    def arm_reopen(self, bot_id: str) -> None:
        parameters = self.bot(bot_id).parameters
        assert isinstance(parameters, HedgeParameters)
        interval = parameters.reopen_interval_seconds
        now = time.time()
        values: dict[str, Any] = {"next_reopen_at": now + interval if interval is not None else None}
        with self.transaction() as db:
            db.execute(update(bot_cycles).where(bot_cycles.c.bot_id == bot_id).values(**values))

    def complete_open(self, bot_id: str, op_id: str, reason: str) -> None:
        parameters = self.bot(bot_id).parameters
        assert isinstance(parameters, HedgeParameters)
        interval = parameters.reopen_interval_seconds
        now = time.time()
        with self.transaction() as db:
            cycle = db.execute(select(bot_cycles).where(bot_cycles.c.bot_id == bot_id)).mappings().one()
            if cycle["open_operation_id"] != op_id:
                raise ValueError("本轮建仓操作身份不匹配")
            self.finish_operation(op_id, "completed", "两腿原生成交已确认", db)
            self.set_state(bot_id, BotState.HOLDING, reason, db)
            db.execute(
                update(bot_cycles)
                .where(bot_cycles.c.bot_id == bot_id)
                .values(opened_at=now, next_reopen_at=now + interval if interval is not None else None)
            )

    def disarm_reopen(self, bot_id: str) -> None:
        with self.transaction() as db:
            db.execute(update(bot_cycles).where(bot_cycles.c.bot_id == bot_id).values(next_reopen_at=None))

    def complete_reopen_close(self, bot_id: str, op_id: str, wait_seconds: int) -> None:
        parameters = self.bot(bot_id).parameters
        assert isinstance(parameters, HedgeParameters)
        if not 0 <= wait_seconds <= parameters.reopen_random_wait_seconds:
            raise ValueError("随机等待超出设置上限")
        unresolved = any(
            not row["applied"] or row["status"] in {"prepared", "submitting", "submitted", "unknown"}
            for row in self.bot_orders(bot_id)
        ) or any(
            row["id"] != op_id and row["status"] in {"pending", "unknown"}
            for row in self.rows(operations, bot_id)
        )
        if self.positions(bot_id) or unresolved:
            raise ValueError("定期平仓尚未确认，不能开始下一轮")
        with self.transaction() as db:
            operation = db.execute(select(operations).where(operations.c.id == op_id)).mappings().one()
            if (
                operation["bot_id"] != bot_id
                or operation["kind"] != "reopen_close"
                or operation["status"] != "pending"
            ):
                raise ValueError("定期平仓操作身份或状态无效")
            self.finish_operation(op_id, "completed", "定期平仓已确认，开始下一轮等待", db)
            db.execute(
                update(bot_cycles)
                .where(bot_cycles.c.bot_id == bot_id)
                .values(
                    number=bot_cycles.c.number + 1,
                    open_operation_id=None,
                    opened_at=None,
                    next_reopen_at=None,
                    entry_not_before=time.time() + wait_seconds,
                )
            )
            self.set_state(
                bot_id, BotState.WAITING, f"定期平仓已确认，随机等待 {wait_seconds} 秒后按价差条件建仓", db
            )

    def turnover(self, bot_id: str) -> dict[str, Any]:
        value = sum(
            (Decimal(row["quantity"]) * Decimal(row["price"]) for row in self.rows(fills, bot_id)), Decimal(0)
        )
        return {"confirmed_usd": str(value), "has_unconfirmed_orders": self.bot_pending(bot_id)}

    def save_point_sample(
        self,
        scope_id: str,
        metric: str,
        sampled_at: float,
        status: str,
        value: Decimal | None,
        reason: str | None,
        source: str,
    ) -> None:
        if (
            status not in {"available", "unavailable"}
            or (status == "available") != (value is not None)
            or (
                status == "available"
                and (reason is not None or value is None or not value.is_finite() or value < 0)
            )
            or (status == "unavailable" and not reason)
        ):
            raise ValueError("积分采样状态与数值不一致")
        with self.transaction() as db:
            db.execute(
                insert(point_samples).values(
                    scope_id=scope_id,
                    metric=metric,
                    sampled_at=sampled_at,
                    status=status,
                    value=str(value) if value is not None else None,
                    reason=reason,
                    source=source,
                )
            )

    def points_history(self, scope_id: str, since: float) -> list[dict[str, Any]]:
        with self.engine.connect() as db:
            return [
                dict(row)
                for row in db.execute(
                    select(point_samples)
                    .where(point_samples.c.scope_id == scope_id, point_samples.c.sampled_at >= since)
                    .order_by(point_samples.c.sampled_at, point_samples.c.id)
                ).mappings()
            ]

    def operation(self, bot_id: str, kind: str) -> str:
        op_id = uuid.uuid4().hex
        now = time.time()
        with self.transaction() as db:
            if kind == "open":
                cycle = db.execute(select(bot_cycles).where(bot_cycles.c.bot_id == bot_id)).mappings().one()
                if cycle["open_operation_id"] is not None:
                    raise ValueError("本轮已有建仓操作，禁止重复提交")
                db.execute(
                    update(bot_cycles)
                    .where(bot_cycles.c.bot_id == bot_id)
                    .values(open_operation_id=op_id, entry_not_before=None)
                )
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

    def skip_unsent_open(self, bot_id: str, op_id: str, reason: str) -> None:
        with self.transaction() as db:
            op = db.execute(select(operations).where(operations.c.id == op_id)).mappings().one()
            cycle = db.execute(select(bot_cycles).where(bot_cycles.c.bot_id == bot_id)).mappings().one()
            if (
                op["bot_id"] != bot_id
                or op["kind"] != "open"
                or op["status"] != "pending"
                or cycle["open_operation_id"] != op_id
                or db.execute(select(orders.c.id).where(orders.c.operation_id == op_id)).first() is not None
            ):
                raise ValueError("本轮已有订单日志或状态不符，不能自动重试")
            self.finish_operation(op_id, "skipped", reason, db)
            db.execute(update(bot_cycles).where(bot_cycles.c.bot_id == bot_id).values(open_operation_id=None))

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
                    current_open = db.execute(
                        select(bot_cycles.c.open_operation_id).where(bot_cycles.c.bot_id == row["bot_id"])
                    ).scalar_one_or_none()
                    if not intent.reduce_only and current_open == row["operation_id"]:
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
                        strategy = db.execute(
                            select(bots.c.strategy).where(bots.c.id == row["bot_id"])
                        ).scalar_one()
                        if strategy != "grid":
                            raise ValueError("此 Bot 已有该腿库存，禁止重复开仓")
                        owned = Decimal(position["quantity"])
                        entry = (owned * Decimal(position["entry_price"]) + quantity * price) / (
                            owned + quantity
                        )
                        opening_fee = (
                            Decimal(position["opening_fee"]) + result.fee
                            if position["opening_fee"] is not None and result.fee is not None
                            else None
                        )
                        db.execute(
                            update(positions)
                            .where(key)
                            .values(
                                quantity=str(owned + quantity),
                                entry_price=str(entry),
                                opening_fee=str(opening_fee) if opening_fee is not None else None,
                            )
                        )
                    else:
                        opposite = db.execute(
                            select(positions).where(
                                positions.c.bot_id == row["bot_id"], positions.c.role != row["role"]
                            )
                        ).first()
                        strategy = db.execute(
                            select(bots.c.strategy).where(bots.c.id == row["bot_id"])
                        ).scalar_one()
                        if strategy == "grid" and opposite is not None:
                            raise ValueError("网格反向建仓前必须确认原方向已平仓")
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
