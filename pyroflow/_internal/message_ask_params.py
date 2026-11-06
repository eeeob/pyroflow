"""Pyrogram arguments `Message.ask` and `Message.ask_rich` accept, for type checkers.

Each class stands alone, with every argument any supported kurigram accepts,
so an argument may be unknown to the installed one; a comment names the
versions of such an argument, and of those Pyrogram deprecated.
"""

from __future__ import annotations as _annotations

from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from datetime import datetime

    from pyrogram import enums as pyro_enums, types as pyro_types


class MessageAskSendKw(TypedDict, total=False):
    """What `Message.ask` accepts when it replies with a text, as `Message.reply`."""

    parse_mode: pyro_enums.ParseMode | None
    """How the text is parsed; `None` uses the client default."""
    entities: list[pyro_types.MessageEntity] | None
    """Entities to use instead of `parse_mode`."""
    link_preview_options: pyro_types.LinkPreviewOptions | None
    """Link preview options for the message."""
    disable_notification: bool | None
    """Send the message silently."""
    effect_id: int | None
    """Message effect to apply."""
    schedule_date: datetime | None
    """Date to send the message at."""
    repeat_period: int | None
    """Interval in seconds to repeat the message at."""
    protect_content: bool | None
    """Protect the message from forwarding and saving."""
    allow_paid_broadcast: bool | None
    """Allow a paid broadcast."""
    paid_message_star_count: int | None
    """Telegram Stars paid to send the message."""
    suggested_post_parameters: pyro_types.SuggestedPostParameters | None
    """Parameters of a suggested channel post."""
    reply_markup: (
        pyro_types.InlineKeyboardMarkup
        | pyro_types.ReplyKeyboardMarkup
        | pyro_types.ReplyKeyboardRemove
        | pyro_types.ForceReply
        | None
    )
    """Keyboard to attach."""


class MessageAskEditKw(TypedDict, total=False):
    """What `Message.ask` accepts when it edits a text, as `Message.edit`."""

    parse_mode: pyro_enums.ParseMode | None
    """How the text is parsed; `None` uses the client default."""
    entities: list[pyro_types.MessageEntity] | None
    """Entities to use instead of `parse_mode`."""
    link_preview_options: pyro_types.LinkPreviewOptions | None
    """Link preview options for the message."""
    reply_markup: pyro_types.InlineKeyboardMarkup | None
    """Keyboard to attach."""


class MessageAskRichSendKw(TypedDict, total=False):
    """What `Message.ask_rich` accepts when it replies, as `Message.reply_rich`."""

    disable_notification: bool | None
    """Send the message silently."""
    protect_content: bool | None
    """Protect the message from forwarding and saving."""
    allow_paid_broadcast: bool | None
    """Allow a paid broadcast."""
    effect_id: int | None
    """Message effect to apply."""
    suggested_post_parameters: pyro_types.SuggestedPostParameters | None
    """Parameters of a suggested channel post."""
    reply_markup: (
        pyro_types.InlineKeyboardMarkup
        | pyro_types.ReplyKeyboardMarkup
        | pyro_types.ReplyKeyboardRemove
        | pyro_types.ForceReply
        | None
    )
    """Keyboard to attach."""


class MessageAskRichEditKw(TypedDict, total=False):
    """What `Message.ask_rich` accepts when it edits, as `Message.edit` with `rich_message`."""

    reply_markup: pyro_types.InlineKeyboardMarkup | None
    """Keyboard to attach."""


__all__ = (
    "MessageAskSendKw",
    "MessageAskEditKw",
    "MessageAskRichSendKw",
    "MessageAskRichEditKw",
)
