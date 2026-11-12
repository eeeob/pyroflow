"""Tests for `pyroflow.client.client`: the patched `Client` (listener accessors,
register/unregister forwarders, the `ask_*` methods)."""

from __future__ import annotations as _annotations

import asyncio
import inspect
from typing import Any
from unittest.mock import AsyncMock, Mock

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
from pyroflow.errors import (
    ListenerAlreadyExists,
    ListenerAttemptsExhausted,
    ListenerRejected,
    ListenerReplaced,
    ListenerTimeout,
)
from pyroflow.models import AskAgain, CallbackQueryKey, ListenerContext, MessageKey
from pyroflow.types import CallbackQuery, Message

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
    assert c.workers_policy is policy
    assert c.ask_context_message is True


def test_setup_pyroflow_resets_what_it_leaves_out() -> None:
    c = make_client()
    c.setup_pyroflow(workers_policy=WorkersPolicy.REJECT, ask_context_message=True)

    c.setup_pyroflow()

    assert c.workers_policy is None
    assert c.ask_context_message is False


def test_ask_context_message_defaults_to_false() -> None:
    assert make_client().ask_context_message is False


# --- shared fakes for the rest of the module ---------------------------------


def _cmd(name: str) -> BotCommand:
    return BotCommand(name, f"{name} description")


class _RecordingListener:
    """Stands in for a registered UpdateListener: records its wait, returns a sentinel."""

    def __init__(self, key_type: type = MessageKey) -> None:
        self.__key_type__ = key_type
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
    listener = _RecordingListener(MessageKey if update_type is Message else CallbackQueryKey)
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


def test_require_listener_returns_the_registered_listener() -> None:
    c = make_client()
    listener = object()
    c.dispatcher.listeners[Message] = listener

    assert c.require_listener(Message) is listener


def test_require_listener_raises_without_one() -> None:
    with pytest.raises(RuntimeError, match="No listener registered for CallbackQuery"):
        make_client().require_listener(CallbackQuery)


def test_context_with_message_leaves_the_context_when_off() -> None:
    c = make_client().setup_pyroflow(ask_context_message=False)
    context = ListenerContext()

    assert c.context_with_message(make_message(), context) is context
    assert c.context_with_message(make_message(), None) is None


def test_context_with_message_builds_a_context_for_none() -> None:
    c = make_client().setup_pyroflow(ask_context_message=True)
    sent = make_message()

    assert c.context_with_message(sent, None).message is sent


def test_context_with_message_copies_a_context_without_a_message() -> None:
    c = make_client().setup_pyroflow(ask_context_message=True)
    sent = make_message()
    context = ListenerContext(step=1)

    result = c.context_with_message(sent, context)

    assert result is not context
    assert result.message is sent
    assert result.step == 1
    assert context.message is None


def test_context_with_message_keeps_a_message_already_there() -> None:
    c = make_client().setup_pyroflow(ask_context_message=True)
    context = ListenerContext(message=make_message())

    assert c.context_with_message(make_message(), context) is context


@pytest.mark.parametrize(
    ("chat_id", "target"),
    [pytest.param(100, (100,), id="client"), pytest.param(None, (), id="message")],
)
async def test_ask_repeatedly_builds_each_call_of_ask(
    chat_id: int | None, target: tuple[int, ...]
) -> None:
    answers = [make_message(), make_message()]
    results = iter([AskAgain("next"), "done"])
    calls: list[tuple[tuple[object, ...], dict[str, Any]]] = []
    listen_kw = {
        "listen_user_id": 7,
        "listen_context": None,
        "listen_filters": None,
        "listen_strict": True,
        "listen_timeout": 3,
    }

    async def ask(*args: object, **kw: Any) -> Message:
        calls.append((args, kw))
        return answers[len(calls) - 1]

    result = await make_client().ask_repeatedly(
        ask,
        chat_id,
        "first",
        5,
        None,
        lambda *_: next(results),
        None,
        {"a": 1},
        listen_user_id=7,
        listen_strict=True,
        listen_timeout=3,
    )

    assert result == "done"
    assert calls == [
        ((*target, "first", 5), {**listen_kw, "a": 1}),
        ((*target, "next", None), listen_kw),
    ]


async def test_listen_passes_the_key_to_the_listener_of_its_update_type() -> None:
    c = make_client()
    messages, queries = _RecordingListener(MessageKey), _RecordingListener(CallbackQueryKey)
    c.dispatcher.listeners[Message] = messages
    c.dispatcher.listeners[CallbackQuery] = queries
    key = CallbackQueryKey(1, 2, 3)

    result = await c.listen(key, timeout=5)

    assert result is queries.result
    assert queries.calls == [{"key": key, "timeout": 5}]
    assert messages.calls == []


async def test_listen_without_a_listener_for_the_update_type_raises() -> None:
    c = make_client()

    with pytest.raises(RuntimeError, match="No listener registered for Message"):
        await c.listen(MessageKey(1))


async def test_listen_message_waits_on_a_key_of_the_listeners_key_type() -> None:
    c = make_client()
    listener = _RecordingListener(MessageKey)
    c.dispatcher.listeners[Message] = listener

    result = await c.listen_message(1, 2, 3, 4, timeout=5)

    assert result is listener.result
    assert listener.calls == [{"key": MessageKey(1, 2, 3, 4), "timeout": 5}]


async def test_listen_callback_query_waits_on_a_key_of_the_listeners_key_type() -> None:
    c = make_client()
    listener = _RecordingListener(CallbackQueryKey)
    c.dispatcher.listeners[CallbackQuery] = listener

    result = await c.listen_callback_query(user_id=2, inline_message_id="im", strict=True)

    assert result is listener.result
    assert listener.calls == [
        {"key": CallbackQueryKey(user_id=2, inline_message_id="im"), "strict": True}
    ]


async def test_listen_message_makes_the_key_with_the_key_class_of_the_listener() -> None:
    class OwnKey(MessageKey):
        pass

    c = make_client()
    listener = _RecordingListener(OwnKey)
    c.dispatcher.listeners[Message] = listener

    await c.listen_message(1)

    assert type(listener.calls[0]["key"]) is OwnKey


async def test_listen_message_reaches_the_override_of_a_listener_subclass() -> None:
    class OnlyChat100(pyroflow.MessageListener):
        async def listen(self, key: MessageKey, **kw: Any) -> Message:
            return await super().listen(MessageKey(100), **kw)

    c = make_client()
    listener = OnlyChat100()
    c.register_listener(listener)
    task = asyncio.ensure_future(c.listen_message(chat_id=7))
    await asyncio.sleep(0)
    reply = make_message(chat_id=100)

    assert await listener.resolve(reply) is True
    assert await task is reply


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
    client: object = None

    def __init__(self) -> None:
        self.stopped = False

    async def stop(self) -> None:
        self.stopped = True


async def test_register_and_unregister_listener_forward_to_the_dispatcher() -> None:
    c = make_client()
    item = _Stoppable()

    assert c.register_listener(item) is None
    assert c.dispatcher.listeners == {Message: item}
    assert item.client is c

    await c.unregister_listener(Message)

    assert c.dispatcher.listeners == {}
    assert item.stopped is True
    assert item.client is None


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
async def test_ask_keys_the_wait_with_the_key_type_of_the_listener(
    method: str, sender: str, content_arg: str, update_type: type, key_type: type
) -> None:
    class OwnKey(key_type):
        pass

    c, listener, _, _ = _ask_client(update_type=update_type)
    listener.__key_type__ = OwnKey

    await getattr(c, method)(100, "hi")

    assert type(listener.calls[0]["key"]) is OwnKey


@pytest.mark.parametrize(ASK_ARGS, ASK_METHODS)
async def test_ask_raises_the_listener_error_unchanged(
    method: str, sender: str, content_arg: str, update_type: type, key_type: type
) -> None:
    error = ExcA("boom")

    class _RaisingListener:
        __key_type__ = key_type

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

    await getattr(c, method)(100, object(), 5, reply_markup=CALLBACK_MARKUP)

    call = edit.calls[0]
    assert call["reply_markup"] is CALLBACK_MARKUP
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
        "ask_until",
        "ask_rich_until",
        "ask_callback_query_until",
        "ask_callback_query_rich_until",
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
        task = await _ask_task(c, edit_message_id=5)
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


async def test_ask_until_asks_again_through_a_real_listener_until_parse_accepts() -> None:
    c, listener = _waiting_client()
    task = await _ask_task(
        c, "ask_until", parse=lambda answer, _: answer if answer.text == "ok" else AskAgain("again")
    )
    answer = make_message(message_id=7, text="ok")

    assert await listener.resolve(make_message(message_id=6, text="no")) is True
    while c.send_message.await_count < 2:
        await asyncio.sleep(0)
    assert await listener.resolve(answer) is True
    assert await task is answer
    assert c.send_message.await_count == 2


async def test_ask_until_leaves_what_fails_listen_filters_to_the_handlers() -> None:
    c, listener = _waiting_client()
    checked: list[object] = []
    task = await _ask_task(
        c, "ask_until", parse=lambda a, _: checked.append(a) or a, listen_filters=pyro_filters.text
    )
    answer = make_message(message_id=7, text="ok")

    assert await listener.resolve(make_message(message_id=6)) is False
    assert await listener.resolve(answer) is True
    assert await task is answer
    assert checked == [answer]
    assert c.send_message.await_count == 1


async def test_ask_callback_query_until_asks_again_through_a_real_listener() -> None:
    c, listener = _waiting_client(pyroflow.CallbackQueryListener())
    task = await _ask_task(
        c,
        "ask_callback_query_until",
        parse=lambda press, _: press if press.data == "ok" else AskAgain("again"),
    )
    press = make_callback_query(message_id=5, data="ok")

    assert await listener.resolve(make_callback_query(message_id=5, data="no")) is True
    while c.send_message.await_count < 2:
        await asyncio.sleep(0)
    assert await listener.resolve(press) is True
    assert await task is press
    assert c.send_message.await_count == 2


# --- the ask_*_until() methods -------------------------------------------------

RICH = object()
"""Stands in for an `InputRichMessage`."""
RICH_AGAIN = object()
"""Stands in for another `InputRichMessage`."""

UNTIL_METHODS = [
    pytest.param("ask_until", "ask", "hi", "again", make_message, id="message"),
    pytest.param("ask_rich_until", "ask_rich", RICH, RICH_AGAIN, make_message, id="message_rich"),
    pytest.param(
        "ask_callback_query_until",
        "ask_callback_query",
        "hi",
        "again",
        make_callback_query,
        id="callback_query",
    ),
    pytest.param(
        "ask_callback_query_rich_until",
        "ask_callback_query_rich",
        RICH,
        RICH_AGAIN,
        make_callback_query,
        id="callback_query_rich",
    ),
]
"""Each `*_until` method, the method it repeats, two questions, and its answer."""
UNTIL_ARGS = "method, asked, question, other, make_answer"
TEXT_METHODS = [UNTIL_METHODS[0], UNTIL_METHODS[2]]
RICH_METHODS = [UNTIL_METHODS[1], UNTIL_METHODS[3]]
CALLBACK_METHODS = [UNTIL_METHODS[2], UNTIL_METHODS[3]]


def _until_client(asked: str, *results: object) -> tuple[pyroflow.Client, AsyncMock]:
    c = make_client()
    c.dispatcher.listeners[Message] = _RecordingListener(MessageKey)
    c.dispatcher.listeners[CallbackQuery] = _RecordingListener(CallbackQueryKey)
    ask = AsyncMock(side_effect=results)
    setattr(c, asked, ask)
    return c, ask


def _sync_parse(*results: object) -> Any:
    remaining = iter(results)

    def parse(update: object, kw: dict[str, Any]) -> object:
        result = next(remaining)
        return update if result is None else result

    return parse


def _async_parse(*results: object) -> Any:
    remaining = iter(results)

    async def parse(update: object, kw: dict[str, Any]) -> object:
        result = next(remaining)
        return update if result is None else result

    return parse


@pytest.mark.parametrize(UNTIL_ARGS, UNTIL_METHODS)
async def test_until_returns_what_parse_returns(
    method: str, asked: str, question: object, other: object, make_answer: Any
) -> None:
    answer = make_answer()
    c, ask = _until_client(asked, answer)
    parse = Mock(return_value="parsed")

    assert (
        await getattr(c, method)(100, question, parse=parse, reply_markup=CALLBACK_MARKUP)
        == "parsed"
    )

    assert ask.await_count == 1
    parse.assert_called_once_with(answer, {"reply_markup": CALLBACK_MARKUP})


@pytest.mark.parametrize(UNTIL_ARGS, UNTIL_METHODS)
async def test_until_returns_none_when_parse_does(
    method: str, asked: str, question: object, other: object, make_answer: Any
) -> None:
    c, _ = _until_client(asked, make_answer())

    assert await getattr(c, method)(100, question, parse=lambda *_: None) is None


@pytest.mark.parametrize(UNTIL_ARGS, UNTIL_METHODS)
@pytest.mark.parametrize("make_parse", [_sync_parse, _async_parse])
async def test_until_takes_a_sync_or_async_parse(
    method: str, asked: str, question: object, other: object, make_answer: Any, make_parse: Any
) -> None:
    last = make_answer()
    c, ask = _until_client(asked, make_answer(), last)

    assert (
        await getattr(c, method)(100, question, parse=make_parse(AskAgain(question), None)) is last
    )
    assert ask.await_count == 2


@pytest.mark.parametrize(UNTIL_ARGS, UNTIL_METHODS)
async def test_until_ask_again_without_kw_asks_with_no_arguments(
    method: str, asked: str, question: object, other: object, make_answer: Any
) -> None:
    c, ask = _until_client(asked, make_answer(), make_answer())

    await getattr(c, method)(
        100, question, parse=_sync_parse(AskAgain(question), None), reply_markup=CALLBACK_MARKUP
    )

    _, second = ask.await_args_list
    assert second.args == (100, question, None)
    assert "reply_markup" not in second.kwargs


@pytest.mark.parametrize(UNTIL_ARGS, UNTIL_METHODS)
async def test_until_ask_again_asks_the_new_question_with_its_kw(
    method: str, asked: str, question: object, other: object, make_answer: Any
) -> None:
    c, ask = _until_client(asked, make_answer(), make_answer())

    await getattr(c, method)(
        100,
        question,
        parse=_sync_parse(AskAgain(other, {"reply_markup": CALLBACK_MARKUP}), None),
        reply_markup=CALLBACK_MARKUP,
    )

    first, second = ask.await_args_list
    assert first.args[1] == question
    assert second.args[1] == other
    assert second.kwargs == first.kwargs


@pytest.mark.parametrize(UNTIL_ARGS, UNTIL_METHODS)
async def test_until_ask_again_with_kw_replaces_the_question_and_kw(
    method: str, asked: str, question: object, other: object, make_answer: Any
) -> None:
    c, ask = _until_client(asked, make_answer(), make_answer())
    parse = _sync_parse(AskAgain(other, {"disable_notification": True}), None)

    await getattr(c, method)(100, question, parse=parse, reply_markup=CALLBACK_MARKUP)

    _, second = ask.await_args_list
    assert second.args[1] == other
    assert second.kwargs["disable_notification"] is True
    assert "reply_markup" not in second.kwargs


@pytest.mark.parametrize(UNTIL_ARGS, TEXT_METHODS)
async def test_until_leaves_the_dict_parse_returned_as_it_was(
    method: str, asked: str, question: object, other: object, make_answer: Any
) -> None:
    c, _ = _until_client(asked, make_answer(), make_answer(), make_answer())
    returned = {"entities": ENTITIES}
    parse = _sync_parse(AskAgain("next", returned), AskAgain("other"), None)

    await getattr(c, method)(100, question, parse=parse)

    assert returned == {"entities": ENTITIES}


@pytest.mark.parametrize(UNTIL_ARGS, UNTIL_METHODS)
async def test_until_the_kw_parse_got_can_be_passed_on(
    method: str, asked: str, question: object, other: object, make_answer: Any
) -> None:
    c, ask = _until_client(asked, make_answer(), make_answer())
    rounds = iter([True, False])

    def parse(update: object, kw: dict[str, Any]) -> object:
        kw["disable_notification"] = True
        return AskAgain(question, kw) if next(rounds) else None

    await getattr(c, method)(100, question, parse=parse)

    first, second = ask.await_args_list
    assert "disable_notification" not in first.kwargs
    assert second.kwargs["disable_notification"] is True


ENTITIES = [object()]
"""What a question's `entities` hold; only their presence matters."""


@pytest.mark.parametrize(UNTIL_ARGS, TEXT_METHODS)
@pytest.mark.parametrize(
    ("result", "kept"),
    [
        pytest.param(AskAgain("again"), False, id="no_kw"),
        pytest.param(AskAgain("again", {"entities": ENTITIES}), True, id="new_kw"),
    ],
)
async def test_until_keeps_entities_only_in_the_kw_of_ask_again(
    method: str,
    asked: str,
    question: object,
    other: object,
    make_answer: Any,
    result: object,
    kept: bool,
) -> None:
    c, ask = _until_client(asked, make_answer(), make_answer())

    await getattr(c, method)(100, question, parse=_sync_parse(result, None), entities=ENTITIES)

    first, retry = ask.await_args_list
    assert first.kwargs["entities"] is ENTITIES
    assert ("entities" in retry.kwargs) is kept


@pytest.mark.parametrize(UNTIL_ARGS, UNTIL_METHODS)
async def test_until_edits_only_the_first_question(
    method: str, asked: str, question: object, other: object, make_answer: Any
) -> None:
    c, ask = _until_client(asked, make_answer(), make_answer(), make_answer())

    await getattr(c, method)(
        100, question, 5, parse=_sync_parse(AskAgain(question), AskAgain(other), None)
    )

    assert [call.args[2] for call in ask.await_args_list] == [5, None, None]


@pytest.mark.parametrize(UNTIL_ARGS, UNTIL_METHODS)
@pytest.mark.parametrize("topic", ["message_thread_id", "direct_messages_topic_id"])
async def test_until_sends_the_retries_of_an_edit_with_no_topic(
    method: str, asked: str, question: object, other: object, make_answer: Any, topic: str
) -> None:
    answer = make_answer()
    setattr(answer.message if isinstance(answer, CallbackQuery) else answer, topic, 9)
    c, ask = _until_client(asked, answer, make_answer())

    await getattr(c, method)(100, question, 5, parse=_sync_parse(AskAgain(question), None))

    _, retry = ask.await_args_list
    assert topic not in retry.kwargs


@pytest.mark.parametrize(UNTIL_ARGS, UNTIL_METHODS)
async def test_until_keeps_the_topic_parse_put_in_kw(
    method: str, asked: str, question: object, other: object, make_answer: Any
) -> None:
    answer = make_answer()
    (answer.message if isinstance(answer, CallbackQuery) else answer).message_thread_id = 9
    c, ask = _until_client(asked, answer, make_answer())
    parse = _sync_parse(AskAgain(other, {"message_thread_id": 3}), None)

    await getattr(c, method)(100, question, 5, parse=parse)

    assert ask.await_args_list[1].kwargs["message_thread_id"] == 3


@pytest.mark.parametrize(UNTIL_ARGS, UNTIL_METHODS)
async def test_until_without_an_edit_adds_no_topic(
    method: str, asked: str, question: object, other: object, make_answer: Any
) -> None:
    answer = make_answer()
    (answer.message if isinstance(answer, CallbackQuery) else answer).message_thread_id = 9
    c, ask = _until_client(asked, answer, make_answer())

    await getattr(c, method)(100, question, parse=_sync_parse(AskAgain(question), None))

    assert "message_thread_id" not in ask.await_args_list[1].kwargs


@pytest.mark.parametrize(UNTIL_ARGS, UNTIL_METHODS)
@pytest.mark.parametrize("attempts", [1, 2, 3])
async def test_until_raises_attempts_exhausted_after_exactly_attempts_questions(
    method: str, asked: str, question: object, other: object, make_answer: Any, attempts: int
) -> None:
    answers = [make_answer() for _ in range(attempts)]
    c, ask = _until_client(asked, *answers)

    with pytest.raises(ListenerAttemptsExhausted) as caught:
        await getattr(c, method)(
            100, question, parse=lambda *_: AskAgain("again"), attempts=attempts, listen_user_id=7
        )

    assert caught.value.update is answers[-1]
    assert caught.value.value == attempts
    assert ask.await_count == attempts


@pytest.mark.parametrize(UNTIL_ARGS, CALLBACK_METHODS)
async def test_until_attempts_exhausted_on_a_press_without_a_message(
    method: str, asked: str, question: object, other: object, make_answer: Any
) -> None:
    press = make_answer(message=None, inline_message_id="inline")
    c, _ = _until_client(asked, press)

    with pytest.raises(ListenerAttemptsExhausted) as caught:
        await getattr(c, method)(100, question, parse=lambda *_: AskAgain("again"), attempts=1)

    assert caught.value.value == 1
    assert caught.value.update is press


@pytest.mark.parametrize(UNTIL_ARGS, UNTIL_METHODS)
@pytest.mark.parametrize("attempts", [0, -1])
async def test_until_refuses_attempts_that_are_not_positive(
    method: str, asked: str, question: object, other: object, make_answer: Any, attempts: int
) -> None:
    c, ask = _until_client(asked)

    with pytest.raises(ValueError, match="attempts must be positive"):
        await getattr(c, method)(100, question, parse=lambda *_: None, attempts=attempts)

    ask.assert_not_awaited()


@pytest.mark.parametrize(UNTIL_ARGS, UNTIL_METHODS)
@pytest.mark.parametrize("listen_strict", [False, True])
async def test_until_passes_the_listen_arguments_to_the_repeated_method(
    method: str, asked: str, question: object, other: object, make_answer: Any, listen_strict: bool
) -> None:
    c, ask = _until_client(asked, make_answer())
    context = ListenerContext(step=1)

    await getattr(c, method)(
        100,
        question,
        parse=lambda *_: None,
        listen_user_id=7,
        listen_context=context,
        listen_filters=pyro_filters.text,
        listen_strict=listen_strict,
        listen_timeout=3,
        reply_markup=CALLBACK_MARKUP,
    )

    ask.assert_awaited_once_with(
        100,
        question,
        None,
        listen_user_id=7,
        listen_context=context,
        listen_filters=pyro_filters.text,
        listen_strict=listen_strict,
        listen_timeout=3,
        reply_markup=CALLBACK_MARKUP,
    )


@pytest.mark.parametrize(UNTIL_ARGS, UNTIL_METHODS)
@pytest.mark.parametrize(
    "error", [ListenerTimeout(), ListenerRejected(), ListenerReplaced(), ExcA()]
)
async def test_until_lets_an_error_of_the_repeated_method_through_at_once(
    method: str, asked: str, question: object, other: object, make_answer: Any, error: Exception
) -> None:
    c, ask = _until_client(asked, error, make_answer())
    parse = Mock(return_value=AskAgain("again"))

    with pytest.raises(type(error)):
        await getattr(c, method)(100, question, parse=parse)

    assert ask.await_count == 1
    parse.assert_not_called()


@pytest.mark.parametrize(UNTIL_ARGS, UNTIL_METHODS)
async def test_until_lets_an_error_of_parse_through(
    method: str, asked: str, question: object, other: object, make_answer: Any
) -> None:
    c, ask = _until_client(asked, make_answer(), make_answer())

    def parse(update: object, kw: dict[str, Any]) -> object:
        raise ExcA

    with pytest.raises(ExcA):
        await getattr(c, method)(100, question, parse=parse)

    assert ask.await_count == 1
