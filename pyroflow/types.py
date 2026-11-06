"""Pyrogram update types patched with conversation helpers such as `Message.ask`."""

from __future__ import annotations as _annotations

from typing import (
    Any,
    Literal,
    overload,
    TYPE_CHECKING,
)

from pyrogram import types as pyro_types
from pyrogram.types import (
    Message as PyroMessage,
    CallbackQuery as PyroCallbackQuery,
    User as PyroUser,
    Update as PyroUpdate,
)

from .enums import ListenMessageId
from .utils import patch_cls


if TYPE_CHECKING:
    import sys

    if sys.version_info >= (3, 11):
        from typing import Unpack
    else:
        from typing_extensions import Unpack

    from pyrogram.filters import Filter
    from pyrogram.types import InputRichMessage
    from pytrove.typings import Number

    from ._internal import (
        MessageAskEditKw,
        MessageAskRichEditKw,
        MessageAskRichSendKw,
        MessageAskSendKw,
    )
    from .client import Client
    from .models import ListenerContext
    from .typings import UpdateType, ListenMessageIdT


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
        listen_user_id: int | None = None,
        listen_message_id: ListenMessageIdT | None = ListenMessageId.AUTO,
        listen_context: ListenerContext | None = None,
        listen_filters: Filter | None = None,
        listen_strict: bool = False,
        listen_timeout: Number | None = None,
        listen_update_type: type[Message] = ...,
        **kw: Unpack[MessageAskEditKw],
    ) -> Message: ...
    @overload
    async def ask(
        self,
        text: str,
        force_send: Literal[False] = False,
        *,
        listen_user_id: int | None = None,
        listen_message_id: ListenMessageIdT | None = ListenMessageId.AUTO,
        listen_context: ListenerContext | None = None,
        listen_filters: Filter | None = None,
        listen_strict: bool = False,
        listen_timeout: Number | None = None,
        listen_update_type: type[UpdateType],
        **kw: Unpack[MessageAskEditKw],
    ) -> UpdateType: ...
    @overload
    async def ask(
        self,
        text: str,
        force_send: Literal[True],
        *,
        listen_user_id: int | None = None,
        listen_message_id: ListenMessageIdT | None = ListenMessageId.AUTO,
        listen_context: ListenerContext | None = None,
        listen_filters: Filter | None = None,
        listen_strict: bool = False,
        listen_timeout: Number | None = None,
        listen_update_type: type[Message] = ...,
        **kw: Unpack[MessageAskSendKw],
    ) -> Message: ...
    @overload
    async def ask(
        self,
        text: str,
        force_send: Literal[True],
        *,
        listen_user_id: int | None = None,
        listen_message_id: ListenMessageIdT | None = ListenMessageId.AUTO,
        listen_context: ListenerContext | None = None,
        listen_filters: Filter | None = None,
        listen_strict: bool = False,
        listen_timeout: Number | None = None,
        listen_update_type: type[UpdateType],
        **kw: Unpack[MessageAskSendKw],
    ) -> UpdateType: ...

    async def ask(
        self,
        text: str,
        force_send: bool = False,
        *,
        listen_user_id: int | None = None,
        listen_message_id: ListenMessageIdT | None = ListenMessageId.AUTO,
        listen_context: ListenerContext | None = None,
        listen_filters: Filter | None = None,
        listen_strict: bool = False,
        listen_timeout: Number | None = None,
        listen_update_type: type[PyroUpdate] = PyroMessage,
        **kw: Any,
    ) -> PyroUpdate:
        """Send a new message or edit the current one, then wait for a matching update.

        If this message is `editable` and `force_send` is `False`, it is edited in
        place; otherwise a new message is sent as a reply to it, by default in
        this message's topic.

        Args:
            text: The text to send or edit.
            force_send: Send a new reply even if this message is `editable`.
            listen_user_id: Only accept updates from this user.
            listen_message_id: Only accept updates for this message id; see
                `Client.ask` for `None` and the `ListenMessageId` values, and
                for the default `AUTO`.
            listen_context: Values attached to the created listener; see
                `Client.ask`.
            listen_filters: A Pyrogram filter the awaited update must pass; see
                `Client.ask`.
            listen_strict: Whether an update that fails `listen_filters` ends the wait with
                `ListenerRejected` instead of being skipped; see `Client.ask`.
            listen_timeout: Seconds to wait before raising `ListenerTimeout`.
            listen_update_type: Class of the update to wait for.
            **kw: Passed through to `Client.ask`.

        Returns:
            The first matching update.

        Raises:
            RuntimeError: If no listener is registered for `listen_update_type`.
            ValueError: If this is a service or empty message.
            ListenerTimeout: If no matching update arrives within `listen_timeout`.
            ListenerCancelled: If the listener is cancelled while waiting.
            ListenerWorkersBusy: Or its subclass `ListenerEvictionTimeout`, if the wait would start inside a handler with
                too few workers free (see `WorkersPolicy`). The message is
                already sent or edited by then.
        """
        message_id = self._ask_target(force_send, kw)

        # `Client.ask` splits send/edit across overloads on `message_id`, which is
        # only known here at runtime; `Client.ask` enforces that contract itself.
        return await self._client.ask(  # ty: ignore[no-matching-overload]
            self.chat.id,  # ty: ignore[unresolved-attribute]  # `kurigram` types `Message.chat` as optional; a non-empty message always has one
            text,
            message_id,
            business_connection_id=self.business_connection_id,
            listen_user_id=listen_user_id,
            listen_message_id=listen_message_id,
            listen_context=listen_context,
            listen_filters=listen_filters,
            listen_strict=listen_strict,
            listen_timeout=listen_timeout,
            listen_update_type=listen_update_type,
            **kw,
        )

    @overload
    async def ask_rich(
        self,
        rich_message: InputRichMessage,
        force_send: Literal[False] = False,
        *,
        listen_user_id: int | None = None,
        listen_message_id: ListenMessageIdT | None = ListenMessageId.AUTO,
        listen_context: ListenerContext | None = None,
        listen_filters: Filter | None = None,
        listen_strict: bool = False,
        listen_timeout: Number | None = None,
        listen_update_type: type[Message] = ...,
        **kw: Unpack[MessageAskRichEditKw],
    ) -> Message: ...
    @overload
    async def ask_rich(
        self,
        rich_message: InputRichMessage,
        force_send: Literal[False] = False,
        *,
        listen_user_id: int | None = None,
        listen_message_id: ListenMessageIdT | None = ListenMessageId.AUTO,
        listen_context: ListenerContext | None = None,
        listen_filters: Filter | None = None,
        listen_strict: bool = False,
        listen_timeout: Number | None = None,
        listen_update_type: type[UpdateType],
        **kw: Unpack[MessageAskRichEditKw],
    ) -> UpdateType: ...
    @overload
    async def ask_rich(
        self,
        rich_message: InputRichMessage,
        force_send: Literal[True],
        *,
        listen_user_id: int | None = None,
        listen_message_id: ListenMessageIdT | None = ListenMessageId.AUTO,
        listen_context: ListenerContext | None = None,
        listen_filters: Filter | None = None,
        listen_strict: bool = False,
        listen_timeout: Number | None = None,
        listen_update_type: type[Message] = ...,
        **kw: Unpack[MessageAskRichSendKw],
    ) -> Message: ...
    @overload
    async def ask_rich(
        self,
        rich_message: InputRichMessage,
        force_send: Literal[True],
        *,
        listen_user_id: int | None = None,
        listen_message_id: ListenMessageIdT | None = ListenMessageId.AUTO,
        listen_context: ListenerContext | None = None,
        listen_filters: Filter | None = None,
        listen_strict: bool = False,
        listen_timeout: Number | None = None,
        listen_update_type: type[UpdateType],
        **kw: Unpack[MessageAskRichSendKw],
    ) -> UpdateType: ...

    async def ask_rich(
        self,
        rich_message: InputRichMessage,
        force_send: bool = False,
        *,
        listen_user_id: int | None = None,
        listen_message_id: ListenMessageIdT | None = ListenMessageId.AUTO,
        listen_context: ListenerContext | None = None,
        listen_filters: Filter | None = None,
        listen_strict: bool = False,
        listen_timeout: Number | None = None,
        listen_update_type: type[PyroUpdate] = PyroMessage,
        **kw: Any,
    ) -> PyroUpdate:
        """Send a new rich message or edit the current one, then wait for a matching update.

        Like `ask`, but goes through `Client.ask_rich`.

        Args:
            rich_message: The rich message to send or edit.
            force_send: Send a new reply even if this message is `editable`.
            listen_user_id: As in `ask`.
            listen_message_id: As in `ask`.
            listen_context: As in `ask`.
            listen_filters: As in `ask`.
            listen_strict: As in `ask`.
            listen_timeout: As in `ask`.
            listen_update_type: As in `ask`.
            **kw: Passed through to `Client.ask_rich`.

        Returns:
            The first matching update.

        Raises:
            RuntimeError: If no listener is registered for `listen_update_type`.
            ValueError: If this is a service or empty message.
            ListenerTimeout: If no matching update arrives within `listen_timeout`.
            ListenerCancelled: If the listener is cancelled while waiting.
            ListenerWorkersBusy: Or its subclass `ListenerEvictionTimeout`, if the wait would start inside a handler with
                too few workers free (see `WorkersPolicy`). The message is
                already sent or edited by then.
        """
        message_id = self._ask_target(force_send, kw)

        # `send_rich_message` takes no `business_connection_id` since kurigram 2.2.25.
        if message_id is not None:
            kw["business_connection_id"] = self.business_connection_id

        # Same runtime-only `message_id` split as in `ask`.
        return await self._client.ask_rich(  # ty: ignore[no-matching-overload]
            self.chat.id,  # ty: ignore[unresolved-attribute]  # `kurigram` types `Message.chat` as optional; a non-empty message always has one
            rich_message,
            message_id,
            listen_user_id=listen_user_id,
            listen_message_id=listen_message_id,
            listen_context=listen_context,
            listen_filters=listen_filters,
            listen_strict=listen_strict,
            listen_timeout=listen_timeout,
            listen_update_type=listen_update_type,
            **kw,
        )

    def _ask_target(self, force_send: bool, kw: dict[str, Any]) -> int | None:
        """Decide whether `ask` edits this message or replies to it.

        When replying, `kw` gets the reply defaults for what it leaves as `None`.

        Args:
            force_send: Reply even if this message is `editable`.
            kw: The Pyrogram arguments `ask` was given.

        Returns:
            This message's id when editing, otherwise `None`.

        Raises:
            ValueError: If this is a service or empty message.
        """
        if self.service or self.empty:
            msg = "Cannot call 'ask' on a service or empty message."
            raise ValueError(msg)

        if not force_send and self.editable:
            return self.id

        if kw.get("reply_parameters") is None:
            kw["reply_parameters"] = pyro_types.ReplyParameters(message_id=self.id)

        if kw.get("message_thread_id") is None:
            kw["message_thread_id"] = self.message_thread_id

        if kw.get("direct_messages_topic_id") is None:
            kw["direct_messages_topic_id"] = self.direct_messages_topic_id

        return None

    @property
    def editable(self) -> bool:
        """`True` if this message was sent by the client itself, so it can be edited."""
        return getattr(self.from_user, "is_self", False) or getattr(
            self.sender_chat, "id", None
        ) == getattr(self._client.me, "id", 0)

    if TYPE_CHECKING:
        # Both signatures, straight from Pyrogram, so nothing here needs updating.
        # `__debug__` is a `bool` checkers cannot resolve, so they keep both branches.
        respond = PyroMessage.edit if __debug__ else PyroMessage.reply
        """`edit` if this message is `editable`, otherwise `reply`."""
    else:

        @property
        def respond(self) -> Any:
            """`edit` if this message is `editable`, otherwise `reply`."""
            return self.edit if self.editable else self.reply


@patch_cls
class CallbackQuery(PyroCallbackQuery):
    """Pyrogram `CallbackQuery` with `message` and `from_user` typed as the patched classes."""

    _client: Client
    """Client that received this callback query."""
    message: Message | None
    """Message with the pressed button, or `None` for a button on an inline-mode message."""
    from_user: User
    """User who pressed the button."""


__all__ = (
    "User",
    "Message",
    "CallbackQuery",
)
