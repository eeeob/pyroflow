"""pyroflow's patched `pyrogram.Client`."""

from __future__ import annotations as _annotations

import copy
from typing import Any, cast, overload, TYPE_CHECKING

from pyrogram import (
    Client as PyroClient,
    types as pyro_types,
    utils as pyro_ut,
)

from ..enums import EphemeralUpdates, ListenMessageId
from ..models import ListenerContext
from ..utils import patch_cls
from ..types import Message, CallbackQuery

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
    from ..typings import (
        ListenMessageIdT,
        UpdateType,
    )
    from ..update_listener import UpdateListener


@patch_cls
class Client(PyroClient):
    """Pyrogram's `Client`, patched in place with listeners and `ask`.

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
    """Whether `ask` puts the message it sent or edited in the wait's `context`."""

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
            ask_context_message: Whether `ask` and `ask_rich` put the message
                they sent or edited in the wait's `context`. Otherwise
                `listen_context` reaches the listener as it is, and
                `MessageListenCancellingCallbackQueryListener` only finds
                waits whose `context.message` the caller set.

        Returns:
            The client itself.
        """
        self.dispatcher.workers_policy = workers_policy
        self.ask_context_message = ask_context_message
        return self

    @property
    def listeners(self) -> dict[type[pyro_types.Update], UpdateListener[Any]]:
        """The registered `UpdateListener` of each update type, such as `Message`."""
        return self.dispatcher.listeners

    @property
    def message_listen(self) -> UpdateListener[Message]:
        """The `UpdateListener` registered for `Message` updates.

        Raises:
            KeyError: If no `Message` listener is registered.
        """
        return self.listeners[Message]

    @property
    def callback_listen(self) -> UpdateListener[CallbackQuery]:
        """The `UpdateListener` registered for `CallbackQuery` updates.

        Raises:
            KeyError: If no `CallbackQuery` listener is registered.
        """
        return self.listeners[CallbackQuery]

    def register_listener(self, listener: UpdateListener[UpdateType]) -> None:
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
        *,
        listen_user_id: int | None = None,
        listen_message_id: ListenMessageIdT | None = None,
        listen_context: ListenerContext | None = None,
        listen_filters: Filter | None = None,
        listen_strict: bool = False,
        listen_timeout: Number | None = None,
        listen_update_type: type[UpdateType],
        **kw: Unpack[AskSendKw],
    ) -> UpdateType: ...

    @overload
    async def ask(
        self,
        chat_id: StrInt,
        text: str,
        *,
        listen_user_id: int | None = None,
        listen_message_id: ListenMessageIdT | None = None,
        listen_context: ListenerContext | None = None,
        listen_filters: Filter | None = None,
        listen_strict: bool = False,
        listen_timeout: Number | None = None,
        listen_update_type: type[Message] = Message,
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
        listen_message_id: ListenMessageIdT | None = None,
        listen_context: ListenerContext | None = None,
        listen_filters: Filter | None = None,
        listen_strict: bool = False,
        listen_timeout: Number | None = None,
        listen_update_type: type[UpdateType],
        **kw: Unpack[AskEditKw],
    ) -> UpdateType: ...

    @overload
    async def ask(
        self,
        chat_id: StrInt,
        text: str,
        message_id: int,
        *,
        listen_user_id: int | None = None,
        listen_message_id: ListenMessageIdT | None = None,
        listen_context: ListenerContext | None = None,
        listen_filters: Filter | None = None,
        listen_strict: bool = False,
        listen_timeout: Number | None = None,
        listen_update_type: type[Message] = Message,
        **kw: Unpack[AskEditKw],
    ) -> Message: ...

    async def ask(
        self,
        chat_id: StrInt,
        text: str,
        message_id: int | None = None,
        *,
        listen_user_id: int | None = None,
        listen_message_id: ListenMessageIdT | None = None,
        listen_context: ListenerContext | None = None,
        listen_filters: Filter | None = None,
        listen_strict: bool = False,
        listen_timeout: Number | None = None,
        listen_update_type: type[pyro_types.Update] = Message,
        **kw: Any,
    ) -> pyro_types.Update:
        """Send or edit a message, then wait for the next matching update.

        With `message_id` the message is edited with `edit_message_text`,
        otherwise a new one is sent with `send_message`. The update is then
        awaited in the chat of that message, filtered by `listen_user_id` and
        `listen_message_id`.

        Args:
            chat_id: Chat to send to, or that holds the message to edit.
            text: The text to send or edit.
            message_id: If provided, edit this message instead of sending a new one.
            listen_user_id: Filter the awaited update by user.
            listen_message_id: Filter the awaited update by message: an id,
                `None` (the default) for no filter, or a `ListenMessageId`:
                `SENT` for the message sent or edited here (a press on its
                buttons), or `NEXT` for the message right after it, which in
                a group another member's message can take. After an ephemeral
                message, pass `EphemeralUpdates.ANY`: the answer reaches no
                other wait. `SENT` and `NEXT` raise `ValueError` there, since
                ephemeral ids do not follow each other.
            listen_context: Values attached to the listener. With
                `ask_context_message` on (see `setup_pyroflow`), it gets the
                sent or edited message as `message`, on a copy, unless it
                holds one. So `on_error_func` can edit or delete the question
                and, with
                `MessageListenCancellingCallbackQueryListener` registered, a
                button pressed on that message cancels the wait.
            listen_filters: A Pyrogram filter the awaited update must pass besides
                `listen_user_id` and `listen_message_id`.
            listen_strict: What an update that matches the key but fails `listen_filters`
                does: `True` ends the wait with `ListenerRejected`, `False`
                skips it and keeps waiting. Without `listen_strict`, a rejected update that cannot
                come again leaves the wait open until `listen_timeout`, or forever
                without one; see the warning in `UpdateListener.listen`.
            listen_timeout: Seconds to wait before raising `ListenerTimeout`.
            listen_update_type: The update type to wait for and return.
            **kw: Passed to `send_message` or `edit_message_text`.

        Returns:
            The matching update of type `listen_update_type`.

        Raises:
            RuntimeError: If no listener is registered for `listen_update_type`.
            ValueError: If `ephemeral_message_parameters` or
                `EphemeralUpdates.ANY` comes without `listen_user_id`, or if
                `listen_message_id` is `SENT` or `NEXT` and the message is
                ephemeral. Both are checked before sending, and the second
                again on the message sent.
            ListenerTimeout: If the timeout expires before the update arrives.
            ListenerCancelled: If the listener is cancelled while waiting.
            ListenerWorkersBusy: If the wait would start inside a handler with
                no worker to spare (see `WorkersPolicy`). The message is
                already sent or edited by then.
            ListenerAlreadyExists: If the listener refuses a second wait on
                the key (`DuplicatePolicy.REJECT`). The message is already
                sent or edited by then.
        """
        listener = self.listeners.get(listen_update_type)

        if listener is None:
            msg = (
                f"No listener registered for {listen_update_type.__name__}. "
                f"Register one via client.register_listener() before calling ask()."
            )
            raise RuntimeError(msg)

        if listen_user_id is None and (
            kw.get("ephemeral_message_parameters") is not None
            or listen_message_id is EphemeralUpdates.ANY
        ):
            msg = "Waiting on an ephemeral message needs listen_user_id"
            raise ValueError(msg)

        if kw.get("ephemeral_message_parameters") is not None and listen_message_id in (
            ListenMessageId.SENT,
            ListenMessageId.NEXT,
        ):
            msg = "An ephemeral message has no id to wait on; use EphemeralUpdates.ANY"
            raise ValueError(msg)

        if message_id is not None:
            # `patch_cls` makes pyrogram's `Message` the same class as pyroflow's at runtime.
            m = cast(
                "Message",
                await self.edit_message_text(
                    chat_id=chat_id, message_id=message_id, text=text, **kw
                ),
            )
        else:
            # `send_message` may return `None` in theory; the behavior (`AttributeError` on `m.chat`) is unchanged.
            m = cast(
                "Message",
                await self.send_message(chat_id=chat_id, text=text, **kw),
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

        final_chat_id = m.chat.id if m.chat and m.chat.id is not None else chat_id

        if isinstance(final_chat_id, str):
            final_chat_id = pyro_ut.get_peer_id(
                await self.resolve_peer(final_chat_id)  # ty: ignore[invalid-argument-type]  # `resolve_peer` returns `None` only for a `None` `peer_id`
            )

        context = listen_context

        if self.ask_context_message:
            if context is None:
                context = ListenerContext(message=m)
            elif context.message is None:
                context = copy.copy(context)
                context.message = m

        return await listener(
            chat_id=final_chat_id,
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
        chat_id: StrInt,
        rich_message: InputRichMessage,
        *,
        listen_user_id: int | None = None,
        listen_message_id: ListenMessageIdT | None = None,
        listen_context: ListenerContext | None = None,
        listen_filters: Filter | None = None,
        listen_strict: bool = False,
        listen_timeout: Number | None = None,
        listen_update_type: type[UpdateType],
        **kw: Unpack[AskRichSendKw],
    ) -> UpdateType: ...

    @overload
    async def ask_rich(
        self,
        chat_id: StrInt,
        rich_message: InputRichMessage,
        *,
        listen_user_id: int | None = None,
        listen_message_id: ListenMessageIdT | None = None,
        listen_context: ListenerContext | None = None,
        listen_filters: Filter | None = None,
        listen_strict: bool = False,
        listen_timeout: Number | None = None,
        listen_update_type: type[Message] = Message,
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
        listen_message_id: ListenMessageIdT | None = None,
        listen_context: ListenerContext | None = None,
        listen_filters: Filter | None = None,
        listen_strict: bool = False,
        listen_timeout: Number | None = None,
        listen_update_type: type[UpdateType],
        **kw: Unpack[AskRichEditKw],
    ) -> UpdateType: ...

    @overload
    async def ask_rich(
        self,
        chat_id: StrInt,
        rich_message: InputRichMessage,
        message_id: int,
        *,
        listen_user_id: int | None = None,
        listen_message_id: ListenMessageIdT | None = None,
        listen_context: ListenerContext | None = None,
        listen_filters: Filter | None = None,
        listen_strict: bool = False,
        listen_timeout: Number | None = None,
        listen_update_type: type[Message] = Message,
        **kw: Unpack[AskRichEditKw],
    ) -> Message: ...

    async def ask_rich(
        self,
        chat_id: StrInt,
        rich_message: InputRichMessage,
        message_id: int | None = None,
        *,
        listen_user_id: int | None = None,
        listen_message_id: ListenMessageIdT | None = None,
        listen_context: ListenerContext | None = None,
        listen_filters: Filter | None = None,
        listen_strict: bool = False,
        listen_timeout: Number | None = None,
        listen_update_type: type[pyro_types.Update] = Message,
        **kw: Any,
    ) -> pyro_types.Update:
        """Send or edit a rich message, then wait for the next matching update.

        Like `ask`, but sends with `send_rich_message`, or edits `message_id`
        with `edit_message_text(rich_message=...)`.

        Args:
            chat_id: Chat to send to, or that holds the message to edit.
            rich_message: The rich message to send or edit.
            message_id: If provided, edit this message instead of sending a new one.
            listen_user_id: As in `ask`.
            listen_message_id: As in `ask`.
            listen_context: As in `ask`.
            listen_filters: As in `ask`.
            listen_strict: As in `ask`.
            listen_timeout: As in `ask`.
            listen_update_type: As in `ask`.
            **kw: Passed to `send_rich_message` or `edit_message_text`.

        Returns:
            The matching update of type `listen_update_type`.

        Raises:
            RuntimeError: If no listener is registered for `listen_update_type`.
            ValueError: As in `ask`.
            ListenerTimeout: If the timeout expires before the update arrives.
            ListenerCancelled: If the listener is cancelled while waiting.
            ListenerWorkersBusy: If the wait would start inside a handler with
                no worker to spare (see `WorkersPolicy`). The message is
                already sent or edited by then.
            ListenerAlreadyExists: As in `ask`.
        """
        listener = self.listeners.get(listen_update_type)

        if listener is None:
            msg = (
                f"No listener registered for {listen_update_type.__name__}. "
                f"Register one via client.register_listener() before calling ask()."
            )
            raise RuntimeError(msg)

        if listen_user_id is None and (
            kw.get("ephemeral_message_parameters") is not None
            or listen_message_id is EphemeralUpdates.ANY
        ):
            msg = "Waiting on an ephemeral message needs listen_user_id"
            raise ValueError(msg)

        if kw.get("ephemeral_message_parameters") is not None and listen_message_id in (
            ListenMessageId.SENT,
            ListenMessageId.NEXT,
        ):
            msg = "An ephemeral message has no id to wait on; use EphemeralUpdates.ANY"
            raise ValueError(msg)

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

        # An ephemeral message's id does not follow the others and can be reused.
        if listen_message_id in (ListenMessageId.SENT, ListenMessageId.NEXT):
            if m.ephemeral_message_id is not None:
                msg = "An ephemeral message has no id to wait on; use EphemeralUpdates.ANY"
                raise ValueError(msg)

            if listen_message_id is ListenMessageId.SENT:
                listen_message_id = m.id
            elif listen_message_id is ListenMessageId.NEXT:
                listen_message_id = m.id + 1

        final_chat_id = m.chat.id if m.chat and m.chat.id is not None else chat_id

        if isinstance(final_chat_id, str):
            final_chat_id = pyro_ut.get_peer_id(
                await self.resolve_peer(final_chat_id)  # ty: ignore[invalid-argument-type]  # `resolve_peer` returns `None` only for a `None` `peer_id`
            )

        context = listen_context

        if self.ask_context_message:
            if context is None:
                context = ListenerContext(message=m)
            elif context.message is None:
                context = copy.copy(context)
                context.message = m

        return await listener(
            chat_id=final_chat_id,
            user_id=listen_user_id,
            message_id=listen_message_id,
            context=context,
            filters=listen_filters,
            strict=listen_strict,
            timeout=listen_timeout,
        )


__all__ = ("Client",)
