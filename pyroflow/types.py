"""Pyrogram update types patched with conversation helpers such as `Message.ask`."""

from __future__ import annotations as _annotations

import sys
from typing import (
    Any,
    Literal,
    overload,
    TYPE_CHECKING,
)

if sys.version_info >= (3, 11):
    from typing import Self
else:
    from typing_extensions import Self

from pyrogram import types as pyro_types, enums as pyro_enums
from pyrogram.types import (
    Message as PyroMessage,
    CallbackQuery as PyroCallbackQuery,
    User as PyroUser,
    Update as PyroUpdate,
)

from .utils import patch_cls


if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping, Iterable
    from datetime import datetime

    from pytrove.typings import Number, JsonValue as JsonValueT

    from .client import Client
    from .typings import UpdateType, AskErrorHandlersT, ListenMessageIdT


@patch_cls
class Update(PyroUpdate):
    """Pyrogram `Update` extended with a per-update `context` dict."""

    @property
    def context(self) -> dict[str, Any] | None:
        """Arbitrary data attached to this update, or `None` if none is set.

        Setting it to `None` removes it.

        Example:
            >>> message = Message(id=1)
            >>> message.context = {"step": 1}
            >>> message.context
            {'step': 1}
            >>> message.context = None
            >>> message.context is None
            True
        """
        try:
            return self.__context
        except AttributeError:
            return

    @context.setter
    def context(self, value: dict[str, Any] | None) -> None:
        """Attach `value` as the context, or remove it when `value` is `None`."""
        if value is None:
            try:
                del self.__context
            except AttributeError:
                pass
        else:
            self.__context = value

    @context.deleter
    def context(self) -> None:
        """Remove the context.

        Raises:
            AttributeError: If no context is set.
        """
        del self.__context

    @overload
    def with_ctx(self, m: Mapping[str, Any], /, **kwargs: Any) -> Self: ...
    @overload
    def with_ctx(self, m: Iterable[tuple[str, Any]], /, **kwargs: Any) -> Self: ...
    @overload
    def with_ctx(self, **kwargs: Any) -> Self: ...
    def with_ctx(self, *args: Any, **kwargs: Any) -> Self:
        """Merge into `context` (same arguments as `dict.update`) and return `self`.

        Creates the context first if none is set.

        Example:
            >>> Message(id=1).with_ctx({"step": 1}, lang="en").context
            {'step': 1, 'lang': 'en'}
        """
        context = self.context
        if context is None:
            self.context = context = {}
        context.update(*args, **kwargs)

        return self


@patch_cls
class User(PyroUser):
    """Pyrogram `User` extended with `lang_code`."""

    _client: Client
    """Client that received this user."""

    @property
    def lang_code(self) -> str | None:
        """Primary language subtag of `language_code`, lowercased, or `None` if unknown.

        Example:
            >>> User(id=1, language_code="pt-BR").lang_code
            'pt'
            >>> User(id=2).lang_code is None
            True
        """
        return lang.split("-")[0].lower() if (lang := self.language_code) else None


if TYPE_CHECKING:

    class User(User, Update):
        """Typing-only view of `User` that also exposes the patched `Update` members."""


@patch_cls
class Message(PyroMessage):
    """Pyrogram `Message` extended with `ask`, `editable` and `respond`."""

    _client: Client
    """Client that received or sent this message."""
    from_user: User | None
    """Sender of the message, or `None` for messages sent on behalf of a chat."""

    @overload
    async def ask(
        self,
        text: str,
        force_send: Literal[False] = False,
        *,
        parse_mode: pyro_enums.ParseMode | None = None,
        entities: list[pyro_types.MessageEntity] | None = None,
        link_preview_options: pyro_types.LinkPreviewOptions | None = None,
        reply_markup: pyro_types.InlineKeyboardMarkup | None = None,
        # listen params
        listen_user_id: int | None = None,
        listen_message_id: ListenMessageIdT | None = None,
        meta: JsonValueT | None = None,
        timeout: Number | None = None,
        update_type: type[Message] = ...,
        error_handlers: AskErrorHandlersT | None = None,
        **kw: Any,
    ) -> Message: ...
    @overload
    async def ask(
        self,
        text: str,
        force_send: Literal[False] = False,
        *,
        parse_mode: pyro_enums.ParseMode | None = None,
        entities: list[pyro_types.MessageEntity] | None = None,
        link_preview_options: pyro_types.LinkPreviewOptions | None = None,
        reply_markup: pyro_types.InlineKeyboardMarkup | None = None,
        # listen params
        listen_user_id: int | None = None,
        listen_message_id: ListenMessageIdT | None = None,
        meta: JsonValueT | None = None,
        timeout: Number | None = None,
        update_type: type[UpdateType],
        error_handlers: AskErrorHandlersT | None = None,
        **kw: Any,
    ) -> UpdateType: ...
    @overload
    async def ask(
        self,
        text: str,
        force_send: Literal[True],
        *,
        parse_mode: pyro_enums.ParseMode | None = None,
        entities: list[pyro_types.MessageEntity] | None = None,
        link_preview_options: pyro_types.LinkPreviewOptions | None = None,
        reply_parameters: pyro_types.ReplyParameters | None = None,
        disable_notification: bool | None = None,
        message_thread_id: int | None = None,
        direct_messages_topic_id: int | None = None,
        effect_id: int | None = None,
        schedule_date: datetime | None = None,
        repeat_period: int | None = None,
        protect_content: bool | None = None,
        allow_paid_broadcast: bool | None = None,
        paid_message_star_count: int | None = None,
        suggested_post_parameters: pyro_types.SuggestedPostParameters | None = None,
        reply_markup: pyro_types.InlineKeyboardMarkup
        | pyro_types.ReplyKeyboardMarkup
        | pyro_types.ReplyKeyboardRemove
        | pyro_types.ForceReply
        | None = None,
        # listen params
        listen_user_id: int | None = None,
        listen_message_id: ListenMessageIdT | None = None,
        meta: JsonValueT | None = None,
        timeout: Number | None = None,
        update_type: type[Message] = ...,
        error_handlers: AskErrorHandlersT | None = None,
        **kw: Any,
    ) -> Message: ...
    @overload
    async def ask(
        self,
        text: str,
        force_send: Literal[True],
        *,
        parse_mode: pyro_enums.ParseMode | None = None,
        entities: list[pyro_types.MessageEntity] | None = None,
        link_preview_options: pyro_types.LinkPreviewOptions | None = None,
        reply_parameters: pyro_types.ReplyParameters | None = None,
        disable_notification: bool | None = None,
        message_thread_id: int | None = None,
        direct_messages_topic_id: int | None = None,
        effect_id: int | None = None,
        schedule_date: datetime | None = None,
        repeat_period: int | None = None,
        protect_content: bool | None = None,
        allow_paid_broadcast: bool | None = None,
        paid_message_star_count: int | None = None,
        suggested_post_parameters: pyro_types.SuggestedPostParameters | None = None,
        reply_markup: pyro_types.InlineKeyboardMarkup
        | pyro_types.ReplyKeyboardMarkup
        | pyro_types.ReplyKeyboardRemove
        | pyro_types.ForceReply
        | None = None,
        # listen params
        listen_user_id: int | None = None,
        listen_message_id: ListenMessageIdT | None = None,
        meta: JsonValueT | None = None,
        timeout: Number | None = None,
        update_type: type[UpdateType],
        error_handlers: AskErrorHandlersT | None = None,
        **kw: Any,
    ) -> UpdateType: ...

    async def ask(
        self,
        text: str,
        force_send: bool = False,
        *,
        parse_mode: pyro_enums.ParseMode | None = None,
        entities: list[pyro_types.MessageEntity] | None = None,
        link_preview_options: pyro_types.LinkPreviewOptions | None = None,
        reply_parameters: pyro_types.ReplyParameters | None = None,
        disable_notification: bool | None = None,
        message_thread_id: int | None = None,
        direct_messages_topic_id: int | None = None,
        effect_id: int | None = None,
        schedule_date: datetime | None = None,
        repeat_period: int | None = None,
        protect_content: bool | None = None,
        allow_paid_broadcast: bool | None = None,
        paid_message_star_count: int | None = None,
        suggested_post_parameters: pyro_types.SuggestedPostParameters | None = None,
        reply_markup: pyro_types.InlineKeyboardMarkup
        | pyro_types.ReplyKeyboardMarkup
        | pyro_types.ReplyKeyboardRemove
        | pyro_types.ForceReply
        | None = None,
        # listen params
        listen_user_id: int | None = None,
        listen_message_id: ListenMessageIdT | None = None,
        meta: JsonValueT | None = None,
        timeout: Number | None = None,
        update_type: type[PyroUpdate] = PyroMessage,
        error_handlers: AskErrorHandlersT | None = None,
        **kw: Any,
    ) -> PyroUpdate:
        """Send a new message or edit the current one, then wait for a matching update.

        If this message is `editable` and `force_send` is `False`, it is edited in
        place; otherwise a new message is sent as a reply to it. The send-only
        arguments (`reply_parameters` through `suggested_post_parameters`) must be
        left as `None` when editing.

        Args:
            text: The text to send or edit.
            force_send: Send a new reply even if this message is `editable`.
            parse_mode: How `text` is parsed; `None` uses the client default.
            entities: Entities to use instead of `parse_mode`.
            link_preview_options: Link preview options for the message.
            reply_parameters: Reply options; defaults to replying to this message.
            disable_notification: Send the message silently.
            message_thread_id: Target topic; defaults to this message's topic.
            direct_messages_topic_id: Target direct messages topic; defaults to this
                message's one.
            effect_id: Message effect to apply.
            schedule_date: Date to send the message at.
            repeat_period: Interval in seconds to repeat the message at.
            protect_content: Protect the message from forwarding and saving.
            allow_paid_broadcast: Allow a paid broadcast.
            paid_message_star_count: Telegram Stars paid to send the message.
            suggested_post_parameters: Parameters of a suggested channel post.
            reply_markup: Keyboard to attach; only `InlineKeyboardMarkup` when editing.
            listen_user_id: Only accept updates from this user.
            listen_message_id: Only accept updates for this message id, or a sync
                callable that receives the sent/edited message and returns the id (or
                `None` for no filter). It runs inline on the event loop, so keep it fast.
            meta: Metadata attached to the created listener.
            timeout: Seconds to wait before raising `ListenerTimeout`.
            update_type: Class of the update to wait for.
            error_handlers: `{exc_type_or_tuple: handler}` mapping. If listening
                raises, the handler of the first key matching `isinstance(exc, key)` is
                awaited as `handler(exc, m)` with `m` the sent/edited message. If none
                matches, the client-wide handlers for `update_type` are tried. The
                exception is re-raised either way.
            **kw: Passed through to `Client.ask`.

        Returns:
            The first matching update.

        Raises:
            RuntimeError: If no listener is registered for `update_type`.
            ValueError: If this is a service or empty message, or if send-only
                arguments are passed while the message is edited.
            ListenerTimeout: If no matching update arrives within `timeout`.
            ListenerCancelled: If the listener is cancelled while waiting.
        """
        if self.service or self.empty:
            msg = "Cannot call 'ask' on a service or empty message."
            raise ValueError(msg)

        message_id = None

        if not force_send and self.editable:
            message_id = self.id

        if message_id is None:
            if reply_parameters is None:
                reply_parameters = pyro_types.ReplyParameters(message_id=self.id)

            if message_thread_id is None:
                message_thread_id = self.message_thread_id

            if direct_messages_topic_id is None:
                direct_messages_topic_id = self.direct_messages_topic_id

        else:
            if any(
                v is not None
                for v in (
                    reply_parameters,
                    disable_notification,
                    message_thread_id,
                    direct_messages_topic_id,
                    effect_id,
                    schedule_date,
                    repeat_period,
                    protect_content,
                    allow_paid_broadcast,
                    paid_message_star_count,
                    suggested_post_parameters,
                )
            ):
                msg = (
                    "Cannot pass additional send options when reusing an existing message. "
                    "Use force_send=True to send a new message."
                )
                raise ValueError(msg)

        # `Client.ask` splits send/edit across overloads on `message_id`, which is
        # only known here at runtime; `Client.ask` enforces that contract itself.
        return await self._client.ask(  # ty: ignore[no-matching-overload]
            self.chat.id,  # ty: ignore[unresolved-attribute]  # `kurigram` types `Message.chat` as optional; a non-empty message always has one
            text,
            message_id,
            parse_mode=parse_mode,
            entities=entities,
            link_preview_options=link_preview_options,
            reply_parameters=reply_parameters,
            business_connection_id=self.business_connection_id,
            disable_notification=disable_notification,
            message_thread_id=message_thread_id,
            direct_messages_topic_id=direct_messages_topic_id,
            effect_id=effect_id,
            schedule_date=schedule_date,
            repeat_period=repeat_period,
            protect_content=protect_content,
            allow_paid_broadcast=allow_paid_broadcast,
            paid_message_star_count=paid_message_star_count,
            suggested_post_parameters=suggested_post_parameters,
            reply_markup=reply_markup,
            listen_user_id=listen_user_id,
            listen_message_id=listen_message_id,
            meta=meta,
            timeout=timeout,
            update_type=update_type,
            error_handlers=error_handlers,
            **kw,
        )

    @property
    def editable(self) -> bool:
        """`True` if this message was sent by the client itself, so it can be edited."""
        return getattr(self.from_user, "is_self", False) or getattr(
            self.sender_chat, "id", None
        ) == getattr(self._client.me, "id", 0)

    @property
    def respond(self) -> Callable[..., Awaitable[PyroMessage | None]]:
        """`edit` if this message is `editable`, otherwise `reply`."""
        return self.edit if self.editable else self.reply


if TYPE_CHECKING:

    class Message(Message, Update):
        """Typing-only view of `Message` that also exposes the patched `Update` members."""


@patch_cls
class CallbackQuery(PyroCallbackQuery):
    """Pyrogram `CallbackQuery` with `message` and `from_user` typed as the patched classes."""

    _client: Client
    """Client that received this callback query."""
    message: Message | None
    """Message with the pressed button, or `None` for a button on an inline-mode message."""
    from_user: User
    """User who pressed the button."""


if TYPE_CHECKING:

    class CallbackQuery(CallbackQuery, Update):
        """Typing-only view of `CallbackQuery` that also exposes the patched `Update` members."""


__all__ = (
    "User",
    "Message",
    "CallbackQuery",
    "Update",
)
