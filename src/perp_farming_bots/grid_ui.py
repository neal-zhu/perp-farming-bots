from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal

from nicegui import ui
from nicegui.elements.mixins.disableable_element import DisableableElement
from nicegui.elements.mixins.validation_element import ValidationElement
from pydantic import ValidationError

from .models import GRID_DIRECTION_NAMES, PROVIDER_NAMES, BotCreate, BotUpdate, GridParameters
from .runtime import Runtime, bounded_price
from .store import Store


def grid_dialog(
    store: Store, runtime: Runtime, request_id: str, on_saved: Callable, bot_id: str | None = None
) -> ui.dialog:
    bot = store.bot(bot_id) if bot_id else None
    p = bot.parameters if bot else None
    assert p is None or isinstance(p, GridParameters)
    editable = store.bot_editability(bot_id) if bot_id else {"entry_parameters": True, "slippage": True}
    accounts = store.connections()
    dialog = ui.dialog()
    with dialog, ui.card().classes("w-full max-w-2xl p-6 gap-3").style("max-height: 90vh; overflow-y: auto"):
        with ui.row().classes("w-full items-center justify-between"):
            with ui.column().classes("gap-1"):
                ui.label("修改网格" if bot else "创建永续网格").classes("text-2xl font-bold")
                ui.label("一个账户，按格线买卖").classes("text-sm text-slate-500")
            ui.button(icon="close", on_click=dialog.close).props("flat round dense")
        name = (
            ui.input(
                "Bot 名称 *",
                value=bot.name if bot else "BTC 网格",
                validation={"请输入 Bot 名称": lambda v: isinstance(v, str) and bool(v.strip())},
            )
            .without_auto_validation()
            .props("outlined dense hide-bottom-space maxlength=80")
            .classes("w-full")
        )
        direction = (
            ui.toggle(GRID_DIRECTION_NAMES, value=p.direction if p else "neutral")
            .props("spread unelevated")
            .classes("w-full")
        )
        direction_help = ui.label().classes("text-sm text-slate-600")

        def explain():
            direction_help.set_text(
                {
                    "long": "下跌加多仓，上涨减多仓。运行时按当前价格建立初始多仓。",
                    "short": "上涨加空仓，下跌减空仓。运行时按当前价格建立初始空仓。",
                    "neutral": "区间中点为零仓位，下方做多、上方做空；经过中点先平仓，再反向建仓。",
                }[direction.value]
            )

        direction.on_value_change(explain)
        explain()
        with ui.row().classes("w-full gap-4"):
            account = (
                ui.select(
                    {a.id: f"{a.name} · {PROVIDER_NAMES[a.provider]}" for a in accounts},
                    label="交易账户",
                    value=p.connection_id if p else accounts[0].id,
                )
                .props("outlined dense hide-bottom-space")
                .classes("flex-1 min-w-48")
            )
            symbol = (
                ui.select(["BTC", "ETH", "SOL"], label="币种", value=p.symbol if p else "BTC")
                .props("outlined dense hide-bottom-space")
                .classes("w-32")
            )
        with ui.row().classes("w-full gap-4"):
            lower = (
                ui.number(
                    "价格下限（USD）",
                    value=float(p.lower_price) if p else None,
                    min=0,
                    validation={"下限须大于 0": lambda v: v is not None and v > 0},
                )
                .without_auto_validation()
                .props("outlined dense hide-bottom-space")
                .classes("flex-1 min-w-40")
            )
            upper = (
                ui.number(
                    "价格上限（USD）",
                    value=float(p.upper_price) if p else None,
                    min=0,
                    validation={
                        "上限须高于下限": lambda v: (
                            v is not None and lower.value is not None and v > lower.value
                        )
                    },
                )
                .without_auto_validation()
                .props("outlined dense hide-bottom-space")
                .classes("flex-1 min-w-40")
            )

        async def fill_range():
            revision = input_revision
            requested_symbol, requested_account = symbol.value, account.value
            try:
                connection = store.connection(requested_account)
                book = await runtime.markets.book(connection.provider, requested_symbol, refresh=True)
                if not book.fresh():
                    raise ValueError("行情已过期，请重试")
                spec = await runtime.markets.spec(connection.provider, requested_symbol)
                if revision != input_revision or dialog.is_deleted:
                    return
                mid = (book.bids[0].price + book.asks[0].price) / 2
                lower.set_value(float(bounded_price(mid * Decimal("0.9"), spec, "buy")))
                upper.set_value(float(bounded_price(mid * Decimal("1.1"), spec, "sell")))
                error.set_text("")
            except ValueError as exc:
                if revision == input_revision and not dialog.is_deleted:
                    error.set_text(str(exc))

        range_button = (
            ui.button("填入当前价 ±10%", icon="auto_fix_high", on_click=fill_range)
            .props("flat dense")
            .classes("text-xs")
        )
        with ui.row().classes("w-full gap-4"):
            count = (
                ui.number(
                    "网格数",
                    value=p.grid_count if p else 10,
                    min=2,
                    max=100,
                    step=2,
                    validation={
                        "格数须为 2–100 的整数；中性需要偶数": lambda v: (
                            v is not None
                            and 2 <= v <= 100
                            and v == int(v)
                            and (direction.value != "neutral" or int(v) % 2 == 0)
                        )
                    },
                )
                .without_auto_validation()
                .props("outlined dense hide-bottom-space")
                .classes("flex-1 min-w-40")
            )
            budget = (
                ui.number(
                    "名义仓位预算（USD）",
                    value=float(p.budget_usd) if p else 1000,
                    min=0,
                    validation={
                        "预算须大于 0，且不超过 1,000,000": lambda v: v is not None and 0 < v <= 1000000
                    },
                )
                .without_auto_validation()
                .props("outlined dense hide-bottom-space")
                .classes("flex-1 min-w-40")
            )
        ui.label("预算是区间内最大名义仓位上限，不是保证金；按交易所精度向下取整，每格数量固定。").classes(
            "text-xs text-slate-500"
        )
        ui.label("保存时自动检查账户余额和每格最低金额；不符合要求会在这里提示，运行时再次核对。").classes(
            "text-xs text-slate-500"
        )
        slippage = (
            ui.number(
                "最大滑点 %",
                value=float(p.slippage_bps / 100) if p else 0.2,
                min=0,
                max=1,
                step=0.05,
                validation={"滑点须为 0–1%": lambda v: v is not None and 0 <= v <= 1},
            )
            .without_auto_validation()
            .props("outlined dense hide-bottom-space")
            .classes("w-full")
        )
        if not editable["entry_parameters"]:
            entry_controls: list[DisableableElement] = [
                account,
                symbol,
                direction,
                lower,
                upper,
                count,
                budget,
                range_button,
            ]
            for control in entry_controls:
                control.disable()
            ui.label(
                "已建立网格，账户、方向和格线已锁定。可修改名称与滑点；调整区间请平仓后新建 Bot。"
            ).classes("text-xs text-amber-800")
        slippage.set_enabled(editable["slippage"])
        with ui.element("div").classes(
            "w-full bg-slate-50 rounded-lg p-4 text-xs text-slate-600 leading-relaxed"
        ):
            ui.label("价格触发网格 · 程序需持续在线")
            ui.label("到达相邻格线后提交限价 IOC；不在交易所提前挂单。跳过多格时逐格处理，按实际成交计账。")
            ui.label("价格超出区间时保留仓位，等待回到区间。暂停保留仓位；平仓结束运行。")
            ui.label("该账户的这个币种须由网格独占，不可与其他 Bot 或手动仓位共用。")
        error = ui.label("").classes("w-full text-sm text-red-600")
        error.bind_visibility_from(error, "text", backward=bool)
        busy = False
        input_revision = 0

        def invalidate(*, clear_range: bool = False):
            nonlocal input_revision
            input_revision += 1
            error.set_text("")
            if clear_range:
                lower.set_value(None)
                upper.set_value(None)

        symbol.on_value_change(lambda: invalidate(clear_range=True))
        for input_control in [account, direction, lower, upper, count, budget, slippage]:
            input_control.on_value_change(invalidate)

        def value() -> BotUpdate | BotCreate:
            values = BotUpdate(
                name=name.value,
                parameters=GridParameters(
                    connection_id=account.value,
                    symbol=symbol.value,
                    direction=direction.value,
                    lower_price=Decimal(str(lower.value)),
                    upper_price=Decimal(str(upper.value)),
                    grid_count=int(count.value),
                    budget_usd=Decimal(str(budget.value)),
                    slippage_bps=Decimal(str(slippage.value)) * 100,
                ),
            )
            return values if bot else BotCreate(**values.model_dump(), request_id=request_id, strategy="grid")

        def validate() -> bool:
            controls: list[ValidationElement] = [name, lower, upper, count, budget, slippage]
            valid = all([control.validate() for control in controls])
            error.set_text("" if valid else "请先修正标红的字段。")
            return valid

        async def save():
            nonlocal busy
            if busy or not validate():
                return
            busy = True
            save_button.set_text("检查并保存…")
            save_button.props("loading")
            save_button.disable()
            save_controls: list[DisableableElement] = [
                name,
                account,
                symbol,
                direction,
                lower,
                upper,
                count,
                budget,
                slippage,
                range_button,
            ]
            previous_enabled = [control.enabled for control in save_controls]
            for control in save_controls:
                control.disable()
            try:
                async with runtime.guard:
                    result = value()
                    await runtime.validate_configuration(result, bot_id=bot_id)
                    if bot_id:
                        store.update_bot(bot_id, result)
                    else:
                        assert isinstance(result, BotCreate)
                        store.add_bot(result)
                dialog.close()
                await on_saved()
                dialog.delete()
            except ValidationError as exc:
                error.set_text("；".join(e["msg"] for e in exc.errors()))
            except ValueError as exc:
                error.set_text(str(exc))
            finally:
                busy = False
                if not save_button.is_deleted:
                    save_button.set_text("保存 Bot")
                    save_button.props(remove="loading")
                    save_button.enable()
                    for control, enabled in zip(save_controls, previous_enabled):
                        control.set_enabled(enabled)

        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("取消", on_click=dialog.close).props("flat")
            save_button = ui.button("保存 Bot", on_click=save)
        ui.label("保存只创建配置；点击运行才会按策略提交真实订单。").classes("text-xs text-slate-500")
    return dialog
