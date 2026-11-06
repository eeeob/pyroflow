"""Tests for `pyroflow.client.client`: the patched `Client` (listener accessors,
register/unregister forwarders, `ask`)."""

from __future__ import annotations as _annotations

import asyncio
import inspect
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pyroflow
import pytest

from pyrogram import filters as pyro_filters
from pyrogram.raw.types import PeerUser
from pyrogram.types import (
    BotCommand,
    InlineKeyboardMarkup,
    ReplyKeyboardRemove,
)

import pyroflow.client.client as client_module
from pyroflow.enums import DuplicatePolicy, EphemeralUpdates, ListenMessageId, WorkersPolicy
from pyroflow.errors import ListenerAlreadyExists
from pyroflow.models import ListenerContext
from pyroflow.types import CallbackQuery, Message

from ..conftest import make_message


class ExcA(Exception):
    pass


# --- Client ---------------------------------------------------------------------


def make_client() -> pyroflow.Client:
    return pyroflow.Client("probe", api_id=1, api_hash="x", in_memory=True)


def test_module_exports() -> None:
    assert client_module.__all__ == ("Client",)


def test_setup_pyroflow_sets_the_values_and_returns_the_client() -> None:
    c = make_client()
    policy = WorkersPolicy.REJECT

    assert c.setup_pyroflow(workers_policy=policy, ask_context_message=True) is c
    assert c.dispatcher.workers_policy is policy
    assert c.ask_context_message is True


def test_setup_pyroflow_resets_what_it_leaves_out() -> None:
    c = make_client()
    c.setup_pyroflow(workers_policy=WorkersPolicy.REJECT, ask_context_message=True)

    c.setup_pyroflow()

    assert c.dispatcher.workers_policy is None
    assert c.ask_context_message is False


def test_ask_context_message_defaults_to_false() -> None:
    assert make_client().ask_context_message is False


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
    c = make_client().setup_pyroflow(ask_context_message=True)
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
    """A listener stand-in that records being stopped."""

    __update_type__ = Message

    def __init__(self) -> None:
        self.stopped = False

    async def stop(self) -> None:
        self.stopped = True


async def test_register_and_unregister_listener_forward_to_the_dispatcher() -> None:
    c = make_client()
    item = _Stoppable()

    assert c.register_listener(item) is None
    assert c.dispatcher.listeners == {Message: item}

    await c.unregister_listener(Message)

    assert c.dispatcher.listeners == {}
    assert item.stopped is True


# --- ask() ------------------------------------------------------------------


async def test_ask_without_a_listener_raises_runtime_error_naming_the_type() -> None:
    c = make_client()
    with pytest.raises(RuntimeError, match="No listener registered for CallbackQuery"):
        await c.ask(100, "hi", listen_update_type=CallbackQuery)


async def test_ask_sends_a_new_message_and_returns_the_listeners_result() -> None:
    c, listener, send, edit = _ask_client()

    result = await c.ask(100, "hi", disable_notification=True, extra="kw", listen_timeout=3)

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
            "context": ListenerContext(message=send.result),
            "filters": None,
            "strict": False,
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


async def test_ask_edit_mode_leaves_the_arguments_to_pyrogram() -> None:
    c, _, _, edit = _ask_client()
    markup = ReplyKeyboardRemove()

    await c.ask(100, "hi", 5, reply_markup=markup, disable_notification=True)

    assert edit.calls[0]["reply_markup"] is markup
    assert edit.calls[0]["disable_notification"] is True


async def test_ask_send_mode_accepts_a_non_inline_reply_markup() -> None:
    c, _, send, _ = _ask_client()
    markup = ReplyKeyboardRemove()

    await c.ask(100, "hi", reply_markup=markup)

    assert send.calls[0]["reply_markup"] is markup


async def test_ask_records_the_sent_message_in_a_copy_of_the_context() -> None:
    c, listener, send, _ = _ask_client()
    context = ListenerContext(step=1)

    await c.ask(100, "hi", listen_context=context)

    assert listener.calls[0]["context"] == ListenerContext(step=1, message=send.result)
    assert context == ListenerContext(step=1)


async def test_ask_passes_an_int_listen_message_id_and_user_id_through() -> None:
    c, listener, _, _ = _ask_client()

    await c.ask(100, "hi", listen_message_id=42, listen_user_id=7)

    assert listener.calls[0]["message_id"] == 42
    assert listener.calls[0]["user_id"] == 7


async def test_ask_listens_on_the_sent_message_for_listen_message_id_sent() -> None:
    c, listener, _, _ = _ask_client(make_message(chat_id=100, message_id=5))

    await c.ask(100, "hi", listen_message_id=ListenMessageId.SENT)

    assert listener.calls[0]["message_id"] == 5


async def test_ask_listens_on_the_next_message_for_listen_message_id_next() -> None:
    c, listener, _, _ = _ask_client(make_message(chat_id=100, message_id=5))

    await c.ask(100, "hi", listen_message_id=ListenMessageId.NEXT)

    assert listener.calls[0]["message_id"] == 6


async def test_ask_defaults_to_no_message_for_a_callback_query() -> None:
    c, listener, _, _ = _ask_client(update_type=CallbackQuery)

    await c.ask(100, "hi", listen_update_type=CallbackQuery)

    assert listener.calls[0]["message_id"] is None


async def test_ask_passes_an_explicit_none_listen_message_id_through() -> None:
    c, listener, _, _ = _ask_client()

    await c.ask(100, "hi", listen_message_id=None)

    assert listener.calls[0]["message_id"] is None


async def test_ask_listens_in_the_chat_of_the_sent_message() -> None:
    c, listener, _, _ = _ask_client(make_message(chat_id=-1001))

    await c.ask("@somechat", "hi")

    assert listener.calls[0]["chat_id"] == -1001


async def test_ask_falls_back_to_the_given_chat_id_without_a_chat() -> None:
    c, listener, _, _ = _ask_client(SimpleNamespace(id=5, chat=None, ephemeral_message_id=None))

    await c.ask(100, "hi")

    assert listener.calls[0]["chat_id"] == 100


async def test_ask_falls_back_to_the_given_chat_id_when_the_chat_has_no_id() -> None:
    c, listener, _, _ = _ask_client(
        SimpleNamespace(id=5, chat=SimpleNamespace(id=None), ephemeral_message_id=None)
    )

    await c.ask(100, "hi")

    assert listener.calls[0]["chat_id"] == 100


async def test_ask_resolves_a_str_chat_id_to_a_peer_id() -> None:
    c, listener, _, _ = _ask_client(SimpleNamespace(id=5, chat=None, ephemeral_message_id=None))
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

    assert await c.ask(100, "hi", listen_update_type=CallbackQuery) is listener.result


async def test_ask_passes_a_context_holding_a_message_as_it_is() -> None:
    c, listener, _, _ = _ask_client()
    context = ListenerContext(message="mine", step=1)

    await c.ask(100, "hi", listen_context=context)

    assert listener.calls[0]["context"] is context


@pytest.mark.parametrize("context", [None, ListenerContext(step=1)])
async def test_ask_without_ask_context_message_passes_the_context_as_it_is(
    context: ListenerContext | None,
) -> None:
    c, listener, _, _ = _ask_client()
    c.ask_context_message = False

    await c.ask(100, "hi", listen_context=context)

    assert listener.calls[0]["context"] is context


@pytest.mark.parametrize("context", [None, ListenerContext(step=1)])
async def test_ask_rich_without_ask_context_message_passes_the_context_as_it_is(
    context: ListenerContext | None,
) -> None:
    c, listener, _, _ = _ask_client()
    c.send_rich_message = AsyncMock(return_value=make_message(chat_id=100, message_id=5))
    c.ask_context_message = False

    await c.ask_rich(100, object(), listen_context=context)

    assert listener.calls[0]["context"] is context


async def test_ask_rich_passes_a_context_holding_a_message_as_it_is() -> None:
    c, listener, _, _ = _ask_client()
    c.send_rich_message = AsyncMock(return_value=make_message(chat_id=100, message_id=5))
    context = ListenerContext(message="mine")

    await c.ask_rich(100, object(), listen_context=context)

    assert listener.calls[0]["context"] is context


async def test_ask_passes_filters_and_strict_to_the_listener() -> None:
    c, listener, _, _ = _ask_client()
    text_only = pyro_filters.text

    await c.ask(100, "hi", listen_filters=text_only, listen_strict=True)

    assert listener.calls[0]["filters"] is text_only
    assert listener.calls[0]["strict"] is True


async def test_ask_raises_the_listener_error_unchanged() -> None:
    error = ExcA("boom")

    class _RaisingListener:
        async def __call__(self, **kw: object) -> None:
            raise error

    c, _, _, _ = _ask_client()
    c.dispatcher.listeners[Message] = _RaisingListener()

    with pytest.raises(ExcA) as exc:
        await c.ask(100, "hi")
    assert exc.value is error


# --- ask_rich() -------------------------------------------------------------


async def test_ask_rich_without_a_listener_raises_runtime_error_naming_the_type() -> None:
    c = make_client()
    with pytest.raises(RuntimeError, match="No listener registered for CallbackQuery"):
        await c.ask_rich(100, object(), listen_update_type=CallbackQuery)


async def test_ask_rich_sends_with_send_rich_message() -> None:
    c, listener, send, edit = _ask_client()
    rich = object()
    markup = ReplyKeyboardRemove()

    result = await c.ask_rich(
        100,
        rich,
        disable_notification=True,
        reply_markup=markup,
        extra="kw",
        listen_timeout=3,
    )

    assert result is listener.result
    assert send.calls == edit.calls == []
    call = c.send_rich_message.calls[0]
    assert (call["chat_id"], call["rich_message"]) == (100, rich)
    assert call["disable_notification"] is True
    assert call["reply_markup"] is markup
    assert call["extra"] == "kw"
    assert listener.calls == [
        {
            "chat_id": 100,
            "user_id": None,
            "message_id": None,
            "context": ListenerContext(message=c.send_rich_message.result),
            "filters": None,
            "strict": False,
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


async def test_ask_rich_edit_mode_leaves_the_arguments_to_pyrogram() -> None:
    c, _, _, edit = _ask_client()
    markup = ReplyKeyboardRemove()

    await c.ask_rich(100, object(), 5, reply_markup=markup)

    assert edit.calls[0]["reply_markup"] is markup


async def test_ask_rich_listens_on_the_sent_message_for_listen_message_id_sent() -> None:
    c, listener, _, _ = _ask_client(make_message(chat_id=100, message_id=5))

    await c.ask_rich(100, object(), listen_message_id=ListenMessageId.SENT)

    assert listener.calls[0]["message_id"] == 5


async def test_ask_rich_waits_on_the_listener_of_the_given_update_type() -> None:
    c, listener, _, _ = _ask_client(update_type=CallbackQuery)

    assert await c.ask_rich(100, object(), listen_update_type=CallbackQuery) is listener.result


def test_client_async_methods_carry_pyrograms_sync_wrapper() -> None:
    for name in (
        "ask",
        "ask_rich",
        "unregister_listener",
    ):
        method = getattr(pyroflow.Client, name)
        assert inspect.iscoroutinefunction(method.__wrapped__), name


def test_client_init_runs_pyrograms_own_init() -> None:
    c = make_client()
    assert c.name == "probe"
    assert c.api_id == 1


# --- ephemeral messages ---------------------------------------------------------


def _ephemeral_sent() -> Message:
    return make_message(chat_id=100, message_id=0, ephemeral_message_id=4)


@pytest.mark.parametrize("method", ["ask", "ask_rich"])
@pytest.mark.parametrize("update_type", [Message, CallbackQuery])
async def test_ask_defaults_to_no_message_after_an_ephemeral_message(
    method: str, update_type: type[Message | CallbackQuery]
) -> None:
    c, listener, _, _ = _ask_client(_ephemeral_sent(), update_type)

    await getattr(c, method)(100, "hi", listen_user_id=7, listen_update_type=update_type)

    assert listener.calls[0]["message_id"] is None


@pytest.mark.parametrize("method", ["ask", "ask_rich"])
@pytest.mark.parametrize("given", [ListenMessageId.SENT, ListenMessageId.NEXT])
async def test_ask_refuses_sent_and_next_after_an_ephemeral_message(
    method: str, given: ListenMessageId
) -> None:
    c, listener, _, _ = _ask_client(_ephemeral_sent())

    with pytest.raises(ValueError, match="no id to wait on"):
        await getattr(c, method)(100, "hi", listen_user_id=7, listen_message_id=given)

    assert listener.calls == []


@pytest.mark.parametrize(
    ("method", "sender"), [("ask", "send_message"), ("ask_rich", "send_rich_message")]
)
@pytest.mark.parametrize("given", [ListenMessageId.SENT, ListenMessageId.NEXT])
async def test_ask_refuses_sent_and_next_on_ephemeral_parameters_before_sending(
    method: str, sender: str, given: ListenMessageId
) -> None:
    c, _, _, _ = _ask_client(_ephemeral_sent())

    with pytest.raises(ValueError, match="no id to wait on"):
        await getattr(c, method)(
            100,
            "hi",
            listen_user_id=7,
            listen_message_id=given,
            ephemeral_message_parameters=object(),
        )

    assert getattr(c, sender).calls == []


@pytest.mark.parametrize("method", ["ask", "ask_rich"])
@pytest.mark.parametrize("given", [None, 3, EphemeralUpdates.ANY])
async def test_ask_keeps_an_explicit_id_after_an_ephemeral_message(
    method: str, given: int | EphemeralUpdates | None
) -> None:
    c, listener, _, _ = _ask_client(_ephemeral_sent())

    await getattr(c, method)(100, "hi", listen_user_id=7, listen_message_id=given)

    assert listener.calls[0]["message_id"] == given


@pytest.mark.parametrize(
    ("method", "sender"), [("ask", "send_message"), ("ask_rich", "send_rich_message")]
)
@pytest.mark.parametrize(
    "kw",
    [
        {"ephemeral_message_parameters": object()},
        {"listen_message_id": EphemeralUpdates.ANY},
    ],
    ids=["parameters", "message_id"],
)
async def test_ask_refuses_an_ephemeral_wait_without_a_user_before_sending(
    method: str, sender: str, kw: dict[str, object]
) -> None:
    c, _, _, _ = _ask_client(_ephemeral_sent())

    with pytest.raises(ValueError, match="needs listen_user_id"):
        await getattr(c, method)(100, "hi", **kw)

    assert getattr(c, sender).calls == []


# --- the default wait, through a real listener -----------------------------------


def _waiting_client(**listener_kw: object) -> tuple[pyroflow.Client, pyroflow.MessageListener]:
    c = make_client()
    listener = pyroflow.MessageListener(**listener_kw)
    c.register_listener(listener)
    sent = make_message(chat_id=100, message_id=5)
    c.send_message = AsyncMock(return_value=sent)
    c.edit_message_text = AsyncMock(return_value=sent)
    return c, listener


async def _ask_task(c: pyroflow.Client, **kw: object) -> asyncio.Future:
    task = asyncio.ensure_future(c.ask(100, "hi", listen_user_id=7, **kw))
    await asyncio.sleep(0)
    return task


async def test_ask_takes_the_reply_after_another_members_message() -> None:
    c, listener = _waiting_client()
    task = await _ask_task(c)
    reply = make_message(message_id=7)

    assert await listener.resolve(make_message(user_id=8, message_id=6)) is False
    assert await listener.resolve(reply) is True
    assert await task is reply


async def test_ask_editing_one_message_takes_the_next_reply_each_time() -> None:
    c, listener = _waiting_client()

    for message_id in (6, 7):
        task = await _ask_task(c, message_id=5)
        reply = make_message(message_id=message_id)

        assert await listener.resolve(reply) is True
        assert await task is reply


async def test_ask_refuses_a_second_question_to_the_user_under_duplicate_reject() -> None:
    c, listener = _waiting_client(duplicate_policy=DuplicatePolicy.REJECT)
    c.send_message = AsyncMock(side_effect=[make_message(message_id=n) for n in (5, 6)])
    task = await _ask_task(c)

    with pytest.raises(ListenerAlreadyExists):
        await asyncio.wait_for(c.ask(100, "again", listen_user_id=7), 1)

    await listener.stop()
    await asyncio.gather(task, return_exceptions=True)
