"""Pyrogram update types patched with conversation helpers such as `Message.ask`."""

from __future__ import annotations as _annotations

import copy
from typing import (
    Any,
    Literal,
    cast,
    overload,
    TYPE_CHECKING,
)

from pyrogram.types import (
    Message as PyroMessage,
    CallbackQuery as PyroCallbackQuery,
    User as PyroUser,
    Update as PyroUpdate,
)

from .enums import EphemeralUpdates, ListenMessageId
from .models import ListenerContext
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

        If this message is `editable` and `force_send` is `False`, it is edited
        with `edit`; otherwise a new message is sent with `reply`. Pyrogram
        fills in the topic, the business connection and the rest, as for any
        call of those methods.

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
            **kw: Passed to `edit` or `reply`.

        Returns:
            The first matching update.

        Raises:
            RuntimeError: If no listener is registered for `listen_update_type`.
            ValueError: If this is a service or empty message, or a wait on an
                ephemeral message lacks `listen_user_id`; a reply to an
                ephemeral message takes it from this message's sender. Or if
                `listen_message_id` is `SENT` or `NEXT` on an ephemeral
                message, checked before sending and again on the message sent.
            ListenerTimeout: If no matching update arrives within `listen_timeout`.
            ListenerCancelled: If the listener is cancelled while waiting.
            ListenerWorkersBusy: If the wait would start inside a handler with
                no worker to spare (see `WorkersPolicy`). The message is
                already sent or edited by then.
        """
        if self.service or self.empty:
            msg = "Cannot call 'ask' on a service or empty message."
            raise ValueError(msg)

        listener = self._client.listeners.get(listen_update_type)

        if listener is None:
            msg = (
                f"No listener registered for {listen_update_type.__name__}. "
                f"Register one via client.register_listener() before calling ask()."
            )
            raise RuntimeError(msg)

        edits = not force_send and self.editable

        if listen_user_id is None:
            if self.ephemeral_message_id is not None and not edits:
                # A reply to an ephemeral message goes to its sender alone.
                listen_user_id = self.from_user.id  # ty: ignore[unresolved-attribute]  # `reply` needs the sender too, and raises the same way without one
            elif self.ephemeral_message_id is not None or listen_message_id is EphemeralUpdates.ANY:
                msg = "Waiting on an ephemeral message needs listen_user_id"
                raise ValueError(msg)

        if self.ephemeral_message_id is not None and listen_message_id in (
            ListenMessageId.SENT,
            ListenMessageId.NEXT,
        ):
            msg = "An ephemeral message has no id to wait on; use EphemeralUpdates.ANY"
            raise ValueError(msg)

        m = cast(
            "Message",
            await (self.edit(text, **kw) if edits else self.reply(text, **kw)),
        )

        if listen_message_id is ListenMessageId.AUTO:
            listen_message_id = (
                ListenMessageId.NEXT
                if issubclass(listen_update_type, Message) and m.ephemeral_message_id is None
                else ListenMessageId.SENT
                if issubclass(listen_update_type, CallbackQuery) and m.ephemeral_message_id is None
                else EphemeralUpdates.ANY
                if issubclass(listen_update_type, (Message, CallbackQuery))
                else None
            )

        # An ephemeral message's id does not follow the others and can be reused.
        if listen_message_id in (ListenMessageId.SENT, ListenMessageId.NEXT):
            if m.ephemeral_message_id is not None:
                msg = "An ephemeral message has no id to wait on; use EphemeralUpdates.ANY"
                raise ValueError(msg)

            if listen_message_id is ListenMessageId.SENT:
                listen_message_id = m.id
            elif listen_message_id is ListenMessageId.NEXT:
                listen_message_id = m.id + 1

        context = listen_context

        if self._client.ask_context_message:
            if context is None:
                context = ListenerContext(message=m)
            elif context.message is None:
                context = copy.copy(context)
                context.message = m

        return await listener(
            chat_id=self.chat.id,  # ty: ignore[unresolved-attribute, invalid-argument-type]  # `kurigram` types `Message.chat` and `Chat.id` as optional; a non-empty message always has both
            user_id=listen_user_id,
            message_id=listen_message_id,
            context=context,
            filters=listen_filters,
            strict=listen_strict,
            timeout=listen_timeout,
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

        Like `ask`, but edits with `edit(rich_message=...)` or sends with `reply_rich`.

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
            **kw: Passed to `edit` or `reply_rich`.

        Returns:
            The first matching update.

        Raises:
            RuntimeError: If no listener is registered for `listen_update_type`.
            ValueError: If this is a service or empty message, or a wait on an
                ephemeral message lacks `listen_user_id`; a reply to an
                ephemeral message takes it from this message's sender. Or if
                `listen_message_id` is `SENT` or `NEXT` on an ephemeral
                message, checked before sending and again on the message sent.
            ListenerTimeout: If no matching update arrives within `listen_timeout`.
            ListenerCancelled: If the listener is cancelled while waiting.
            ListenerWorkersBusy: If the wait would start inside a handler with
                no worker to spare (see `WorkersPolicy`). The message is
                already sent or edited by then.
        """
        if self.service or self.empty:
            msg = "Cannot call 'ask' on a service or empty message."
            raise ValueError(msg)

        listener = self._client.listeners.get(listen_update_type)

        if listener is None:
            msg = (
                f"No listener registered for {listen_update_type.__name__}. "
                f"Register one via client.register_listener() before calling ask()."
            )
            raise RuntimeError(msg)

        edits = not force_send and self.editable

        if listen_user_id is None:
            if self.ephemeral_message_id is not None and not edits:
                # A reply to an ephemeral message goes to its sender alone.
                listen_user_id = self.from_user.id  # ty: ignore[unresolved-attribute]  # `reply` needs the sender too, and raises the same way without one
            elif self.ephemeral_message_id is not None or listen_message_id is EphemeralUpdates.ANY:
                msg = "Waiting on an ephemeral message needs listen_user_id"
                raise ValueError(msg)

        if self.ephemeral_message_id is not None and listen_message_id in (
            ListenMessageId.SENT,
            ListenMessageId.NEXT,
        ):
            msg = "An ephemeral message has no id to wait on; use EphemeralUpdates.ANY"
            raise ValueError(msg)

        m = cast(
            "Message",
            await (
                self.edit(rich_message=rich_message, **kw)
                if edits
                else self.reply_rich(rich_message, **kw)
            ),
        )

        if listen_message_id is ListenMessageId.AUTO:
            listen_message_id = (
                ListenMessageId.NEXT
                if issubclass(listen_update_type, Message) and m.ephemeral_message_id is None
                else ListenMessageId.SENT
                if issubclass(listen_update_type, CallbackQuery) and m.ephemeral_message_id is None
                else EphemeralUpdates.ANY
                if issubclass(listen_update_type, (Message, CallbackQuery))
                else None
            )

        # An ephemeral message's id does not follow the others and can be reused.
        if listen_message_id in (ListenMessageId.SENT, ListenMessageId.NEXT):
            if m.ephemeral_message_id is not None:
                msg = "An ephemeral message has no id to wait on; use EphemeralUpdates.ANY"
                raise ValueError(msg)

            if listen_message_id is ListenMessageId.SENT:
                listen_message_id = m.id
            elif listen_message_id is ListenMessageId.NEXT:
                listen_message_id = m.id + 1

        context = listen_context

        if self._client.ask_context_message:
            if context is None:
                context = ListenerContext(message=m)
            elif context.message is None:
                context = copy.copy(context)
                context.message = m

        return await listener(
            chat_id=self.chat.id,  # ty: ignore[unresolved-attribute, invalid-argument-type]  # `kurigram` types `Message.chat` and `Chat.id` as optional; a non-empty message always has both
            user_id=listen_user_id,
            message_id=listen_message_id,
            context=context,
            filters=listen_filters,
            strict=listen_strict,
            timeout=listen_timeout,
        )

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

        async def respond(self, *args: Any, **kw: Any) -> Any:
            """`edit` if this message is `editable`, otherwise `reply`."""
            return await (self.edit if self.editable else self.reply)(*args, **kw)


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
