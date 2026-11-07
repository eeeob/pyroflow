"""Pyrogram's `Message`, patched with the `ask_*` methods, `editable` and `respond`, its messages and users typed as the patched classes."""

from __future__ import annotations as _annotations

import copy
from typing import (
    Any,
    Literal,
    cast,
    overload,
    TYPE_CHECKING,
)

from pyrogram.types import Message as PyroMessage

from ..models import CallbackQueryKey, ListenerContext, MessageKey
from ..utils import patch_cls
from .callback_query import CallbackQuery
from ..update_listener.update_listener import UpdateListener


if TYPE_CHECKING:
    import sys

    if sys.version_info >= (3, 11):
        from typing import Unpack
    else:
        from typing_extensions import Unpack

    from pyrogram.filters import Filter
    from pyrogram.types import InputRichMessage
    from pytrove.typings import Number

    from .._internal import (
        MessageAskEditKw,
        MessageAskRichEditKw,
        MessageAskRichSendKw,
        MessageAskSendKw,
    )
    from ..client import Client
    from .user import User


@patch_cls
class Message(PyroMessage):
    """Pyrogram `Message` extended with the `ask_*` methods, `editable` and `respond`."""

    _client: Client
    """Client that received or sent this message."""
    from_user: User | None
    """Sender of the message, or `None` for messages sent on behalf of a chat."""
    sender_business_bot: User | None
    """Bot that sent the message on behalf of the business account."""
    receiver_user: User | None
    """For ephemeral messages, the user who received the message."""
    reply_to_message: Message | None
    """The message this one replies to."""
    new_chat_members: list[User] | None
    """Members added to the group."""
    left_chat_member: User | None
    """Member removed from the group."""
    pinned_message: Message | None
    """The message that was pinned."""
    via_bot: User | None
    """Bot through which the message was sent."""
    guest_bot_caller_user: User | None
    """User who called the guest bot."""

    @overload
    async def ask(
        self,
        text: str,
        force_send: Literal[False] = False,
        *,
        listen_user_id: int | None = None,
        listen_context: ListenerContext | None = None,
        listen_filters: Filter | None = None,
        listen_strict: bool = False,
        listen_timeout: Number | None = None,
        **kw: Unpack[MessageAskEditKw],
    ) -> Message: ...
    @overload
    async def ask(
        self,
        text: str,
        force_send: Literal[True],
        *,
        listen_user_id: int | None = None,
        listen_context: ListenerContext | None = None,
        listen_filters: Filter | None = None,
        listen_strict: bool = False,
        listen_timeout: Number | None = None,
        **kw: Unpack[MessageAskSendKw],
    ) -> Message: ...

    async def ask(
        self,
        text: str,
        force_send: bool = False,
        *,
        listen_user_id: int | None = None,
        listen_context: ListenerContext | None = None,
        listen_filters: Filter | None = None,
        listen_strict: bool = False,
        listen_timeout: Number | None = None,
        **kw: Any,
    ) -> Message:
        """Send a new message or edit the current one, then wait for the answer.

        If this message is `editable` and `force_send` is `False`, it is edited
        with `edit`; otherwise a new message is sent with `reply`. Pyrogram
        fills in the topic, the business connection and the rest, as for any
        call of those methods. The answer is awaited on `MessageKey.from_sent`
        of the message sent or edited: from `listen_user_id`, or from any user
        without it.

        Args:
            text: The text to send or edit.
            force_send: Send a new reply even if this message is `editable`.
            listen_user_id: The user to wait for, or `None` for any user.
            listen_context: Values attached to the listener; see
                `Client.ask`.
            listen_filters: A Pyrogram filter the answer must pass besides
                its key; see `Client.ask`.
            listen_strict: Whether an update that fails `listen_filters` ends
                the wait with `ListenerRejected` instead of being skipped; see
                `Client.ask`.
            listen_timeout: Seconds to wait before raising `ListenerTimeout`.
            **kw: Passed to `edit` or `reply`.

        Returns:
            The answer.

        Raises:
            RuntimeError: If no listener is registered for `Message`.
            ValueError: If this is an empty message. Checked before sending.
            ListenerTimeout: If no matching update arrives within `listen_timeout`.
            ListenerCancelled: If the listener is cancelled while waiting.
            ListenerWorkersBusy: If the wait would start inside a handler with
                no worker to spare (see `WorkersPolicy`). The message is
                already sent or edited by then.
            ListenerAlreadyExists: If the listener refuses a second wait on
                the key (`DuplicatePolicy.REJECT`). The message is already
                sent or edited by then.
        """
        if self.empty:
            msg = "Cannot call 'ask' on an empty message."
            raise ValueError(msg)

        listener = self._client.get_listener(Message)

        if listener is None:
            msg = (
                "No listener registered for Message. "
                "Register one via client.register_listener() before calling ask()."
            )
            raise RuntimeError(msg)

        m = cast(
            "Message",
            await (
                self.edit(text, **kw)
                if not force_send and self.editable
                else self.reply(text, **kw)
            ),
        )

        key = MessageKey.from_sent(m, listen_user_id)
        context = listen_context

        if self._client.ask_context_message:
            if context is None:
                context = ListenerContext(message=m)
            elif context.message is None:
                context = copy.copy(context)
                context.message = m

        return await UpdateListener.listen(
            listener,
            key,
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
        listen_context: ListenerContext | None = None,
        listen_filters: Filter | None = None,
        listen_strict: bool = False,
        listen_timeout: Number | None = None,
        **kw: Unpack[MessageAskRichEditKw],
    ) -> Message: ...
    @overload
    async def ask_rich(
        self,
        rich_message: InputRichMessage,
        force_send: Literal[True],
        *,
        listen_user_id: int | None = None,
        listen_context: ListenerContext | None = None,
        listen_filters: Filter | None = None,
        listen_strict: bool = False,
        listen_timeout: Number | None = None,
        **kw: Unpack[MessageAskRichSendKw],
    ) -> Message: ...

    async def ask_rich(
        self,
        rich_message: InputRichMessage,
        force_send: bool = False,
        *,
        listen_user_id: int | None = None,
        listen_context: ListenerContext | None = None,
        listen_filters: Filter | None = None,
        listen_strict: bool = False,
        listen_timeout: Number | None = None,
        **kw: Any,
    ) -> Message:
        """Send a new rich message or edit the current one, then wait for the answer.

        Like `ask`, but edits with `edit(rich_message=...)` or sends
        with `reply_rich`.

        Args:
            rich_message: The rich message to send or edit.
            force_send: Send a new reply even if this message is `editable`.
            listen_user_id: As in `ask`.
            listen_context: As in `ask`.
            listen_filters: As in `ask`.
            listen_strict: As in `ask`.
            listen_timeout: As in `ask`.
            **kw: Passed to `edit` or `reply_rich`.

        Returns:
            The answer.

        Raises:
            RuntimeError: If no listener is registered for `Message`.
            ValueError: As in `ask`.
            ListenerTimeout: If no matching update arrives within `listen_timeout`.
            ListenerCancelled: If the listener is cancelled while waiting.
            ListenerWorkersBusy: As in `ask`.
            ListenerAlreadyExists: As in `ask`.
        """
        if self.empty:
            msg = "Cannot call 'ask_rich' on an empty message."
            raise ValueError(msg)

        listener = self._client.get_listener(Message)

        if listener is None:
            msg = (
                "No listener registered for Message. "
                "Register one via client.register_listener() before calling ask_rich()."
            )
            raise RuntimeError(msg)

        m = cast(
            "Message",
            await (
                self.edit(rich_message=rich_message, **kw)
                if not force_send and self.editable
                else self.reply_rich(rich_message, **kw)
            ),
        )

        key = MessageKey.from_sent(m, listen_user_id)
        context = listen_context

        if self._client.ask_context_message:
            if context is None:
                context = ListenerContext(message=m)
            elif context.message is None:
                context = copy.copy(context)
                context.message = m

        return await UpdateListener.listen(
            listener,
            key,
            context=context,
            filters=listen_filters,
            strict=listen_strict,
            timeout=listen_timeout,
        )

    @overload
    async def ask_callback_query(
        self,
        text: str,
        force_send: Literal[False] = False,
        *,
        listen_user_id: int | None = None,
        listen_context: ListenerContext | None = None,
        listen_filters: Filter | None = None,
        listen_strict: bool = False,
        listen_timeout: Number | None = None,
        **kw: Unpack[MessageAskEditKw],
    ) -> CallbackQuery: ...
    @overload
    async def ask_callback_query(
        self,
        text: str,
        force_send: Literal[True],
        *,
        listen_user_id: int | None = None,
        listen_context: ListenerContext | None = None,
        listen_filters: Filter | None = None,
        listen_strict: bool = False,
        listen_timeout: Number | None = None,
        **kw: Unpack[MessageAskSendKw],
    ) -> CallbackQuery: ...

    async def ask_callback_query(
        self,
        text: str,
        force_send: bool = False,
        *,
        listen_user_id: int | None = None,
        listen_context: ListenerContext | None = None,
        listen_filters: Filter | None = None,
        listen_strict: bool = False,
        listen_timeout: Number | None = None,
        **kw: Any,
    ) -> CallbackQuery:
        """Send a new message or edit the current one, then wait for a press on its buttons.

        Like `ask`, but the press is awaited on
        `CallbackQueryKey.from_sent` of the message sent or edited.

        Args:
            text: The text to send or edit.
            force_send: Send a new reply even if this message is `editable`.
            listen_user_id: As in `ask`.
            listen_context: As in `ask`.
            listen_filters: As in `ask`.
            listen_strict: As in `ask`.
            listen_timeout: As in `ask`.
            **kw: Passed to `edit` or `reply`.

        Returns:
            The press.

        Raises:
            RuntimeError: If no listener is registered for `CallbackQuery`.
            ValueError: As in `ask`.
            ListenerTimeout: If no matching update arrives within `listen_timeout`.
            ListenerCancelled: If the listener is cancelled while waiting.
            ListenerWorkersBusy: As in `ask`.
            ListenerAlreadyExists: As in `ask`.
        """
        if self.empty:
            msg = "Cannot call 'ask_callback_query' on an empty message."
            raise ValueError(msg)

        listener = self._client.get_listener(CallbackQuery)

        if listener is None:
            msg = (
                "No listener registered for CallbackQuery. "
                "Register one via client.register_listener() before calling ask_callback_query()."
            )
            raise RuntimeError(msg)

        m = cast(
            "Message",
            await (
                self.edit(text, **kw)
                if not force_send and self.editable
                else self.reply(text, **kw)
            ),
        )

        key = CallbackQueryKey.from_sent(m, listen_user_id)
        context = listen_context

        if self._client.ask_context_message:
            if context is None:
                context = ListenerContext(message=m)
            elif context.message is None:
                context = copy.copy(context)
                context.message = m

        return await UpdateListener.listen(
            listener,
            key,
            context=context,
            filters=listen_filters,
            strict=listen_strict,
            timeout=listen_timeout,
        )

    @overload
    async def ask_callback_query_rich(
        self,
        rich_message: InputRichMessage,
        force_send: Literal[False] = False,
        *,
        listen_user_id: int | None = None,
        listen_context: ListenerContext | None = None,
        listen_filters: Filter | None = None,
        listen_strict: bool = False,
        listen_timeout: Number | None = None,
        **kw: Unpack[MessageAskRichEditKw],
    ) -> CallbackQuery: ...
    @overload
    async def ask_callback_query_rich(
        self,
        rich_message: InputRichMessage,
        force_send: Literal[True],
        *,
        listen_user_id: int | None = None,
        listen_context: ListenerContext | None = None,
        listen_filters: Filter | None = None,
        listen_strict: bool = False,
        listen_timeout: Number | None = None,
        **kw: Unpack[MessageAskRichSendKw],
    ) -> CallbackQuery: ...

    async def ask_callback_query_rich(
        self,
        rich_message: InputRichMessage,
        force_send: bool = False,
        *,
        listen_user_id: int | None = None,
        listen_context: ListenerContext | None = None,
        listen_filters: Filter | None = None,
        listen_strict: bool = False,
        listen_timeout: Number | None = None,
        **kw: Any,
    ) -> CallbackQuery:
        """Send a new rich message or edit the current one, then wait for a press on its buttons.

        Like `ask_callback_query`, but edits with `edit(rich_message=...)` or
        sends with `reply_rich`.

        Args:
            rich_message: The rich message to send or edit.
            force_send: Send a new reply even if this message is `editable`.
            listen_user_id: As in `ask`.
            listen_context: As in `ask`.
            listen_filters: As in `ask`.
            listen_strict: As in `ask`.
            listen_timeout: As in `ask`.
            **kw: Passed to `edit` or `reply_rich`.

        Returns:
            The press.

        Raises:
            RuntimeError: If no listener is registered for `CallbackQuery`.
            ValueError: As in `ask`.
            ListenerTimeout: If no matching update arrives within `listen_timeout`.
            ListenerCancelled: If the listener is cancelled while waiting.
            ListenerWorkersBusy: As in `ask`.
            ListenerAlreadyExists: As in `ask`.
        """
        if self.empty:
            msg = "Cannot call 'ask_callback_query_rich' on an empty message."
            raise ValueError(msg)

        listener = self._client.get_listener(CallbackQuery)

        if listener is None:
            msg = (
                "No listener registered for CallbackQuery. "
                "Register one via client.register_listener() "
                "before calling ask_callback_query_rich()."
            )
            raise RuntimeError(msg)

        m = cast(
            "Message",
            await (
                self.edit(rich_message=rich_message, **kw)
                if not force_send and self.editable
                else self.reply_rich(rich_message, **kw)
            ),
        )

        key = CallbackQueryKey.from_sent(m, listen_user_id)
        context = listen_context

        if self._client.ask_context_message:
            if context is None:
                context = ListenerContext(message=m)
            elif context.message is None:
                context = copy.copy(context)
                context.message = m

        return await UpdateListener.listen(
            listener,
            key,
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


__all__ = ("Message",)
