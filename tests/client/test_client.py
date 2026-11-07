"""Tests for `pyroflow.client.client`: the patched `Client` (listener accessors,
register/unregister forwarders, the `ask_*` methods)."""

from __future__ import annotations as _annotations

import asyncio
import inspect
from datetime import datetime
from unittest.mock import AsyncMock

import pyroflow
import pytest

from pyrogram import filters as pyro_filters
from pyrogram.types import (
    BotCommand,
    InlineKeyboardMarkup,
    ReplyKeyboardRemove,
)

import pyroflow.client.client as client_module
from pyroflow.enums import DuplicatePolicy, WorkersPolicy
from pyroflow.errors import ListenerAlreadyExists
from pyroflow.models import CallbackQueryKey, ListenerContext, MessageKey
from pyroflow.types import CallbackQuery, Message
from pyroflow.update_listener import UpdateListener

from ..conftest import CALLBACK_MARKUP, make_callback_query, make_message


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


@pytest.fixture(autouse=True)
def _waits_reach_the_fake_listener(monkeypatch: pytest.MonkeyPatch) -> None:
    # `ask_*` call `UpdateListener.listen` itself, past any override; send a fake's wait to the fake.
    real = UpdateListener.listen

    def listen(self: object, key: object, **kw: object) -> object:
        if isinstance(self, UpdateListener):
            return real(self, key, **kw)  # ty: ignore[invalid-argument-type]
        return self.listen(key, **kw)  # ty: ignore[unresolved-attribute]

    monkeypatch.setattr(UpdateListener, "listen", listen)


class _RecordingListener:
    """Stands in for a registered UpdateListener: records its wait, returns a sentinel."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.result = object()

    async def listen(self, key: object, **kw: object) -> object:
        self.calls.append({"key": key, **kw})
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
    sent: Message | None = None, update_type: type[Message | CallbackQuery] = Message
) -> tuple[pyroflow.Client, _RecordingListener, _Recorder, _Recorder]:
    c = make_client().setup_pyroflow(ask_context_message=True)
    listener = _RecordingListener()
    c.dispatcher.listeners[update_type] = listener
    if sent is None:
        sent = make_message(chat_id=100, message_id=5, reply_markup=CALLBACK_MARKUP)
    send, edit = _Recorder(sent), _Recorder(sent)
    c.send_message = send
    c.edit_message_text = edit
    c.send_rich_message = _Recorder(sent)
    return c, listener, send, edit


# One row per `ask_*` method: its name, the Pyrogram method that sends, the
# argument that carries the content, the update type it waits for, and its key.
ASK_METHODS = [
    pytest.param("ask", "send_message", "text", Message, MessageKey, id="message"),
    pytest.param(
        "ask_rich",
        "send_rich_message",
        "rich_message",
        Message,
        MessageKey,
        id="message_rich",
    ),
    pytest.param(
        "ask_callback_query",
        "send_message",
        "text",
        CallbackQuery,
        CallbackQueryKey,
        id="callback_query",
    ),
    pytest.param(
        "ask_callback_query_rich",
        "send_rich_message",
        "rich_message",
        CallbackQuery,
        CallbackQueryKey,
        id="callback_query_rich",
    ),
]
ASK_ARGS = "method, sender, content_arg, update_type, key_type"


# --- get_listener / listen_message / listen_callback_query -------------------


def test_get_listener_returns_the_listener_of_the_update_type() -> None:
    c = make_client()
    listener = object()
    c.dispatcher.listeners[Message] = listener
    assert c.get_listener(Message) is listener


def test_get_listener_returns_none_when_unregistered() -> None:
    c = make_client()
    c.dispatcher.listeners[Message] = object()
    assert c.get_listener(CallbackQuery) is None


async def test_listen_message_waits_on_a_message_key_of_the_fields() -> None:
    c = make_client()
    listener = _RecordingListener()
    c.dispatcher.listeners[Message] = listener

    result = await c.listen_message(1, 2, 3, 4, timeout=5)

    assert result is listener.result
    assert listener.calls == [{"key": MessageKey(1, 2, 3, 4), "timeout": 5}]


async def test_listen_callback_query_waits_on_a_callback_query_key_of_the_fields() -> None:
    c = make_client()
    listener = _RecordingListener()
    c.dispatcher.listeners[CallbackQuery] = listener

    result = await c.listen_callback_query(user_id=2, inline_message_id="im", strict=True)

    assert result is listener.result
    assert listener.calls == [
        {"key": CallbackQueryKey(user_id=2, inline_message_id="im"), "strict": True}
    ]


@pytest.mark.parametrize(
    ("method", "update_type"),
    [("listen_message", "Message"), ("listen_callback_query", "CallbackQuery")],
)
async def test_listen_raises_without_a_listener(method: str, update_type: str) -> None:
    with pytest.raises(RuntimeError, match=f"No listener registered for {update_type}"):
        await getattr(make_client(), method)()


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


# --- the ask_* methods --------------------------------------------------------


@pytest.mark.parametrize(ASK_ARGS, ASK_METHODS)
async def test_ask_without_a_listener_raises_runtime_error_and_sends_nothing(
    method: str, sender: str, content_arg: str, update_type: type, key_type: type
) -> None:
    c, _, _, _ = _ask_client()
    c.dispatcher.listeners.clear()

    with pytest.raises(RuntimeError, match=f"No listener registered for {update_type.__name__}"):
        await getattr(c, method)(100, "hi")

    assert getattr(c, sender).calls == []


@pytest.mark.parametrize(ASK_ARGS, ASK_METHODS)
async def test_ask_sends_a_new_message_and_waits_on_the_key_of_the_sent_one(
    method: str, sender: str, content_arg: str, update_type: type, key_type: type
) -> None:
    c, listener, _, edit = _ask_client(update_type=update_type)
    content = object()

    result = await getattr(c, method)(
        100, content, disable_notification=True, extra="kw", listen_timeout=3
    )

    sent = getattr(c, sender).result
    assert result is listener.result
    assert edit.calls == []
    assert getattr(c, sender).calls == [
        {"chat_id": 100, content_arg: content, "disable_notification": True, "extra": "kw"}
    ]
    assert listener.calls == [
        {
            "key": key_type.from_sent(sent),
            "context": ListenerContext(message=sent),
            "filters": None,
            "strict": False,
            "timeout": 3,
        }
    ]


@pytest.mark.parametrize(ASK_ARGS, ASK_METHODS)
async def test_ask_with_message_id_edits_instead_of_sending(
    method: str, sender: str, content_arg: str, update_type: type, key_type: type
) -> None:
    c, listener, _, edit = _ask_client(update_type=update_type)
    content = object()
    markup = InlineKeyboardMarkup([])

    await getattr(c, method)(100, content, 5, reply_markup=markup, extra="kw")

    assert getattr(c, sender).calls == []
    assert edit.calls == [
        {
            "chat_id": 100,
            "message_id": 5,
            content_arg: content,
            "reply_markup": markup,
            "extra": "kw",
        }
    ]
    assert listener.calls[0]["key"] == key_type.from_sent(edit.result)


@pytest.mark.parametrize(ASK_ARGS, ASK_METHODS[:2])
async def test_ask_message_keys_the_answer_by_the_chat_and_topics_of_the_sent_message(
    method: str, sender: str, content_arg: str, update_type: type, key_type: type
) -> None:
    sent = make_message(chat_id=-1001, message_thread_id=3, direct_messages_topic_id=4)
    c, listener, _, _ = _ask_client(sent)

    await getattr(c, method)("@somechat", "hi")

    assert listener.calls[0]["key"] == MessageKey(-1001, None, 3, 4)


@pytest.mark.parametrize(ASK_ARGS, ASK_METHODS[2:])
async def test_ask_callback_query_keys_the_press_by_the_sent_message(
    method: str, sender: str, content_arg: str, update_type: type, key_type: type
) -> None:
    sent = make_message(chat_id=-1001, message_id=9, reply_markup=CALLBACK_MARKUP)
    c, listener, _, _ = _ask_client(sent, CallbackQuery)

    await getattr(c, method)("@somechat", "hi")

    assert listener.calls[0]["key"] == CallbackQueryKey(-1001, None, 9)


@pytest.mark.parametrize(ASK_ARGS, ASK_METHODS)
async def test_ask_waits_on_listen_user_id(
    method: str, sender: str, content_arg: str, update_type: type, key_type: type
) -> None:
    c, listener, _, _ = _ask_client(update_type=update_type)

    await getattr(c, method)(100, "hi", listen_user_id=7)

    assert listener.calls[0]["key"] == key_type.from_sent(getattr(c, sender).result, 7)
    assert listener.calls[0]["key"].user_id == 7


@pytest.mark.parametrize(ASK_ARGS, ASK_METHODS)
async def test_ask_records_the_sent_message_in_a_copy_of_the_context(
    method: str, sender: str, content_arg: str, update_type: type, key_type: type
) -> None:
    c, listener, _, _ = _ask_client(update_type=update_type)
    context = ListenerContext(step=1)

    await getattr(c, method)(100, "hi", listen_context=context)

    sent = getattr(c, sender).result
    assert listener.calls[0]["context"] == ListenerContext(step=1, message=sent)
    assert context == ListenerContext(step=1)


@pytest.mark.parametrize(ASK_ARGS, ASK_METHODS)
async def test_ask_passes_a_context_holding_a_message_as_it_is(
    method: str, sender: str, content_arg: str, update_type: type, key_type: type
) -> None:
    c, listener, _, _ = _ask_client(update_type=update_type)
    context = ListenerContext(message="mine", step=1)

    await getattr(c, method)(100, "hi", listen_context=context)

    assert listener.calls[0]["context"] is context


@pytest.mark.parametrize(ASK_ARGS, ASK_METHODS)
@pytest.mark.parametrize("context", [None, ListenerContext(step=1)])
async def test_ask_without_ask_context_message_passes_the_context_as_it_is(
    method: str,
    sender: str,
    content_arg: str,
    update_type: type,
    key_type: type,
    context: ListenerContext | None,
) -> None:
    c, listener, _, _ = _ask_client(update_type=update_type)
    c.ask_context_message = False

    await getattr(c, method)(100, "hi", listen_context=context)

    assert listener.calls[0]["context"] is context


@pytest.mark.parametrize(ASK_ARGS, ASK_METHODS)
async def test_ask_passes_filters_and_strict_to_the_listener(
    method: str, sender: str, content_arg: str, update_type: type, key_type: type
) -> None:
    c, listener, _, _ = _ask_client(update_type=update_type)
    text_only = pyro_filters.text

    await getattr(c, method)(100, "hi", listen_filters=text_only, listen_strict=True)

    assert listener.calls[0]["filters"] is text_only
    assert listener.calls[0]["strict"] is True


@pytest.mark.parametrize(ASK_ARGS, ASK_METHODS)
async def test_ask_raises_the_listener_error_unchanged(
    method: str, sender: str, content_arg: str, update_type: type, key_type: type
) -> None:
    error = ExcA("boom")

    class _RaisingListener:
        async def listen(self, key: object, **kw: object) -> None:
            raise error

    c, _, _, _ = _ask_client()
    c.dispatcher.listeners[update_type] = _RaisingListener()

    with pytest.raises(ExcA) as exc:
        await getattr(c, method)(100, "hi")
    assert exc.value is error


async def test_ask_message_edit_mode_leaves_the_arguments_to_pyrogram() -> None:
    c, _, _, edit = _ask_client()
    markup = ReplyKeyboardRemove()

    await c.ask(100, "hi", 5, reply_markup=markup, disable_notification=True)

    assert edit.calls[0]["reply_markup"] is markup
    assert edit.calls[0]["disable_notification"] is True


async def test_ask_message_send_mode_accepts_a_non_inline_reply_markup() -> None:
    c, _, send, _ = _ask_client()
    markup = ReplyKeyboardRemove()

    await c.ask(100, "hi", reply_markup=markup)

    assert send.calls[0]["reply_markup"] is markup


@pytest.mark.parametrize(ASK_ARGS, [p for p in ASK_METHODS if "rich" in p.id])
async def test_rich_asks_edit_passes_the_edit_arguments(
    method: str, sender: str, content_arg: str, update_type: type, key_type: type
) -> None:
    c, _, _, edit = _ask_client(update_type=update_type)
    when = datetime(2026, 1, 1)

    await getattr(c, method)(100, object(), 5, schedule_date=when, business_connection_id="bc")

    call = edit.calls[0]
    assert call["schedule_date"] is when
    assert call["business_connection_id"] == "bc"
    assert "text" not in call


@pytest.mark.parametrize(ASK_ARGS, [p for p in ASK_METHODS if "rich" in p.id])
async def test_rich_asks_forward_only_arguments_kurigram_accepts(
    method: str, sender: str, content_arg: str, update_type: type, key_type: type
) -> None:
    # The recorders accept anything; bind what was forwarded to the real signatures.
    c, _, _, edit = _ask_client(update_type=update_type)
    await getattr(c, method)(100, object())
    await getattr(c, method)(100, object(), 5)

    inspect.signature(pyroflow.Client.send_rich_message).bind(c, **c.send_rich_message.calls[0])
    inspect.signature(pyroflow.Client.edit_message_text).bind(c, **edit.calls[0])


def test_client_async_methods_carry_pyrograms_sync_wrapper() -> None:
    for name in (
        "ask",
        "ask_rich",
        "ask_callback_query",
        "ask_callback_query_rich",
        "unregister_listener",
    ):
        method = getattr(pyroflow.Client, name)
        assert inspect.iscoroutinefunction(method.__wrapped__), name


def test_client_init_runs_pyrograms_own_init() -> None:
    c = make_client()
    assert c.name == "probe"
    assert c.api_id == 1


# --- the wait, through a real listener --------------------------------------------


def _waiting_client(
    listener: pyroflow.MessageListener | pyroflow.CallbackQueryListener | None = None,
) -> tuple[pyroflow.Client, pyroflow.MessageListener | pyroflow.CallbackQueryListener]:
    c = make_client()
    listener = pyroflow.MessageListener() if listener is None else listener
    c.register_listener(listener)
    sent = make_message(chat_id=100, message_id=5, reply_markup=CALLBACK_MARKUP)
    c.send_message = AsyncMock(return_value=sent)
    c.edit_message_text = AsyncMock(return_value=sent)
    return c, listener


async def _ask_task(c: pyroflow.Client, method: str = "ask", **kw: object) -> asyncio.Future:
    task = asyncio.ensure_future(getattr(c, method)(100, "hi", **kw))
    await asyncio.sleep(0)
    return task


async def test_ask_message_takes_the_next_message_in_the_chat_from_any_user() -> None:
    c, listener = _waiting_client()
    task = await _ask_task(c)
    reply = make_message(user_id=8, message_id=6)

    assert await listener.resolve(make_message(chat_id=200, message_id=6)) is False
    assert await listener.resolve(reply) is True
    assert await task is reply


async def test_ask_message_narrows_the_user_with_listen_filters() -> None:
    c, listener = _waiting_client()
    task = await _ask_task(c, listen_filters=pyro_filters.user(7))
    reply = make_message(message_id=7)

    assert await listener.resolve(make_message(user_id=8, message_id=6)) is False
    assert await listener.resolve(reply) is True
    assert await task is reply


async def test_ask_message_editing_one_message_takes_the_next_reply_each_time() -> None:
    c, listener = _waiting_client()

    for message_id in (6, 7):
        task = await _ask_task(c, message_id=5)
        reply = make_message(message_id=message_id)

        assert await listener.resolve(reply) is True
        assert await task is reply


async def test_ask_message_refuses_a_second_question_in_the_chat_under_duplicate_reject() -> None:
    c, listener = _waiting_client(pyroflow.MessageListener(duplicate_policy=DuplicatePolicy.REJECT))
    c.send_message = AsyncMock(side_effect=[make_message(message_id=n) for n in (5, 6)])
    task = await _ask_task(c)

    with pytest.raises(ListenerAlreadyExists):
        await asyncio.wait_for(c.ask(100, "again"), 1)

    await listener.stop()
    await asyncio.gather(task, return_exceptions=True)


async def test_ask_callback_query_takes_a_press_on_the_sent_message_only() -> None:
    c, listener = _waiting_client(pyroflow.CallbackQueryListener())
    task = await _ask_task(c, "ask_callback_query")
    press = make_callback_query(message_id=5)

    assert await listener.resolve(make_callback_query(message_id=4)) is False
    assert await listener.resolve(press) is True
    assert await task is press
