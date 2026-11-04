"""Tests for `pyroflow.client.bot_commands_mixin`: `BotCommandsMixin`."""

from __future__ import annotations as _annotations

import asyncio
import inspect
from types import SimpleNamespace

import pyroflow
import pytest

from pyrogram.handlers import MessageHandler
from pyrogram.types import (
    BotCommand,
    BotCommandScopeAllGroupChats,
    BotCommandScopeDefault,
)

import pyroflow.client.bot_commands_mixin as module
import pyroflow.utils.bot_commands as bot_commands_module
from pyroflow.client.bot_commands_mixin import BotCommandsMixin, _ClientForTypeCheckers
from pyroflow.constants import BOT_COMMANDS_ATTR


class ExcA(Exception):
    pass


def _cmd(name: str) -> BotCommand:
    return BotCommand(name, f"{name} description")


# --- BotCommandsMixin -------------------------------------------------------


class _MixinBase:
    """A minimal stand-in for `Client` under `BotCommandsMixin`, recording every call."""

    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []
        self.set_error: Exception | None = None
        self.delete_error: Exception | None = None
        self.stop_error: Exception | None = None

    def add_handler(self, handler: object, group: int = 0) -> tuple[object, int]:
        self.calls.append(("add", handler, group))
        return handler, group

    def remove_handler(self, handler: object, group: int = 0) -> None:
        self.calls.append(("remove", handler, group))

    async def set_bot_commands(self, commands: list[BotCommand], **kw: object) -> bool:
        self.calls.append(("set", commands, kw))
        if self.set_error is not None:
            raise self.set_error
        return True

    async def delete_bot_commands(self, **kw: object) -> bool:
        self.calls.append(("delete", kw))
        if self.delete_error is not None:
            raise self.delete_error
        return True

    async def start(self, *args: object, **kw: object) -> str:
        self.calls.append(("start", args, kw))
        return "started"

    async def stop(self, *args: object, **kw: object) -> str:
        self.calls.append(("stop", args, kw))
        if self.stop_error is not None:
            raise self.stop_error
        return "stopped"


class _MixedFake(BotCommandsMixin, _MixinBase):
    pass


class _MixedClient(BotCommandsMixin, pyroflow.Client):
    async def set_bot_commands(self, commands: list[BotCommand], **kw: object) -> bool:
        self.sent = [*getattr(self, "sent", []), commands]
        return True


def _declare(client: BotCommandsMixin, *entries: object, group: int = 0) -> SimpleNamespace:
    """Record a fake handler on `client` that declares `entries`."""
    handler = SimpleNamespace()
    setattr(handler, BOT_COMMANDS_ATTR, entries)
    client._registered_handlers.append((handler, group))
    return handler


def _handler(*entries: object) -> MessageHandler:
    async def callback(client: object, message: object) -> None:
        return None

    handler = MessageHandler(callback)
    if entries:
        setattr(handler, BOT_COMMANDS_ATTR, entries)
    return handler


def _client_with_a_busy_worker() -> tuple[_MixedClient, asyncio.Lock]:
    """A real client with one worker lock, as `Dispatcher.start` creates it."""
    c = _MixedClient("probe", api_id=1, api_hash="x", in_memory=True)
    worker_lock = asyncio.Lock()
    c.dispatcher.locks_list.append(worker_lock)
    return c, worker_lock


async def _drain() -> None:
    for _ in range(5):
        await asyncio.sleep(0)


def test_bot_commands_mixin_is_a_plain_object_at_runtime() -> None:
    assert BotCommandsMixin.__bases__ == (object,)
    assert _ClientForTypeCheckers is object


def test_bot_commands_mixin_public_coroutines_carry_the_sync_wrapper() -> None:
    for name in ("push_bot_commands", "remove_bot_commands", "start", "stop"):
        method = getattr(BotCommandsMixin, name)
        assert inspect.iscoroutinefunction(method.__wrapped__), name


def test_module_exports_the_mixin_and_re_exports_mark_bot_commands() -> None:
    assert module.__all__ == ("BotCommandsMixin", "mark_bot_commands")
    assert module.mark_bot_commands is bot_commands_module.mark_bot_commands


def test_package_exports_both_modules() -> None:
    assert pyroflow.client.__all__ == ("Client", "BotCommandsMixin", "mark_bot_commands")


def test_bot_command_groups_starts_empty_and_is_cached_per_instance() -> None:
    a, b = _MixedFake(), _MixedFake()
    assert a.bot_command_groups == []
    assert a.bot_command_groups is a.bot_command_groups
    assert a.bot_command_groups is not b.bot_command_groups


def test_bot_command_groups_lock_is_a_cached_per_instance_lock() -> None:
    a, b = _MixedFake(), _MixedFake()
    assert isinstance(a.bot_command_groups_lock, asyncio.Lock)
    assert a.bot_command_groups_lock is a.bot_command_groups_lock
    assert a.bot_command_groups_lock is not b.bot_command_groups_lock


def test_registered_handlers_starts_empty_and_is_cached_per_instance() -> None:
    a, b = _MixedFake(), _MixedFake()
    assert a._registered_handlers == []
    assert a._registered_handlers is a._registered_handlers
    assert a._registered_handlers is not b._registered_handlers


async def test_add_handler_registers_with_pyrogram_and_records_the_handler() -> None:
    c = _MixedClient("probe", api_id=1, api_hash="x", in_memory=True)
    handler = _handler([_cmd("a")])

    assert c.add_handler(handler, 2) == (handler, 2)
    await _drain()

    assert c.dispatcher.groups[2] == [handler]
    assert c._registered_handlers == [(handler, 2)]


async def test_add_handler_records_before_pyrogram_places_the_handler() -> None:
    c, worker_lock = _client_with_a_busy_worker()
    handler = _handler([_cmd("a")])

    async with worker_lock:  # A worker is running a handler, so Pyrogram's task waits.
        c.add_handler(handler)
        await _drain()

        assert c.dispatcher.groups == {}
        assert c._registered_handlers == [(handler, 0)]

    await _drain()
    assert c.dispatcher.groups[0] == [handler]


async def test_remove_handler_unregisters_and_drops_one_record() -> None:
    c = _MixedClient("probe", api_id=1, api_hash="x", in_memory=True)
    handler = _handler([_cmd("a")])
    c.add_handler(handler)
    c.add_handler(handler)

    assert c.remove_handler(handler) is None
    await _drain()

    assert c.dispatcher.groups[0] == [handler]
    assert c._registered_handlers == [(handler, 0)]


async def test_remove_handler_from_another_group_keeps_the_record() -> None:
    c = _MixedClient("probe", api_id=1, api_hash="x", in_memory=True)
    handler = _handler([_cmd("a")])
    c.add_handler(handler)
    c.add_handler(_handler(), 1)

    c.remove_handler(handler, 1)  # Pyrogram's own task raises ValueError: not in group 1
    await _drain()

    assert c.dispatcher.groups[0] == [handler]
    assert (handler, 0) in c._registered_handlers


def test_declared_bot_command_groups_groups_dedupes_and_drops_empty_groups() -> None:
    c = _MixedFake()
    a, b, d = _cmd("a"), _cmd("b"), _cmd("d")
    groups_scope = BotCommandScopeAllGroupChats()
    _declare(c, [b, a, b], (groups_scope, [d]), group=5)
    _declare(c, a, ("en", BotCommandScopeDefault(), []), group=1)
    _declare(c)  # declares no commands

    assert c._declared_bot_command_groups() == [
        ((None, None), [b, a]),
        ((None, groups_scope), [d]),
    ]


async def test_push_bot_commands_sends_each_declared_group() -> None:
    c = _MixedFake()
    a, b, d = _cmd("a"), _cmd("b"), _cmd("d")
    scope = BotCommandScopeDefault()
    _declare(c, [a, b], ("en", scope, [d]))

    await c.push_bot_commands()

    assert c.calls == [
        ("set", [a, b], {}),
        ("set", [d], {"scope": scope, "language_code": "en"}),
    ]
    assert c.bot_command_groups == [((None, None), [a, b]), (("en", scope), [d])]
    assert not c.bot_command_groups_lock.locked()


async def test_push_bot_commands_deletes_groups_no_handler_declares_any_more() -> None:
    c = _MixedFake()
    a = _cmd("a")
    _declare(c, [a])
    c.bot_command_groups.append((("fr", None), [_cmd("gone")]))

    await c.push_bot_commands()

    assert c.calls == [("delete", {"language_code": "fr"}), ("set", [a], {})]
    assert c.bot_command_groups == [((None, None), [a])]


async def test_push_bot_commands_sends_nothing_without_declared_commands() -> None:
    c = _MixedFake()

    await c.push_bot_commands()

    assert c.calls == []
    assert c.bot_command_groups == []


async def test_push_bot_commands_waits_for_the_groups_lock() -> None:
    c = _MixedFake()
    a = _cmd("a")
    _declare(c, [a])
    await c.bot_command_groups_lock.acquire()

    task = asyncio.ensure_future(c.push_bot_commands())
    await _drain()
    assert c.calls == []

    c.bot_command_groups_lock.release()
    await task

    assert c.calls == [("set", [a], {})]


async def test_push_bot_commands_from_a_handler_never_waits_on_the_dispatcher() -> None:
    c, worker_lock = _client_with_a_busy_worker()
    a = _cmd("a")

    # `handler_worker` holds its lock around the handler, as it does in an `ask`.
    async with worker_lock:
        c.add_handler(_handler([a]))
        await asyncio.wait_for(c.push_bot_commands(), 1)

    assert c.sent == [[a]]


async def test_push_bot_commands_records_the_groups_when_sending_fails() -> None:
    c = _MixedFake()
    a = _cmd("a")
    _declare(c, [a])
    c.set_error = ExcA("boom")

    with pytest.raises(ExcA):
        await c.push_bot_commands()

    assert c.bot_command_groups == [((None, None), [a])]
    assert not c.bot_command_groups_lock.locked()


async def test_remove_bot_commands_deletes_every_sent_group_and_forgets_them() -> None:
    c = _MixedFake()
    scope = BotCommandScopeDefault()
    c.bot_command_groups.extend([((None, None), [_cmd("a")]), (("en", scope), [_cmd("b")])])

    await c.remove_bot_commands()

    assert c.calls == [("delete", {}), ("delete", {"language_code": "en", "scope": scope})]
    assert c.bot_command_groups == []
    assert not c.bot_command_groups_lock.locked()


async def test_remove_bot_commands_with_no_groups_deletes_nothing() -> None:
    c = _MixedFake()

    await c.remove_bot_commands()

    assert c.calls == []


async def test_remove_bot_commands_keeps_the_groups_when_deleting_fails() -> None:
    c = _MixedFake()
    c.bot_command_groups.append(((None, None), [_cmd("a")]))
    c.delete_error = ExcA("boom")

    with pytest.raises(ExcA):
        await c.remove_bot_commands()

    assert c.bot_command_groups == [((None, None), [_cmd("a")])]
    assert not c.bot_command_groups_lock.locked()


async def test_start_starts_then_publishes_the_commands() -> None:
    c = _MixedFake()
    a = _cmd("a")
    _declare(c, [a])

    result = await c.start(1, flag=True)

    assert result == "started"
    assert c.calls == [("start", (1,), {"flag": True}), ("set", [a], {})]


async def test_stop_deletes_the_sent_commands_stops_and_drops_the_records() -> None:
    c = _MixedFake()
    handler = _declare(c, [_cmd("a")])
    await c.push_bot_commands()
    c.remove_handler(handler)  # Removed after publishing: its group must still be deleted.
    c.calls.clear()

    result = await c.stop(False)

    assert result == "stopped"
    assert c.calls == [("delete", {}), ("stop", (False, True), {})]
    assert c._registered_handlers == []


async def test_stop_without_clear_handlers_keeps_the_records() -> None:
    c = _MixedFake()
    handler = _declare(c, [_cmd("a")])

    await c.stop(clear_handlers=False, remove_commands=False)

    assert c.calls == [("stop", (True, False), {})]
    assert c._registered_handlers == [(handler, 0)]


async def test_stop_with_remove_commands_false_keeps_them_on_telegram() -> None:
    c = _MixedFake()
    a = _cmd("a")
    c.bot_command_groups.append(((None, None), [a]))

    await c.stop(remove_commands=False)

    assert c.calls == [("stop", (True, True), {})]
    assert c.bot_command_groups == [((None, None), [a])]


async def test_stop_keeps_the_records_when_stopping_fails() -> None:
    c = _MixedFake()
    handler = _declare(c, [_cmd("a")])
    c.stop_error = ExcA("boom")

    with pytest.raises(ExcA):
        await c.stop(remove_commands=False)

    assert c._registered_handlers == [(handler, 0)]
