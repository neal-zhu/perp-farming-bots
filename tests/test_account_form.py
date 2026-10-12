"""Exercise the actual page callbacks and fields, without production credentials."""

import asyncio
import json
from unittest.mock import AsyncMock

import pytest
from nicegui import background_tasks, core, ui
from nicegui.client import Client

from perp_farming_bots.notifications import Notifications
from perp_farming_bots.ui import install_ui


@pytest.fixture
async def page(env, monkeypatch):
    monkeypatch.setattr(core, "loop", asyncio.get_running_loop())
    store, runtime, _, _ = env
    notifications = Notifications(store, runtime.accounts.secrets)
    timer_factory = ui.timer
    refresh_callbacks = []

    def timer(interval, callback, **kwargs):
        refresh_callbacks.append(callback)
        return timer_factory(interval, callback, **kwargs)

    monkeypatch.setattr(ui, "timer", timer)
    install_ui(store, runtime, notifications)
    home = [f for f, path in Client.page_routes.items() if path == "/"][-1]
    client = Client(ui.page("/form-test"))
    with client:
        await home()
    client.test_refresh = refresh_callbacks[-1]
    yield client
    client.delete()
    Client.page_routes.pop(home, None)


def click(client, text):
    button = next(e for e in client.elements.values() if isinstance(e, ui.button) and e.text == text)
    listener = next(e for e in button._event_listeners.values() if e.type == "click")
    before = set(background_tasks.running_tasks)
    client.handle_event({"id": button.id, "listener_id": listener.id, "args": []})
    return list(background_tasks.running_tasks - before)


def name_inputs(client):
    return [e for e in client.elements.values() if isinstance(e, ui.input) and e.label.startswith("账户昵称")]


def test_reopening_connection_form_keeps_one_form_and_entered_name(page):
    click(page, "连接账户")
    name = name_inputs(page)[0]
    name.set_value("Arcus 账户 1")
    click(page, "连接账户")
    assert len(name_inputs(page)) == 1
    assert name_inputs(page)[0].value == "Arcus 账户 1"
    assert sum(isinstance(e, ui.dialog) for e in page.elements.values()) == 1


async def test_empty_name_is_inline_and_does_not_validate_exchange_key(page, env, monkeypatch):
    _, runtime, _, _ = env
    add = AsyncMock()
    monkeypatch.setattr(runtime.accounts, "add", add)
    click(page, "连接账户")
    for e in page.elements.values():
        if isinstance(e, ui.input) and e.label == "钱包地址":
            e.set_value("0x" + "11" * 20)
        elif isinstance(e, ui.input) and e.label == "API Signing Key":
            e.set_value("22" * 32)
    await asyncio.gather(*click(page, "验证并连接账户"))
    assert name_inputs(page)[0].error == "请输入账户昵称"
    assert any(
        isinstance(e, ui.label) and e.text == "请先修正标红的字段，再验证账户。"
        for e in page.elements.values()
    )
    add.assert_not_awaited()


async def test_current_entered_name_is_submitted_after_reopening(page, env, monkeypatch):
    _, runtime, a, _ = env
    add = AsyncMock(return_value=a)
    monkeypatch.setattr(runtime.accounts, "add", add)
    click(page, "连接账户")
    name_inputs(page)[0].set_value("Arcus 账户 1")
    click(page, "取消")
    click(page, "连接账户")
    name = name_inputs(page)[0]
    listener = next(e for e in name._event_listeners.values() if e.type == "update:value")
    # The same value-change transport as typing immediately before clicking submit.
    page.handle_event({"id": name.id, "listener_id": listener.id, "args": [json.dumps("Arcus 新昵称")]})
    for e in page.elements.values():
        if isinstance(e, ui.input) and e.label == "钱包地址":
            e.set_value("0x" + "11" * 20)
        elif isinstance(e, ui.input) and e.label == "API Signing Key":
            e.set_value("22" * 32)
    await asyncio.gather(*click(page, "验证并连接账户"))
    add.assert_awaited_once()
    assert add.call_args.args[0].name == "Arcus 新昵称"
    assert len(name_inputs(page)) == 1
    click(page, "连接账户")
    assert len(name_inputs(page)) == 1
    assert name_inputs(page)[0].value == ""


async def test_submission_in_progress_cannot_start_another_verification(page, env, monkeypatch):
    _, runtime, a, _ = env
    submitted = asyncio.Event()
    release = asyncio.Event()
    calls = []

    async def add(value):
        calls.append(value)
        submitted.set()
        await release.wait()
        return a

    monkeypatch.setattr(runtime.accounts, "add", add)
    click(page, "连接账户")
    name_inputs(page)[0].set_value("Arcus 账户 1")
    for e in page.elements.values():
        if isinstance(e, ui.input) and e.label == "钱包地址":
            e.set_value("0x" + "11" * 20)
        elif isinstance(e, ui.input) and e.label == "API Signing Key":
            e.set_value("22" * 32)
    tasks = click(page, "验证并连接账户")
    await asyncio.wait_for(submitted.wait(), timeout=1)
    assert not name_inputs(page)[0].enabled
    click(page, "正在验证账户…")
    await asyncio.sleep(0)
    assert len(calls) == 1
    release.set()
    await asyncio.gather(*tasks)
