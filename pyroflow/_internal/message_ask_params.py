"""Pyrogram arguments the `Message.ask_*` methods accept, for type checkers.

Each class holds the arguments of its kurigram counterpart
(`Message.edit_text`, `reply` or `reply_rich`) without what the method
fills in and without what does not suit `ask`: scheduling, since `ask`
waits for the answer to a question asked now.

There is one class for each of plain and rich text, editing
(`force_send=False`) and sending (`force_send=True`). The classes are
kept in sync with every kurigram release, and `tests/_internal` fails
when they drift from their counterparts.
"""

from __future__ import annotations as _annotations

from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from pyrogram import enums as pyro_enums, types as pyro_types


class MessageAskSendKw(TypedDict, total=False):
    """What `Message.ask`, `ask_callback_query` and `flow_reply` accept to reply with a text: `Message.reply` without `text` and scheduling."""

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
    """What `Message.ask`, `ask_callback_query` and `flow_edit` accept to edit a text: `Message.edit_text` without `text` and `rich_message`."""

    parse_mode: pyro_enums.ParseMode | None
    """How the text is parsed; `None` uses the client default."""
    entities: list[pyro_types.MessageEntity] | None
    """Entities to use instead of `parse_mode`."""
    link_preview_options: pyro_types.LinkPreviewOptions | None
    """Link preview options for the message."""
    reply_markup: pyro_types.InlineKeyboardMarkup | None
    """Keyboard to attach."""


class MessageAskRichSendKw(TypedDict, total=False):
    """What the `Message.ask_*_rich` methods and `flow_reply_rich` accept to reply: `Message.reply_rich` without `rich_message`."""

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
    """What the `Message.ask_*_rich` methods and `flow_edit_rich` accept to edit: `Message.edit_text` without `rich_message` and what only a text takes."""

    link_preview_options: pyro_types.LinkPreviewOptions | None
    """Link preview options for the message."""
    reply_markup: pyro_types.InlineKeyboardMarkup | None
    """Keyboard to attach."""


__all__ = (
    "MessageAskSendKw",
    "MessageAskEditKw",
    "MessageAskRichSendKw",
    "MessageAskRichEditKw",
)
