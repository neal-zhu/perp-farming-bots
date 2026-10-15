from __future__ import annotations

import asyncio
import re
import uuid
from decimal import Decimal

from nicegui import ui
from nicegui.elements.mixins.disableable_element import DisableableElement
from pydantic import SecretStr, ValidationError

from .account_guide import GUIDE_URL, guide_url
from .bot_styles import BOT_STYLES
from .bot_widgets import AlertFeed, BotCard
from .formatting import money, stamp
from .grid_ui import grid_dialog
from .grid_widgets import GridBotCard
from .market_ui import MarketSelector
from .models import (
    PROVIDER_NAMES,
    STRATEGIES,
    TRADING_PROVIDERS,
    BotCreate,
    BotState,
    BotUpdate,
    ConnectionCreate,
    HedgeParameters,
    Preview,
    Provider,
)
from .notifications import Notifications
from .points_widgets import PointsFeed
from .runtime import Runtime
from .store import Store, fills, operations
from .strategy_widgets import observe_strategy


def install_ui(store: Store, runtime: Runtime, notifications: Notifications) -> None:
    @ui.page("/")
    async def home():
        bot_forms: dict[str, ui.dialog] = {}
        client = ui.context.client

        def notify(message: str, **kwargs):
            with client.layout:
                ui.notify(message, **kwargs)

        ui.colors(primary="#059669", positive="#059669")
        ui.add_head_html('<meta name="viewport" content="width=device-width, initial-scale=1">')
        ui.add_css("""
        body { background: #f4f6f9; color: #17243b; }
        .q-card { border-radius: 16px; box-shadow: 0 2px 12px #17243b08; }
        .q-tab { font-weight: 600; }
        .q-field--outlined .q-field__control { border-radius: 10px; }
        .q-btn { text-transform: none; border-radius: 9px; }
        """)
        ui.add_css(BOT_STYLES)
        with ui.header().classes("bg-white text-slate-900 border-b px-6 py-4"):
            with ui.row().classes("w-full items-center justify-between"):
                with ui.row().classes("items-center gap-3"):
                    ui.icon("smart_toy", size="32px").classes("text-emerald-600")
                    with ui.column().classes("gap-0"):
                        ui.label("Perp Farming Bots").classes("text-xl font-bold")
                        ui.label("自己的账户，自己的策略").classes("text-xs text-slate-500")
                ui.badge("连接自己的交易所账户", color="amber-8").classes("px-3 py-2")
        with ui.column().classes("w-full max-w-7xl mx-auto p-5 gap-5"):
            with ui.row().classes("w-full justify-between items-center"):
                with ui.column().classes("gap-1"):
                    ui.label("你的交易工作台").classes("text-3xl font-bold")
                    ui.label("连接账户、选择策略，统一查看持仓、交易记录与盈亏。").classes("text-slate-500")
                ui.button("创建 Bot", icon="add", on_click=lambda: bot_dialog()).props("unelevated")
            with ui.tabs().classes("w-full bg-white rounded-xl") as tabs:
                bots_tab = ui.tab("我的 Bots", icon="smart_toy")
                strategies_tab = ui.tab("策略库", icon="widgets")
                accounts_tab = ui.tab("账户实例", icon="account_balance_wallet")
                points_tab = ui.tab("积分", icon="stars")
                alerts_tab = ui.tab("通知", icon="notifications_none")

            async def action(bot_id: str, command: str):
                try:
                    await runtime.command(bot_id, command)
                    notify("操作已完成", color="positive")
                except (ValueError, Exception) as exc:
                    notify(
                        str(exc) if isinstance(exc, ValueError) else "操作失败，请查看后台日志",
                        color="negative",
                    )
                await bots_view()

            async def close_dialog(bot_id: str):
                bot = store.bot(bot_id)
                with ui.dialog() as dialog, ui.card().classes("w-full max-w-md p-6"):
                    ui.label(f"平仓：{bot.name}").classes("text-xl font-bold")
                    ui.label(
                        "将向交易所提交减仓订单，只关闭此 Bot 已分配的数量，并结束策略运行。"
                        if store.positions(bot_id)
                        else "当前没有持仓。确认后将结束此 Bot 的策略运行。"
                    )

                    async def confirm():
                        button.disable()
                        await action(bot_id, "close")
                        dialog.close()

                    with ui.row().classes("w-full justify-end"):
                        ui.button("取消", on_click=dialog.close).props("flat")
                        button = ui.button("确认平仓", on_click=confirm, color="orange")
                dialog.open()

            bot_cards: dict[str, BotCard] = {}
            view_lock = asyncio.Lock()

            async def bots_view():
                async with view_lock:
                    current = store.bots()
                    empty_bots.set_visibility(not current)
                    bot_summary.set_visibility(bool(current))
                    for label, value in [
                        ("Bots", len(current)),
                        ("持仓 Bots", sum(bool(store.positions(b.id)) for b in current)),
                        ("账户实例", len(store.connections())),
                    ]:
                        summary_values[label].set_text(str(value))
                    keep = {b.id for b in current}
                    for bid in list(bot_cards):
                        if bid not in keep:
                            bot_cards.pop(bid).root.delete()
                    for bot in current:
                        pnl, funding, strategy_market = await asyncio.gather(
                            runtime.pnl(bot.id), runtime.funding(bot.id), observe_strategy(runtime, bot)
                        )
                        if bot.id not in {b.id for b in store.bots()}:
                            continue
                        latest_bot = store.bot(bot.id)
                        if latest_bot.parameters != bot.parameters:
                            continue  # A form edit during the read must not display the prior asset's quotes.
                        bot = latest_bot
                        if bot.id not in bot_cards:
                            with cards_container:
                                card_class = GridBotCard if bot.strategy == "grid" else BotCard
                                bot_cards[bot.id] = card_class(
                                    bot.id, action, bot_dialog, delete_dialog, close_dialog, detail_dialog
                                )
                        bot_cards[bot.id].update(bot, store, pnl, funding)
                        bot_cards[bot.id].monitor.update(bot, store, strategy_market)

            def detail_dialog(bot_id: str):
                with ui.dialog() as dialog, ui.card().classes("w-full max-w-4xl p-6"):
                    ui.label(store.bot(bot_id).name + " · 成交记录").classes("text-xl font-bold")
                    rows = [
                        {
                            **f,
                            "time": stamp(f["created_at"]),
                            "price": money(f["price"]),
                            "fee": money(f["fee"]),
                        }
                        for f in store.rows(fills, bot_id)
                    ]
                    ui.table(
                        columns=[
                            {"name": key, "label": label, "field": key}
                            for key, label in [
                                ("time", "时间"),
                                ("role", "腿"),
                                ("side", "方向"),
                                ("quantity", "数量"),
                                ("price", "价格"),
                                ("fee", "手续费"),
                            ]
                        ],
                        rows=rows,
                    ).classes("w-full")
                    for order in store.bot_orders(bot_id):
                        intent = order["intent"]
                        ui.label(
                            f"订单 {intent['client_id']} · {intent['side']} {intent['quantity']} · {order['status']}"
                        ).classes("text-sm")
                    for op in store.rows(operations, bot_id)[:10]:
                        ui.label(
                            f"{stamp(op['created_at'])} · {op['kind']} · {op['status']} · {op['message']}"
                        ).classes("text-sm")
                    ui.button("关闭", on_click=dialog.close)
                dialog.open()

            def delete_dialog(bot_id: str):
                bot = store.bot(bot_id)
                with ui.context.client.layout:
                    dialog = ui.dialog()
                with dialog, ui.card().classes("w-full max-w-md p-6"):
                    ui.label(f"删除 Bot：{bot.name}").classes("text-xl font-bold")
                    ui.label("删除此 Bot 的配置，历史交易记录仍保留在数据库中。")

                    async def confirm():
                        button.disable()
                        try:
                            async with runtime.guard:
                                store.delete_bot(bot_id)
                            form = bot_forms.pop(bot_id, None)
                            if form is not None:
                                form.delete()
                            dialog.close()
                            await bots_view()
                            notify("Bot 已删除", color="positive")
                        except ValueError as exc:
                            notify(str(exc), color="negative")
                            button.enable()

                    with ui.row().classes("w-full justify-end"):
                        ui.button("取消", on_click=dialog.close).props("flat")
                        button = ui.button("确认删除", on_click=confirm, color="negative")
                dialog.open()

            def bot_dialog(bot_id: str | None = None, strategy_id: str | None = None):
                if bot_id:
                    strategy_id = store.bot(bot_id).strategy
                if strategy_id is None:
                    with ui.context.client.layout:
                        picker = ui.dialog()
                    with picker, ui.card().classes("w-full max-w-xl p-6 gap-4"):
                        ui.label("选择策略").classes("text-2xl font-bold")
                        ui.label("每个 Bot 独立配置、独立记录成交。").classes("text-sm text-slate-500")
                        for item in STRATEGIES:
                            if not item["available"]:
                                continue
                            with ui.card().classes("w-full p-4 border border-slate-200 shadow-none"):
                                ui.label(item["name"]).classes("font-semibold text-lg")
                                ui.label(item["description"]).classes("text-sm text-slate-500")

                                def choose(sid=item["id"]):
                                    with client.layout:
                                        picker.close()
                                        picker.delete()
                                        bot_dialog(strategy_id=sid)

                                ui.button("选择此策略", on_click=choose).props("outline dense")
                        ui.button("取消", on_click=picker.close).props("flat")
                    picker.open()
                    return
                form_key = bot_id or f"create:{strategy_id}"
                if form_key in bot_forms:
                    bot_forms[form_key].open()
                    return
                accounts = store.connections()
                minimum = 1 if strategy_id == "grid" else 2
                if len(accounts) < minimum:
                    notify(
                        "网格需要至少一个账户实例"
                        if minimum == 1
                        else "请先添加至少两个账户实例；同一交易所可以添加多个",
                        color="warning",
                    )
                    tabs.set_value(accounts_tab)
                    return
                request_id = uuid.uuid4().hex
                if strategy_id == "grid":

                    async def saved():
                        bot_forms.pop(form_key, None)
                        await bots_view()
                        tabs.set_value(bots_tab)
                        notify("网格已保存" if bot_id else "网格已创建，点击运行开始", color="positive")

                    with ui.context.client.layout:
                        bot_forms[form_key] = grid_dialog(store, runtime, request_id, saved, bot_id)
                    bot_forms[form_key].open()
                    return
                bot = store.bot(bot_id) if bot_id else None
                parameters = bot.parameters if bot else None
                assert parameters is None or isinstance(parameters, HedgeParameters)
                editable = (
                    store.bot_editability(bot_id)
                    if bot_id
                    else {"entry_parameters": True, "slippage": True, "reopen": True}
                )
                with ui.context.client.layout:
                    dialog = ui.dialog()
                bot_forms[form_key] = dialog
                with dialog, ui.card().classes("w-full max-w-xl p-6 gap-4").style("max-height: 90vh; overflow-y: auto"):
                    ui.label("修改 Bot" if bot else "创建 Bot").classes("text-2xl font-bold")
                    ui.label("跨账户价差对冲").classes("text-emerald-700")
                    name = (
                        ui.input(
                            "Bot 名称 *",
                            value=bot.name if bot else "价差对冲",
                            validation={"请输入 Bot 名称": lambda v: isinstance(v, str) and bool(v.strip())},
                        )
                        .without_auto_validation()
                        .classes("w-full")
                        .props("outlined maxlength=80")
                    )
                    choices = {a.id: f"{a.name} · {PROVIDER_NAMES[a.provider]}" for a in accounts}
                    long = (
                        ui.select(
                            choices,
                            label="做多账户",
                            value=parameters.long_connection_id if parameters else accounts[0].id,
                        )
                        .classes("w-full")
                        .props("outlined")
                    )
                    long_ticker = MarketSelector(
                        store, runtime.markets, long, label="做多 ticker",
                        value=parameters.long_symbol if parameters else None,
                        enabled=editable["entry_parameters"],
                    )
                    short = (
                        ui.select(
                            choices,
                            label="做空账户",
                            value=parameters.short_connection_id if parameters else accounts[1].id,
                        )
                        .classes("w-full")
                        .props("outlined")
                    )
                    short_ticker = MarketSelector(
                        store, runtime.markets, short, label="做空 ticker",
                        value=parameters.short_symbol if parameters else None,
                        enabled=editable["entry_parameters"],
                    )
                    ui.label("价差 =（做空报价 ÷ 做多报价 − 1）× 100%；两腿 ticker 分别选择。").classes(
                        "text-xs text-slate-500"
                    )
                    with ui.row().classes("w-full"):
                        threshold = (
                            ui.number(
                                "价差条件 %",
                                value=float(parameters.threshold_pct) if parameters else 0.1,
                                min=-100,
                                step=0.01,
                                validation={
                                    "价差条件须大于 -100%": lambda v: (
                                        v is not None and v > -100
                                    )
                                },
                            )
                            .without_auto_validation()
                            .classes("flex-1")
                            .props("outlined")
                        )
                        amount = (
                            ui.number(
                                "单侧目标金额（USD）",
                                value=float(parameters.target_usd) if parameters else 1000,
                                min=0.01,
                                max=1000000,
                                validation={
                                    "金额须大于 0，且不超过 1,000,000": lambda v: (
                                        v is not None and 0 < v <= 1000000
                                    )
                                },
                            )
                            .without_auto_validation()
                            .classes("flex-1")
                            .props("outlined")
                        )
                    if not editable["entry_parameters"]:
                        ui.label("建仓参数已锁定。可修改名称、允许的滑点和定期重开设置。").classes(
                            "text-amber-800 text-sm"
                        )
                        entry_controls: list[DisableableElement] = [
                            long, short, long_ticker.select, short_ticker.select, threshold, amount
                        ]
                        for entry_control in entry_controls:
                            entry_control.disable()
                    else:
                        ui.label(
                            "可选择同一交易所的两个不同账户。保存参数不会下单；等待中的 Bot 修改参数后需重新点击运行。"
                        ).classes("text-sm")
                    slippage = (
                        ui.number(
                            "最大滑点 %",
                            value=float(parameters.slippage_bps / 100) if parameters else 0.2,
                            min=0,
                            max=1,
                            step=0.05,
                            validation={"请输入 0 到 1 的最大滑点": lambda v: v is not None and 0 <= v <= 1},
                        )
                        .without_auto_validation()
                        .classes("w-full")
                        .props("outlined")
                    )
                    if not editable["slippage"]:
                        slippage.disable()
                    reopen = ui.switch(
                        "定期重开",
                        value=parameters.reopen_interval_seconds is not None if parameters else False,
                    )
                    with ui.row().classes("w-full"):
                        reopen_interval = (
                            ui.number(
                                "持仓间隔（分钟）",
                                value=parameters.reopen_interval_seconds / 60
                                if parameters and parameters.reopen_interval_seconds
                                else 60,
                                min=1,
                                max=43200,
                                step=1,
                                validation={
                                    "间隔须为 1–43,200 分钟": lambda v: (
                                        v is not None
                                        and 1 <= v <= 43200
                                        and Decimal(str(v)) * 60 == (Decimal(str(v)) * 60).to_integral_value()
                                    )
                                },
                            )
                            .without_auto_validation()
                            .classes("flex-1")
                            .props("outlined")
                        )
                        random_wait = (
                            ui.number(
                                "随机等待上限（分钟）",
                                value=parameters.reopen_random_wait_seconds / 60 if parameters else 5,
                                min=0,
                                max=5,
                                step=0.5,
                                validation={
                                    "随机等待须为 0–5 分钟": lambda v: (
                                        v is not None
                                        and 0 <= v <= 5
                                        and Decimal(str(v)) * 60 == (Decimal(str(v)) * 60).to_integral_value()
                                    )
                                },
                            )
                            .without_auto_validation()
                            .classes("flex-1")
                            .props("outlined")
                        )

                    def update_reopen_controls():
                        reopen.set_enabled(editable["reopen"])
                        for control in [reopen_interval, random_wait]:
                            control.set_enabled(editable["reopen"] and reopen.value)

                    reopen.on_value_change(update_reopen_controls)
                    update_reopen_controls()
                    ui.label(
                        "双腿建仓确认后计时 → 平仓 → 随机等待 → 等待价差建仓。暂停保留持仓并取消计时；恢复后重新计时，手动平仓结束运行。持仓中修改间隔会从保存时重新计时。"
                    ).classes("text-xs text-slate-500")
                    form_error = ui.label("").classes("text-sm text-red-600")
                    busy = False
                    preview_label = ui.label(
                        "保存会更新运行中的 Bot；修改重开间隔后重新计时。"
                        if bot and bot.state == BotState.HOLDING
                        else "预览后保存，点击运行才会等待条件。"
                    ).classes("text-sm text-slate-500")

                    def value():
                        result = BotUpdate(
                            name=name.value,
                            parameters=HedgeParameters(
                                long_connection_id=long.value,
                                short_connection_id=short.value,
                                long_symbol=long_ticker.select.value,
                                short_symbol=short_ticker.select.value,
                                threshold_pct=Decimal(str(threshold.value)),
                                target_usd=Decimal(str(amount.value)),
                                slippage_bps=Decimal(str(slippage.value)) * 100,
                                reopen_interval_seconds=int(Decimal(str(reopen_interval.value)) * 60)
                                if reopen.value
                                else None,
                                reopen_random_wait_seconds=int(Decimal(str(random_wait.value)) * 60),
                            ),
                        )
                        return result if bot else BotCreate(**result.model_dump(), request_id=request_id)

                    def validate():
                        valid = all(
                            [name.validate(), threshold.validate(), amount.validate(), slippage.validate()]
                        )
                        if reopen.value:
                            valid = all([reopen_interval.validate(), random_wait.validate(), valid])
                        if long.value == short.value:
                            form_error.set_text("做多和做空必须选择不同账户实例。")
                            return False
                        if not long_ticker.valid() or not short_ticker.valid():
                            form_error.set_text("请分别选择两腿的可用合约；列表读取失败时点击刷新重试。")
                            return False
                        form_error.set_text("" if valid else "请先修正标红的字段。")
                        return valid

                    async def preview():
                        await asyncio.gather(long_ticker.ensure_loaded(), short_ticker.ensure_loaded())
                        if not validate():
                            return
                        try:
                            result = await runtime.preview(value())
                            assert isinstance(result, Preview)
                            preview_label.set_text(
                                f"{result.source} · 当前价差 {result.spread_pct:.4f}% · "
                                f"做多 {result.long_quantity} {long_ticker.select.value} / "
                                f"做空 {result.short_quantity} {short_ticker.select.value}"
                            )
                        except Exception as exc:
                            preview_label.set_text(
                                str(exc) if isinstance(exc, ValueError) else "预览失败，请重试"
                            )

                    async def save():
                        nonlocal busy
                        if busy:
                            return
                        await asyncio.gather(long_ticker.ensure_loaded(), short_ticker.ensure_loaded())
                        if busy or not validate():
                            return
                        busy = True
                        save_button.disable()
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
                            bot_forms.pop(form_key, None)
                            dialog.delete()
                            await bots_view()
                            tabs.set_value(bots_tab)
                            notify("Bot 已保存" if bot_id else "Bot 已创建，可点击运行", color="positive")
                        except ValidationError:
                            form_error.set_text("参数格式不正确，请检查各字段。")
                        except ValueError as exc:
                            form_error.set_text(str(exc))
                        except Exception:
                            form_error.set_text("保存失败，请稍后重试。")
                        finally:
                            busy = False
                            if not save_button.is_deleted:
                                save_button.enable()

                    with ui.row().classes("w-full justify-end"):
                        ui.button("取消", on_click=dialog.close).props("flat")
                        ui.button("查看报价", on_click=preview).props("outline")
                        save_button = ui.button("保存 Bot", on_click=save)
                dialog.open()

            connection_form: ui.dialog | None = None

            def account_dialog():
                nonlocal connection_form
                if connection_form is not None:
                    connection_form.open()
                    return
                # Keep the form attached to the page, so refreshing the account list
                # cannot delete the cached dialog or its pending input values.
                with ui.context.client.layout:
                    connection_form = ui.dialog()
                with connection_form as dialog, ui.card().classes("w-full max-w-lg p-6 gap-4"):
                    ui.label("连接交易所账户").classes("text-2xl font-bold")
                    ui.label("先在交易所的 API 页面生成交易用密钥，再填写以下信息。")
                    name = (
                        ui.input(
                            "账户昵称 *",
                            placeholder="例如 Arcus · 账户 A",
                            validation={
                                "请输入账户昵称": lambda value: isinstance(value, str) and bool(value.strip())
                            },
                        )
                        .without_auto_validation()
                        .classes("w-full")
                        .props("outlined maxlength=80")
                    )
                    provider = (
                        ui.select(
                            {p.value: label for p, label in PROVIDER_NAMES.items() if p in TRADING_PROVIDERS},
                            label="交易所",
                            value=Provider.ARCUS.value,
                        )
                        .classes("w-full")
                        .props("outlined")
                    )
                    wallet = (
                        ui.input(
                            "钱包地址",
                            validation={
                                "请输入正确的钱包地址（0x 开头的 40 位十六进制）": lambda value: (
                                    re.fullmatch(r"0x[0-9a-fA-F]{40}", value.strip()) is not None
                                )
                            },
                        )
                        .without_auto_validation()
                        .classes("w-full")
                        .props("outlined")
                    )
                    index = (
                        ui.number(
                            "子账户编号",
                            value=0,
                            min=0,
                            precision=0,
                            validation=lambda value: (
                                None
                                if value is not None
                                and value == int(value)
                                and 0 <= value <= (9 if provider.value == Provider.ARCUS.value else 2**48 - 1)
                                else "请输入正确的整数账户编号（Arcus 为 0–9）"
                            ),
                        )
                        .without_auto_validation()
                        .classes("w-full")
                        .props("outlined")
                    )
                    key_index = (
                        ui.number(
                            "API key 编号",
                            value=None,
                            min=0,
                            max=254,
                            precision=0,
                            validation=lambda value: (
                                None
                                if value is not None and 0 <= value <= 254 and value == int(value)
                                else "请输入 0–254 之间的整数 API key 编号"
                            ),
                        )
                        .without_auto_validation()
                        .classes("w-full")
                        .props("outlined")
                    )
                    key_index.set_visibility(False)
                    key_id = (
                        ui.input("API Key ID", password=True, password_toggle_button=True,
                            validation={"请输入完整 API Key ID（ondoKeyId_ 开头）": lambda v: isinstance(v, str) and v.startswith("ondoKeyId_") and len(v) > 10})
                        .without_auto_validation().classes("w-full").props("outlined autocomplete=off")
                    )
                    key_id.set_visibility(False)
                    signing_key = (
                        ui.input(
                            "API Signing Key",
                            password=True,
                            password_toggle_button=True,
                            validation={
                                "请输入 API 签名密钥": lambda value: (
                                    isinstance(value, str) and bool(value.strip())
                                )
                            },
                        )
                        .without_auto_validation()
                        .classes("w-full")
                        .props("outlined autocomplete=off")
                    )
                    help_label = ui.label(
                        "Arcus：填写 API Keys 页面显示的 API Signing Key 和 Subaccount #。"
                    ).classes("text-sm text-slate-500")
                    api_help = ui.link("查看 API 配置图文指南 ↗", guide_url(provider.value), new_tab=True).classes(
                        "text-emerald-700 text-sm font-semibold"
                    ).props('rel="noopener noreferrer"')

                    def change_provider():
                        is_arcus = provider.value == Provider.ARCUS.value
                        is_entropy = provider.value == Provider.ENTROPY.value
                        is_ondo = provider.value == Provider.ONDO.value
                        api_help.props["href"] = guide_url(provider.value)
                        wallet.set_visibility(is_arcus or is_entropy)
                        index.set_visibility(not is_entropy and not is_ondo)
                        key_index.set_visibility(not is_arcus and not is_entropy and not is_ondo)
                        key_id.set_visibility(is_ondo)
                        key_id.set_value("")
                        index.set_label("子账户编号" if is_arcus else "Account Index")
                        index.set_value(0 if is_arcus else None)
                        key_index.set_value(None)
                        signing_key.set_value("")
                        signing_key.set_label("API Secret" if is_ondo else "API Signing Key")
                        help_label.set_text(
                            "Arcus：填写 API Keys 页面显示的 API Signing Key 和 Subaccount #。"
                            if is_arcus
                            else "Entropy：使用交易账户地址与 Hyperliquid API 代理私钥。先在 Entropy 官网完成交易授权；支持标准和统一账户，暂不支持组合保证金。请勿填写主钱包私钥。"
                            if is_entropy
                            else "Ondo Perps：在 API Keys 创建 View & Trade 密钥，填写完整 Key ID 与 Secret（保留前缀）。验证后自动识别账户；无需钱包私钥。"
                            if is_ondo
                            else "Lighter：填写该部署的 Account Index、API key 编号和 API 私钥。"
                        )

                    provider.on_value_change(change_provider)

                    form_error = ui.label("").classes("text-red-700 text-sm")
                    busy = False

                    async def save():
                        nonlocal busy
                        if busy:
                            return
                        form_error.set_text("")
                        is_arcus = provider.value == Provider.ARCUS.value
                        is_entropy = provider.value == Provider.ENTROPY.value
                        is_ondo = provider.value == Provider.ONDO.value
                        checks = [name.validate(), signing_key.validate()]
                        if not is_entropy and not is_ondo:
                            checks.append(index.validate())
                        checks.append(key_id.validate() if is_ondo else wallet.validate() if is_arcus or is_entropy else key_index.validate())
                        if not all(checks):
                            form_error.set_text("请先修正标红的字段，再验证账户。")
                            return
                        busy = True
                        button.disable()
                        button.set_text("正在验证账户…")
                        editable_fields: list[DisableableElement] = [
                            name,
                            provider,
                            wallet,
                            index,
                            key_index,
                            key_id,
                            signing_key,
                        ]
                        for field in editable_fields:
                            field.disable()
                        try:
                            value = ConnectionCreate(
                                name=name.value,
                                provider=Provider(provider.value),
                                account_index=None
                                if is_entropy or is_ondo
                                else index.value
                                if index.value is not None
                                else -1,
                                address=wallet.value.strip() if is_arcus or is_entropy else None,
                                api_key_index=key_index.value
                                if not is_arcus and not is_entropy and not is_ondo and key_index.value is not None
                                else None,
                                api_private_key=SecretStr(signing_key.value.strip()),
                                api_key_id=SecretStr(key_id.value.strip()) if is_ondo else None,
                            )
                            async with runtime.guard:
                                await runtime.accounts.add(value)
                            signing_key.set_value("")
                            name.set_value("")
                            wallet.set_value("")
                            index.set_value(0 if is_arcus else None)
                            key_index.set_value(None)
                            key_id.set_value("")
                            dialog.close()
                            await accounts_view.refresh()
                            notify("账户已连接，余额与持仓已读取", color="positive")
                        except ValidationError:
                            form_error.set_text(
                                "账户信息格式不正确，请核对钱包地址、账户编号和 API 签名密钥。"
                            )
                        except Exception as exc:
                            notify(
                                str(exc) if isinstance(exc, ValueError) else "账户连接失败，请核对账户和密钥",
                                color="negative",
                            )
                        finally:
                            busy = False
                            button.enable()
                            button.set_text("验证并连接账户")
                            for field in editable_fields:
                                field.enable()

                    with ui.row().classes("w-full justify-end"):
                        ui.button("取消", on_click=dialog.close).props("flat")
                        button = ui.button("验证并连接账户", on_click=save)
                dialog.open()

            @ui.refreshable
            async def accounts_view():
                with ui.row().classes("w-full justify-between"):
                    ui.label("交易所账户").classes("text-xl font-bold")
                    with ui.row().classes("items-center gap-3"):
                        ui.link("API 配置指南 ↗", GUIDE_URL, new_tab=True).classes(
                            "text-sm text-emerald-700 font-semibold"
                        ).props('rel="noopener noreferrer"')
                        ui.button("连接账户", icon="add", on_click=account_dialog)
                ui.label("同一交易所可以连接多个账户，Bot 绑定到你选择的具体账户。")
                for account in store.connections():
                    view = runtime.accounts.view(account.id)
                    snapshot = view["snapshot"]
                    with ui.card().classes("w-full p-5"):
                        with ui.row().classes("w-full justify-between"):
                            ui.label(account.name).classes("text-xl font-semibold")
                            ui.badge(
                                {"connected": "已连接", "stale": "等待更新", "unavailable": "读取失败"}[
                                    view["status"]
                                ],
                                color="positive" if view["status"] == "connected" else "grey-7",
                            )
                        ui.label(PROVIDER_NAMES[account.provider])
                        ui.label(f"账户：{account.account_ref}")
                        if view["error"]:
                            ui.label(view["error"]).classes("text-amber-800")
                        if snapshot is not None:
                            equity_label = "USDC 抵押余额" if account.provider == Provider.ENTROPY else "账户资产"
                            ui.label(
                                f"可用抵押资产 {money(snapshot['available'])} · {equity_label} {money(snapshot['equity'])}"
                            )
                            ui.label(f"上次读取：{stamp(snapshot['received_at'])}").classes(
                                "text-xs text-slate-500"
                            )
                            for position in snapshot["positions"]:
                                ui.label(
                                    f"{position['symbol']} · 数量 {position['quantity']} · 入场价 {money(position['entry_price'])} · 交易所浮盈 {money(position['unrealized_pnl'])}"
                                ).classes("text-sm")
                        else:
                            ui.label("余额与持仓待读取").classes("text-slate-500")

                        async def check(a=account):
                            try:
                                await runtime.accounts.refresh(a.id)
                                await accounts_view.refresh()
                                notify("账户已更新", color="positive")
                            except ValueError as exc:
                                notify(str(exc), color="negative")

                        ui.button("刷新余额与持仓", icon="refresh", on_click=check).props("outline")
                if not store.connections():
                    ui.label("尚未连接账户。连接后即可创建 Bot。")

            alert_feed: AlertFeed | None = None

            def alerts_view():
                nonlocal alert_feed
                ui.label("通知与告警").classes("text-xl font-bold")
                ui.label(
                    "这里保留历史事件，不代表当前仍在失败。账户最新状态可在“账户实例”刷新查看。"
                ).classes("text-xs text-slate-500")
                alert_feed = AlertFeed(store)
                alert_feed.update()
                with ui.expansion("Telegram 通知设置", icon="send").classes("w-full bg-white rounded-xl"):
                    ui.label("Token 仅加密保存在本机。网络失败时请以站内通知为准。")
                    token = ui.input("Bot Token", password=True).classes("w-full")
                    chat = ui.input("Chat ID").classes("w-full")

                    def save_telegram():
                        try:
                            notifications.save(token.value, chat.value)
                            token.set_value("")
                            notify("Telegram 配置已加密保存", color="positive")
                        except ValueError as exc:
                            notify(str(exc), color="negative")

                    async def test_telegram():
                        try:
                            await notifications.send("这是你主动请求的 Perp Farming Bots 通知测试消息。")
                            notify("测试消息已发送", color="positive")
                        except ValueError as exc:
                            notify(str(exc), color="negative")

                    with ui.row():
                        ui.button("保存", on_click=save_telegram)
                        ui.button("发送测试消息", on_click=test_telegram).props("outline")
                        ui.button("停用", on_click=notifications.disable).props("flat")

            with ui.tab_panels(tabs, value=bots_tab).classes("w-full bg-transparent"):
                with ui.tab_panel(bots_tab).classes("p-0 gap-4"):
                    with ui.card().classes("w-full p-10 items-center gap-4") as empty_bots:
                        ui.icon("rocket_launch", size="48px").classes("text-emerald-600")
                        ui.label("从你的第一个 Bot 开始").classes("text-2xl font-bold")
                        ui.label("先连接交易所账户，再选择策略、币种和金额。").classes("text-slate-500")
                        ui.button("连接交易所账户", on_click=lambda: tabs.set_value(accounts_tab), icon="add")
                    with ui.element("div").classes("w-full pfb-summary") as bot_summary:
                        summary_values = {}
                        for key, title in [
                            ("Bots", "全部 Bots"),
                            ("持仓 Bots", "持仓中"),
                            ("账户实例", "账户"),
                        ]:
                            with ui.element("div").classes("pfb-summary-item"):
                                ui.label(title).classes("pfb-summary-label")
                                summary_values[key] = ui.label().classes("pfb-summary-value")
                    cards_container = ui.column().classes("w-full gap-4")
                    await bots_view()
                with ui.tab_panel(strategies_tab).classes("p-0 gap-4"):
                    for strategy in STRATEGIES:
                        with ui.card().classes("w-full p-6"):
                            ui.label(strategy["name"]).classes("text-xl font-bold")
                            ui.label(strategy["description"])
                            if strategy["available"]:
                                ui.button(
                                    "创建 Bot",
                                    on_click=lambda sid=strategy["id"]: bot_dialog(strategy_id=sid),
                                )
                            else:
                                ui.badge("后续开放 · 当前未实现", color="grey")
                with ui.tab_panel(accounts_tab).classes("p-0 gap-4"):
                    await accounts_view()
                with ui.tab_panel(points_tab).classes("p-0 gap-4"):

                    async def refresh_points():
                        points_button.disable()
                        try:
                            await runtime.points.refresh_all()
                            points_feed.update()
                        finally:
                            points_button.enable()

                    with ui.row().classes("w-full items-center justify-between"):
                        ui.label("平台积分").classes("text-xl font-bold")
                        points_button = ui.button("刷新积分", icon="refresh", on_click=refresh_points).props(
                            "outline"
                        )
                    ui.label(
                        "每 2 分钟自动采集账户自己的官方积分，并保存历史曲线。关闭浏览器也会持续采集，积分不分摊到 Bot。"
                    ).classes("text-slate-600")
                    points_feed = PointsFeed(runtime.points)
                with ui.tab_panel(alerts_tab).classes("p-0 gap-4"):
                    alerts_view()

            async def refresh():
                if tabs.value == bots_tab:
                    await bots_view()
                elif tabs.value == alerts_tab and alert_feed is not None:
                    alert_feed.update()
                points_feed.update()

            ui.timer(6, refresh)
            ui.label(
                "关闭浏览器不影响 Bot；停止程序会停止条件监测。实际资金费归属尚未计入 Bot 盈亏。"
            ).classes("text-xs text-slate-500")
