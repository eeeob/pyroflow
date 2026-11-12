"""pyroflow's patched `pyrogram.Client`."""

from __future__ import annotations as _annotations

import copy
from typing import Any, cast, overload, TYPE_CHECKING

from pyrogram import (
    Client as PyroClient,
    types as pyro_types,
)

from ..errors import ListenerAttemptsExhausted
from ..models import AskAgain, ListenerContext
from ..utils import patch_cls, call_maybe_async, get_update_executor
from ..types import Message, CallbackQuery

if TYPE_CHECKING:
    import sys
    from collections.abc import Awaitable, Callable

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
    from ..models import AskParser, CallbackQueryKey, ListenerKey, MessageKey
    from ..typings import QuestionT, ResultT, UpdateType
    from ..update_listener import ListenKw, UpdateListener


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

    workers_policy: WorkersPolicy | None = None
    """What a wait inside a handler does when the workers run short; `None` does nothing."""
    ask_context_message: bool = False
    """Whether the `ask_*` methods put the message they sent or edited in the wait's `context`."""

    def setup_pyroflow(
        self,
        *,
        workers_policy: WorkersPolicy | None = workers_policy,
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
        self.workers_policy = workers_policy
        self.ask_context_message = ask_context_message
        return self

    def get_listener(self, update_type: type[UpdateType]) -> UpdateListener[UpdateType] | None:
        """Return the `UpdateListener` registered for `update_type`, or `None` if there is none.

        Args:
            update_type: The update type, such as `Message`.

        Returns:
            The listener, or `None`.
        """
        return self.dispatcher.listeners.get(update_type)

    def require_listener(self, update_type: type[UpdateType]) -> UpdateListener[UpdateType]:
        """Return the `UpdateListener` registered for `update_type`.

        Args:
            update_type: The update type, such as `Message`.

        Returns:
            The listener.

        Raises:
            RuntimeError: If no listener is registered for `update_type`.
        """
        listener = self.get_listener(update_type)

        if listener is None:
            msg = (
                f"No listener registered for {update_type.__name__}. "
                "Register one via client.register_listener()."
            )
            raise RuntimeError(msg)

        return listener

    async def listen(self, key: ListenerKey[UpdateType], **kw: Unpack[ListenKw]) -> UpdateType:
        """Wait for the next update matching `key`, on the listener of its update type.

        Args:
            key: The key to wait on; its `__update_type__` picks the listener.
            **kw: The arguments of the wait, as `UpdateListener.listen` takes them.

        Returns:
            The matching update.

        Raises:
            RuntimeError: If no listener is registered for the update type of `key`.
            ListenerTimeout: If the timeout expires before an update arrives.
            ListenerCancelled: If the wait is cancelled.
            ListenerAlreadyExists: If the listener refuses a second wait on
                the key (`DuplicatePolicy.REJECT`).
        """
        return await self.require_listener(key.__update_type__).listen(key, **kw)

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

        Calls `listen` of the listener registered for `Message`, with a key
        of its `__key_type__` made of these fields.

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
        listener = self.require_listener(Message)
        key = cast("type[MessageKey]", listener.__key_type__)(
            chat_id=chat_id,
            user_id=user_id,
            message_thread_id=message_thread_id,
            direct_messages_topic_id=direct_messages_topic_id,
            ephemeral=ephemeral,
        )
        return await listener.listen(key, **kw)

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

        Calls `listen` of the listener registered for `CallbackQuery`, with
        a key of its `__key_type__` made of these fields.

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
        listener = self.require_listener(CallbackQuery)
        key = cast("type[CallbackQueryKey]", listener.__key_type__)(
            chat_id=chat_id,
            user_id=user_id,
            message_id=message_id,
            inline_message_id=inline_message_id,
            ephemeral=ephemeral,
        )
        return await listener.listen(key, **kw)

    def register_listener(self, listener: UpdateListener[UpdateType]) -> None:
        """Register a listener for its declared update type.

        Only one listener per update type, and only before the client starts.
        The listener is bound to this client, so one listener serves one client.

        Args:
            listener: The listener to register.

        Raises:
            RuntimeError: If the client is already running.
            ValueError: If a listener is already registered for that update
                type, or the listener is registered on another client.
        """
        self.dispatcher.register_listener(listener)

    async def unregister_listener(self, update_type: type[pyro_types.Update]) -> None:
        """Unregister and stop the listener for the given update type, and unbind it.

        Does nothing if no listener is registered for that type.

        Args:
            update_type: The Pyrogram update class whose listener to remove.
        """
        await self.dispatcher.unregister_listener(update_type)

    def context_with_message(
        self, sent: Message, context: ListenerContext | None
    ) -> ListenerContext | None:
        """Put `sent` in `context` when `ask_context_message` is on, in a copy of it.

        Args:
            sent: The message the wait is for.
            context: The context given to the `ask_*` method, or `None`.

        Returns:
            The context of the wait; `context` itself if it holds a message
            already, or if `ask_context_message` is off.
        """
        if not self.ask_context_message:
            return context

        if context is None:
            return ListenerContext(message=sent)

        if context.message is not None:
            return context

        context = copy.copy(context)
        context.message = sent

        return context

    async def ask_repeatedly(
        self,
        ask: Callable[..., Awaitable[UpdateType]],
        chat_id: StrInt | None,
        question: QuestionT,
        mode: object,
        retry_mode: object,
        parse: AskParser[UpdateType, QuestionT, Any],
        attempts: int | None,
        kw: dict[str, Any],
        *,
        listen_user_id: int | None = None,
        listen_context: ListenerContext | None = None,
        listen_filters: Filter | None = None,
        listen_strict: bool = False,
        listen_timeout: Number | None = None,
    ) -> Any:
        """Call `ask` until `parse` returns a value.

        Args:
            ask: The `ask_*` method to repeat, called as
                `ask(chat_id, question, mode, listen_..., **kw)`.
            chat_id: The first argument of `ask`, or `None` if it takes none.
            question: The first question.
            mode: The second argument of `ask` for the first question.
            retry_mode: The second argument of `ask` for each retry.
            parse: `(answer, kw) -> AskAgain | value`, sync or async: `AskAgain`
                asks again, and anything else is returned.
            attempts: How many times to ask, or `None` for no limit.
            kw: The arguments of the first question.
            listen_user_id: Passed to `ask`.
            listen_context: Passed to `ask`.
            listen_filters: Passed to `ask`.
            listen_strict: Passed to `ask`.
            listen_timeout: Passed to `ask`, for each wait on its own.

        Returns:
            The value `parse` returned.

        Raises:
            ValueError: If `attempts` is not positive; nothing is asked then.
            ListenerAttemptsExhausted: If `parse` rejects an answer when
                `attempts` questions were asked; `update` holds that answer.
        """
        if attempts is not None and attempts < 1:
            msg = "attempts must be positive"
            raise ValueError(msg)

        target = () if chat_id is None else (chat_id,)
        listen_kw = {
            "listen_user_id": listen_user_id,
            "listen_context": listen_context,
            "listen_filters": listen_filters,
            "listen_strict": listen_strict,
            "listen_timeout": listen_timeout,
        }
        asked = 0

        while True:
            asked += 1
            answer = await ask(*target, question, mode, **(listen_kw | kw))
            result = await call_maybe_async(parse, answer, kw, executor=get_update_executor(answer))

            if not isinstance(result, AskAgain):
                return result

            if attempts is not None and asked >= attempts:
                raise ListenerAttemptsExhausted(attempts, answer)

            question, mode, kw = result.question, retry_mode, result.kw

    @overload
    async def ask(
        self,
        chat_id: StrInt,
        text: str,
        edit_message_id: None = None,
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
        edit_message_id: int,
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
        edit_message_id: int | None = None,
        *,
        listen_user_id: int | None = None,
        listen_context: ListenerContext | None = None,
        listen_filters: Filter | None = None,
        listen_strict: bool = False,
        listen_timeout: Number | None = None,
        **kw: Any,
    ) -> Message:
        """Send or edit a message, then wait for the next message in its chat and topic.

        With `edit_message_id` the message is edited with `edit_message_text`,
        otherwise a new one is sent with `send_message`. The answer is then
        awaited on `from_sent` of the listener's `__key_type__` for that
        message: from `listen_user_id`, or from any user without it.

        Args:
            chat_id: Chat to send to, or that holds the message to edit.
            text: The text to send or edit.
            edit_message_id: If provided, edit this message instead of sending a new one.
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
        listener = self.require_listener(Message)
        # What `ask_*` accepts always gets a message back, and `patch_cls` makes pyrogram's
        # `Message` the same class as pyroflow's at runtime.
        sent = cast(
            "Message",
            await (
                self.send_message(chat_id=chat_id, text=text, **kw)
                if edit_message_id is None
                else self.edit_message_text(
                    chat_id=chat_id, message_id=edit_message_id, text=text, **kw
                )
            ),
        )

        return await listener.listen(
            listener.__key_type__.from_sent(sent, listen_user_id),
            context=self.context_with_message(sent, listen_context),
            filters=listen_filters,
            strict=listen_strict,
            timeout=listen_timeout,
        )

    @overload
    async def ask_rich(
        self,
        chat_id: StrInt,
        rich_message: InputRichMessage,
        edit_message_id: None = None,
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
        edit_message_id: int,
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
        edit_message_id: int | None = None,
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
        `edit_message_id` with `edit_message_text(rich_message=...)`.

        Args:
            chat_id: Chat to send to, or that holds the message to edit.
            rich_message: The rich message to send or edit.
            edit_message_id: If provided, edit this message instead of sending a new one.
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
        listener = self.require_listener(Message)
        sent = cast(
            "Message",
            await (
                self.send_rich_message(chat_id=chat_id, rich_message=rich_message, **kw)
                if edit_message_id is None
                else self.edit_message_text(
                    chat_id=chat_id, message_id=edit_message_id, rich_message=rich_message, **kw
                )
            ),
        )

        return await listener.listen(
            listener.__key_type__.from_sent(sent, listen_user_id),
            context=self.context_with_message(sent, listen_context),
            filters=listen_filters,
            strict=listen_strict,
            timeout=listen_timeout,
        )

    @overload
    async def ask_callback_query(
        self,
        chat_id: StrInt,
        text: str,
        edit_message_id: None = None,
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
        edit_message_id: int,
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
        edit_message_id: int | None = None,
        *,
        listen_user_id: int | None = None,
        listen_context: ListenerContext | None = None,
        listen_filters: Filter | None = None,
        listen_strict: bool = False,
        listen_timeout: Number | None = None,
        **kw: Any,
    ) -> CallbackQuery:
        """Send or edit a message, then wait for a press on its buttons.

        Like `ask`, but the press is awaited on `from_sent` of the listener's
        `__key_type__` for the message: from any user, so narrow it with
        `listen_filters`.

        Pass `reply_markup`: a question without buttons cannot be answered, and
        its wait stays open until `listen_timeout`, or forever without one.

        Args:
            chat_id: Chat to send to, or that holds the message to edit.
            text: The text to send or edit.
            edit_message_id: If provided, edit this message instead of sending a new one.
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
        listener = self.require_listener(CallbackQuery)
        sent = cast(
            "Message",
            await (
                self.send_message(chat_id=chat_id, text=text, **kw)
                if edit_message_id is None
                else self.edit_message_text(
                    chat_id=chat_id, message_id=edit_message_id, text=text, **kw
                )
            ),
        )

        return await listener.listen(
            listener.__key_type__.from_sent(sent, listen_user_id),
            context=self.context_with_message(sent, listen_context),
            filters=listen_filters,
            strict=listen_strict,
            timeout=listen_timeout,
        )

    @overload
    async def ask_callback_query_rich(
        self,
        chat_id: StrInt,
        rich_message: InputRichMessage,
        edit_message_id: None = None,
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
        edit_message_id: int,
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
        edit_message_id: int | None = None,
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
        `edit_message_id` with `edit_message_text(rich_message=...)`.

        Args:
            chat_id: Chat to send to, or that holds the message to edit.
            rich_message: The rich message to send or edit.
            edit_message_id: If provided, edit this message instead of sending a new one.
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
        listener = self.require_listener(CallbackQuery)
        sent = cast(
            "Message",
            await (
                self.send_rich_message(chat_id=chat_id, rich_message=rich_message, **kw)
                if edit_message_id is None
                else self.edit_message_text(
                    chat_id=chat_id, message_id=edit_message_id, rich_message=rich_message, **kw
                )
            ),
        )

        return await listener.listen(
            listener.__key_type__.from_sent(sent, listen_user_id),
            context=self.context_with_message(sent, listen_context),
            filters=listen_filters,
            strict=listen_strict,
            timeout=listen_timeout,
        )

    @overload
    async def ask_until(
        self,
        chat_id: StrInt,
        text: str,
        edit_message_id: None = None,
        *,
        parse: AskParser[Message, str, ResultT],
        attempts: int | None = None,
        listen_user_id: int | None = None,
        listen_context: ListenerContext | None = None,
        listen_filters: Filter | None = None,
        listen_strict: bool = False,
        listen_timeout: Number | None = None,
        **kw: Unpack[AskSendKw],
    ) -> ResultT: ...

    # Retries send what the first question edits, so only edit arguments fit both.
    @overload
    async def ask_until(
        self,
        chat_id: StrInt,
        text: str,
        edit_message_id: int,
        *,
        parse: AskParser[Message, str, ResultT],
        attempts: int | None = None,
        listen_user_id: int | None = None,
        listen_context: ListenerContext | None = None,
        listen_filters: Filter | None = None,
        listen_strict: bool = False,
        listen_timeout: Number | None = None,
        **kw: Unpack[AskEditKw],
    ) -> ResultT: ...

    async def ask_until(
        self,
        chat_id: StrInt,
        text: str,
        edit_message_id: int | None = None,
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
        dict of keyword arguments of the question. What it returns decides what
        happens next:

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

        With `edit_message_id` only the first question edits that message; after a
        rejection each question is sent as a new message, since Telegram
        refuses an edit that changes nothing. To send it to a topic, name the
        topic in the `kw` of `AskAgain`.

        Args:
            chat_id: As in `ask`.
            text: The first question.
            edit_message_id: As in `ask`, for the first question only.
            parse: Decides what happens with each answer, as above.
            attempts: How many times to ask, or `None` for no limit.
            listen_user_id: As in `ask`.
            listen_context: As in `ask`.
            listen_filters: As in `ask`, a pre-filter in front of `parse`.
            listen_strict: As in `ask`; a rejection by `listen_filters` ends
                the loop, not only the wait.
            listen_timeout: As in `ask`, for each wait on its own.
            **kw: Passed to `send_message` or `edit_message_text`.

        Returns:
            The value `parse` returned.

        Raises:
            ValueError: If `attempts` is not positive; nothing is sent then.
            ListenerAttemptsExhausted: If `parse` rejects an answer when
                `attempts` questions were asked; `update` holds that answer.
            Anything else `ask` or `parse` raises, at once.
        """
        return await self.ask_repeatedly(
            self.ask,
            chat_id,
            text,
            edit_message_id,
            None,
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
        chat_id: StrInt,
        rich_message: InputRichMessage,
        edit_message_id: None = None,
        *,
        parse: AskParser[Message, InputRichMessage, ResultT],
        attempts: int | None = None,
        listen_user_id: int | None = None,
        listen_context: ListenerContext | None = None,
        listen_filters: Filter | None = None,
        listen_strict: bool = False,
        listen_timeout: Number | None = None,
        **kw: Unpack[AskRichSendKw],
    ) -> ResultT: ...

    # A retry sends only the `kw` in `AskAgain`, so these need not fit `send_rich_message`.
    @overload
    async def ask_rich_until(
        self,
        chat_id: StrInt,
        rich_message: InputRichMessage,
        edit_message_id: int,
        *,
        parse: AskParser[Message, InputRichMessage, ResultT],
        attempts: int | None = None,
        listen_user_id: int | None = None,
        listen_context: ListenerContext | None = None,
        listen_filters: Filter | None = None,
        listen_strict: bool = False,
        listen_timeout: Number | None = None,
        **kw: Unpack[AskRichEditKw],
    ) -> ResultT: ...

    async def ask_rich_until(
        self,
        chat_id: StrInt,
        rich_message: InputRichMessage,
        edit_message_id: int | None = None,
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
            chat_id: As in `ask`.
            rich_message: The first question.
            edit_message_id: As in `ask`, for the first question only.
            parse: As in `ask_until`.
            attempts: As in `ask_until`.
            listen_user_id: As in `ask`.
            listen_context: As in `ask`.
            listen_filters: As in `ask_until`.
            listen_strict: As in `ask_until`.
            listen_timeout: As in `ask`, for each wait on its own.
            **kw: Passed to `send_rich_message` or `edit_message_text`, for the
                first question.

        Returns:
            The value `parse` returned.

        Raises:
            ValueError: If `attempts` is not positive; nothing is sent then.
            ListenerAttemptsExhausted: If `parse` rejects an answer when
                `attempts` questions were asked; `update` holds that answer.
            Anything else `ask_rich` or `parse` raises, at once.
        """
        return await self.ask_repeatedly(
            self.ask_rich,
            chat_id,
            rich_message,
            edit_message_id,
            None,
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
        chat_id: StrInt,
        text: str,
        edit_message_id: None = None,
        *,
        parse: AskParser[CallbackQuery, str, ResultT],
        attempts: int | None = None,
        listen_user_id: int | None = None,
        listen_context: ListenerContext | None = None,
        listen_filters: Filter | None = None,
        listen_strict: bool = False,
        listen_timeout: Number | None = None,
        **kw: Unpack[AskSendKw],
    ) -> ResultT: ...

    # Retries send what the first question edits, so only edit arguments fit both.
    @overload
    async def ask_callback_query_until(
        self,
        chat_id: StrInt,
        text: str,
        edit_message_id: int,
        *,
        parse: AskParser[CallbackQuery, str, ResultT],
        attempts: int | None = None,
        listen_user_id: int | None = None,
        listen_context: ListenerContext | None = None,
        listen_filters: Filter | None = None,
        listen_strict: bool = False,
        listen_timeout: Number | None = None,
        **kw: Unpack[AskEditKw],
    ) -> ResultT: ...

    async def ask_callback_query_until(
        self,
        chat_id: StrInt,
        text: str,
        edit_message_id: int | None = None,
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
            chat_id: As in `ask`.
            text: The first question.
            edit_message_id: As in `ask`, for the first question only.
            parse: As in `ask_until`.
            attempts: As in `ask_until`.
            listen_user_id: As in `ask`.
            listen_context: As in `ask`.
            listen_filters: As in `ask_until`.
            listen_strict: As in `ask_until`.
            listen_timeout: As in `ask`, for each wait on its own.
            **kw: Passed to `send_message` or `edit_message_text`.

        Returns:
            The value `parse` returned.

        Raises:
            ValueError: If `attempts` is not positive; nothing is sent then.
            ListenerAttemptsExhausted: If `parse` rejects a press when
                `attempts` questions were asked; `update` holds that press.
            Anything else `ask_callback_query` or `parse` raises, at once.
        """
        return await self.ask_repeatedly(
            self.ask_callback_query,
            chat_id,
            text,
            edit_message_id,
            None,
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
        chat_id: StrInt,
        rich_message: InputRichMessage,
        edit_message_id: None = None,
        *,
        parse: AskParser[CallbackQuery, InputRichMessage, ResultT],
        attempts: int | None = None,
        listen_user_id: int | None = None,
        listen_context: ListenerContext | None = None,
        listen_filters: Filter | None = None,
        listen_strict: bool = False,
        listen_timeout: Number | None = None,
        **kw: Unpack[AskRichSendKw],
    ) -> ResultT: ...

    # A retry sends only the `kw` in `AskAgain`, so these need not fit `send_rich_message`.
    @overload
    async def ask_callback_query_rich_until(
        self,
        chat_id: StrInt,
        rich_message: InputRichMessage,
        edit_message_id: int,
        *,
        parse: AskParser[CallbackQuery, InputRichMessage, ResultT],
        attempts: int | None = None,
        listen_user_id: int | None = None,
        listen_context: ListenerContext | None = None,
        listen_filters: Filter | None = None,
        listen_strict: bool = False,
        listen_timeout: Number | None = None,
        **kw: Unpack[AskRichEditKw],
    ) -> ResultT: ...

    async def ask_callback_query_rich_until(
        self,
        chat_id: StrInt,
        rich_message: InputRichMessage,
        edit_message_id: int | None = None,
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
            chat_id: As in `ask`.
            rich_message: The first question.
            edit_message_id: As in `ask`, for the first question only.
            parse: As in `ask_until`.
            attempts: As in `ask_until`.
            listen_user_id: As in `ask`.
            listen_context: As in `ask`.
            listen_filters: As in `ask_until`.
            listen_strict: As in `ask_until`.
            listen_timeout: As in `ask`, for each wait on its own.
            **kw: Passed to `send_rich_message` or `edit_message_text`, for the
                first question.

        Returns:
            The value `parse` returned.

        Raises:
            ValueError: If `attempts` is not positive; nothing is sent then.
            ListenerAttemptsExhausted: If `parse` rejects a press when
                `attempts` questions were asked; `update` holds that press.
            Anything else `ask_callback_query_rich` or `parse` raises, at once.
        """
        return await self.ask_repeatedly(
            self.ask_callback_query_rich,
            chat_id,
            rich_message,
            edit_message_id,
            None,
            parse,
            attempts,
            kw,
            listen_user_id=listen_user_id,
            listen_context=listen_context,
            listen_filters=listen_filters,
            listen_strict=listen_strict,
            listen_timeout=listen_timeout,
        )


__all__ = ("Client",)
