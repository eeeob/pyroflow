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
from pyroflow.client.bot_commands_mixin import BotCommandsMixin, _BotCommandsMixinBase
from pyroflow.constants import BOT_COMMANDS_ATTR


class ExcA(Exception):
    pass


def _cmd(name: str) -> BotCommand:
    return BotCommand(name, f"{name} description")


# --- BotCommandsMixin -------------------------------------------------------


class _MixinBase:
    """A minimal stand-in for `Client` under `BotCommandsMixin`, recording every call."""

    def __init__(self) -> None:
        self.dispatcher = SimpleNamespace(groups={}, locks_list=[])
        self.calls: list[tuple[object, ...]] = []
        self.set_error: Exception | None = None
        self.delete_error: Exception | None = None
        self.stop_error: Exception | None = None

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        return asyncio.get_running_loop()

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
    pass


def _declare(client: _MixedFake, *entries: object, group: int = 0) -> SimpleNamespace:
    """Register a fake handler in `client.dispatcher.groups` that declares `entries`."""
    handler = SimpleNamespace()
    setattr(handler, BOT_COMMANDS_ATTR, entries)
    client.dispatcher.groups.setdefault(group, []).append(handler)
    return handler


def _handler(*entries: object) -> MessageHandler:
    async def callback(client: object, message: object) -> None:
        return None

    handler = MessageHandler(callback)
    if entries:
        setattr(handler, BOT_COMMANDS_ATTR, entries)
    return handler


async def _drain() -> None:
    for _ in range(5):
        await asyncio.sleep(0)


def test_bot_commands_mixin_is_a_plain_object_at_runtime() -> None:
    assert BotCommandsMixin.__bases__ == (object,)
    assert _BotCommandsMixinBase is object


def test_bot_commands_mixin_public_coroutines_carry_the_sync_wrapper() -> None:
    for name in ("push_bot_commands", "remove_bot_commands", "start", "stop"):
        method = getattr(BotCommandsMixin, name)
        assert inspect.iscoroutinefunction(method.__wrapped__), name
    assert not hasattr(BotCommandsMixin._track_bot_commands, "__wrapped__")


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


def test_collect_bot_commands_creates_then_extends_a_group() -> None:
    c = _MixedFake()
    a, b, d = _cmd("a"), _cmd("b"), _cmd("d")

    c._collect_bot_commands(None, None, [a])
    c._collect_bot_commands(None, None, b)
    c._collect_bot_commands("en", None, [d])

    assert c.bot_command_groups == [((None, None), [a, b]), (("en", None), [d])]


def test_collect_bot_commands_keeps_scopes_apart() -> None:
    c = _MixedFake()
    a, b = _cmd("a"), _cmd("b")

    c._collect_bot_commands(None, BotCommandScopeDefault(), [a])
    c._collect_bot_commands(None, BotCommandScopeAllGroupChats(), [b])

    assert [commands for _, commands in c.bot_command_groups] == [[a], [b]]


def test_discard_bot_commands_removes_commands_and_keeps_the_rest() -> None:
    c = _MixedFake()
    a, b = _cmd("a"), _cmd("b")
    c._collect_bot_commands(None, None, [a, b])

    c._discard_bot_commands(None, None, a)

    assert c.bot_command_groups == [((None, None), [b])]


def test_discard_bot_commands_drops_the_group_once_empty() -> None:
    c = _MixedFake()
    a, b = _cmd("a"), _cmd("b")
    c._collect_bot_commands(None, None, [a])
    c._collect_bot_commands("en", None, [b])

    c._discard_bot_commands(None, None, [a])

    assert c.bot_command_groups == [(("en", None), [b])]


def test_discard_bot_commands_ignores_unknown_commands_and_keys() -> None:
    c = _MixedFake()
    a = _cmd("a")
    c._collect_bot_commands(None, None, [a])

    c._discard_bot_commands(None, None, [_cmd("missing")])
    c._discard_bot_commands("fr", None, [a])

    assert c.bot_command_groups == [((None, None), [a])]


def test_discard_bot_commands_removes_one_copy_per_command() -> None:
    c = _MixedFake()
    a = _cmd("a")
    c._collect_bot_commands(None, None, [a, a])

    c._discard_bot_commands(None, None, [a])

    assert c.bot_command_groups == [((None, None), [a])]


def test_prune_bot_commands_clears_everything_without_declaring_handlers() -> None:
    c = _MixedFake()
    c._collect_bot_commands(None, None, [_cmd("a")])
    c.dispatcher.groups[0] = [SimpleNamespace()]

    c._prune_bot_commands()

    assert c.bot_command_groups == []


def test_prune_bot_commands_keeps_only_still_declared_commands() -> None:
    c = _MixedFake()
    a, b, d = _cmd("a"), _cmd("b"), _cmd("d")
    _declare(c, [a])
    c._collect_bot_commands(None, None, [a, b])
    c._collect_bot_commands("en", None, [d])

    c._prune_bot_commands()

    assert c.bot_command_groups == [((None, None), [a])]


def test_prune_bot_commands_matches_the_declared_key() -> None:
    c = _MixedFake()
    a = _cmd("a")
    scope = BotCommandScopeDefault()
    _declare(c, ("en", scope, [a]))
    c._collect_bot_commands("en", scope, [a])
    c._collect_bot_commands(None, scope, [a])

    c._prune_bot_commands()

    assert c.bot_command_groups == [(("en", scope), [a])]


def test_prune_bot_commands_never_adds_commands() -> None:
    c = _MixedFake()
    a, b = _cmd("a"), _cmd("b")
    _declare(c, [a, b], (BotCommandScopeDefault(), [_cmd("x")]))
    c._collect_bot_commands(None, None, [a])

    c._prune_bot_commands()

    assert c.bot_command_groups == [((None, None), [a])]


async def test_track_bot_commands_ignores_a_handler_that_never_landed() -> None:
    c = _MixedFake()
    handler = SimpleNamespace()
    setattr(handler, BOT_COMMANDS_ATTR, ([_cmd("a")],))

    c._track_bot_commands(handler, True)
    await _drain()

    assert c.bot_command_groups == []


async def test_track_bot_commands_keeps_commands_of_a_handler_still_registered() -> None:
    c = _MixedFake()
    a = _cmd("a")
    handler = _declare(c, [a])
    c._collect_bot_commands(None, None, [a])

    c._track_bot_commands(handler, False)
    await _drain()

    assert c.bot_command_groups == [((None, None), [a])]


async def test_track_bot_commands_discards_a_removed_handler() -> None:
    c = _MixedFake()
    a = _cmd("a")
    handler = SimpleNamespace()
    setattr(handler, BOT_COMMANDS_ATTR, ([a],))
    c._collect_bot_commands(None, None, [a])

    c._track_bot_commands(handler, False)
    await _drain()

    assert c.bot_command_groups == []


async def test_track_bot_commands_skips_handlers_without_commands() -> None:
    c = _MixedFake()
    handler = _declare(c)

    c._track_bot_commands(handler, True)
    await _drain()

    assert c.bot_command_groups == []
    assert not c.bot_command_groups_lock.locked()


async def test_track_bot_commands_waits_for_the_dispatcher_locks() -> None:
    c = _MixedFake()
    a = _cmd("a")
    handler = _declare(c, [a])
    dispatcher_lock = asyncio.Lock()
    c.dispatcher.locks_list.append(dispatcher_lock)
    await dispatcher_lock.acquire()

    c._track_bot_commands(handler, True)
    await _drain()
    assert c.bot_command_groups == []

    dispatcher_lock.release()
    await _drain()

    assert c.bot_command_groups == [((None, None), [a])]
    assert not c.bot_command_groups_lock.locked()
    assert not dispatcher_lock.locked()


async def test_track_bot_commands_cancelled_releases_only_what_it_acquired() -> None:
    c = _MixedFake()
    handler = _declare(c, [_cmd("a")])
    dispatcher_lock = asyncio.Lock()
    c.dispatcher.locks_list.append(dispatcher_lock)
    await dispatcher_lock.acquire()
    before = asyncio.all_tasks()

    c._track_bot_commands(handler, True)
    (task,) = asyncio.all_tasks() - before
    await _drain()
    assert c.bot_command_groups_lock.locked()

    task.cancel()
    await _drain()

    assert task.cancelled()
    assert not c.bot_command_groups_lock.locked()
    assert dispatcher_lock.locked()
    assert c.bot_command_groups == []
    dispatcher_lock.release()


async def test_add_handler_registers_then_collects_marked_commands() -> None:
    c = _MixedClient("probe", api_id=1, api_hash="x", in_memory=True)
    a = _cmd("a")
    handler = _handler([a])

    assert c.add_handler(handler) == (handler, 0)
    await _drain()

    assert c.dispatcher.groups[0] == [handler]
    assert c.bot_command_groups == [((None, None), [a])]


async def test_add_handler_without_marked_commands_collects_nothing() -> None:
    c = _MixedClient("probe", api_id=1, api_hash="x", in_memory=True)
    handler = _handler()

    c.add_handler(handler, 3)
    await _drain()

    assert c.dispatcher.groups[3] == [handler]
    assert c.bot_command_groups == []


async def test_remove_handler_unregisters_then_drops_marked_commands() -> None:
    c = _MixedClient("probe", api_id=1, api_hash="x", in_memory=True)
    a = _cmd("a")
    handler = _handler([a])
    c.add_handler(handler)
    await _drain()

    assert c.remove_handler(handler) is None
    await _drain()

    assert 0 not in c.dispatcher.groups
    assert c.bot_command_groups == []


async def test_remove_handler_from_the_wrong_group_keeps_the_commands() -> None:
    c = _MixedClient("probe", api_id=1, api_hash="x", in_memory=True)
    a = _cmd("a")
    handler = _handler([a])
    c.add_handler(handler)
    await _drain()
    c.dispatcher.groups[1] = [_handler()]

    c.remove_handler(handler, 1)  # Pyrogram's own task raises ValueError: not in group 1
    await _drain()

    assert c.dispatcher.groups[0] == [handler]
    assert c.bot_command_groups == [((None, None), [a])]


async def test_push_bot_commands_sends_each_group_deduplicated() -> None:
    c = _MixedFake()
    a, b, d = _cmd("a"), _cmd("b"), _cmd("d")
    scope = BotCommandScopeDefault()
    _declare(c, [a, b], ("en", scope, [d]))
    c._collect_bot_commands(None, None, [a, b, a])
    c._collect_bot_commands("en", scope, [d])

    await c.push_bot_commands()

    assert c.calls == [
        ("set", [a, b], {}),
        ("set", [d], {"scope": scope, "language_code": "en"}),
    ]
    assert not c.bot_command_groups_lock.locked()


async def test_push_bot_commands_prunes_undeclared_commands_first() -> None:
    c = _MixedFake()
    a = _cmd("a")
    _declare(c, [a])
    c._collect_bot_commands(None, None, [a, _cmd("gone")])
    c._collect_bot_commands("fr", None, [_cmd("gone_too")])

    await c.push_bot_commands()

    assert c.calls == [("set", [a], {})]
    assert c.bot_command_groups == [((None, None), [a])]


async def test_push_bot_commands_sends_nothing_without_groups() -> None:
    c = _MixedFake()

    await c.push_bot_commands()

    assert c.calls == []
    assert not c.bot_command_groups_lock.locked()


async def test_push_bot_commands_waits_for_the_groups_lock() -> None:
    c = _MixedFake()
    a = _cmd("a")
    _declare(c, [a])
    c._collect_bot_commands(None, None, [a])
    await c.bot_command_groups_lock.acquire()

    task = asyncio.ensure_future(c.push_bot_commands())
    await _drain()
    assert c.calls == []

    c.bot_command_groups_lock.release()
    await task

    assert c.calls == [("set", [a], {})]


async def test_push_bot_commands_releases_the_lock_when_sending_fails() -> None:
    c = _MixedFake()
    a = _cmd("a")
    _declare(c, [a])
    c._collect_bot_commands(None, None, [a])
    c.set_error = ExcA("boom")

    with pytest.raises(ExcA):
        await c.push_bot_commands()

    assert not c.bot_command_groups_lock.locked()


async def test_remove_bot_commands_deletes_every_group_without_pruning() -> None:
    c = _MixedFake()
    scope = BotCommandScopeDefault()
    c._collect_bot_commands(None, None, [_cmd("a")])
    c._collect_bot_commands("en", scope, [_cmd("b")])

    await c.remove_bot_commands()

    assert c.calls == [("delete", {}), ("delete", {"language_code": "en", "scope": scope})]
    assert len(c.bot_command_groups) == 2
    assert not c.bot_command_groups_lock.locked()


async def test_remove_bot_commands_with_no_groups_deletes_nothing() -> None:
    c = _MixedFake()

    await c.remove_bot_commands()

    assert c.calls == []
    assert not c.bot_command_groups_lock.locked()


async def test_remove_bot_commands_releases_the_lock_when_deleting_fails() -> None:
    c = _MixedFake()
    c._collect_bot_commands(None, None, [_cmd("a")])
    c.delete_error = ExcA("boom")

    with pytest.raises(ExcA):
        await c.remove_bot_commands()

    assert not c.bot_command_groups_lock.locked()


async def test_start_starts_then_publishes_the_commands() -> None:
    c = _MixedFake()
    a = _cmd("a")
    _declare(c, [a])
    c._collect_bot_commands(None, None, [a])

    result = await c.start(1, flag=True)

    assert result == "started"
    assert c.calls == [("start", (1,), {"flag": True}), ("set", [a], {})]


async def test_stop_deletes_the_commands_then_stops() -> None:
    c = _MixedFake()
    c._collect_bot_commands(None, None, [_cmd("a")])

    result = await c.stop(1, flag=True)

    assert result == "stopped"
    assert c.calls == [("delete", {}), ("stop", (1,), {"flag": True})]
    assert c.bot_command_groups == []  # pruned: no handler declares them


async def test_stop_with_remove_commands_false_keeps_them_on_telegram() -> None:
    c = _MixedFake()
    a = _cmd("a")
    _declare(c, [a])
    c._collect_bot_commands(None, None, [a, _cmd("gone")])

    await c.stop(remove_commands=False)

    assert c.calls == [("stop", (), {})]
    assert c.bot_command_groups == [((None, None), [a])]


async def test_stop_prunes_even_when_stopping_fails() -> None:
    c = _MixedFake()
    c._collect_bot_commands(None, None, [_cmd("a")])
    c.stop_error = ExcA("boom")

    with pytest.raises(ExcA):
        await c.stop(remove_commands=False)

    assert c.bot_command_groups == []
