"""pyroflow's patched `pyrogram.Client`."""

from __future__ import annotations as _annotations

import copy
from typing import Any, cast, overload, TYPE_CHECKING

from pyrogram import (
    Client as PyroClient,
    types as pyro_types,
)

from ..models import CallbackQueryKey, ListenerContext, MessageKey
from ..utils import patch_cls
from ..types import Message, CallbackQuery
from ..update_listener import UpdateListener

if TYPE_CHECKING:
    import sys

    if sys.version_info >= (3, 11):
        from typing import Self, Unpack
    else:
        from typing_extensions import Self, Unpack

    from pyrogram.filters import Filter
    from pyrogram.types import InputRichMessage
    from pytrove.typings import (
        Number,
        StrInt,
    )

    from .._internal import AskEditKw, AskRichEditKw, AskRichSendKw, AskSendKw
    from ..dispatcher import Dispatcher
    from ..enums import WorkersPolicy
    from ..typings import UpdateType
    from ..update_listener import ListenKw


@patch_cls
class Client(PyroClient):
    """Pyrogram's `Client`, patched in place with listeners and the `ask_*` methods.

    Attach the per-update-type systems before the client starts with
    `register_listener`. An update claimed by a listener never reaches the
    normal handlers. Like
    `pyrogram.Client`, every `async` method can also be called synchronously
    from outside an event loop.
    """

    # `patch_cls` makes pyroflow's `Dispatcher` the same class as pyrogram's at runtime.
    dispatcher: Dispatcher  # ty: ignore[invalid-mutable-override]  # same class at runtime via `patch_cls`
    """The dispatcher that routes updates to listeners and handlers."""

    ask_context_message: bool = False
    """Whether the `ask_*` methods put the message they sent or edited in the wait's `context`."""

    def setup_pyroflow(
        self,
        *,
        workers_policy: WorkersPolicy | None = None,
        ask_context_message: bool = ask_context_message,
    ) -> Self:
        """Set up pyroflow on this client, and return the client.

        Every call sets all the values: one it leaves out goes back to its
        default.

        It is a method rather than `Client(...)` arguments so pyroflow does
        not redeclare `pyrogram.Client.__init__`, a long signature it would
        then have to follow on every Pyrogram change. Chain it instead:
        `Client("bot", workers=12).setup_pyroflow(workers_policy=WorkersPolicy.REJECT)`.

        Args:
            workers_policy: What waits inside handlers do when the workers
                run short. With `None` there is no policy: waits hold their
                workers, and the bot freezes if all of them wait.
            ask_context_message: Whether the `ask_*` methods put the message
                they sent or edited in the wait's `context`. Otherwise
                `listen_context` reaches the listener as it is.

        Returns:
            The client itself.
        """
        self.dispatcher.workers_policy = workers_policy
        self.ask_context_message = ask_context_message
        return self

    def get_listener(self, update_type: type[UpdateType]) -> UpdateListener[UpdateType, Any] | None:
        """Return the `UpdateListener` registered for `update_type`, or `None` if there is none.

        Args:
            update_type: The update type, such as `Message`.

        Returns:
            The listener, or `None`.
        """
        return self.dispatcher.listeners.get(update_type)

    async def listen_message(
        self,
        chat_id: int | None = None,
        user_id: int | None = None,
        message_thread_id: int | None = None,
        direct_messages_topic_id: int | None = None,
        ephemeral: bool = False,
        **kw: Unpack[ListenKw],
    ) -> Message:
        """Wait for the next message matching the given fields; `None` matches any value.

        Waits on the listener registered for `Message`, with a `MessageKey`
        of the given fields.

        Args:
            chat_id: The chat to listen in; a user's private chat has the
                user's id.
            user_id: The sender to wait for.
            message_thread_id: The forum topic to listen in.
            direct_messages_topic_id: The topic of a channel's direct messages
                chat to listen in.
            ephemeral: Wait on ephemeral messages, the only wait they reach.
            **kw: The arguments of the wait, as `UpdateListener.listen` takes them.

        Returns:
            The matching message.

        Raises:
            RuntimeError: If no listener is registered for `Message`.
            ListenerTimeout: If the timeout expires before a message arrives.
            ListenerCancelled: If the wait is cancelled.
            ListenerAlreadyExists: If the listener refuses a second wait on
                the key (`DuplicatePolicy.REJECT`).
        """
        listener = self.get_listener(Message)

        if listener is None:
            msg = (
                "No listener registered for Message. "
                "Register one via client.register_listener() before calling listen_message()."
            )
            raise RuntimeError(msg)

        key = MessageKey(chat_id, user_id, message_thread_id, direct_messages_topic_id, ephemeral)
        return await UpdateListener.listen(listener, key, **kw)

    async def listen_callback_query(
        self,
        chat_id: int | None = None,
        user_id: int | None = None,
        message_id: int | None = None,
        inline_message_id: str | None = None,
        ephemeral: bool = False,
        **kw: Unpack[ListenKw],
    ) -> CallbackQuery:
        """Wait for the next button press matching the given fields; `None` matches any value.

        Waits on the listener registered for `CallbackQuery`, with a
        `CallbackQueryKey` of the given fields.

        Args:
            chat_id: The chat to listen in; a user's private chat has the
                user's id. A press on an inline-mode message has no chat.
            user_id: The user to wait for.
            message_id: The message whose buttons to wait on.
            inline_message_id: The inline-mode message whose buttons to wait
                on.
            ephemeral: Wait on presses on ephemeral messages, the only wait
                they reach.
            **kw: The arguments of the wait, as `UpdateListener.listen` takes them.

        Returns:
            The matching callback query.

        Raises:
            RuntimeError: If no listener is registered for `CallbackQuery`.
            ListenerTimeout: If the timeout expires before a press arrives.
            ListenerCancelled: If the wait is cancelled.
            ListenerAlreadyExists: If the listener refuses a second wait on
                the key (`DuplicatePolicy.REJECT`).
        """
        listener = self.get_listener(CallbackQuery)

        if listener is None:
            msg = (
                "No listener registered for CallbackQuery. "
                "Register one via client.register_listener() before calling listen_callback_query()."
            )
            raise RuntimeError(msg)

        key = CallbackQueryKey(chat_id, user_id, message_id, inline_message_id, ephemeral)
        return await UpdateListener.listen(listener, key, **kw)

    def register_listener(self, listener: UpdateListener[UpdateType, Any]) -> None:
        """Register a listener for its declared update type.

        Only one listener per update type, and only before the client starts.

        Args:
            listener: The listener to register.

        Raises:
            RuntimeError: If the client is already running.
            ValueError: If a listener is already registered for that update type.
        """
        self.dispatcher.register_listener(listener)

    async def unregister_listener(self, update_type: type[pyro_types.Update]) -> None:
        """Unregister and stop the listener for the given update type.

        Does nothing if no listener is registered for that type.

        Args:
            update_type: The Pyrogram update class whose listener to remove.
        """
        await self.dispatcher.unregister_listener(update_type)

    @overload
    async def ask(
        self,
        chat_id: StrInt,
        text: str,
        message_id: None = None,
        *,
        listen_user_id: int | None = None,
        listen_context: ListenerContext | None = None,
        listen_filters: Filter | None = None,
        listen_strict: bool = False,
        listen_timeout: Number | None = None,
        **kw: Unpack[AskSendKw],
    ) -> Message: ...

    @overload
    async def ask(
        self,
        chat_id: StrInt,
        text: str,
        message_id: int,
        *,
        listen_user_id: int | None = None,
        listen_context: ListenerContext | None = None,
        listen_filters: Filter | None = None,
        listen_strict: bool = False,
        listen_timeout: Number | None = None,
        **kw: Unpack[AskEditKw],
    ) -> Message: ...

    async def ask(
        self,
        chat_id: StrInt,
        text: str,
        message_id: int | None = None,
        *,
        listen_user_id: int | None = None,
        listen_context: ListenerContext | None = None,
        listen_filters: Filter | None = None,
        listen_strict: bool = False,
        listen_timeout: Number | None = None,
        **kw: Any,
    ) -> Message:
        """Send or edit a message, then wait for the next message in its chat and topic.

        With `message_id` the message is edited with `edit_message_text`,
        otherwise a new one is sent with `send_message`. The answer is then
        awaited on `MessageKey.from_sent` of that message: from
        `listen_user_id`, or from any user without it.

        Args:
            chat_id: Chat to send to, or that holds the message to edit.
            text: The text to send or edit.
            message_id: If provided, edit this message instead of sending a new one.
            listen_user_id: The user to wait for, or `None` for any user.
            listen_context: Values attached to the listener. With
                `ask_context_message` on (see `setup_pyroflow`), it gets the
                sent or edited message as `message`, on a copy, unless it
                holds one. So `on_error_func` can edit or delete the question.
            listen_filters: A Pyrogram filter the answer must pass besides its key.
            listen_strict: What an update that matches the key but fails
                `listen_filters` does: `True` ends the wait with
                `ListenerRejected`, `False` skips it and keeps waiting.
                Without `listen_strict`, a rejected update that cannot come
                again leaves the wait open until `listen_timeout`, or forever
                without one; see the warning in `UpdateListener.listen`.
            listen_timeout: Seconds to wait before raising `ListenerTimeout`.
            **kw: Passed to `send_message` or `edit_message_text`.

        Returns:
            The answer.

        Raises:
            RuntimeError: If no listener is registered for `Message`.
            ListenerTimeout: If the timeout expires before the answer arrives.
            ListenerCancelled: If the listener is cancelled while waiting.
            ListenerWorkersBusy: If the wait would start inside a handler with
                no worker to spare (see `WorkersPolicy`). The message is
                already sent or edited by then.
            ListenerAlreadyExists: If the listener refuses a second wait on
                the key (`DuplicatePolicy.REJECT`). The message is already
                sent or edited by then.
        """
        listener = self.get_listener(Message)

        if listener is None:
            msg = (
                "No listener registered for Message. "
                "Register one via client.register_listener() before calling ask()."
            )
            raise RuntimeError(msg)

        if message_id is not None:
            # `patch_cls` makes pyrogram's `Message` the same class as pyroflow's at runtime.
            m = cast(
                "Message",
                await self.edit_message_text(
                    chat_id=chat_id, message_id=message_id, text=text, **kw
                ),
            )
        else:
            m = cast(
                "Message",
                await self.send_message(chat_id=chat_id, text=text, **kw),
            )

        key = MessageKey.from_sent(m, listen_user_id)
        context = listen_context

        if self.ask_context_message:
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
        chat_id: StrInt,
        rich_message: InputRichMessage,
        message_id: None = None,
        *,
        listen_user_id: int | None = None,
        listen_context: ListenerContext | None = None,
        listen_filters: Filter | None = None,
        listen_strict: bool = False,
        listen_timeout: Number | None = None,
        **kw: Unpack[AskRichSendKw],
    ) -> Message: ...

    @overload
    async def ask_rich(
        self,
        chat_id: StrInt,
        rich_message: InputRichMessage,
        message_id: int,
        *,
        listen_user_id: int | None = None,
        listen_context: ListenerContext | None = None,
        listen_filters: Filter | None = None,
        listen_strict: bool = False,
        listen_timeout: Number | None = None,
        **kw: Unpack[AskRichEditKw],
    ) -> Message: ...

    async def ask_rich(
        self,
        chat_id: StrInt,
        rich_message: InputRichMessage,
        message_id: int | None = None,
        *,
        listen_user_id: int | None = None,
        listen_context: ListenerContext | None = None,
        listen_filters: Filter | None = None,
        listen_strict: bool = False,
        listen_timeout: Number | None = None,
        **kw: Any,
    ) -> Message:
        """Send or edit a rich message, then wait for the next message in its chat and topic.

        Like `ask`, but sends with `send_rich_message`, or edits
        `message_id` with `edit_message_text(rich_message=...)`.

        Args:
            chat_id: Chat to send to, or that holds the message to edit.
            rich_message: The rich message to send or edit.
            message_id: If provided, edit this message instead of sending a new one.
            listen_user_id: As in `ask`.
            listen_context: As in `ask`.
            listen_filters: As in `ask`.
            listen_strict: As in `ask`.
            listen_timeout: As in `ask`.
            **kw: Passed to `send_rich_message` or `edit_message_text`.

        Returns:
            The answer.

        Raises:
            RuntimeError: If no listener is registered for `Message`.
            ListenerTimeout: If the timeout expires before the answer arrives.
            ListenerCancelled: If the listener is cancelled while waiting.
            ListenerWorkersBusy: As in `ask`.
            ListenerAlreadyExists: As in `ask`.
        """
        listener = self.get_listener(Message)

        if listener is None:
            msg = (
                "No listener registered for Message. "
                "Register one via client.register_listener() before calling ask_rich()."
            )
            raise RuntimeError(msg)

        if message_id is not None:
            m = cast(
                "Message",
                await self.edit_message_text(
                    chat_id=chat_id, message_id=message_id, rich_message=rich_message, **kw
                ),
            )
        else:
            m = cast(
                "Message",
                await self.send_rich_message(chat_id=chat_id, rich_message=rich_message, **kw),
            )

        key = MessageKey.from_sent(m, listen_user_id)
        context = listen_context

        if self.ask_context_message:
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
        chat_id: StrInt,
        text: str,
        message_id: None = None,
        *,
        listen_user_id: int | None = None,
        listen_context: ListenerContext | None = None,
        listen_filters: Filter | None = None,
        listen_strict: bool = False,
        listen_timeout: Number | None = None,
        **kw: Unpack[AskSendKw],
    ) -> CallbackQuery: ...

    @overload
    async def ask_callback_query(
        self,
        chat_id: StrInt,
        text: str,
        message_id: int,
        *,
        listen_user_id: int | None = None,
        listen_context: ListenerContext | None = None,
        listen_filters: Filter | None = None,
        listen_strict: bool = False,
        listen_timeout: Number | None = None,
        **kw: Unpack[AskEditKw],
    ) -> CallbackQuery: ...

    async def ask_callback_query(
        self,
        chat_id: StrInt,
        text: str,
        message_id: int | None = None,
        *,
        listen_user_id: int | None = None,
        listen_context: ListenerContext | None = None,
        listen_filters: Filter | None = None,
        listen_strict: bool = False,
        listen_timeout: Number | None = None,
        **kw: Any,
    ) -> CallbackQuery:
        """Send or edit a message, then wait for a press on its buttons.

        Like `ask`, but the press is awaited on
        `CallbackQueryKey.from_sent` of the message: from any user, so narrow
        it with `listen_filters`.

        Args:
            chat_id: Chat to send to, or that holds the message to edit.
            text: The text to send or edit.
            message_id: If provided, edit this message instead of sending a new one.
            listen_user_id: As in `ask`.
            listen_context: As in `ask`.
            listen_filters: As in `ask`.
            listen_strict: As in `ask`.
            listen_timeout: As in `ask`.
            **kw: Passed to `send_message` or `edit_message_text`.

        Returns:
            The press.

        Raises:
            RuntimeError: If no listener is registered for `CallbackQuery`.
            ListenerTimeout: If the timeout expires before the press arrives.
            ListenerCancelled: If the listener is cancelled while waiting.
            ListenerWorkersBusy: As in `ask`.
            ListenerAlreadyExists: As in `ask`.
        """
        listener = self.get_listener(CallbackQuery)

        if listener is None:
            msg = (
                "No listener registered for CallbackQuery. "
                "Register one via client.register_listener() before calling ask_callback_query()."
            )
            raise RuntimeError(msg)

        if message_id is not None:
            m = cast(
                "Message",
                await self.edit_message_text(
                    chat_id=chat_id, message_id=message_id, text=text, **kw
                ),
            )
        else:
            m = cast(
                "Message",
                await self.send_message(chat_id=chat_id, text=text, **kw),
            )

        key = CallbackQueryKey.from_sent(m, listen_user_id)
        context = listen_context

        if self.ask_context_message:
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
        chat_id: StrInt,
        rich_message: InputRichMessage,
        message_id: None = None,
        *,
        listen_user_id: int | None = None,
        listen_context: ListenerContext | None = None,
        listen_filters: Filter | None = None,
        listen_strict: bool = False,
        listen_timeout: Number | None = None,
        **kw: Unpack[AskRichSendKw],
    ) -> CallbackQuery: ...

    @overload
    async def ask_callback_query_rich(
        self,
        chat_id: StrInt,
        rich_message: InputRichMessage,
        message_id: int,
        *,
        listen_user_id: int | None = None,
        listen_context: ListenerContext | None = None,
        listen_filters: Filter | None = None,
        listen_strict: bool = False,
        listen_timeout: Number | None = None,
        **kw: Unpack[AskRichEditKw],
    ) -> CallbackQuery: ...

    async def ask_callback_query_rich(
        self,
        chat_id: StrInt,
        rich_message: InputRichMessage,
        message_id: int | None = None,
        *,
        listen_user_id: int | None = None,
        listen_context: ListenerContext | None = None,
        listen_filters: Filter | None = None,
        listen_strict: bool = False,
        listen_timeout: Number | None = None,
        **kw: Any,
    ) -> CallbackQuery:
        """Send or edit a rich message, then wait for a press on its buttons.

        Like `ask_callback_query`, but sends with `send_rich_message`, or edits
        `message_id` with `edit_message_text(rich_message=...)`.

        Args:
            chat_id: Chat to send to, or that holds the message to edit.
            rich_message: The rich message to send or edit.
            message_id: If provided, edit this message instead of sending a new one.
            listen_user_id: As in `ask`.
            listen_context: As in `ask`.
            listen_filters: As in `ask`.
            listen_strict: As in `ask`.
            listen_timeout: As in `ask`.
            **kw: Passed to `send_rich_message` or `edit_message_text`.

        Returns:
            The press.

        Raises:
            RuntimeError: If no listener is registered for `CallbackQuery`.
            ListenerTimeout: If the timeout expires before the press arrives.
            ListenerCancelled: If the listener is cancelled while waiting.
            ListenerWorkersBusy: As in `ask`.
            ListenerAlreadyExists: As in `ask`.
        """
        listener = self.get_listener(CallbackQuery)

        if listener is None:
            msg = (
                "No listener registered for CallbackQuery. "
                "Register one via client.register_listener() "
                "before calling ask_callback_query_rich()."
            )
            raise RuntimeError(msg)

        if message_id is not None:
            m = cast(
                "Message",
                await self.edit_message_text(
                    chat_id=chat_id, message_id=message_id, rich_message=rich_message, **kw
                ),
            )
        else:
            m = cast(
                "Message",
                await self.send_rich_message(chat_id=chat_id, rich_message=rich_message, **kw),
            )

        key = CallbackQueryKey.from_sent(m, listen_user_id)
        context = listen_context

        if self.ask_context_message:
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


__all__ = ("Client",)
