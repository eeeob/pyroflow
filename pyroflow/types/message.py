"""Pyrogram's `Message`, patched with the `ask_*` methods, `editable` and `respond`, its messages and users typed as the patched classes."""

from __future__ import annotations as _annotations

from typing import (
    Any,
    Literal,
    cast,
    overload,
    TYPE_CHECKING,
)

from pyrogram.types import Message as PyroMessage

from ..utils import patch_cls
from .callback_query import CallbackQuery


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
    from ..models import AskParser, ListenerContext
    from ..typings import ResultT
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
        call of those methods. The answer is awaited on `from_sent` of the
        listener's `__key_type__` for the message sent or edited: from
        `listen_user_id`, or from any user without it.

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

        listener = self._client.require_listener(Message)
        # What `ask_*` accepts always gets a message back, and `patch_cls` makes pyrogram's
        # `Message` the same class as pyroflow's at runtime.
        sent = cast(
            "Message",
            await (
                self.edit(text, **kw)
                if not force_send and self.editable
                else self.reply(text, **kw)
            ),
        )

        return await listener.listen(
            listener.__key_type__.from_sent(sent, listen_user_id),
            context=self._client.context_with_message(sent, listen_context),
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

        listener = self._client.require_listener(Message)
        sent = cast(
            "Message",
            await (
                self.edit(rich_message=rich_message, **kw)
                if not force_send and self.editable
                else self.reply_rich(rich_message, **kw)
            ),
        )

        return await listener.listen(
            listener.__key_type__.from_sent(sent, listen_user_id),
            context=self._client.context_with_message(sent, listen_context),
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

        Like `ask`, but the press is awaited on `from_sent` of the listener's
        `__key_type__` for the message sent or edited.

        Pass `reply_markup`: a question without buttons cannot be answered, and
        its wait stays open until `listen_timeout`, or forever without one.

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

        listener = self._client.require_listener(CallbackQuery)
        sent = cast(
            "Message",
            await (
                self.edit(text, **kw)
                if not force_send and self.editable
                else self.reply(text, **kw)
            ),
        )

        return await listener.listen(
            listener.__key_type__.from_sent(sent, listen_user_id),
            context=self._client.context_with_message(sent, listen_context),
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

        listener = self._client.require_listener(CallbackQuery)
        sent = cast(
            "Message",
            await (
                self.edit(rich_message=rich_message, **kw)
                if not force_send and self.editable
                else self.reply_rich(rich_message, **kw)
            ),
        )

        return await listener.listen(
            listener.__key_type__.from_sent(sent, listen_user_id),
            context=self._client.context_with_message(sent, listen_context),
            filters=listen_filters,
            strict=listen_strict,
            timeout=listen_timeout,
        )

    @overload
    async def ask_until(
        self,
        text: str,
        force_send: Literal[False] = False,
        *,
        parse: AskParser[Message, str, ResultT],
        attempts: int | None = None,
        listen_user_id: int | None = None,
        listen_context: ListenerContext | None = None,
        listen_filters: Filter | None = None,
        listen_strict: bool = False,
        listen_timeout: Number | None = None,
        **kw: Unpack[MessageAskEditKw],
    ) -> ResultT: ...
    @overload
    async def ask_until(
        self,
        text: str,
        force_send: Literal[True],
        *,
        parse: AskParser[Message, str, ResultT],
        attempts: int | None = None,
        listen_user_id: int | None = None,
        listen_context: ListenerContext | None = None,
        listen_filters: Filter | None = None,
        listen_strict: bool = False,
        listen_timeout: Number | None = None,
        **kw: Unpack[MessageAskSendKw],
    ) -> ResultT: ...

    async def ask_until(
        self,
        text: str,
        force_send: bool = False,
        *,
        parse: AskParser[Message, str, ResultT],
        attempts: int | None = None,
        listen_user_id: int | None = None,
        listen_context: ListenerContext | None = None,
        listen_filters: Filter | None = None,
        listen_strict: bool = False,
        listen_timeout: Number | None = None,
        **kw: Any,
    ) -> ResultT:
        """Repeat `ask` until `parse` returns a value.

        `parse` is called as `parse(answer, kw)`, sync or async, where `kw` is the
        dict of keyword arguments of the question. It runs on the event loop,
        so a slow sync `parse` stops every update; keep it light. What it
        returns decides what happens next:

        - `AskAgain(question)`: rejected; `question` is asked with no arguments.
        - `AskAgain(question, new_kw)`: rejected; `question` is asked with
          `new_kw`. Return the `kw` it was given to keep the arguments.
        - Anything else, `None` included: returned to the caller.

        An answer that reaches `parse` was taken by the wait, so it reaches no
        handler even when rejected, and a command sent instead of an answer
        counts as one. Let those through with `listen_filters`, for example
        `~filters.command`: what fails `listen_filters` goes on to the handlers
        without reaching `parse`, or with `listen_strict` raises
        `ListenerRejected` at once.

        On an `editable` message only the first question edits it; after a
        rejection each question replies, since Telegram refuses an edit that
        changes nothing.

        Args:
            text: The first question.
            force_send: As in `ask`, for the first question; later ones always
                reply.
            parse: Decides what happens with each answer, as above.
            attempts: How many times to ask, or `None` for no limit.
            listen_user_id: As in `ask`.
            listen_context: As in `ask`.
            listen_filters: As in `ask`, a pre-filter in front of `parse`.
            listen_strict: As in `ask`; a rejection by `listen_filters` ends
                the loop, not only the wait.
            listen_timeout: As in `ask`, for each wait on its own.
            **kw: Passed to `edit` or `reply`.

        Returns:
            The value `parse` returned.

        Raises:
            ValueError: If `attempts` is not positive; nothing is sent then.
            ListenerAttemptsExhausted: If `parse` rejects an answer when
                `attempts` questions were asked; `update` holds that answer.
            Anything else `ask` or `parse` raises, at once.
        """
        return await self._client.ask_repeatedly(
            self.ask,
            None,
            text,
            force_send,
            True,
            parse,
            attempts,
            kw,
            listen_user_id=listen_user_id,
            listen_context=listen_context,
            listen_filters=listen_filters,
            listen_strict=listen_strict,
            listen_timeout=listen_timeout,
        )

    @overload
    async def ask_rich_until(
        self,
        rich_message: InputRichMessage,
        force_send: Literal[False] = False,
        *,
        parse: AskParser[Message, InputRichMessage, ResultT],
        attempts: int | None = None,
        listen_user_id: int | None = None,
        listen_context: ListenerContext | None = None,
        listen_filters: Filter | None = None,
        listen_strict: bool = False,
        listen_timeout: Number | None = None,
        **kw: Unpack[MessageAskRichEditKw],
    ) -> ResultT: ...
    @overload
    async def ask_rich_until(
        self,
        rich_message: InputRichMessage,
        force_send: Literal[True],
        *,
        parse: AskParser[Message, InputRichMessage, ResultT],
        attempts: int | None = None,
        listen_user_id: int | None = None,
        listen_context: ListenerContext | None = None,
        listen_filters: Filter | None = None,
        listen_strict: bool = False,
        listen_timeout: Number | None = None,
        **kw: Unpack[MessageAskRichSendKw],
    ) -> ResultT: ...

    async def ask_rich_until(
        self,
        rich_message: InputRichMessage,
        force_send: bool = False,
        *,
        parse: AskParser[Message, InputRichMessage, ResultT],
        attempts: int | None = None,
        listen_user_id: int | None = None,
        listen_context: ListenerContext | None = None,
        listen_filters: Filter | None = None,
        listen_strict: bool = False,
        listen_timeout: Number | None = None,
        **kw: Any,
    ) -> ResultT:
        """Repeat `ask_rich` until `parse` returns a value.

        Like `ask_until`, but each question is a rich message and a new
        question from `parse` is an `InputRichMessage`.

        Args:
            rich_message: The first question.
            force_send: As in `ask_until`.
            parse: As in `ask_until`.
            attempts: As in `ask_until`.
            listen_user_id: As in `ask`.
            listen_context: As in `ask`.
            listen_filters: As in `ask_until`.
            listen_strict: As in `ask_until`.
            listen_timeout: As in `ask`, for each wait on its own.
            **kw: Passed to `edit` or `reply_rich`, for the first question.

        Returns:
            The value `parse` returned.

        Raises:
            ValueError: If `attempts` is not positive; nothing is sent then.
            ListenerAttemptsExhausted: If `parse` rejects an answer when
                `attempts` questions were asked; `update` holds that answer.
            Anything else `ask_rich` or `parse` raises, at once.
        """
        return await self._client.ask_repeatedly(
            self.ask_rich,
            None,
            rich_message,
            force_send,
            True,
            parse,
            attempts,
            kw,
            listen_user_id=listen_user_id,
            listen_context=listen_context,
            listen_filters=listen_filters,
            listen_strict=listen_strict,
            listen_timeout=listen_timeout,
        )

    @overload
    async def ask_callback_query_until(
        self,
        text: str,
        force_send: Literal[False] = False,
        *,
        parse: AskParser[CallbackQuery, str, ResultT],
        attempts: int | None = None,
        listen_user_id: int | None = None,
        listen_context: ListenerContext | None = None,
        listen_filters: Filter | None = None,
        listen_strict: bool = False,
        listen_timeout: Number | None = None,
        **kw: Unpack[MessageAskEditKw],
    ) -> ResultT: ...
    @overload
    async def ask_callback_query_until(
        self,
        text: str,
        force_send: Literal[True],
        *,
        parse: AskParser[CallbackQuery, str, ResultT],
        attempts: int | None = None,
        listen_user_id: int | None = None,
        listen_context: ListenerContext | None = None,
        listen_filters: Filter | None = None,
        listen_strict: bool = False,
        listen_timeout: Number | None = None,
        **kw: Unpack[MessageAskSendKw],
    ) -> ResultT: ...

    async def ask_callback_query_until(
        self,
        text: str,
        force_send: bool = False,
        *,
        parse: AskParser[CallbackQuery, str, ResultT],
        attempts: int | None = None,
        listen_user_id: int | None = None,
        listen_context: ListenerContext | None = None,
        listen_filters: Filter | None = None,
        listen_strict: bool = False,
        listen_timeout: Number | None = None,
        **kw: Any,
    ) -> ResultT:
        """Repeat `ask_callback_query` until `parse` returns a value.

        Like `ask_until`, but each question waits for a press on its own
        buttons, so pass `reply_markup`, and put it in the `kw` of each
        `AskAgain`: a question without buttons cannot be answered, and its wait
        stays open until `listen_timeout`, or forever without one. A rejected
        press was taken by the wait like a rejected answer.

        Args:
            text: The first question.
            force_send: As in `ask_until`.
            parse: As in `ask_until`.
            attempts: As in `ask_until`.
            listen_user_id: As in `ask`.
            listen_context: As in `ask`.
            listen_filters: As in `ask_until`.
            listen_strict: As in `ask_until`.
            listen_timeout: As in `ask`, for each wait on its own.
            **kw: Passed to `edit` or `reply`.

        Returns:
            The value `parse` returned.

        Raises:
            ValueError: If `attempts` is not positive; nothing is sent then.
            ListenerAttemptsExhausted: If `parse` rejects a press when
                `attempts` questions were asked; `update` holds that press.
            Anything else `ask_callback_query` or `parse` raises, at once.
        """
        return await self._client.ask_repeatedly(
            self.ask_callback_query,
            None,
            text,
            force_send,
            True,
            parse,
            attempts,
            kw,
            listen_user_id=listen_user_id,
            listen_context=listen_context,
            listen_filters=listen_filters,
            listen_strict=listen_strict,
            listen_timeout=listen_timeout,
        )

    @overload
    async def ask_callback_query_rich_until(
        self,
        rich_message: InputRichMessage,
        force_send: Literal[False] = False,
        *,
        parse: AskParser[CallbackQuery, InputRichMessage, ResultT],
        attempts: int | None = None,
        listen_user_id: int | None = None,
        listen_context: ListenerContext | None = None,
        listen_filters: Filter | None = None,
        listen_strict: bool = False,
        listen_timeout: Number | None = None,
        **kw: Unpack[MessageAskRichEditKw],
    ) -> ResultT: ...
    @overload
    async def ask_callback_query_rich_until(
        self,
        rich_message: InputRichMessage,
        force_send: Literal[True],
        *,
        parse: AskParser[CallbackQuery, InputRichMessage, ResultT],
        attempts: int | None = None,
        listen_user_id: int | None = None,
        listen_context: ListenerContext | None = None,
        listen_filters: Filter | None = None,
        listen_strict: bool = False,
        listen_timeout: Number | None = None,
        **kw: Unpack[MessageAskRichSendKw],
    ) -> ResultT: ...

    async def ask_callback_query_rich_until(
        self,
        rich_message: InputRichMessage,
        force_send: bool = False,
        *,
        parse: AskParser[CallbackQuery, InputRichMessage, ResultT],
        attempts: int | None = None,
        listen_user_id: int | None = None,
        listen_context: ListenerContext | None = None,
        listen_filters: Filter | None = None,
        listen_strict: bool = False,
        listen_timeout: Number | None = None,
        **kw: Any,
    ) -> ResultT:
        """Repeat `ask_callback_query_rich` until `parse` returns a value.

        Like `ask_callback_query_until`, but each question is a rich message
        and a new question from `parse` is an `InputRichMessage`.

        Args:
            rich_message: The first question.
            force_send: As in `ask_until`.
            parse: As in `ask_until`.
            attempts: As in `ask_until`.
            listen_user_id: As in `ask`.
            listen_context: As in `ask`.
            listen_filters: As in `ask_until`.
            listen_strict: As in `ask_until`.
            listen_timeout: As in `ask`, for each wait on its own.
            **kw: Passed to `edit` or `reply_rich`, for the first question.

        Returns:
            The value `parse` returned.

        Raises:
            ValueError: If `attempts` is not positive; nothing is sent then.
            ListenerAttemptsExhausted: If `parse` rejects a press when
                `attempts` questions were asked; `update` holds that press.
            Anything else `ask_callback_query_rich` or `parse` raises, at once.
        """
        return await self._client.ask_repeatedly(
            self.ask_callback_query_rich,
            None,
            rich_message,
            force_send,
            True,
            parse,
            attempts,
            kw,
            listen_user_id=listen_user_id,
            listen_context=listen_context,
            listen_filters=listen_filters,
            listen_strict=listen_strict,
            listen_timeout=listen_timeout,
        )

    @property
    def editable(self) -> bool:
        """`True` if this message was sent by the client itself, so it can be edited.

        An ephemeral message is never editable here: its `id` is `0`, and
        Pyrogram cannot edit it.
        """
        return self.ephemeral_message_id is None and (
            bool(self.outgoing) or getattr(self.from_user, "is_self", False)
        )

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
