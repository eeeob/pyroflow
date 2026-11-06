"""Tests for `pyroflow.types`: the patched `User`, `Message` and `CallbackQuery`."""

from __future__ import annotations as _annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, call

import pyrogram
import pytest
from pyrogram.enums import ChatType
from pyrogram.types import Chat

from pyroflow import types as pf_types
from pyroflow.enums import ListenMessageId
from pyroflow.models import ListenerContext
from pyroflow.types import CallbackQuery, Message, User


ME_ID = 42
SENTINEL = object()
SENT = SimpleNamespace(id=9, ephemeral_message_id=None)
EPHEMERAL_SENT = SimpleNamespace(id=0, ephemeral_message_id=4)
CONTEXT = ListenerContext(step=1)


def make_client(me_id: int | None = ME_ID) -> SimpleNamespace:
    me = None if me_id is None else SimpleNamespace(id=me_id)
    listener = AsyncMock(return_value=SENTINEL)
    return SimpleNamespace(
        me=me,
        ask_context_message=True,
        listeners={
            pyrogram.types.Message: listener,
            CallbackQuery: listener,
            pyrogram.types.Poll: listener,
        },
    )


def make_msg(
    *,
    is_self: bool = False,
    client: SimpleNamespace | None = None,
    **fields: Any,
) -> Message:
    return Message(
        id=5,
        client=client or make_client(),
        chat=Chat(id=100, type=ChatType.PRIVATE),
        from_user=User(id=ME_ID if is_self else 7, is_self=is_self),
        **fields,
    )


# --- module surface -------------------------------------------------------


def test_all_lists_the_patched_classes() -> None:
    assert set(pf_types.__all__) == {"User", "Message", "CallbackQuery"}


@pytest.mark.parametrize("name", ["User", "Message", "CallbackQuery"])
def test_classes_patch_pyrogram_in_place(name: str) -> None:
    assert getattr(pf_types, name) is getattr(pyrogram.types, name)


# --- User.lang_code -------------------------------------------------------


@pytest.mark.parametrize(
    ("language_code", "expected"),
    [
        ("pt-BR", "pt"),
        ("EN", "en"),
        ("en", "en"),
        ("zh-Hant-TW", "zh"),
        ("", None),
        (None, None),
    ],
)
def test_lang_code(language_code: str | None, expected: str | None) -> None:
    assert User(id=1, language_code=language_code).lang_code == expected


# --- Message.editable -----------------------------------------------------


def test_editable_when_sent_by_self_user() -> None:
    assert make_msg(is_self=True).editable is True


def test_not_editable_for_other_user() -> None:
    assert make_msg().editable is False


def test_editable_when_sender_chat_is_me() -> None:
    m = make_msg(sender_chat=Chat(id=ME_ID, type=ChatType.CHANNEL))
    m.from_user = None
    assert m.editable is True


def test_not_editable_when_sender_chat_is_another_chat() -> None:
    m = make_msg(sender_chat=Chat(id=999, type=ChatType.CHANNEL))
    m.from_user = None
    assert m.editable is False


def test_not_editable_without_sender_or_me() -> None:
    m = make_msg(client=make_client(me_id=None))
    m.from_user = None
    assert m.editable is False


# --- Message.respond ------------------------------------------------------


def test_respond_is_edit_when_editable() -> None:
    m = make_msg(is_self=True)
    assert m.respond == m.edit


def test_respond_is_reply_when_not_editable() -> None:
    m = make_msg()
    assert m.respond == m.reply


# --- Message.ask ----------------------------------------------------------


def make_ask_msg(*, is_self: bool = False, **fields: Any) -> Any:
    m = make_msg(is_self=is_self, **fields)
    m.reply = AsyncMock(return_value=SENT)
    m.edit = AsyncMock(return_value=SENT)
    m.reply_rich = AsyncMock(return_value=SENT)
    return m


def assert_listened(m: Any, **expected: Any) -> None:
    wait = {
        "chat_id": 100,
        "user_id": None,
        "message_id": 10,
        "context": ListenerContext(message=SENT),
        "filters": None,
        "strict": False,
        "timeout": None,
    }
    listener = m._client.listeners[pyrogram.types.Message]
    assert listener.await_args == call(**{**wait, **expected})


@pytest.mark.parametrize("field", ["service", "empty"])
async def test_ask_rejects_service_or_empty_message(field: str) -> None:
    m = make_ask_msg()
    setattr(m, field, True)
    with pytest.raises(ValueError, match="service or empty"):
        await m.ask("hi")
    m.reply.assert_not_awaited()


async def test_ask_replies_when_not_editable() -> None:
    m = make_ask_msg()
    result = await m.ask(
        "hi",
        listen_user_id=7,
        listen_context=CONTEXT,
        listen_filters=pyrogram.filters.text,
        listen_strict=True,
        listen_timeout=1,
        extra="kw",
    )

    assert result is SENTINEL
    assert m.reply.await_args == call("hi", extra="kw")
    m.edit.assert_not_awaited()
    assert_listened(
        m,
        user_id=7,
        context=ListenerContext(step=1, message=SENT),
        filters=pyrogram.filters.text,
        strict=True,
        timeout=1,
    )


async def test_ask_edits_when_editable() -> None:
    m = make_ask_msg(is_self=True)
    assert await m.ask("hi", listen_update_type=CallbackQuery, parse_mode=None) is SENTINEL

    assert m.edit.await_args == call("hi", parse_mode=None)
    m.reply.assert_not_awaited()
    assert_listened(m, message_id=9)


async def test_ask_force_send_replies_even_when_editable() -> None:
    m = make_ask_msg(is_self=True)
    await m.ask("hi", True, disable_notification=True)

    assert m.reply.await_args == call("hi", disable_notification=True)
    m.edit.assert_not_awaited()


async def test_ask_sends_nothing_without_a_listener() -> None:
    m = make_ask_msg()
    m._client.listeners.clear()

    with pytest.raises(RuntimeError, match="No listener registered for Message"):
        await m.ask("hi")

    m.reply.assert_not_awaited()


@pytest.mark.parametrize(
    ("given", "listened"),
    [(ListenMessageId.SENT, 9), (ListenMessageId.NEXT, 10), (None, None), (3, 3)],
)
async def test_ask_turns_listen_message_id_into_the_id_to_wait_on(
    given: ListenMessageId | int | None, listened: int | None
) -> None:
    m = make_ask_msg()
    await m.ask("hi", listen_message_id=given)

    assert_listened(m, message_id=listened)


async def test_ask_auto_waits_on_no_message_for_other_update_types() -> None:
    m = make_ask_msg()
    await m.ask("hi", listen_update_type=pyrogram.types.Poll)

    assert_listened(m, message_id=None)


async def test_ask_passes_a_context_holding_a_message_as_it_is() -> None:
    m = make_ask_msg()
    context = ListenerContext(message="mine")
    await m.ask("hi", listen_context=context)

    assert m._client.listeners[pyrogram.types.Message].await_args.kwargs["context"] is context


@pytest.mark.parametrize("context", [None, CONTEXT])
async def test_ask_without_ask_context_message_passes_the_context_as_it_is(
    context: ListenerContext | None,
) -> None:
    m = make_ask_msg()
    m._client.ask_context_message = False
    await m.ask("hi", listen_context=context)

    assert m._client.listeners[pyrogram.types.Message].await_args.kwargs["context"] is context


# --- Message.ask_rich -----------------------------------------------------

RICH = object()


@pytest.mark.parametrize("field", ["service", "empty"])
async def test_ask_rich_rejects_service_or_empty_message(field: str) -> None:
    m = make_ask_msg()
    setattr(m, field, True)
    with pytest.raises(ValueError, match="service or empty"):
        await m.ask_rich(RICH)
    m.reply_rich.assert_not_awaited()


async def test_ask_rich_replies_when_not_editable() -> None:
    m = make_ask_msg()
    result = await m.ask_rich(RICH, listen_user_id=7, listen_timeout=1, extra="kw")

    assert result is SENTINEL
    assert m.reply_rich.await_args == call(RICH, extra="kw")
    m.edit.assert_not_awaited()
    assert_listened(m, user_id=7, timeout=1)


async def test_ask_rich_edits_when_editable() -> None:
    m = make_ask_msg(is_self=True)
    assert await m.ask_rich(RICH, listen_update_type=CallbackQuery, reply_markup=None) is SENTINEL

    assert m.edit.await_args == call(rich_message=RICH, reply_markup=None)
    m.reply_rich.assert_not_awaited()
    assert_listened(m, message_id=9)


async def test_ask_rich_force_send_replies_even_when_editable() -> None:
    m = make_ask_msg(is_self=True)
    await m.ask_rich(RICH, True, disable_notification=True)

    assert m.reply_rich.await_args == call(RICH, disable_notification=True)
    m.edit.assert_not_awaited()


async def test_ask_rich_sends_nothing_without_a_listener() -> None:
    m = make_ask_msg()
    m._client.listeners.clear()

    with pytest.raises(RuntimeError, match="No listener registered for Message"):
        await m.ask_rich(RICH)

    m.reply_rich.assert_not_awaited()


async def test_ask_rich_turns_sent_into_the_id_to_wait_on() -> None:
    m = make_ask_msg()
    await m.ask_rich(RICH, listen_message_id=ListenMessageId.SENT)

    assert_listened(m, message_id=9)


async def test_ask_rich_passes_a_context_holding_a_message_as_it_is() -> None:
    m = make_ask_msg()
    context = ListenerContext(message="mine")
    await m.ask_rich(RICH, listen_context=context)

    assert m._client.listeners[pyrogram.types.Message].await_args.kwargs["context"] is context


@pytest.mark.parametrize("context", [None, CONTEXT])
async def test_ask_rich_without_ask_context_message_passes_the_context_as_it_is(
    context: ListenerContext | None,
) -> None:
    m = make_ask_msg()
    m._client.ask_context_message = False
    await m.ask_rich(RICH, listen_context=context)

    assert m._client.listeners[pyrogram.types.Message].await_args.kwargs["context"] is context


# --- ephemeral messages ---------------------------------------------------


def make_ephemeral_msg(*, is_self: bool = False) -> Any:
    m = make_ask_msg(is_self=is_self, ephemeral_message_id=3)
    m.id = 0
    m.reply.return_value = EPHEMERAL_SENT
    m.edit.return_value = EPHEMERAL_SENT
    m.reply_rich.return_value = EPHEMERAL_SENT
    return m


def listened(m: Any) -> dict[str, Any]:
    return m._client.listeners[pyrogram.types.Message].await_args.kwargs


@pytest.mark.parametrize(("method", "content"), [("ask", "hi"), ("ask_rich", RICH)])
async def test_ask_replying_to_an_ephemeral_message_waits_on_its_sender(
    method: str, content: object
) -> None:
    m = make_ephemeral_msg()
    await getattr(m, method)(content)

    assert listened(m)["user_id"] == 7
    assert listened(m)["message_id"] is None


@pytest.mark.parametrize(("method", "content"), [("ask", "hi"), ("ask_rich", RICH)])
async def test_ask_keeps_the_given_user_on_an_ephemeral_message(
    method: str, content: object
) -> None:
    m = make_ephemeral_msg()
    await getattr(m, method)(content, listen_user_id=8)

    assert listened(m)["user_id"] == 8


@pytest.mark.parametrize(("method", "content"), [("ask", "hi"), ("ask_rich", RICH)])
async def test_ask_waits_on_the_buttons_of_an_ephemeral_reply(method: str, content: object) -> None:
    m = make_ephemeral_msg()
    await getattr(m, method)(content, listen_update_type=CallbackQuery)

    assert listened(m)["message_id"] is ListenMessageId.EPHEMERAL


@pytest.mark.parametrize(("method", "content"), [("ask", "hi"), ("ask_rich", RICH)])
async def test_ask_refuses_ephemeral_without_a_user_before_sending(
    method: str, content: object
) -> None:
    m = make_ask_msg()

    with pytest.raises(ValueError, match="needs listen_user_id"):
        await getattr(m, method)(content, listen_message_id=ListenMessageId.EPHEMERAL)

    m.reply.assert_not_awaited()
    m.reply_rich.assert_not_awaited()


@pytest.mark.parametrize(("method", "content"), [("ask", "hi"), ("ask_rich", RICH)])
async def test_ask_editing_an_ephemeral_message_needs_a_user_before_sending(
    method: str, content: object
) -> None:
    m = make_ephemeral_msg(is_self=True)

    with pytest.raises(ValueError, match="needs listen_user_id"):
        await getattr(m, method)(content)

    m.edit.assert_not_awaited()
