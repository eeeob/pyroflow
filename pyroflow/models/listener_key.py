"""Listener keys: what a wait takes, one class per update type."""

from __future__ import annotations as _annotations

from dataclasses import dataclass, field, fields
from typing import ClassVar, TYPE_CHECKING

from pytrove import classproperty

if TYPE_CHECKING:
    import sys

    if sys.version_info >= (3, 11):
        from typing import Self
    else:
        from typing_extensions import Self

    from ..types import CallbackQuery, Message


def _answering_user(sent: Message) -> int | None:
    """Return the user who answers `sent`, as the message itself tells.

    That is the receiver of an ephemeral `sent`, or else the sender of the
    message `sent` replies to, unless that message is the client's own
    (`editable`) or has no sender. Pyrogram builds both from the arguments
    `sent` was sent with, such as `ephemeral_message_parameters` and
    `reply_parameters`.

    Args:
        sent: The message just sent or edited.

    Returns:
        The user's id, or `None` if the message names no one.
    """
    if sent.receiver_user is not None:
        return sent.receiver_user.id

    replied = sent.reply_to_message

    if replied is None or replied.editable:
        return None

    return getattr(replied.from_user, "id", None)


@dataclass(frozen=True, slots=True)
class ListenerKey:
    """Identifies what a wait takes: each field narrows it, and `None` means any value.

    A subclass adds the fields of its update type. The key holds the values
    as given, and changes none of them. A field marked `exact` in its
    metadata is always compared, `None` included, so it splits the waits
    rather than narrowing them.

    Example:
        >>> ListenerKey(1).to_dict()
        {'chat_id': 1}
    """

    chat_id: int | None = None
    """The chat the wait is in, or `None` for any chat."""

    if TYPE_CHECKING:
        # Spelled out for type checkers, which cannot solve the decorator `classproperty(cached=True)`.
        key_fields: ClassVar[tuple[str, ...]]
        """The names of the key's fields, in order; computed once per class."""
        exact_fields: ClassVar[tuple[str, ...]]
        """The names of the fields marked `exact`, in order; computed once per class."""
    else:

        @classproperty(cached=True)
        def key_fields(cls) -> tuple[str, ...]:
            """The names of the key's fields, in order; computed once per class.

            Example:
                >>> MessageKey.key_fields
                ('chat_id', 'user_id', 'message_thread_id', 'direct_messages_topic_id', 'ephemeral')
            """
            return tuple(f.name for f in fields(cls))

        @classproperty(cached=True)
        def exact_fields(cls) -> tuple[str, ...]:
            """The names of the fields marked `exact`, in order; computed once per class.

            Example:
                >>> MessageKey.exact_fields
                ('ephemeral',)
            """
            return tuple(f.name for f in fields(cls) if f.metadata.get("exact"))

    def to_tuple(self) -> tuple[object, ...]:
        """Return the key's values, in field order.

        Example:
            >>> MessageKey(1, 2).to_tuple()
            (1, 2, None, None, False)
        """
        return tuple(getattr(self, name) for name in self.key_fields)

    def to_dict(self) -> dict[str, object]:
        """Return the key's values by field name, in field order.

        Example:
            >>> CallbackQueryKey(1, 2, 3).to_dict()
            {'chat_id': 1, 'user_id': 2, 'message_id': 3, 'inline_message_id': None, 'ephemeral': False}
        """
        return {name: getattr(self, name) for name in self.key_fields}


@dataclass(frozen=True, slots=True)
class MessageKey(ListenerKey):
    """Identifies the messages a wait takes: by chat, sender and topic.

    Example:
        >>> MessageKey(user_id=2)
        MessageKey(chat_id=None, user_id=2, message_thread_id=None, direct_messages_topic_id=None, ephemeral=False)
    """

    user_id: int | None = None
    """The sender, or `None` for any sender."""
    message_thread_id: int | None = None
    """The forum topic, or `None` for any topic."""
    direct_messages_topic_id: int | None = None
    """The topic of a channel's direct messages chat, or `None` for any."""
    ephemeral: bool = field(default=False, metadata={"exact": True})
    """Whether the wait takes ephemeral messages, and only them."""

    @classmethod
    def from_message(cls, message: Message) -> Self:
        """Key an incoming message by its chat, sender and topics.

        Args:
            message: The message; it must have a chat.

        Returns:
            The key of the message.

        Example:
            >>> from pyrogram.types import Chat, Message, User
            >>> MessageKey.from_message(Message(id=5, chat=Chat(id=1), from_user=User(id=2)))
            MessageKey(chat_id=1, user_id=2, message_thread_id=None, direct_messages_topic_id=None, ephemeral=False)
        """
        return cls(
            message.chat.id,  # ty: ignore[unresolved-attribute]  # the caller passes a message with a chat
            # `from_user` can be `None` (an anonymous admin, a channel post).
            getattr(message.from_user, "id", None),
            message.message_thread_id,
            message.direct_messages_topic_id,
            message.ephemeral_message_id is not None,
        )

    @classmethod
    def from_sent(cls, sent: Message, user_id: int | None = None) -> Self:
        """Key the answer to a message just sent or edited: its chat and topics.

        Args:
            sent: The message sent or edited.
            user_id: The user to wait for. With `None`, the receiver of an
                ephemeral `sent`, or the sender of the message `sent` replies
                to unless it is the client's own; otherwise any user.

        Returns:
            The key of the answer.

        Example:
            >>> from pyrogram.types import Chat, Message
            >>> MessageKey.from_sent(Message(id=5, chat=Chat(id=1), message_thread_id=3), 2)
            MessageKey(chat_id=1, user_id=2, message_thread_id=3, direct_messages_topic_id=None, ephemeral=False)
        """
        return cls(
            sent.chat.id,  # ty: ignore[unresolved-attribute]  # a sent message has a chat
            _answering_user(sent) if user_id is None else user_id,
            sent.message_thread_id,
            sent.direct_messages_topic_id,
            sent.ephemeral_message_id is not None,
        )


@dataclass(frozen=True, slots=True)
class CallbackQueryKey(ListenerKey):
    """Identifies the button presses a wait takes: by chat, user and message, or inline message.

    Example:
        >>> CallbackQueryKey(1, message_id=3)
        CallbackQueryKey(chat_id=1, user_id=None, message_id=3, inline_message_id=None, ephemeral=False)
    """

    user_id: int | None = None
    """The user who presses, or `None` for any user."""
    message_id: int | None = None
    """The message whose button is pressed, or `None` for any message."""
    inline_message_id: str | None = None
    """The inline-mode message whose button is pressed, or `None` for any."""
    ephemeral: bool = field(default=False, metadata={"exact": True})
    """Whether the wait takes presses on ephemeral messages, and only them."""

    @classmethod
    def from_callback_query(cls, query: CallbackQuery) -> Self | None:
        """Key a press by its message's chat, the user and the message.

        A press on an ephemeral message is keyed with no `message_id` and
        `ephemeral` set, as ephemeral ids can repeat. A press on a message
        sent in inline mode has no message, so it is keyed by the user and
        `inline_message_id`.

        Args:
            query: The callback query.

        Returns:
            The key of the press, or `None` if it has neither a message
            with a chat nor an `inline_message_id`.

        Example:
            >>> from pyrogram.types import CallbackQuery, Chat, Message, User
            >>> query = CallbackQuery(
            ...     id="q", from_user=User(id=2), chat_instance="c", message=Message(id=3, chat=Chat(id=1))
            ... )
            >>> CallbackQueryKey.from_callback_query(query)
            CallbackQueryKey(chat_id=1, user_id=2, message_id=3, inline_message_id=None, ephemeral=False)
        """
        m = query.message

        if m is None or m.chat is None:
            if query.inline_message_id is None:
                return None

            return cls(user_id=query.from_user.id, inline_message_id=query.inline_message_id)

        if m.ephemeral_message_id is not None:
            return cls(m.chat.id, query.from_user.id, ephemeral=True)

        return cls(m.chat.id, query.from_user.id, m.id)

    @classmethod
    def from_sent(cls, sent: Message, user_id: int | None = None) -> Self:
        """Key a press on a message just sent or edited.

        Args:
            sent: The message sent or edited.
            user_id: The user to wait for. With `None`, the receiver of an
                ephemeral `sent`, or the sender of the message `sent` replies
                to unless it is the client's own; otherwise any user.

        Returns:
            The key of a press on `sent`, or on any ephemeral message if
            `sent` is one.

        Example:
            >>> from pyrogram.types import (
            ...     Chat, InlineKeyboardButton, InlineKeyboardMarkup, Message,
            ... )
            >>> markup = InlineKeyboardMarkup([[InlineKeyboardButton("Yes", callback_data="y")]])
            >>> CallbackQueryKey.from_sent(Message(id=5, chat=Chat(id=1), reply_markup=markup))
            CallbackQueryKey(chat_id=1, user_id=None, message_id=5, inline_message_id=None, ephemeral=False)
        """
        chat_id = sent.chat.id  # ty: ignore[unresolved-attribute]  # a sent message has a chat

        if user_id is None:
            user_id = _answering_user(sent)

        if sent.ephemeral_message_id is not None:
            return cls(chat_id, user_id, ephemeral=True)

        return cls(chat_id, user_id, sent.id)


__all__ = (
    "ListenerKey",
    "MessageKey",
    "CallbackQueryKey",
)
