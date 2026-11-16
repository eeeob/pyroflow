"""Pyrogram's `Message`, patched with the `ask_*` and `flow_*` methods, `editable`, `respond` and `respond_rich`, its messages and users typed as the patched classes."""

from __future__ import annotations as _annotations

from typing import (
    Any,
    Literal,
    cast,
    overload,
    TYPE_CHECKING,
)

from pyrogram.types import EphemeralMessageParameters, Message as PyroMessage, ReplyParameters

from ..errors import ListenerNotSent
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
    """Pyrogram `Message` extended with the `ask_*` and `flow_*` methods, `editable`, `respond` and `respond_rich`.

    The `flow_*` methods (`flow_edit`, `flow_edit_rich`, `flow_reply`,
    `flow_reply_rich`, `flow_respond` and `flow_respond_rich`) are what the
    `ask_*` methods edit and reply with: they reply to an ephemeral message
    ephemerally, for its receiver if it is the client's own (`editable`) and
    for its sender otherwise, and edit one with
    `Client.edit_ephemeral_message_text`.
    They take the `ask_*` arguments; for kurigram's full signatures, call
    `edit_text`, `reply` and `reply_rich`.
    """

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
        with `flow_edit`, an ephemeral one too; otherwise a new message is sent
        with `flow_reply`, which fills in the topic, the business connection
        and, for an ephemeral message, the user to reply to (see
        `flow_reply`). The answer is awaited on `from_sent` of the listener's
        `__key_type__` for the message sent or edited: from `listen_user_id`,
        or from any user without it.

        Args:
            text: The text to send or edit.
            force_send: Send a new reply even if this message is `editable`.
            listen_user_id: The user to wait for, or `None` for any user.
                Pass it in a group and for an ephemeral question; see
                `Client.ask`.
            listen_context: Values attached to the listener; see
                `Client.ask`.
            listen_filters: A Pyrogram filter the answer must pass besides
                its key; see `Client.ask`.
            listen_strict: Whether an update that fails `listen_filters` ends
                the wait with `ListenerRejected` instead of being skipped; see
                `Client.ask`.
            listen_timeout: Seconds to wait before raising `ListenerTimeout`;
                `None` uses the listener's `timeout`.
            **kw: Passed to `flow_edit` or `flow_reply`: the arguments of
                kurigram's `edit_text` or `reply` without what those fill in
                and without scheduling; for the full signatures, call
                kurigram's methods.

        Returns:
            The answer.

        Raises:
            RuntimeError: If no listener is registered for `Message`.
            ValueError: If this is an empty message, or an ephemeral one whose
                user is unknown: its `receiver_user` for an edit or a reply to
                the client's own message, else its `from_user` (see
                `flow_edit` and `flow_reply`). Checked before sending.
            TypeError: If `listen_timeout` is neither a number nor `None`; the
                message is already sent or edited by then.
            ListenerNotSent: If Telegram returns no message for the question,
                such as an edit of an ephemeral message it answers with none.
            ListenerTimeout: If the timeout expires before the answer arrives.
            ListenerCancelled: If the listener is stopped or the wait is
                cancelled; also its subclasses `ListenerClosed` (the listener
                is stopped: raised before sending, or from the wait if it
                stops while the question is sent), `ListenerReplaced` (a
                newer wait on the key, under the default
                `DuplicatePolicy.REPLACE`),
                `ListenerEvicted` (`WorkersPolicy.CANCEL_OLDEST`, the default,
                for a wait inside a handler) and `ListenerRejected` (with
                `listen_strict` or the listener's `strict_filter`).
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
        sent = await (
            self.flow_edit(text, **kw)
            if not force_send and self.editable
            else self.flow_reply(text, **kw)
        )
        if sent is None:
            raise ListenerNotSent

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

        Like `ask`, but edits with `flow_edit_rich` or sends with
        `flow_reply_rich`.

        Args:
            rich_message: The rich message to send or edit.
            force_send: Send a new reply even if this message is `editable`.
            listen_user_id: As in `ask`.
            listen_context: As in `ask`.
            listen_filters: As in `ask`.
            listen_strict: As in `ask`.
            listen_timeout: As in `ask`.
            **kw: Passed to `flow_edit_rich` or `flow_reply_rich`: the
                arguments of kurigram's `edit_text` or `reply_rich` without what
                those fill in and without scheduling; for the full signatures,
                call kurigram's methods. On a message that is not `editable`
                the question is a reply, so an edit-only argument such as
                `link_preview_options` raises `TypeError`; pass it only with
                an `editable` message.

        Returns:
            The answer.

        Raises:
            RuntimeError: If no listener is registered for `Message`.
            ValueError: As in `ask`.
            TypeError: As in `ask`, or if the question is a reply and `kw`
                holds an edit-only argument, which `send_rich_message` does
                not take; nothing is sent then.
            ListenerNotSent: As in `ask`.
            ListenerTimeout: If the timeout expires before the answer arrives.
            ListenerCancelled: As in `ask`.
            ListenerWorkersBusy: As in `ask`.
            ListenerAlreadyExists: As in `ask`.
        """
        if self.empty:
            msg = "Cannot call 'ask_rich' on an empty message."
            raise ValueError(msg)

        listener = self._client.require_listener(Message)
        sent = await (
            self.flow_edit_rich(rich_message, **kw)
            if not force_send and self.editable
            else self.flow_reply_rich(rich_message, **kw)
        )
        if sent is None:
            raise ListenerNotSent

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
        its wait stays open until `listen_timeout`, or the listener's `timeout`,
        or forever without either.

        Args:
            text: The text to send or edit.
            force_send: Send a new reply even if this message is `editable`.
            listen_user_id: As in `ask`. Pass it when this message is
                ephemeral: without it, a press from any user on any ephemeral
                message in the chat ends the wait.
            listen_context: As in `ask`.
            listen_filters: As in `ask`.
            listen_strict: As in `ask`.
            listen_timeout: As in `ask`.
            **kw: Passed to `flow_edit` or `flow_reply`: the arguments of
                kurigram's `edit_text` or `reply` without what those fill in
                and without scheduling; for the full signatures, call
                kurigram's methods.

        Returns:
            The press.

        Raises:
            RuntimeError: If no listener is registered for `CallbackQuery`.
            ValueError: As in `ask`.
            TypeError: As in `ask`.
            ListenerNotSent: As in `ask`.
            ListenerTimeout: If the timeout expires before the press arrives.
            ListenerCancelled: As in `ask`.
            ListenerWorkersBusy: As in `ask`.
            ListenerAlreadyExists: As in `ask`.
        """
        if self.empty:
            msg = "Cannot call 'ask_callback_query' on an empty message."
            raise ValueError(msg)

        listener = self._client.require_listener(CallbackQuery)
        sent = await (
            self.flow_edit(text, **kw)
            if not force_send and self.editable
            else self.flow_reply(text, **kw)
        )
        if sent is None:
            raise ListenerNotSent

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

        Like `ask_callback_query`, but edits with `flow_edit_rich` or sends
        with `flow_reply_rich`.

        Args:
            rich_message: The rich message to send or edit.
            force_send: Send a new reply even if this message is `editable`.
            listen_user_id: As in `ask`. Pass it when this message is
                ephemeral: without it, a press from any user on any ephemeral
                message in the chat ends the wait.
            listen_context: As in `ask`.
            listen_filters: As in `ask`.
            listen_strict: As in `ask`.
            listen_timeout: As in `ask`.
            **kw: Passed to `flow_edit_rich` or `flow_reply_rich`: the
                arguments of kurigram's `edit_text` or `reply_rich` without what
                those fill in and without scheduling; for the full signatures,
                call kurigram's methods. As in `ask_rich`, an edit-only
                argument raises `TypeError` on a message that is not
                `editable`.

        Returns:
            The press.

        Raises:
            RuntimeError: If no listener is registered for `CallbackQuery`.
            ValueError: As in `ask`.
            TypeError: As in `ask_rich`.
            ListenerNotSent: As in `ask`.
            ListenerTimeout: If the timeout expires before the press arrives.
            ListenerCancelled: As in `ask`.
            ListenerWorkersBusy: As in `ask`.
            ListenerAlreadyExists: As in `ask`.
        """
        if self.empty:
            msg = "Cannot call 'ask_callback_query_rich' on an empty message."
            raise ValueError(msg)

        listener = self._client.require_listener(CallbackQuery)
        sent = await (
            self.flow_edit_rich(rich_message, **kw)
            if not force_send and self.editable
            else self.flow_reply_rich(rich_message, **kw)
        )
        if sent is None:
            raise ListenerNotSent

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
        `~filters.regex(r"^/")`: what fails `listen_filters` goes on to the handlers
        without reaching `parse`, or with `listen_strict` raises
        `ListenerRejected` at once.

        On an `editable` message only the first question edits it; after a
        rejection each question replies, so it comes after the rejected reply
        instead of staying above it.

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
            **kw: As in `ask`, for the first question.

        Returns:
            The value `parse` returned.

        Raises:
            ValueError: If `attempts` is not positive; nothing is sent then.
            ListenerAttemptsExhausted: If `parse` rejects an answer when
                `attempts` questions were asked; `update` holds that answer.
            Exception: Whatever `ask` or `parse` raises, unchanged and at once.
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

        A question sent as a reply, the first one on a message that is not
        `editable` or a retry with the `kw` it was given, raises `TypeError`
        when that `kw` holds an edit-only argument such as
        `link_preview_options`, which `flow_reply_rich` does not take.

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
            **kw: As in `ask_rich`, for the first question.

        Returns:
            The value `parse` returned.

        Raises:
            ValueError: If `attempts` is not positive; nothing is sent then.
            ListenerAttemptsExhausted: If `parse` rejects an answer when
                `attempts` questions were asked; `update` holds that answer.
            Exception: Whatever `ask_rich` or `parse` raises, unchanged and at once.
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
        stays open until `listen_timeout`, or the listener's `timeout`, or
        forever without either. A rejected press was taken by the wait like a
        rejected answer.

        Args:
            text: The first question.
            force_send: As in `ask_until`.
            parse: As in `ask_until`.
            attempts: As in `ask_until`.
            listen_user_id: As in `ask`. Pass it when this message is
                ephemeral: without it, a press from any user on any ephemeral
                message in the chat ends the wait.
            listen_context: As in `ask`.
            listen_filters: As in `ask_until`.
            listen_strict: As in `ask_until`.
            listen_timeout: As in `ask`, for each wait on its own.
            **kw: As in `ask`, for the first question.

        Returns:
            The value `parse` returned.

        Raises:
            ValueError: If `attempts` is not positive; nothing is sent then.
            ListenerAttemptsExhausted: If `parse` rejects a press when
                `attempts` questions were asked; `update` holds that press.
            Exception: Whatever `ask_callback_query` or `parse` raises, unchanged
                and at once.
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

        A question sent as a reply, the first one on a message that is not
        `editable` or a retry with the `kw` it was given, raises `TypeError`
        when that `kw` holds an edit-only argument such as
        `link_preview_options`, which `flow_reply_rich` does not take.

        Args:
            rich_message: The first question.
            force_send: As in `ask_until`.
            parse: As in `ask_until`.
            attempts: As in `ask_until`.
            listen_user_id: As in `ask`. Pass it when this message is
                ephemeral: without it, a press from any user on any ephemeral
                message in the chat ends the wait.
            listen_context: As in `ask`.
            listen_filters: As in `ask_until`.
            listen_strict: As in `ask_until`.
            listen_timeout: As in `ask`, for each wait on its own.
            **kw: As in `ask_rich`, for the first question.

        Returns:
            The value `parse` returned.

        Raises:
            ValueError: If `attempts` is not positive; nothing is sent then.
            ListenerAttemptsExhausted: If `parse` rejects a press when
                `attempts` questions were asked; `update` holds that press.
            Exception: Whatever `ask_callback_query_rich` or `parse` raises,
                unchanged and at once.
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
        """`True` if this is the client's own message, so it can be edited.

        An ephemeral message of the client's own is editable too, with
        `flow_edit` or `flow_edit_rich`; kurigram's `edit` cannot edit it.
        In a business chat only what this bot sent for the account counts:
        a message the account's owner typed is outgoing too, but it is theirs.
        """
        if self.business_connection_id is not None:
            return bool(getattr(self.sender_business_bot, "is_self", False))

        return bool(self.outgoing or getattr(self.from_user, "is_self", False))

    async def flow_edit(self, text: str, **kw: Unpack[MessageAskEditKw]) -> Message | None:
        """Edit the text of this message, an ephemeral one too.

        Kurigram's `edit_text` edits by `id`, which is `0` for an ephemeral
        message. This method edits an ephemeral message with
        `Client.edit_ephemeral_message_text` for its `receiver_user`, and any
        other with `Client.edit_message_text`, through its business
        connection.

        Args:
            text: The new text.
            **kw: Passed to the client method; for the full signature, call
                `edit_text`.

        Returns:
            The edited message, or `None` if Telegram returned none for an
            ephemeral one.

        Raises:
            ValueError: If this message is ephemeral and has no
                `receiver_user`; nothing is edited then.
        """
        if self.ephemeral_message_id is None:
            return cast(
                "Message",
                await self._client.edit_message_text(
                    chat_id=self.chat.id,  # ty: ignore[unresolved-attribute, invalid-argument-type]  # a message has a chat
                    message_id=self.id,
                    text=text,
                    business_connection_id=self.business_connection_id,
                    **kw,
                ),
            )
        if self.receiver_user is None:
            msg = "Cannot edit this ephemeral message: its receiver is unknown."
            raise ValueError(msg)
        return cast(
            "Message | None",
            await self._client.edit_ephemeral_message_text(
                chat_id=self.chat.id,  # ty: ignore[unresolved-attribute, invalid-argument-type]  # a message has a chat
                receiver_user_id=self.receiver_user.id,
                ephemeral_message_id=self.ephemeral_message_id,
                text=text,
                **kw,
            ),
        )

    async def flow_edit_rich(
        self, rich_message: InputRichMessage, **kw: Unpack[MessageAskRichEditKw]
    ) -> Message | None:
        """Edit this message to a rich message, an ephemeral one too.

        Like `flow_edit`, but with `rich_message` instead of a text.

        Args:
            rich_message: The new rich content.
            **kw: Passed to the client method; for the full signature, call
                `edit_text`.

        Returns:
            The edited message, or `None` if Telegram returned none for an
            ephemeral one.

        Raises:
            ValueError: As in `flow_edit`; nothing is edited then.
        """
        if self.ephemeral_message_id is None:
            return cast(
                "Message",
                await self._client.edit_message_text(
                    chat_id=self.chat.id,  # ty: ignore[unresolved-attribute, invalid-argument-type]  # a message has a chat
                    message_id=self.id,
                    rich_message=rich_message,
                    business_connection_id=self.business_connection_id,
                    **kw,
                ),
            )
        if self.receiver_user is None:
            msg = "Cannot edit this ephemeral message: its receiver is unknown."
            raise ValueError(msg)
        return cast(
            "Message | None",
            await self._client.edit_ephemeral_message_text(
                chat_id=self.chat.id,  # ty: ignore[unresolved-attribute, invalid-argument-type]  # a message has a chat
                receiver_user_id=self.receiver_user.id,
                ephemeral_message_id=self.ephemeral_message_id,
                rich_message=rich_message,
                **kw,
            ),
        )

    async def flow_reply(self, text: str, **kw: Unpack[MessageAskSendKw]) -> Message | None:
        """Reply to this message with `Client.send_message`.

        The reply goes to this message's chat, topics and business connection.
        A reply to an ephemeral message is ephemeral too, for its receiver
        when this message is the client's own (`editable`), otherwise for its
        sender. Kurigram's `reply` takes the sender even for the client's own
        message, which sends the reply to the client itself.

        Args:
            text: The text to send.
            **kw: Passed to `Client.send_message`; for the full signature,
                call `reply`.

        Returns:
            The sent message, or `None` if Telegram returned none.

        Raises:
            ValueError: If this message is ephemeral and the user to reply to
                is unknown; nothing is sent then.
        """
        if self.ephemeral_message_id is None:
            reply_parameters = ReplyParameters(message_id=self.id)
            ephemeral_message_parameters = None
        else:
            receiver = self.receiver_user if self.editable else self.from_user
            if receiver is None:
                msg = "Cannot reply to this ephemeral message: the user to reply to is unknown."
                raise ValueError(msg)
            reply_parameters = ReplyParameters(ephemeral_message_id=self.ephemeral_message_id)
            ephemeral_message_parameters = EphemeralMessageParameters(receiver_user_id=receiver.id)

        return cast(
            "Message | None",
            await self._client.send_message(
                chat_id=self.chat.id,  # ty: ignore[unresolved-attribute, invalid-argument-type]  # a message has a chat
                text=text,
                message_thread_id=self.message_thread_id,
                direct_messages_topic_id=self.direct_messages_topic_id,
                ephemeral_message_parameters=ephemeral_message_parameters,
                reply_parameters=reply_parameters,
                business_connection_id=self.business_connection_id,
                **kw,
            ),
        )

    async def flow_reply_rich(
        self, rich_message: InputRichMessage, **kw: Unpack[MessageAskRichSendKw]
    ) -> Message | None:
        """Reply to this message with `Client.send_rich_message`.

        Like `flow_reply`, but with a rich message.

        Args:
            rich_message: The rich message to send.
            **kw: Passed to `Client.send_rich_message`; for the full
                signature, call `reply_rich`.

        Returns:
            The sent message, or `None` if Telegram returned none.

        Raises:
            ValueError: As in `flow_reply`; nothing is sent then.
        """
        if self.ephemeral_message_id is None:
            reply_parameters = ReplyParameters(message_id=self.id)
            ephemeral_message_parameters = None
        else:
            receiver = self.receiver_user if self.editable else self.from_user
            if receiver is None:
                msg = "Cannot reply to this ephemeral message: the user to reply to is unknown."
                raise ValueError(msg)
            reply_parameters = ReplyParameters(ephemeral_message_id=self.ephemeral_message_id)
            ephemeral_message_parameters = EphemeralMessageParameters(receiver_user_id=receiver.id)

        return cast(
            "Message | None",
            await self._client.send_rich_message(
                chat_id=self.chat.id,  # ty: ignore[unresolved-attribute, invalid-argument-type]  # a message has a chat
                rich_message=rich_message,
                message_thread_id=self.message_thread_id,
                direct_messages_topic_id=self.direct_messages_topic_id,
                ephemeral_message_parameters=ephemeral_message_parameters,
                reply_parameters=reply_parameters,
                business_connection_id=self.business_connection_id,
                **kw,
            ),
        )

    if TYPE_CHECKING:
        # `__debug__` is a `bool` checkers cannot resolve, so they keep both branches,
        # and accept only what both take.
        respond = PyroMessage.edit if __debug__ else PyroMessage.reply
        """`edit` if this message is `editable`, otherwise `reply`."""
        # Kurigram's `edit` takes the text first, so it shares no signature with `reply_rich`.
        respond_rich = PyroMessage.reply_rich
        """`edit(rich_message=...)` if this message is `editable`, otherwise `reply_rich`; the edit takes only what `edit` takes."""
        flow_respond = flow_edit if __debug__ else flow_reply
        """`flow_edit` if this message is `editable`, otherwise `flow_reply`."""
        flow_respond_rich = flow_edit_rich if __debug__ else flow_reply_rich
        """`flow_edit_rich` if this message is `editable`, otherwise `flow_reply_rich`."""
    else:

        async def respond(self, *args: Any, **kw: Any) -> Any:
            """Edit this message if it is `editable`, otherwise reply to it, with kurigram.

            On the client's own ephemeral message kurigram's `edit` fails, so
            use `flow_respond` there.

            Args:
                *args: Passed to `edit` or `reply`.
                **kw: Passed to `edit` or `reply`.

            Returns:
                What `edit` or `reply` returns.
            """
            return await (self.edit if self.editable else self.reply)(*args, **kw)

        async def respond_rich(self, rich_message: InputRichMessage, **kw: Any) -> Any:
            """Edit this message to a rich message if it is `editable`, otherwise reply with one, with kurigram.

            The edit takes only what `edit` takes besides `rich_message`. On
            the client's own ephemeral message kurigram's `edit` fails, so use
            `flow_respond_rich` there.

            Args:
                rich_message: The rich message to edit to or send.
                **kw: Passed to `edit` or `reply_rich`.

            Returns:
                What `edit` or `reply_rich` returns.
            """
            if self.editable:
                return await self.edit(rich_message=rich_message, **kw)
            return await self.reply_rich(rich_message, **kw)

        async def flow_respond(self, *args: Any, **kw: Any) -> Any:
            """Edit this message with `flow_edit` if it is `editable`, otherwise reply with `flow_reply`.

            Args:
                *args: Passed to `flow_edit` or `flow_reply`.
                **kw: Passed to `flow_edit` or `flow_reply`.

            Returns:
                What `flow_edit` or `flow_reply` returns.

            Raises:
                ValueError: As in `flow_edit` or `flow_reply`.
            """
            return await (self.flow_edit if self.editable else self.flow_reply)(*args, **kw)

        async def flow_respond_rich(self, *args: Any, **kw: Any) -> Any:
            """Edit this message with `flow_edit_rich` if it is `editable`, otherwise reply with `flow_reply_rich`.

            Args:
                *args: Passed to `flow_edit_rich` or `flow_reply_rich`.
                **kw: Passed to `flow_edit_rich` or `flow_reply_rich`.

            Returns:
                What `flow_edit_rich` or `flow_reply_rich` returns.

            Raises:
                ValueError: As in `flow_edit_rich` or `flow_reply_rich`.
            """
            return await (self.flow_edit_rich if self.editable else self.flow_reply_rich)(
                *args, **kw
            )


__all__ = ("Message",)
