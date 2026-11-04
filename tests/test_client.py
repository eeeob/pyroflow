"""Tests for `pyroflow.client`: the patched `Client` (listener accessors,
register/unregister forwarders, ask error handlers, `ask`) and `BotCommandsMixin`.
"""

from __future__ import annotations as _annotations

import asyncio
import inspect
from datetime import datetime
from types import SimpleNamespace

import pyroflow
import pytest

from pyrogram.handlers import MessageHandler
from pyrogram.raw.types import PeerUser
from pyrogram.types import (
    BotCommand,
    BotCommandScopeAllGroupChats,
    BotCommandScopeDefault,
    InlineKeyboardMarkup,
    ReplyKeyboardRemove,
)

import pyroflow.client as client_module
import pyroflow.utils.bot_commands as bot_commands_module
from pyroflow.client import BotCommandsMixin, _BotCommandsMixinBase
from pyroflow.constants import BOT_COMMANDS_ATTR
from pyroflow.types import CallbackQuery, Message

from .conftest import make_message


class ExcA(Exception):
    pass


class ExcB(Exception):
    pass


# --- ask() error handling, end to end ---------------------------------------
#
# These go through Client.ask() itself, with send_message and the listener
# faked out so no network is needed, so a change to ask()'s except block (e.g.
# flattening the per-update_type scoping into one shared mapping) is caught.


class _RaisingListener:
    """Stands in for a registered UpdateListener whose wait raised ExcA."""

    async def __call__(self, **kw: object) -> None:
        msg = "boom"
        raise ExcA(msg)


def _install_raising_ask(
    c: pyroflow.Client, update_type: type[Message | CallbackQuery] = Message
) -> None:
    c.dispatcher.listeners[update_type] = _RaisingListener()

    async def fake_send(**kw: object) -> SimpleNamespace:
        return SimpleNamespace(id=5, chat=None)

    c.send_message = fake_send
    c.send_rich_message = fake_send


async def test_ask_routes_a_listening_error_to_the_scoped_client_handler() -> None:
    c = make_client()
    calls = []
    _install_raising_ask(c, update_type=Message)

    c.register_ask_error_handler(ExcA, lambda exc, m: calls.append("message"), update_type=Message)
    c.register_ask_error_handler(
        ExcA, lambda exc, m: calls.append("callback_query"), update_type=CallbackQuery
    )

    with pytest.raises(ExcA):
        await c.ask(100, "hi")

    assert calls == ["message"], (
        "ask()'s except block did not scope its client_handlers lookup to "
        "the call's own update_type"
    )


# --- Client.ask_error_handlers attribute ------------------------------------


def make_client() -> pyroflow.Client:
    return pyroflow.Client("probe", api_id=1, api_hash="x", in_memory=True)


def test_ask_error_handlers_is_not_shared_between_instances() -> None:
    """The classic mutable-default trap: each Client must get its own dict,
    not one every instance ends up sharing."""
    a, b = make_client(), make_client()
    a.ask_error_handlers[ExcA] = "handler"
    assert b.ask_error_handlers == {}


# --- register_ask_error_handler() / unregister_ask_error_handler() ---------
#
# ask_error_handlers is keyed by update_type: {Message: {...}, CallbackQuery:
# {...}}. register_/unregister_ each default update_type to Message, matching
# ask()'s own default.


def test_register_ask_error_handler_adds_an_entry_under_message_by_default() -> None:
    c = make_client()
    handler = lambda exc, m: None

    c.register_ask_error_handler(ExcA, handler)

    assert c.ask_error_handlers == {Message: {ExcA: handler}}


def test_register_ask_error_handler_keeps_update_types_independent() -> None:
    """A handler registered for Message must not become visible under
    CallbackQuery, or vice versa — the two update types must not share a
    single flat mapping."""
    c = make_client()
    msg_handler = lambda exc, m: None
    cb_handler = lambda exc, m: None

    c.register_ask_error_handler(ExcA, msg_handler, update_type=Message)
    c.register_ask_error_handler(ExcA, cb_handler, update_type=CallbackQuery)

    assert c.ask_error_handlers[Message] == {ExcA: msg_handler}
    assert c.ask_error_handlers[CallbackQuery] == {ExcA: cb_handler}


def test_register_ask_error_handler_replaces_an_existing_entry() -> None:
    """No ValueError on re-registering — unlike register_listener() and
    friends, this has no dispatcher lifecycle or duplicate check."""
    c = make_client()
    first = lambda exc, m: None
    second = lambda exc, m: None

    c.register_ask_error_handler(ExcA, first)
    c.register_ask_error_handler(ExcA, second)

    assert c.ask_error_handlers == {Message: {ExcA: second}}


def test_unregister_ask_error_handler_removes_an_entry_and_reports_true() -> None:
    c = make_client()
    c.register_ask_error_handler(ExcA, lambda exc, m: None)

    removed = c.unregister_ask_error_handler(ExcA)

    assert removed is True
    assert c.ask_error_handlers == {Message: {}}


def test_unregister_ask_error_handler_requires_the_exact_key() -> None:
    """A tuple key is not decomposed: registering (ExcA, ExcB) and then
    unregistering plain ExcA must not remove it."""
    c = make_client()
    c.register_ask_error_handler((ExcA, ExcB), lambda exc, m: None)

    removed = c.unregister_ask_error_handler(ExcA)

    assert removed is False
    assert len(c.ask_error_handlers[Message]) == 1


def test_unregister_ask_error_handler_requires_the_exact_update_type() -> None:
    """Registered under Message; unregistering the same exc_types under
    CallbackQuery must not touch it."""
    c = make_client()
    c.register_ask_error_handler(ExcA, lambda exc, m: None, update_type=Message)

    removed = c.unregister_ask_error_handler(ExcA, update_type=CallbackQuery)

    assert removed is False
    assert c.ask_error_handlers[Message] != {}


# --- shared fakes for the rest of the module ---------------------------------


def _cmd(name: str) -> BotCommand:
    return BotCommand(name, f"{name} description")


class _RecordingListener:
    """Stands in for a registered UpdateListener: records its call, returns a sentinel."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.result = object()

    async def __call__(self, **kw: object) -> object:
        self.calls.append(kw)
        return self.result


class _Recorder:
    """Records the keyword arguments of every await, returns a fixed message."""

    def __init__(self, result: object) -> None:
        self.calls: list[dict[str, object]] = []
        self.result = result

    async def __call__(self, **kw: object) -> object:
        self.calls.append(kw)
        return self.result


def _ask_client(
    sent: object | None = None, update_type: type[Message | CallbackQuery] = Message
) -> tuple[pyroflow.Client, _RecordingListener, _Recorder, _Recorder]:
    c = make_client()
    listener = _RecordingListener()
    c.dispatcher.listeners[update_type] = listener
    message = make_message(chat_id=100, message_id=5) if sent is None else sent
    send, edit = _Recorder(message), _Recorder(message)
    c.send_message = send
    c.edit_message_text = edit
    c.send_rich_message = _Recorder(message)
    return c, listener, send, edit


# --- listeners / message_listen / callback_listen ---------------------------


def test_listeners_is_the_dispatchers_mapping() -> None:
    c = make_client()
    assert c.listeners is c.dispatcher.listeners


def test_message_listen_returns_the_message_listener() -> None:
    c = make_client()
    listener = object()
    c.dispatcher.listeners[Message] = listener
    assert c.message_listen is listener


def test_message_listen_raises_key_error_when_unregistered() -> None:
    with pytest.raises(KeyError):
        make_client().message_listen  # noqa: B018


def test_callback_listen_returns_the_callback_query_listener() -> None:
    c = make_client()
    listener = object()
    c.dispatcher.listeners[CallbackQuery] = listener
    assert c.callback_listen is listener


def test_callback_listen_raises_key_error_when_unregistered() -> None:
    c = make_client()
    c.dispatcher.listeners[Message] = object()
    with pytest.raises(KeyError):
        c.callback_listen  # noqa: B018


# --- register_* / unregister_* forwarders -----------------------------------


class _Stoppable:
    """A listener or coordinated stand-in that is its own coordinator, so unregistering stops it either way."""

    __update_type__ = Message

    def __init__(self) -> None:
        self.stopped = False
        self.coordinator = self

    async def stop(self) -> None:
        self.stopped = True


@pytest.mark.parametrize(
    ("register", "unregister", "attr"),
    [
        ("register_listener", "unregister_listener", "listeners"),
        ("register_coordinated", "unregister_coordinated", "coordinateds"),
    ],
)
async def test_register_and_unregister_forward_to_the_dispatcher(
    register: str, unregister: str, attr: str
) -> None:
    c = make_client()
    item = _Stoppable()

    assert getattr(c, register)(item) is None
    assert getattr(c.dispatcher, attr) == {Message: item}

    await getattr(c, unregister)(Message)

    assert getattr(c.dispatcher, attr) == {}
    assert item.stopped is True


# --- ask() ------------------------------------------------------------------


async def test_ask_without_a_listener_raises_runtime_error_naming_the_type() -> None:
    c = make_client()
    with pytest.raises(RuntimeError, match="No listener registered for CallbackQuery"):
        await c.ask(100, "hi", update_type=CallbackQuery)


async def test_ask_sends_a_new_message_and_returns_the_listeners_result() -> None:
    c, listener, send, edit = _ask_client()

    result = await c.ask(100, "hi", disable_notification=True, extra="kw", timeout=3)

    assert result is listener.result
    assert edit.calls == []
    assert len(send.calls) == 1
    call = send.calls[0]
    assert (call["chat_id"], call["text"]) == (100, "hi")
    assert call["disable_notification"] is True
    assert call["extra"] == "kw"
    assert listener.calls == [
        {
            "chat_id": 100,
            "user_id": None,
            "message_id": None,
            "meta": {"message_id": 5},
            "timeout": 3,
        }
    ]


async def test_ask_with_message_id_edits_instead_of_sending() -> None:
    c, listener, send, edit = _ask_client()
    markup = InlineKeyboardMarkup([])

    await c.ask(100, "hi", 5, reply_markup=markup, extra="kw")

    assert send.calls == []
    assert len(edit.calls) == 1
    call = edit.calls[0]
    assert (call["chat_id"], call["message_id"], call["text"]) == (100, 5, "hi")
    assert call["reply_markup"] is markup
    assert call["extra"] == "kw"
    assert "disable_notification" not in call
    assert len(listener.calls) == 1


async def test_ask_edit_mode_rejects_a_non_inline_reply_markup() -> None:
    c, listener, send, edit = _ask_client()

    with pytest.raises(ValueError, match="InlineKeyboardMarkup"):
        await c.ask(100, "hi", 5, reply_markup=ReplyKeyboardRemove())

    assert send.calls == edit.calls == listener.calls == []


async def test_ask_send_mode_accepts_a_non_inline_reply_markup() -> None:
    c, _, send, _ = _ask_client()
    markup = ReplyKeyboardRemove()

    await c.ask(100, "hi", reply_markup=markup)

    assert send.calls[0]["reply_markup"] is markup


async def test_ask_copies_a_dict_meta_and_adds_the_message_id() -> None:
    c, listener, _, _ = _ask_client()
    meta = {"step": 1}

    await c.ask(100, "hi", meta=meta)

    assert listener.calls[0]["meta"] == {"step": 1, "message_id": 5}
    assert meta == {"step": 1}


async def test_ask_keeps_an_existing_message_id_in_meta() -> None:
    c, listener, _, _ = _ask_client()

    await c.ask(100, "hi", meta={"message_id": 99})

    assert listener.calls[0]["meta"] == {"message_id": 99}


async def test_ask_passes_a_non_dict_meta_through_unchanged() -> None:
    c, listener, _, _ = _ask_client()
    meta = ["a", 1]

    await c.ask(100, "hi", meta=meta)

    assert listener.calls[0]["meta"] is meta


async def test_ask_passes_an_int_listen_message_id_and_user_id_through() -> None:
    c, listener, _, _ = _ask_client()

    await c.ask(100, "hi", listen_message_id=42, listen_user_id=7)

    assert listener.calls[0]["message_id"] == 42
    assert listener.calls[0]["user_id"] == 7


async def test_ask_calls_a_callable_listen_message_id_with_the_sent_message() -> None:
    sent = make_message(chat_id=100, message_id=5)
    c, listener, _, _ = _ask_client(sent)
    seen = []

    def pick(m: Message) -> int:
        seen.append(m)
        return m.id + 1

    await c.ask(100, "hi", listen_message_id=pick)

    assert seen == [sent]
    assert listener.calls[0]["message_id"] == 6


async def test_ask_listens_in_the_chat_of_the_sent_message() -> None:
    c, listener, _, _ = _ask_client(make_message(chat_id=-1001))

    await c.ask("@somechat", "hi")

    assert listener.calls[0]["chat_id"] == -1001


async def test_ask_falls_back_to_the_given_chat_id_without_a_chat() -> None:
    c, listener, _, _ = _ask_client(SimpleNamespace(id=5, chat=None))

    await c.ask(100, "hi")

    assert listener.calls[0]["chat_id"] == 100


async def test_ask_falls_back_to_the_given_chat_id_when_the_chat_has_no_id() -> None:
    c, listener, _, _ = _ask_client(SimpleNamespace(id=5, chat=SimpleNamespace(id=None)))

    await c.ask(100, "hi")

    assert listener.calls[0]["chat_id"] == 100


async def test_ask_resolves_a_str_chat_id_to_a_peer_id() -> None:
    c, listener, _, _ = _ask_client(SimpleNamespace(id=5, chat=None))
    resolved = []

    async def fake_resolve_peer(peer_id: str) -> PeerUser:
        resolved.append(peer_id)
        return PeerUser(user_id=42)

    c.resolve_peer = fake_resolve_peer

    await c.ask("@someone", "hi")

    assert resolved == ["@someone"]
    assert listener.calls[0]["chat_id"] == 42


async def test_ask_waits_on_the_listener_of_the_given_update_type() -> None:
    c, listener, _, _ = _ask_client(update_type=CallbackQuery)

    assert await c.ask(100, "hi", update_type=CallbackQuery) is listener.result


async def test_ask_call_error_handlers_take_precedence_over_client_handlers() -> None:
    c = make_client()
    _install_raising_ask(c)
    calls = []
    c.register_ask_error_handler(ExcA, lambda exc, m: calls.append("client"))

    with pytest.raises(ExcA):
        await c.ask(100, "hi", error_handlers={ExcA: lambda exc, m: calls.append("call")})

    assert calls == ["call"]


async def test_ask_falls_back_to_client_handlers_when_call_handlers_do_not_match() -> None:
    c = make_client()
    _install_raising_ask(c)
    calls = []
    c.register_ask_error_handler(ExcA, lambda exc, m: calls.append(("client", m.id)))

    with pytest.raises(ExcA):
        await c.ask(100, "hi", error_handlers={ExcB: lambda exc, m: calls.append("call")})

    assert calls == [("client", 5)]


async def test_ask_re_raises_with_no_handlers_registered() -> None:
    c = make_client()
    _install_raising_ask(c)
    c.ask_error_handlers[Message] = {}

    with pytest.raises(ExcA, match="boom"):
        await c.ask(100, "hi")


# --- ask_rich() -------------------------------------------------------------


async def test_ask_rich_without_a_listener_raises_runtime_error_naming_the_type() -> None:
    c = make_client()
    with pytest.raises(RuntimeError, match="No listener registered for CallbackQuery"):
        await c.ask_rich(100, object(), update_type=CallbackQuery)


async def test_ask_rich_sends_with_send_rich_message() -> None:
    c, listener, send, edit = _ask_client()
    rich = object()
    markup = ReplyKeyboardRemove()

    result = await c.ask_rich(
        100,
        rich,
        disable_notification=True,
        business_connection_id="bc",
        reply_markup=markup,
        schedule_date=datetime(2026, 1, 1),
        extra="kw",
        timeout=3,
    )

    assert result is listener.result
    assert send.calls == edit.calls == []
    call = c.send_rich_message.calls[0]
    assert (call["chat_id"], call["rich_message"]) == (100, rich)
    assert call["disable_notification"] is True
    assert call["reply_markup"] is markup
    assert call["extra"] == "kw"
    # `send_rich_message` takes neither (kurigram 2.2.26 dropped `business_connection_id`)
    assert "schedule_date" not in call
    assert "business_connection_id" not in call
    assert listener.calls == [
        {
            "chat_id": 100,
            "user_id": None,
            "message_id": None,
            "meta": {"message_id": 5},
            "timeout": 3,
        }
    ]


async def test_ask_rich_with_message_id_edits_with_rich_message() -> None:
    c, listener, send, edit = _ask_client()
    rich = object()
    markup = InlineKeyboardMarkup([])
    when = datetime(2026, 1, 1)

    await c.ask_rich(
        100,
        rich,
        5,
        reply_markup=markup,
        schedule_date=when,
        business_connection_id="bc",
        extra="kw",
    )

    assert send.calls == c.send_rich_message.calls == []
    call = edit.calls[0]
    assert (call["chat_id"], call["message_id"], call["rich_message"]) == (100, 5, rich)
    assert call["reply_markup"] is markup
    assert call["schedule_date"] is when
    assert call["business_connection_id"] == "bc"
    assert call["extra"] == "kw"
    assert "text" not in call
    assert "disable_notification" not in call
    assert len(listener.calls) == 1


async def test_ask_rich_forwards_only_arguments_kurigram_accepts() -> None:
    # The recorders accept anything; bind what was forwarded to the real signatures.
    c, _, _, edit = _ask_client()
    await c.ask_rich(100, object())
    await c.ask_rich(100, object(), 5)

    inspect.signature(pyroflow.Client.send_rich_message).bind(c, **c.send_rich_message.calls[0])
    inspect.signature(pyroflow.Client.edit_message_text).bind(c, **edit.calls[0])


async def test_ask_rich_edit_mode_rejects_a_non_inline_reply_markup() -> None:
    c, listener, _, edit = _ask_client()

    with pytest.raises(ValueError, match="InlineKeyboardMarkup"):
        await c.ask_rich(100, object(), 5, reply_markup=ReplyKeyboardRemove())

    assert edit.calls == c.send_rich_message.calls == listener.calls == []


async def test_ask_rich_calls_a_callable_listen_message_id_with_the_sent_message() -> None:
    sent = make_message(chat_id=100, message_id=5)
    c, listener, _, _ = _ask_client(sent)

    await c.ask_rich(100, object(), listen_message_id=lambda m: m.id + 1)

    assert listener.calls[0]["message_id"] == 6


async def test_ask_rich_waits_on_the_listener_of_the_given_update_type() -> None:
    c, listener, _, _ = _ask_client(update_type=CallbackQuery)

    assert await c.ask_rich(100, object(), update_type=CallbackQuery) is listener.result


async def test_ask_rich_routes_a_listening_error_to_the_error_handlers() -> None:
    c = make_client()
    _install_raising_ask(c)
    calls = []
    c.register_ask_error_handler(ExcA, lambda exc, m: calls.append(("client", m.id)))

    with pytest.raises(ExcA):
        await c.ask_rich(100, object(), error_handlers={ExcA: lambda exc, m: calls.append("call")})
    with pytest.raises(ExcA):
        await c.ask_rich(100, object(), error_handlers={ExcB: lambda exc, m: calls.append("call")})

    assert calls == ["call", ("client", 5)]


# --- ask helpers --------------------------------------------------------------


def test_ask_listener_returns_the_registered_listener() -> None:
    c = make_client()
    listener = object()
    c.dispatcher.listeners[CallbackQuery] = listener
    assert c._ask_listener(CallbackQuery) is listener


def test_ask_listener_raises_runtime_error_naming_the_type() -> None:
    with pytest.raises(RuntimeError, match=r"No listener registered for Message\. Register"):
        make_client()._ask_listener(Message)


@pytest.mark.parametrize("markup", [None, InlineKeyboardMarkup([])])
def test_check_edit_reply_markup_returns_none_or_an_inline_markup(
    markup: InlineKeyboardMarkup | None,
) -> None:
    assert pyroflow.Client._check_edit_reply_markup(markup) is markup


def test_check_edit_reply_markup_rejects_other_markups() -> None:
    with pytest.raises(ValueError, match="Edit mode only supports InlineKeyboardMarkup"):
        pyroflow.Client._check_edit_reply_markup(ReplyKeyboardRemove())


async def _await_reply(
    c: pyroflow.Client,
    listener: object,
    m: object,
    chat_id: int | str = 100,
    **overrides: object,
) -> object:
    kw: dict[str, object] = {
        "listen_user_id": None,
        "listen_message_id": None,
        "meta": None,
        "timeout": None,
        "update_type": Message,
        "error_handlers": None,
    }
    kw.update(overrides)
    return await c._await_reply(listener, m, chat_id, **kw)


async def test_await_reply_waits_on_the_listener_in_the_chat_of_the_message() -> None:
    c, listener = make_client(), _RecordingListener()

    result = await _await_reply(
        c, listener, make_message(chat_id=-1001), "@x", listen_user_id=7, timeout=3
    )

    assert result is listener.result
    assert listener.calls == [
        {
            "chat_id": -1001,
            "user_id": 7,
            "message_id": None,
            "meta": {"message_id": 5},
            "timeout": 3,
        }
    ]


@pytest.mark.parametrize(
    ("meta", "expected"),
    [
        ({"step": 1}, {"step": 1, "message_id": 5}),
        ({"message_id": 99}, {"message_id": 99}),
    ],
)
async def test_await_reply_copies_a_dict_meta_and_adds_the_message_id(
    meta: dict[str, int], expected: dict[str, int]
) -> None:
    c, listener = make_client(), _RecordingListener()
    original = dict(meta)

    await _await_reply(c, listener, make_message(), meta=meta)

    assert listener.calls[0]["meta"] == expected
    assert meta == original


async def test_await_reply_passes_a_non_dict_meta_through_unchanged() -> None:
    c, listener = make_client(), _RecordingListener()
    meta = ["a", 1]

    await _await_reply(c, listener, make_message(), meta=meta)

    assert listener.calls[0]["meta"] is meta


async def test_await_reply_resolves_a_callable_listen_message_id() -> None:
    c, listener = make_client(), _RecordingListener()
    sent = make_message()
    seen = []

    await _await_reply(c, listener, sent, listen_message_id=lambda m: seen.append(m) or 42)

    assert seen == [sent]
    assert listener.calls[0]["message_id"] == 42


async def test_await_reply_falls_back_to_chat_id_and_resolves_a_str() -> None:
    c, listener = make_client(), _RecordingListener()

    async def fake_resolve_peer(peer_id: str) -> PeerUser:
        return PeerUser(user_id=42)

    c.resolve_peer = fake_resolve_peer

    await _await_reply(c, listener, SimpleNamespace(id=5, chat=None))
    await _await_reply(c, listener, SimpleNamespace(id=5, chat=None), "@someone")

    assert [call["chat_id"] for call in listener.calls] == [100, 42]


async def test_await_reply_tries_call_then_scoped_client_handlers_and_re_raises() -> None:
    c = make_client()
    calls = []
    c.register_ask_error_handler(ExcA, lambda exc, m: calls.append("message"))
    c.register_ask_error_handler(
        ExcA, lambda exc, m: calls.append("callback_query"), update_type=CallbackQuery
    )
    m = SimpleNamespace(id=5, chat=None)

    with pytest.raises(ExcA):
        await _await_reply(
            c, _RaisingListener(), m, error_handlers={ExcA: lambda exc, m: calls.append("call")}
        )
    with pytest.raises(ExcA):
        await _await_reply(c, _RaisingListener(), m, update_type=CallbackQuery)

    assert calls == ["call", "callback_query"]


def test_client_async_methods_carry_pyrograms_sync_wrapper() -> None:
    for name in (
        "ask",
        "ask_rich",
        "unregister_listener",
        "unregister_coordinated",
    ):
        method = getattr(pyroflow.Client, name)
        assert inspect.iscoroutinefunction(method.__wrapped__), name


def test_client_init_runs_pyrograms_own_init() -> None:
    c = make_client()
    assert c.name == "probe"
    assert c.api_id == 1


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


def test_module_all_lists_the_public_names() -> None:
    assert client_module.__all__ == ("Client", "BotCommandsMixin", "mark_bot_commands")
    assert client_module.mark_bot_commands is bot_commands_module.mark_bot_commands


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
