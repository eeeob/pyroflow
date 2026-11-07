"""Tests for `pyroflow.models.listener_key`: ListenerKey, MessageKey, CallbackQueryKey."""

from __future__ import annotations as _annotations

import dataclasses

import pytest
from pyrogram.types import (
    CallbackGame,
    CallbackQuery,
    Chat,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    User,
)

from pyroflow.models import CallbackQueryKey, ListenerKey, MessageKey
from pyroflow.models import listener_key as listener_key_module

from ..conftest import make_callback_query, make_message


# --- ListenerKey ----------------------------------------------------------------------


def test_listener_key_defaults_to_any_chat() -> None:
    assert ListenerKey().chat_id is None
    assert ListenerKey(1).chat_id == 1


def test_key_fields_lists_each_class_own_fields_in_order() -> None:
    assert ListenerKey.key_fields == ("chat_id",)
    assert MessageKey.key_fields == (
        "chat_id",
        "user_id",
        "message_thread_id",
        "direct_messages_topic_id",
        "ephemeral",
    )
    assert CallbackQueryKey.key_fields == (
        "chat_id",
        "user_id",
        "message_id",
        "inline_message_id",
        "ephemeral",
    )
    assert MessageKey(1).key_fields is MessageKey.key_fields


def test_key_fields_is_computed_once_per_class(monkeypatch: pytest.MonkeyPatch) -> None:
    @dataclasses.dataclass(frozen=True, slots=True)
    class FreshKey(ListenerKey):
        extra: int | None = None

    calls: list[type] = []
    real_fields = dataclasses.fields

    def counting_fields(cls: type) -> tuple[dataclasses.Field, ...]:
        calls.append(cls)
        return real_fields(cls)

    monkeypatch.setattr(listener_key_module, "fields", counting_fields)

    assert FreshKey.key_fields == ("chat_id", "extra")
    assert FreshKey.key_fields is FreshKey.key_fields
    assert FreshKey.exact_fields == ()
    assert FreshKey.exact_fields is FreshKey.exact_fields
    assert calls == [FreshKey, FreshKey]


def test_exact_fields_lists_the_fields_marked_exact() -> None:
    assert ListenerKey.exact_fields == ()
    assert MessageKey.exact_fields == ("ephemeral",)
    assert CallbackQueryKey.exact_fields == ("ephemeral",)


def test_keys_hold_the_values_as_given() -> None:
    assert MessageKey(user_id=5).to_tuple() == (None, 5, None, None, False)
    assert CallbackQueryKey(user_id=5, message_id=3).to_tuple() == (None, 5, 3, None, False)
    assert MessageKey(5, 5).to_tuple() == (5, 5, None, None, False)


def test_to_tuple_follows_key_fields() -> None:
    assert ListenerKey(1).to_tuple() == (1,)
    assert MessageKey(1, 2, 3).to_tuple() == (1, 2, 3, None, False)
    assert CallbackQueryKey(1, 2, 3).to_tuple() == (1, 2, 3, None, False)


def test_to_dict_follows_key_fields() -> None:
    assert ListenerKey(1).to_dict() == {"chat_id": 1}
    assert list(MessageKey(1, 2).to_dict().items()) == [
        ("chat_id", 1),
        ("user_id", 2),
        ("message_thread_id", None),
        ("direct_messages_topic_id", None),
        ("ephemeral", False),
    ]


def test_keys_are_frozen_and_slotted() -> None:
    for key in (ListenerKey(1), MessageKey(1), CallbackQueryKey(1)):
        assert not hasattr(key, "__dict__")
        with pytest.raises(dataclasses.FrozenInstanceError):
            key.chat_id = 2  # ty: ignore[invalid-assignment]


def test_keys_of_different_classes_are_never_equal() -> None:
    assert ListenerKey(1) != MessageKey(1)
    assert MessageKey(1) != CallbackQueryKey(1)


# --- MessageKey -----------------------------------------------------------------------


def test_message_key_defaults_match_any_message() -> None:
    assert MessageKey().to_tuple() == (None, None, None, None, False)


def test_message_key_from_message_keys_chat_sender_and_topics() -> None:
    message = make_message(1, 2, 5, message_thread_id=3, direct_messages_topic_id=4)

    assert MessageKey.from_message(message) == MessageKey(1, 2, 3, 4)


def test_message_key_from_message_without_a_sender_has_no_user() -> None:
    assert MessageKey.from_message(make_message(1, from_user=None)) == MessageKey(1)


def test_message_key_from_message_marks_an_ephemeral_message() -> None:
    message = make_message(1, 2, 0, ephemeral_message_id=4)

    assert MessageKey.from_message(message) == MessageKey(1, 2, ephemeral=True)


def test_message_key_from_sent_keys_chat_topics_and_the_given_user() -> None:
    sent = Message(id=5, chat=Chat(id=1), message_thread_id=3, direct_messages_topic_id=4)

    assert MessageKey.from_sent(sent) == MessageKey(1, None, 3, 4)
    assert MessageKey.from_sent(sent, 2) == MessageKey(1, 2, 3, 4)


def test_message_key_from_sent_marks_an_ephemeral_message() -> None:
    sent = Message(id=0, chat=Chat(id=1), ephemeral_message_id=4)

    assert MessageKey.from_sent(sent, 2) == MessageKey(1, 2, ephemeral=True)


# --- CallbackQueryKey -----------------------------------------------------------------


def test_callback_query_key_defaults_match_any_press() -> None:
    assert CallbackQueryKey().to_tuple() == (None, None, None, None, False)


def test_callback_query_key_with_an_inline_message_has_no_chat() -> None:
    key = CallbackQueryKey(user_id=2, inline_message_id="im")

    assert key.to_tuple() == (None, 2, None, "im", False)


def test_callback_query_key_from_callback_query_keys_chat_user_and_message() -> None:
    query = make_callback_query(chat_id=-100, user_id=9, message_id=42)

    assert CallbackQueryKey.from_callback_query(query) == CallbackQueryKey(-100, 9, 42)


def test_callback_query_key_from_callback_query_on_an_ephemeral_message() -> None:
    query = make_callback_query(chat_id=1, user_id=2, message_id=0)
    query.message.ephemeral_message_id = 4

    assert CallbackQueryKey.from_callback_query(query) == CallbackQueryKey(1, 2, ephemeral=True)


def test_callback_query_key_from_callback_query_on_an_inline_message() -> None:
    query = make_callback_query(user_id=2, message=None, inline_message_id="im")

    assert CallbackQueryKey.from_callback_query(query) == CallbackQueryKey(
        user_id=2, inline_message_id="im"
    )


def test_callback_query_key_from_callback_query_without_a_message_or_chat_is_none() -> None:
    assert CallbackQueryKey.from_callback_query(make_callback_query(message=None)) is None

    query = make_callback_query()
    query.message.chat = None
    assert CallbackQueryKey.from_callback_query(query) is None


def _buttons(*buttons: InlineKeyboardButton) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([list(buttons)])


CALLBACK_MARKUP = _buttons(InlineKeyboardButton("Yes", callback_data="y"))
"""Markup with one button that sends a callback query."""


def test_callback_query_key_from_sent_keys_chat_message_and_the_given_user() -> None:
    sent = Message(id=5, chat=Chat(id=1), reply_markup=CALLBACK_MARKUP)

    assert CallbackQueryKey.from_sent(sent) == CallbackQueryKey(1, None, 5)
    assert CallbackQueryKey.from_sent(sent, 2) == CallbackQueryKey(1, 2, 5)


def test_callback_query_key_from_sent_on_an_ephemeral_message() -> None:
    sent = Message(id=0, chat=Chat(id=1), ephemeral_message_id=4, reply_markup=CALLBACK_MARKUP)

    assert CallbackQueryKey.from_sent(sent, 2) == CallbackQueryKey(1, 2, ephemeral=True)


def test_callback_query_key_from_sent_accepts_a_game_button() -> None:
    sent = Message(
        id=5,
        chat=Chat(id=1),
        reply_markup=_buttons(
            InlineKeyboardButton("Site", url="https://example.com"),
            InlineKeyboardButton("Play", callback_game=CallbackGame()),
        ),
    )

    assert CallbackQueryKey.from_sent(sent) == CallbackQueryKey(1, None, 5)


@pytest.mark.parametrize(
    "markup",
    [
        None,
        _buttons(InlineKeyboardButton("Site", url="https://example.com")),
        InlineKeyboardMarkup([]),
    ],
    ids=["no-markup", "no-callback-button", "empty-keyboard"],
)
def test_callback_query_key_from_sent_refuses_a_message_nothing_can_press(
    markup: InlineKeyboardMarkup | None,
) -> None:
    sent = Message(id=5, chat=Chat(id=1), reply_markup=markup)

    with pytest.raises(ValueError, match="no button that sends a callback query"):
        CallbackQueryKey.from_sent(sent, 2)


def test_callback_query_key_from_callback_query_takes_the_presser_not_the_sender() -> None:
    query = CallbackQuery(
        id="q",
        from_user=User(id=2),
        chat_instance="c",
        message=Message(id=3, chat=Chat(id=1), from_user=User(id=99)),
    )

    assert CallbackQueryKey.from_callback_query(query) == CallbackQueryKey(1, 2, 3)


def test_listener_key_all() -> None:
    assert listener_key_module.__all__ == ("ListenerKey", "MessageKey", "CallbackQueryKey")
