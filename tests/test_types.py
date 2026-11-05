"""Tests for `pyroflow.types`: the patched `Update`, `User`, `Message` and `CallbackQuery`."""

from __future__ import annotations as _annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pyrogram
import pytest
from pyrogram.enums import ChatType
from pyrogram.types import Chat, ReplyParameters

from pyroflow import types as pf_types
from pyroflow.enums import ListenMessageId
from pyroflow.models import ListenerContext
from pyroflow.types import CallbackQuery, Message, User

from .conftest import make_callback_query

ME_ID = 42
SENTINEL = object()
CONTEXT = ListenerContext(step=1)


def make_client(me_id: int | None = ME_ID) -> SimpleNamespace:
    me = None if me_id is None else SimpleNamespace(id=me_id)
    return SimpleNamespace(
        me=me, ask=AsyncMock(return_value=SENTINEL), ask_rich=AsyncMock(return_value=SENTINEL)
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
    assert set(pf_types.__all__) == {"User", "Message", "CallbackQuery", "Update"}


@pytest.mark.parametrize("name", ["Update", "User", "Message", "CallbackQuery"])
def test_classes_patch_pyrogram_in_place(name: str) -> None:
    assert getattr(pf_types, name) is getattr(pyrogram.types, name)


def test_callback_query_inherits_update_members() -> None:
    cbq = make_callback_query()
    assert cbq.with_ctx(step=1).context == {"step": 1}


# --- Update.context -------------------------------------------------------


def test_context_is_none_when_unset() -> None:
    assert Message(id=1).context is None


def test_context_setter_stores_the_same_dict() -> None:
    m = Message(id=1)
    ctx = {"step": 1}
    m.context = ctx
    assert m.context is ctx


def test_context_setter_none_removes_it() -> None:
    m = Message(id=1)
    m.context = {"step": 1}
    m.context = None
    assert m.context is None


def test_context_setter_none_when_unset_is_noop() -> None:
    m = Message(id=1)
    m.context = None
    assert m.context is None


def test_context_deleter_removes_it() -> None:
    m = Message(id=1)
    m.context = {"step": 1}
    del m.context
    assert m.context is None


def test_context_deleter_raises_when_unset() -> None:
    m = Message(id=1)
    with pytest.raises(AttributeError):
        del m.context


# --- Update.with_ctx ------------------------------------------------------


def test_with_ctx_creates_context_and_returns_self() -> None:
    m = Message(id=1)
    assert m.with_ctx(lang="en") is m
    assert m.context == {"lang": "en"}


def test_with_ctx_merges_mapping_and_kwargs() -> None:
    assert Message(id=1).with_ctx({"step": 1}, lang="en").context == {"step": 1, "lang": "en"}


def test_with_ctx_updates_existing_context_in_place() -> None:
    m = Message(id=1)
    ctx = {"step": 1, "keep": True}
    m.context = ctx
    m.with_ctx(step=2)
    assert m.context is ctx
    assert ctx == {"step": 2, "keep": True}


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


@pytest.mark.parametrize("field", ["service", "empty"])
async def test_ask_rejects_service_or_empty_message(field: str) -> None:
    m = make_msg()
    setattr(m, field, True)
    with pytest.raises(ValueError, match="service or empty"):
        await m.ask("hi")
    m._client.ask.assert_not_awaited()


async def test_ask_sends_reply_when_not_editable() -> None:
    m = make_msg(message_thread_id=3, direct_messages_topic_id=4, business_connection_id="bc")
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
    args, kwargs = m._client.ask.await_args
    assert args == (100, "hi", None)
    assert kwargs["reply_parameters"].message_id == 5
    assert kwargs["message_thread_id"] == 3
    assert kwargs["direct_messages_topic_id"] == 4
    assert kwargs["business_connection_id"] == "bc"
    assert kwargs["listen_user_id"] == 7
    assert kwargs["listen_message_id"] is ListenMessageId.AUTO
    assert kwargs["listen_context"] is CONTEXT
    assert kwargs["listen_filters"] is pyrogram.filters.text
    assert kwargs["listen_strict"] is True
    assert kwargs["listen_timeout"] == 1
    assert kwargs["listen_update_type"] is pyrogram.types.Message
    assert kwargs["extra"] == "kw"


async def test_ask_send_keeps_explicit_send_options() -> None:
    m = make_msg(message_thread_id=3, direct_messages_topic_id=4)
    rp = ReplyParameters(message_id=99)
    await m.ask("hi", reply_parameters=rp, message_thread_id=8, direct_messages_topic_id=9)

    kwargs = m._client.ask.await_args.kwargs
    assert kwargs["reply_parameters"] is rp
    assert kwargs["message_thread_id"] == 8
    assert kwargs["direct_messages_topic_id"] == 9


async def test_ask_edits_when_editable() -> None:
    m = make_msg(is_self=True)
    assert await m.ask("hi", listen_update_type=CallbackQuery) is SENTINEL

    args, kwargs = m._client.ask.await_args
    assert args == (100, "hi", 5)
    assert kwargs["reply_parameters"] is None
    assert kwargs["message_thread_id"] is None
    assert kwargs["direct_messages_topic_id"] is None
    assert kwargs["listen_update_type"] is CallbackQuery


async def test_ask_force_send_sends_even_when_editable() -> None:
    m = make_msg(is_self=True)
    await m.ask("hi", True, disable_notification=True)

    args, kwargs = m._client.ask.await_args
    assert args[2] is None
    assert kwargs["reply_parameters"].message_id == 5
    assert kwargs["disable_notification"] is True


@pytest.mark.parametrize(
    ("option", "value"),
    [
        ("reply_parameters", ReplyParameters(message_id=1)),
        ("disable_notification", False),
        ("message_thread_id", 1),
        ("direct_messages_topic_id", 1),
        ("effect_id", 1),
        ("schedule_date", datetime(2026, 1, 1)),
        ("repeat_period", 60),
        ("protect_content", False),
        ("allow_paid_broadcast", False),
        ("paid_message_star_count", 0),
        ("suggested_post_parameters", object()),
    ],
)
async def test_ask_edit_rejects_send_only_options(option: str, value: object) -> None:
    m = make_msg(is_self=True)
    with pytest.raises(ValueError, match="force_send=True"):
        await m.ask("hi", **{option: value})
    m._client.ask.assert_not_awaited()


# --- Message.ask_rich -----------------------------------------------------

RICH = object()


@pytest.mark.parametrize("field", ["service", "empty"])
async def test_ask_rich_rejects_service_or_empty_message(field: str) -> None:
    m = make_msg()
    setattr(m, field, True)
    with pytest.raises(ValueError, match="service or empty"):
        await m.ask_rich(RICH)
    m._client.ask_rich.assert_not_awaited()


async def test_ask_rich_sends_reply_when_not_editable() -> None:
    m = make_msg(message_thread_id=3, direct_messages_topic_id=4, business_connection_id="bc")
    result = await m.ask_rich(
        RICH,
        listen_user_id=7,
        listen_context=CONTEXT,
        listen_filters=pyrogram.filters.text,
        listen_strict=True,
        listen_timeout=1,
        extra="kw",
    )

    assert result is SENTINEL
    m._client.ask.assert_not_awaited()
    args, kwargs = m._client.ask_rich.await_args
    assert args == (100, RICH, None)
    assert kwargs["reply_parameters"].message_id == 5
    assert kwargs["message_thread_id"] == 3
    assert kwargs["direct_messages_topic_id"] == 4
    assert kwargs["business_connection_id"] == "bc"
    assert kwargs["listen_user_id"] == 7
    assert kwargs["listen_message_id"] is ListenMessageId.AUTO
    assert kwargs["listen_context"] is CONTEXT
    assert kwargs["listen_filters"] is pyrogram.filters.text
    assert kwargs["listen_strict"] is True
    assert kwargs["listen_timeout"] == 1
    assert kwargs["listen_update_type"] is pyrogram.types.Message
    assert kwargs["extra"] == "kw"


async def test_ask_rich_edits_when_editable() -> None:
    m = make_msg(is_self=True)
    assert await m.ask_rich(RICH, listen_update_type=CallbackQuery) is SENTINEL

    args, kwargs = m._client.ask_rich.await_args
    assert args == (100, RICH, 5)
    assert kwargs["reply_parameters"] is None
    assert kwargs["message_thread_id"] is None
    assert kwargs["listen_update_type"] is CallbackQuery


async def test_ask_rich_force_send_sends_even_when_editable() -> None:
    m = make_msg(is_self=True)
    await m.ask_rich(RICH, True, disable_notification=True)

    args, kwargs = m._client.ask_rich.await_args
    assert args[2] is None
    assert kwargs["reply_parameters"].message_id == 5
    assert kwargs["disable_notification"] is True


@pytest.mark.parametrize(
    ("option", "value"),
    [
        ("reply_parameters", ReplyParameters(message_id=1)),
        ("disable_notification", False),
        ("message_thread_id", 1),
        ("direct_messages_topic_id", 1),
        ("effect_id", 1),
        ("protect_content", False),
        ("allow_paid_broadcast", False),
        ("suggested_post_parameters", object()),
    ],
)
async def test_ask_rich_edit_rejects_send_only_options(option: str, value: object) -> None:
    m = make_msg(is_self=True)
    with pytest.raises(ValueError, match="force_send=True"):
        await m.ask_rich(RICH, **{option: value})
    m._client.ask_rich.assert_not_awaited()


# --- Message._ask_target --------------------------------------------------


@pytest.mark.parametrize("field", ["service", "empty"])
def test_ask_target_rejects_service_or_empty_message(field: str) -> None:
    m = make_msg(is_self=True)
    setattr(m, field, True)
    with pytest.raises(ValueError, match="Cannot call 'ask' on a service or empty message"):
        m._ask_target(False, None, None, None, ())


def test_ask_target_edits_an_editable_message() -> None:
    assert make_msg(is_self=True)._ask_target(False, None, None, None, ()) == (
        5,
        None,
        None,
        None,
    )


@pytest.mark.parametrize(("is_self", "force_send"), [(False, False), (True, True)])
def test_ask_target_replies_with_this_messages_defaults(is_self: bool, force_send: bool) -> None:
    m = make_msg(is_self=is_self, message_thread_id=3, direct_messages_topic_id=4)

    message_id, rp, thread, topic = m._ask_target(force_send, None, None, None, (1,))

    assert (message_id, rp.message_id, thread, topic) == (None, 5, 3, 4)


def test_ask_target_reply_keeps_explicit_values() -> None:
    m = make_msg(message_thread_id=3, direct_messages_topic_id=4)
    rp = ReplyParameters(message_id=99)

    assert m._ask_target(False, rp, 8, 9, ()) == (None, rp, 8, 9)


@pytest.mark.parametrize(
    "args",
    [
        (ReplyParameters(message_id=1), None, None, ()),
        (None, 1, None, ()),
        (None, None, 1, ()),
        (None, None, None, (None, False)),
    ],
)
def test_ask_target_edit_rejects_send_only_values(args: tuple[Any, ...]) -> None:
    with pytest.raises(ValueError, match="Use force_send=True to send a new message"):
        make_msg(is_self=True)._ask_target(False, *args)
