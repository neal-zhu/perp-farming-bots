from __future__ import annotations

import asyncio
import re
import uuid
from decimal import Decimal

from nicegui import ui
from nicegui.elements.mixins.disableable_element import DisableableElement
from pydantic import SecretStr, ValidationError

from .bot_widgets import AlertFeed, BotCard
from .formatting import money, stamp
from .models import (
    PROVIDER_NAMES,
    STRATEGIES,
    TRADING_PROVIDERS,
    BotCreate,
    BotUpdate,
    ConnectionCreate,
    HedgeParameters,
    Provider,
)
from .notifications import Notifications
from .runtime import Runtime
from .store import Store, fills, operations


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
                    ui.label("将向交易所提交减仓订单，只关闭此 Bot 已分配的数量。")

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
                        pnl, funding = await asyncio.gather(runtime.pnl(bot.id), runtime.funding(bot.id))
                        if bot.id not in {b.id for b in store.bots()}:
                            continue
                        bot = store.bot(bot.id)
                        if bot.id not in bot_cards:
                            with cards_container:
                                bot_cards[bot.id] = BotCard(
                                    bot.id, action, bot_dialog, delete_dialog, close_dialog, detail_dialog
                                )
                        bot_cards[bot.id].update(bot, store, pnl, funding)

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

            def bot_dialog(bot_id: str | None = None):
                form_key = bot_id or "create"
                if form_key in bot_forms:
                    bot_forms[form_key].open()
                    return
                accounts = store.connections()
                if len(accounts) < 2:
                    notify("请先添加至少两个账户实例；同一交易所可以添加多个", color="warning")
                    tabs.set_value(accounts_tab)
                    return
                request_id = uuid.uuid4().hex
                bot = store.bot(bot_id) if bot_id else None
                parameters = bot.parameters if bot else None
                editable = (
                    store.bot_editability(bot_id) if bot_id else {"entry_parameters": True, "slippage": True}
                )
                with ui.context.client.layout:
                    dialog = ui.dialog()
                bot_forms[form_key] = dialog
                with dialog, ui.card().classes("w-full max-w-xl p-6 gap-4"):
                    ui.label("修改 Bot" if bot else "创建 Bot").classes("text-2xl font-bold")
                    ui.label("跨账户价差对冲").classes("text-emerald-700")
                    name = (
                        ui.input(
                            "Bot 名称 *",
                            value=bot.name if bot else "BTC 对冲",
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
                    short = (
                        ui.select(
                            choices,
                            label="做空账户",
                            value=parameters.short_connection_id if parameters else accounts[1].id,
                        )
                        .classes("w-full")
                        .props("outlined")
                    )
                    symbol = (
                        ui.select(
                            ["BTC", "ETH", "SOL"],
                            label="币种",
                            value=parameters.symbol if parameters else "BTC",
                        )
                        .classes("w-full")
                        .props("outlined")
                    )
                    with ui.row().classes("w-full"):
                        threshold = (
                            ui.number(
                                "价差条件 %",
                                value=float(parameters.threshold_pct) if parameters else 0.1,
                                min=-10,
                                max=100,
                                step=0.01,
                                validation={
                                    "请输入 -10 到 100 的价差条件": lambda v: (
                                        v is not None and -10 <= v <= 100
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
                        ui.label(
                            "此 Bot 已有订单或持仓，建仓参数已锁定。可修改名称和允许的滑点；新参数请另建 Bot。"
                        ).classes("text-amber-800 text-sm")
                        entry_controls: list[DisableableElement] = [long, short, symbol, threshold, amount]
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
                    form_error = ui.label("").classes("text-sm text-red-600")
                    busy = False
                    preview_label = ui.label("预览后保存，点击运行才会等待条件。").classes(
                        "text-sm text-slate-500"
                    )

                    def value():
                        result = BotUpdate(
                            name=name.value,
                            parameters=HedgeParameters(
                                long_connection_id=long.value,
                                short_connection_id=short.value,
                                symbol=symbol.value,
                                threshold_pct=Decimal(str(threshold.value)),
                                target_usd=Decimal(str(amount.value)),
                                slippage_bps=Decimal(str(slippage.value)) * 100,
                            ),
                        )
                        return result if bot else BotCreate(**result.model_dump(), request_id=request_id)

                    def validate():
                        valid = all(
                            [name.validate(), threshold.validate(), amount.validate(), slippage.validate()]
                        )
                        if long.value == short.value:
                            form_error.set_text("做多和做空必须选择不同账户实例。")
                            return False
                        form_error.set_text("" if valid else "请先修正标红的字段。")
                        return valid

                    async def preview():
                        if not validate():
                            return
                        try:
                            result = await runtime.preview(value())
                            preview_label.set_text(
                                f"{result.source} · 当前价差 {result.spread_pct:.4f}% · "
                                f"数量 {result.quantity} · 预计费用 {money(result.estimated_fees)}"
                            )
                        except Exception as exc:
                            preview_label.set_text(
                                str(exc) if isinstance(exc, ValueError) else "预览失败，请重试"
                            )

                    async def save():
                        nonlocal busy
                        if busy or not validate():
                            return
                        busy = True
                        save_button.disable()
                        try:
                            async with runtime.guard:
                                result = value()
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
                    ui.link("Arcus API Keys", "https://app.arcus.xyz/api-keys", new_tab=True)
                    ui.link("Lighter Robinhood", "https://robinhoodchain.lighter.xyz/apikeys", new_tab=True)

                    def change_provider():
                        is_arcus = provider.value == Provider.ARCUS.value
                        wallet.set_visibility(is_arcus)
                        key_index.set_visibility(not is_arcus)
                        index.set_label("子账户编号" if is_arcus else "Account Index")
                        index.set_value(0 if is_arcus else None)
                        key_index.set_value(None)
                        signing_key.set_value("")
                        help_label.set_text(
                            "Arcus：填写 API Keys 页面显示的 API Signing Key 和 Subaccount #。"
                            if is_arcus
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
                        checks = [name.validate(), index.validate(), signing_key.validate()]
                        checks.append(wallet.validate() if is_arcus else key_index.validate())
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
                            signing_key,
                        ]
                        for field in editable_fields:
                            field.disable()
                        try:
                            value = ConnectionCreate(
                                name=name.value,
                                provider=Provider(provider.value),
                                account_index=index.value if index.value is not None else -1,
                                address=wallet.value.strip() if is_arcus else None,
                                api_key_index=key_index.value
                                if not is_arcus and key_index.value is not None
                                else None,
                                api_private_key=SecretStr(signing_key.value.strip()),
                            )
                            async with runtime.guard:
                                await runtime.accounts.add(value)
                            signing_key.set_value("")
                            name.set_value("")
                            wallet.set_value("")
                            index.set_value(0 if is_arcus else None)
                            key_index.set_value(None)
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
                            ui.label(
                                f"可用抵押资产 {money(snapshot['available'])} · 账户资产 {money(snapshot['equity'])}"
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

            @ui.refreshable
            def points_view():
                ui.label("平台积分").classes("text-xl font-bold")
                ui.label("积分按交易所账户展示，官方积分读取尚未接入。")
                for account in store.connections():
                    with ui.card().classes("w-full p-5"):
                        ui.label(account.name).classes("text-lg font-semibold")
                        ui.label("积分：暂不可读取").classes("text-slate-500")

            alert_feed: AlertFeed | None = None

            def alerts_view():
                nonlocal alert_feed
                ui.label("通知与告警").classes("text-xl font-bold")
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
                        ui.label("先连接两个交易所账户，再选择策略、币种和金额。").classes("text-slate-500")
                        ui.button("连接交易所账户", on_click=lambda: tabs.set_value(accounts_tab), icon="add")
                    with ui.row().classes("w-full gap-4") as bot_summary:
                        summary_values = {}
                        for title in ["Bots", "持仓 Bots", "账户实例"]:
                            with ui.card().classes("flex-1 min-w-40 p-5 gap-1"):
                                ui.label(title).classes("text-slate-500 text-sm")
                                summary_values[title] = ui.label().classes("text-3xl font-bold")
                    cards_container = ui.column().classes("w-full gap-4")
                    await bots_view()
                with ui.tab_panel(strategies_tab).classes("p-0 gap-4"):
                    for strategy in STRATEGIES:
                        with ui.card().classes("w-full p-6"):
                            ui.label(strategy["name"]).classes("text-xl font-bold")
                            ui.label(strategy["description"])
                            if strategy["available"]:
                                ui.button("创建 Bot", on_click=bot_dialog)
                            else:
                                ui.badge("后续开放 · 当前未实现", color="grey")
                with ui.tab_panel(accounts_tab).classes("p-0 gap-4"):
                    await accounts_view()
                with ui.tab_panel(points_tab).classes("p-0 gap-4"):
                    points_view()
                with ui.tab_panel(alerts_tab).classes("p-0 gap-4"):
                    alerts_view()

            async def refresh():
                if tabs.value == bots_tab:
                    await bots_view()
                elif tabs.value == alerts_tab and alert_feed is not None:
                    alert_feed.update()

            ui.timer(6, refresh)
            ui.label(
                "关闭浏览器不影响 Bot；停止程序会停止条件监测。官方积分读取和资金费归属尚未接入。"
            ).classes("text-xs text-slate-500")
