"""Tests for `pyroflow.models.listener_key`: `ListenerKey`, `MessageKey`, `CallbackQueryKey`."""

from __future__ import annotations as _annotations

import asyncio
import dataclasses
from datetime import datetime
from typing import Any

import pytest
from pyrogram.types import (
    CallbackQuery,
    Chat,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    User,
)

from pyroflow import CallbackQueryListener, MessageListener
from pyroflow.models import CallbackQueryKey, ListenerKey, MessageKey
from pyroflow.models import listener_key as listener_key_module
from pyroflow.typings import UpdateType

from ..conftest import bind_listener, make_callback_query, make_message


# --- ListenerKey ----------------------------------------------------------------------


@dataclasses.dataclass(frozen=True, slots=True)
class _ChatKey(ListenerKey[Message]):
    """The smallest concrete key: one field, and both builders."""

    __update_type__ = Message

    chat_id: int | None = None

    @classmethod
    def from_update(cls, update: Message) -> _ChatKey:
        return cls(update.chat.id)

    @classmethod
    def from_sent(cls, sent: Message, user_id: int | None = None) -> _ChatKey:
        return cls(sent.chat.id)


def test_a_key_class_without_its_builders_cannot_be_created() -> None:
    @dataclasses.dataclass(frozen=True, slots=True)
    class OnlyFromSent(ListenerKey[Message]):
        __update_type__ = Message

        @classmethod
        def from_sent(cls, sent: Message, user_id: int | None = None) -> OnlyFromSent:
            return cls()

    @dataclasses.dataclass(frozen=True, slots=True)
    class OnlyFromUpdate(ListenerKey[Message]):
        __update_type__ = Message

        @classmethod
        def from_update(cls, update: Message) -> OnlyFromUpdate:
            return cls()

    with pytest.raises(TypeError, match="from_sent"):
        ListenerKey()  # ty: ignore[call-non-callable]  # instantiates an abstract class on purpose
    with pytest.raises(TypeError, match="from_update"):
        OnlyFromSent()  # ty: ignore[call-non-callable]  # instantiates an abstract class on purpose
    with pytest.raises(TypeError, match="from_sent"):
        OnlyFromUpdate()  # ty: ignore[call-non-callable]  # instantiates an abstract class on purpose


def test_a_key_class_without_an_update_type_is_refused() -> None:
    with pytest.raises(TypeError, match="must define __update_type__"):

        class NoUpdateType(ListenerKey[Message]):
            pass


def test_keys_are_bound_to_their_update_type() -> None:
    assert ListenerKey.__parameters__ == (UpdateType,)
    assert MessageKey.__update_type__ is Message
    assert CallbackQueryKey.__update_type__ is CallbackQuery


def test_listener_key_defaults_to_any_chat() -> None:
    assert _ChatKey().chat_id is None
    assert _ChatKey(1).chat_id == 1


def test_key_fields_lists_each_class_own_fields_in_order() -> None:
    assert ListenerKey.key_fields == ()
    assert MessageKey.key_fields == (
        "chat_id",
        "user_id",
        "message_thread_id",
        "direct_messages_topic_id",
        "ephemeral",
        "business_connection_id",
    )
    assert CallbackQueryKey.key_fields == (
        "chat_id",
        "user_id",
        "message_id",
        "inline_message_id",
        "ephemeral",
        "business_connection_id",
    )
    assert MessageKey(1).key_fields is MessageKey.key_fields


def test_key_fields_is_computed_once_per_class(monkeypatch: pytest.MonkeyPatch) -> None:
    @dataclasses.dataclass(frozen=True, slots=True)
    class FreshKey(MessageKey):
        extra: int | None = None

    calls: list[type] = []
    real_fields = dataclasses.fields

    def counting_fields(cls: type) -> tuple[dataclasses.Field, ...]:
        calls.append(cls)
        return real_fields(cls)

    monkeypatch.setattr(listener_key_module, "fields", counting_fields)

    assert FreshKey.key_fields == (*MessageKey.key_fields, "extra")
    assert FreshKey.key_fields is FreshKey.key_fields
    assert FreshKey.exact_fields == ("ephemeral", "business_connection_id")
    assert FreshKey.exact_fields is FreshKey.exact_fields
    assert calls == [FreshKey, FreshKey]


def test_exact_fields_lists_the_fields_marked_exact() -> None:
    assert ListenerKey.exact_fields == ()
    assert MessageKey.exact_fields == ("ephemeral", "business_connection_id")
    assert CallbackQueryKey.exact_fields == ("ephemeral", "business_connection_id")


def test_keys_hold_the_values_as_given() -> None:
    assert MessageKey(user_id=5).to_tuple() == (None, 5, None, None, False, None)
    assert CallbackQueryKey(user_id=5, message_id=3).to_tuple() == (None, 5, 3, None, False, None)
    assert MessageKey(5, 5).to_tuple() == (5, 5, None, None, False, None)


def test_to_tuple_follows_key_fields() -> None:
    assert _ChatKey(1).to_tuple() == (1,)
    assert MessageKey(1, 2, 3).to_tuple() == (1, 2, 3, None, False, None)
    assert CallbackQueryKey(1, 2, 3).to_tuple() == (1, 2, 3, None, False, None)


def test_to_dict_follows_key_fields() -> None:
    assert _ChatKey(1).to_dict() == {"chat_id": 1}
    assert list(MessageKey(1, 2).to_dict().items()) == [
        ("chat_id", 1),
        ("user_id", 2),
        ("message_thread_id", None),
        ("direct_messages_topic_id", None),
        ("ephemeral", False),
        ("business_connection_id", None),
    ]


def test_keys_are_frozen_and_slotted() -> None:
    for key in (_ChatKey(1), MessageKey(1), CallbackQueryKey(1)):
        assert not hasattr(key, "__dict__")
        with pytest.raises(dataclasses.FrozenInstanceError):
            key.chat_id = 2  # ty: ignore[invalid-assignment]  # writes a frozen field on purpose


def test_keys_of_different_classes_are_never_equal() -> None:
    assert _ChatKey(1) != MessageKey(1)
    assert MessageKey(1) != CallbackQueryKey(1)


# --- MessageKey -----------------------------------------------------------------------


def test_message_key_defaults_match_any_message() -> None:
    assert MessageKey().to_tuple() == (None, None, None, None, False, None)


def test_message_key_from_update_keys_chat_sender_and_topics() -> None:
    message = make_message(1, 2, 5, message_thread_id=3, direct_messages_topic_id=4)

    assert MessageKey.from_update(message) == MessageKey(1, 2, 3, 4)


def test_message_key_from_update_without_a_sender_has_no_user() -> None:
    assert MessageKey.from_update(make_message(1, from_user=None)) == MessageKey(1)


def test_message_key_from_update_marks_an_ephemeral_message() -> None:
    message = make_message(1, 2, 0, ephemeral_message_id=4)

    assert MessageKey.from_update(message) == MessageKey(1, 2, ephemeral=True)


def test_message_key_from_update_of_an_ephemeral_message_without_a_sender() -> None:
    update = make_message(message_id=0, ephemeral_message_id=4, from_user=None)

    assert MessageKey.from_update(update) == MessageKey(100, None, ephemeral=True)


@pytest.mark.parametrize(
    "overrides",
    [
        {"outgoing": True},
        {"service": True},
        {"empty": True},
        {"edit_date": datetime(2024, 1, 1)},
        {"edit_hidden": True},
        {"chat": None},
    ],
)
def test_message_key_from_update_is_none_for_an_unlistenable_message(
    overrides: dict[str, Any],
) -> None:
    assert MessageKey.from_update(make_message(**overrides)) is None


def test_message_key_from_update_is_none_for_own_messages() -> None:
    msg = make_message()
    msg.from_user.is_self = True

    assert MessageKey.from_update(msg) is None


def test_message_key_from_sent_keys_chat_topics_and_the_given_user() -> None:
    sent = Message(id=5, chat=Chat(id=1), message_thread_id=3, direct_messages_topic_id=4)

    assert MessageKey.from_sent(sent) == MessageKey(1, None, 3, 4)
    assert MessageKey.from_sent(sent, 2) == MessageKey(1, 2, 3, 4)


def test_message_key_from_sent_marks_an_ephemeral_message() -> None:
    sent = Message(id=0, chat=Chat(id=1), ephemeral_message_id=4)

    assert MessageKey.from_sent(sent, 2) == MessageKey(1, 2, ephemeral=True)


def test_general_topic_id_is_one() -> None:
    assert listener_key_module._GENERAL_TOPIC_ID == 1


def test_message_key_from_update_keys_a_forum_message_without_a_topic_as_general() -> None:
    general = make_message(-100, chat=Chat(id=-100, is_forum=True))
    in_topic = make_message(-100, chat=Chat(id=-100, is_forum=True), message_thread_id=3)
    not_forum = make_message(-100, chat=Chat(id=-100, is_forum=False))

    assert MessageKey.from_update(general) == MessageKey(-100, 7, 1)
    assert MessageKey.from_update(in_topic) == MessageKey(-100, 7, 3)
    assert MessageKey.from_update(not_forum) == MessageKey(-100, 7)


def test_message_key_from_update_keys_the_business_connection() -> None:
    message = make_message(1, 2, business_connection_id="bc")

    assert MessageKey.from_update(message) == MessageKey(1, 2, business_connection_id="bc")


def test_message_key_from_sent_keys_a_forum_message_without_a_topic_as_general() -> None:
    general = Message(id=5, chat=Chat(id=-100, is_forum=True))
    not_forum = Message(id=5, chat=Chat(id=-100))

    assert MessageKey.from_sent(general, 2) == MessageKey(-100, 2, 1)
    assert MessageKey.from_sent(not_forum, 2) == MessageKey(-100, 2)


def test_message_key_from_sent_keys_the_business_connection() -> None:
    sent = Message(id=5, chat=Chat(id=1), business_connection_id="bc")

    assert MessageKey.from_sent(sent, 2) == MessageKey(1, 2, business_connection_id="bc")


async def test_message_key_business_connection_splits_the_waits() -> None:
    lis = bind_listener(MessageListener())
    business_wait = asyncio.ensure_future(lis.listen(MessageKey(100, business_connection_id="bc")))
    await asyncio.sleep(0)

    assert await lis.resolve(make_message(100)) is False
    business = make_message(100, business_connection_id="bc")
    assert await lis.resolve(business) is True
    assert await business_wait is business

    plain_wait = asyncio.ensure_future(lis.listen(MessageKey(100)))
    await asyncio.sleep(0)

    assert await lis.resolve(make_message(100, business_connection_id="bc")) is False
    plain = make_message(100)
    assert await lis.resolve(plain) is True
    assert await plain_wait is plain


async def test_message_key_in_general_takes_only_a_general_message() -> None:
    lis = bind_listener(MessageListener())
    task = asyncio.ensure_future(
        lis.listen(MessageKey.from_sent(Message(id=5, chat=Chat(id=-100, is_forum=True))))
    )
    await asyncio.sleep(0)

    forum = Chat(id=-100, is_forum=True)
    assert await lis.resolve(make_message(-100, chat=forum, message_thread_id=55)) is False
    general = make_message(-100, chat=forum)
    assert await lis.resolve(general) is True
    assert await task is general


# --- CallbackQueryKey -----------------------------------------------------------------


def test_callback_query_key_defaults_match_any_press() -> None:
    assert CallbackQueryKey().to_tuple() == (None, None, None, None, False, None)


def test_callback_query_key_with_an_inline_message_has_no_chat() -> None:
    key = CallbackQueryKey(user_id=2, inline_message_id="im")

    assert key.to_tuple() == (None, 2, None, "im", False, None)


def test_callback_query_key_from_update_keys_chat_user_and_message() -> None:
    query = make_callback_query(chat_id=-100, user_id=9, message_id=42)

    assert CallbackQueryKey.from_update(query) == CallbackQueryKey(-100, 9, 42)


def test_callback_query_key_from_update_on_an_ephemeral_message() -> None:
    query = make_callback_query(chat_id=1, user_id=2, message_id=0)
    query.message.ephemeral_message_id = 4

    assert CallbackQueryKey.from_update(query) == CallbackQueryKey(1, 2, ephemeral=True)


def test_callback_query_key_from_update_on_an_inline_message() -> None:
    query = make_callback_query(user_id=2, message=None, inline_message_id="im")

    assert CallbackQueryKey.from_update(query) == CallbackQueryKey(
        user_id=2, inline_message_id="im"
    )


def test_callback_query_key_from_update_without_a_message_or_chat_is_none() -> None:
    assert CallbackQueryKey.from_update(make_callback_query(message=None)) is None

    query = make_callback_query()
    query.message.chat = None
    assert CallbackQueryKey.from_update(query) is None


def _buttons(*buttons: InlineKeyboardButton) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([list(buttons)])


CALLBACK_MARKUP = _buttons(InlineKeyboardButton("Yes", callback_data="y"))
"""Markup with one button that sends a callback query."""


def test_callback_query_key_from_sent_keys_chat_message_and_the_given_user() -> None:
    sent = Message(id=5, chat=Chat(id=1), reply_markup=CALLBACK_MARKUP)

    assert CallbackQueryKey.from_sent(sent) == CallbackQueryKey(1, None, 5)
    assert CallbackQueryKey.from_sent(sent, 2) == CallbackQueryKey(1, 2, 5)


@pytest.mark.parametrize("key_type", [MessageKey, CallbackQueryKey])
def test_from_sent_without_a_user_waits_on_any_user(
    key_type: type[MessageKey | CallbackQueryKey],
) -> None:
    replied = Message(id=3, chat=Chat(id=1), from_user=User(id=7))
    sent = Message(
        id=0,
        chat=Chat(id=1),
        ephemeral_message_id=4,
        receiver_user=User(id=9),
        reply_to_message=replied,
        reply_markup=CALLBACK_MARKUP,
    )

    assert key_type.from_sent(sent).user_id is None


def test_callback_query_key_from_sent_on_an_ephemeral_message() -> None:
    sent = Message(id=0, chat=Chat(id=1), ephemeral_message_id=4, reply_markup=CALLBACK_MARKUP)

    assert CallbackQueryKey.from_sent(sent, 2) == CallbackQueryKey(1, 2, ephemeral=True)


def test_callback_query_key_from_update_keys_the_business_connection_of_the_message() -> None:
    query = make_callback_query(chat_id=1, user_id=2, message_id=3)
    query.message.business_connection_id = "bc"

    assert CallbackQueryKey.from_update(query) == CallbackQueryKey(
        1, 2, 3, business_connection_id="bc"
    )

    query.message.ephemeral_message_id = 4
    assert CallbackQueryKey.from_update(query) == CallbackQueryKey(
        1, 2, ephemeral=True, business_connection_id="bc"
    )


def test_callback_query_key_from_sent_keys_the_business_connection() -> None:
    sent = Message(id=5, chat=Chat(id=1), business_connection_id="bc")
    ephemeral = Message(id=0, chat=Chat(id=1), ephemeral_message_id=4, business_connection_id="bc")

    assert CallbackQueryKey.from_sent(sent, 2) == CallbackQueryKey(
        1, 2, 5, business_connection_id="bc"
    )
    assert CallbackQueryKey.from_sent(ephemeral, 2) == CallbackQueryKey(
        1, 2, ephemeral=True, business_connection_id="bc"
    )


async def test_callback_query_key_business_connection_splits_the_waits() -> None:
    lis = bind_listener(CallbackQueryListener())
    business_wait = asyncio.ensure_future(
        lis.listen(CallbackQueryKey(100, business_connection_id="bc"))
    )
    await asyncio.sleep(0)

    assert await lis.resolve(make_callback_query()) is False
    business = make_callback_query()
    business.message.business_connection_id = "bc"
    assert await lis.resolve(business) is True
    assert await business_wait is business

    plain_wait = asyncio.ensure_future(lis.listen(CallbackQueryKey(100)))
    await asyncio.sleep(0)

    assert await lis.resolve(business) is False
    plain = make_callback_query()
    assert await lis.resolve(plain) is True
    assert await plain_wait is plain


def test_callback_query_key_from_update_takes_the_presser_not_the_sender() -> None:
    query = CallbackQuery(
        id="q",
        from_user=User(id=2),
        chat_instance="c",
        message=Message(id=3, chat=Chat(id=1), from_user=User(id=99)),
    )

    assert CallbackQueryKey.from_update(query) == CallbackQueryKey(1, 2, 3)


def test_listener_key_all() -> None:
    assert listener_key_module.__all__ == ("ListenerKey", "MessageKey", "CallbackQueryKey")
