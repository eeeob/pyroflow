"""Pyrogram arguments `Client.ask` and `Client.ask_rich` accept, for type checkers.

Each class stands alone, with every argument any supported kurigram accepts,
so an argument may be unknown to the installed one; a comment names the
versions of such an argument, and of those Pyrogram deprecated.
"""

from __future__ import annotations as _annotations

from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from datetime import datetime

    from pyrogram import enums as pyro_enums, types as pyro_types


class AskSendKw(TypedDict, total=False):
    """What `Client.ask` accepts when it sends a text."""

    parse_mode: pyro_enums.ParseMode | None
    """How the text is parsed; `None` uses the client default."""
    entities: list[pyro_types.MessageEntity] | None
    """Entities to use instead of `parse_mode`."""
    link_preview_options: pyro_types.LinkPreviewOptions | None
    """Link preview options for the message."""
    disable_notification: bool | None
    """Send the message silently."""
    message_thread_id: int | None
    """Target topic."""
    direct_messages_topic_id: int | None
    """Target direct messages topic."""
    ephemeral_message_parameters: pyro_types.EphemeralMessageParameters | None
    """Parameters of an ephemeral message."""
    effect_id: int | None
    """Message effect to apply."""
    show_caption_above_media: bool | None  # deprecated in Pyrogram
    """Show the caption above the media."""
    reply_parameters: pyro_types.ReplyParameters | None
    """Reply options."""
    schedule_date: datetime | None
    """Date to send the message at."""
    repeat_period: int | None
    """Interval in seconds to repeat the message at."""
    protect_content: bool | None
    """Protect the message from forwarding and saving."""
    business_connection_id: str | None
    """Business connection to send through."""
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
    reply_to_message_id: int | None  # deprecated in Pyrogram
    """Message to reply to."""
    reply_to_chat_id: int | str | None  # deprecated in Pyrogram
    """Chat of the message to reply to."""
    reply_to_story_id: int | None  # deprecated in Pyrogram
    """Story to reply to."""
    quote_text: str | None  # deprecated in Pyrogram
    """Quoted part of the replied message."""
    quote_entities: list[pyro_types.MessageEntity] | None  # deprecated in Pyrogram
    """Entities of the quote."""
    quote_offset: int | None  # deprecated in Pyrogram
    """Position of the quote in the replied message."""
    disable_web_page_preview: bool | None  # deprecated in Pyrogram
    """Disable the link preview."""


class AskEditKw(TypedDict, total=False):
    """What `Client.ask` accepts when it edits a text."""

    parse_mode: pyro_enums.ParseMode | None
    """How the text is parsed; `None` uses the client default."""
    entities: list[pyro_types.MessageEntity] | None
    """Entities to use instead of `parse_mode`."""
    link_preview_options: pyro_types.LinkPreviewOptions | None
    """Link preview options for the message."""
    schedule_date: datetime | None
    """Date to send the edited message at."""
    business_connection_id: str | None
    """Business connection to edit through."""
    reply_markup: pyro_types.InlineKeyboardMarkup | None
    """Keyboard to attach."""
    show_caption_above_media: bool | None  # deprecated in Pyrogram
    """Show the caption above the media."""
    disable_web_page_preview: bool | None  # deprecated in Pyrogram
    """Disable the link preview."""


class AskRichSendKw(TypedDict, total=False):
    """What `Client.ask_rich` accepts when it sends a rich message."""

    disable_notification: bool | None
    """Send the message silently."""
    message_thread_id: int | None
    """Target topic."""
    direct_messages_topic_id: int | None
    """Target direct messages topic."""
    ephemeral_message_parameters: pyro_types.EphemeralMessageParameters | None
    """Parameters of an ephemeral message."""
    effect_id: int | None
    """Message effect to apply."""
    reply_parameters: pyro_types.ReplyParameters | None
    """Reply options."""
    protect_content: bool | None
    """Protect the message from forwarding and saving."""
    allow_paid_broadcast: bool | None
    """Allow a paid broadcast."""
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


class AskRichEditKw(TypedDict, total=False):
    """What `Client.ask_rich` accepts when it edits to a rich message."""

    schedule_date: datetime | None
    """Date to send the edited message at."""
    business_connection_id: str | None
    """Business connection to edit through."""
    reply_markup: pyro_types.InlineKeyboardMarkup | None
    """Keyboard to attach."""


__all__ = (
    "AskSendKw",
    "AskEditKw",
    "AskRichSendKw",
    "AskRichEditKw",
)
