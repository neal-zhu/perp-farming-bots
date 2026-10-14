"""Account-scoped, searchable native ticker selectors shared by strategy forms."""

from __future__ import annotations

from nicegui import ui

from .markets import Markets
from .store import Store


class MarketSelector:
    def __init__(
        self,
        store: Store,
        markets: Markets,
        account: ui.select,
        *,
        label: str,
        value: str | None = None,
        enabled: bool = True,
    ):
        self.store, self.markets, self.account = store, markets, account
        self.enabled = enabled
        self.loaded_account: str | None = None
        self.revision = 0
        self.initial_value = value
        self.loading = False
        self.select = (
            ui.select([], label=label, value=None, with_input=True)
            .props("outlined dense input-debounce=0 clearable")
            .classes("w-full")
        )
        self.select.disable()
        with ui.row().classes("w-full items-center gap-2"):
            self.status = ui.label("正在读取合约列表…").classes("text-xs text-slate-500")
            ui.button(icon="refresh", on_click=lambda: self.load(refresh=True)).props(
                "flat round dense size=xs"
            ).tooltip("重新读取交易所合约列表")
        account.on_value_change(self.account_changed)
        ui.timer(0.01, self.load, once=True)

    def account_changed(self):
        self.revision += 1
        self.loaded_account = None
        self.initial_value = None
        self.select.set_options([], value=None)
        self.select.disable()
        self.status.set_text("正在读取合约列表…")
        ui.timer(0.01, self.load, once=True)

    async def load(self, *, refresh: bool = False):
        self.revision += 1
        revision, requested_account = self.revision, self.account.value
        selected = self.select.value if self.loaded_account == requested_account else self.initial_value
        self.loading = True
        self.select.disable()
        self.status.set_text("正在读取合约列表…")
        try:
            connection = self.store.connection(requested_account)
            symbols = await self.markets.catalog(connection.provider, refresh=refresh)
            if revision != self.revision or requested_account != self.account.value or self.select.is_deleted:
                return
            if not symbols:
                raise ValueError("该交易所没有可用的永续合约")
            choice = selected if selected in symbols else None
            if selected is None:
                choice = "BTC" if "BTC" in symbols else symbols[0]
            self.select.set_options(symbols, value=choice)
            self.loaded_account = requested_account
            self.initial_value = None
            self.status.set_text(f"{len(symbols)} 个合约 · 输入 ticker 搜索")
            if selected is not None and selected not in symbols:
                self.status.set_text(f"原合约 {selected} 已不可用，请重新选择")
        except Exception as exc:
            if revision == self.revision and not self.select.is_deleted:
                self.loaded_account = None
                self.select.set_options([], value=None)
                self.status.set_text(str(exc) if isinstance(exc, ValueError) else "合约列表读取失败，请重试")
        finally:
            if revision == self.revision and not self.select.is_deleted:
                self.loading = False
                self.select.set_enabled(self.enabled and self.loaded_account == requested_account)

    async def ensure_loaded(self):
        if self.loaded_account != self.account.value:
            await self.load()

    def valid(self) -> bool:
        return (
            not self.loading
            and self.loaded_account == self.account.value
            and bool(self.select.value)
            and self.select.value in self.select.options
        )
