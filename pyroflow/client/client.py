"""pyroflow's patched `pyrogram.Client`."""

from __future__ import annotations as _annotations

import copy
from typing import Any, cast, overload, TYPE_CHECKING

from pyrogram import (
    Client as PyroClient,
    types as pyro_types,
    utils as pyro_ut,
)

from ..enums import ListenMessageId
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
    from ..models import WorkersPolicy
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

    def with_workers_policy(self, policy: WorkersPolicy | None) -> Self:
        """Set the `WorkersPolicy` waits inside handlers follow, and return the client.

        Without a call there is no policy: waits hold their workers, and the
        bot freezes if all of them wait.

        It is a method rather than a `Client(...)` argument so pyroflow does
        not redeclare `pyrogram.Client.__init__`, a long signature it would
        then have to follow on every Pyrogram change. Chain it instead:
        `Client("bot", workers=12).with_workers_policy(WorkersPolicy(WorkersBusyMode.REJECT))`.

        Args:
            policy: The policy, see `WorkersPolicy` and `WorkersBusyMode`, or
                `None` to remove the current one.

        Returns:
            The client itself.

        Raises:
            ValueError: If `policy.free_workers` is above the client's `workers`.
        """
        if policy is not None and policy.free_workers > self.workers:
            msg = (
                f"free_workers must not exceed workers ({self.workers}), got {policy.free_workers}"
            )
            raise ValueError(msg)

        self.dispatcher.workers_policy = policy
        return self

    if TYPE_CHECKING:
        register_listener = Dispatcher.register_listener
        """Forward to `Dispatcher.register_listener`."""

        unregister_listener = Dispatcher.unregister_listener
        """Forward to `Dispatcher.unregister_listener`."""

    else:

        def register_listener(self, *args: object, **kw: object) -> None:
            """Forward to `Dispatcher.register_listener`."""
            return self.dispatcher.register_listener(*args, **kw)

        async def unregister_listener(self, *args: object, **kw: object) -> None:
            """Forward to `Dispatcher.unregister_listener`."""
            return await self.dispatcher.unregister_listener(*args, **kw)

    @overload
    async def ask(
        self,
        chat_id: StrInt,
        text: str,
        *,
        listen_user_id: int | None = None,
        listen_message_id: ListenMessageIdT | None = ListenMessageId.AUTO,
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
        listen_message_id: ListenMessageIdT | None = ListenMessageId.AUTO,
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
        listen_message_id: ListenMessageIdT | None = ListenMessageId.AUTO,
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
        listen_message_id: ListenMessageIdT | None = ListenMessageId.AUTO,
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
        listen_message_id: ListenMessageIdT | None = ListenMessageId.AUTO,
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
                `None` for no filter, or a `ListenMessageId`: `SENT` for the
                message sent or edited here (a press on its buttons), `NEXT`
                for the message right after it, or `AUTO` (the default),
                which is `NEXT` for a `Message` wait, `SENT` for a
                `CallbackQuery` and no filter otherwise.
                In a group, `NEXT` can be taken by another member's message;
                pass `None` there.
            listen_context: Values attached to the listener. It is copied,
                and the copy's `message_id` and `message` are set to the id
                of the sent or edited message and to the message itself,
                each unless it is already set. So `on_error_func` can edit
                or delete the question and, with
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
            ListenerTimeout: If the timeout expires before the update arrives.
            ListenerCancelled: If the listener is cancelled while waiting.
            ListenerWorkersBusy: Or its subclass `ListenerEvictionTimeout`, if the wait would start inside a handler with
                too few workers free (see `WorkersPolicy`). The message is
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

        if listen_message_id is ListenMessageId.AUTO:
            listen_message_id = (
                ListenMessageId.NEXT
                if issubclass(listen_update_type, Message)
                else ListenMessageId.SENT
                if issubclass(listen_update_type, CallbackQuery)
                else None
            )

        if listen_message_id is ListenMessageId.SENT:
            listen_message_id = m.id
        elif listen_message_id is ListenMessageId.NEXT:
            listen_message_id = m.id + 1

        final_chat_id = m.chat.id if m.chat and m.chat.id is not None else chat_id

        if isinstance(final_chat_id, str):
            final_chat_id = pyro_ut.get_peer_id(
                await self.resolve_peer(final_chat_id)  # ty: ignore[invalid-argument-type]  # `resolve_peer` returns `None` only for a `None` `peer_id`
            )

        context = ListenerContext() if listen_context is None else copy.copy(listen_context)

        if context.message_id is None:
            context.message_id = m.id

        if context.message is None:
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
        listen_message_id: ListenMessageIdT | None = ListenMessageId.AUTO,
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
        listen_message_id: ListenMessageIdT | None = ListenMessageId.AUTO,
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
        listen_message_id: ListenMessageIdT | None = ListenMessageId.AUTO,
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
        listen_message_id: ListenMessageIdT | None = ListenMessageId.AUTO,
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
        listen_message_id: ListenMessageIdT | None = ListenMessageId.AUTO,
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
            ListenerTimeout: If the timeout expires before the update arrives.
            ListenerCancelled: If the listener is cancelled while waiting.
            ListenerWorkersBusy: Or its subclass `ListenerEvictionTimeout`, if the wait would start inside a handler with
                too few workers free (see `WorkersPolicy`). The message is
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

        if listen_message_id is ListenMessageId.AUTO:
            listen_message_id = (
                ListenMessageId.NEXT
                if issubclass(listen_update_type, Message)
                else ListenMessageId.SENT
                if issubclass(listen_update_type, CallbackQuery)
                else None
            )

        if listen_message_id is ListenMessageId.SENT:
            listen_message_id = m.id
        elif listen_message_id is ListenMessageId.NEXT:
            listen_message_id = m.id + 1

        final_chat_id = m.chat.id if m.chat and m.chat.id is not None else chat_id

        if isinstance(final_chat_id, str):
            final_chat_id = pyro_ut.get_peer_id(
                await self.resolve_peer(final_chat_id)  # ty: ignore[invalid-argument-type]  # `resolve_peer` returns `None` only for a `None` `peer_id`
            )

        context = ListenerContext() if listen_context is None else copy.copy(listen_context)

        if context.message_id is None:
            context.message_id = m.id

        if context.message is None:
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
