"""pyroflow's patched `pyrogram.Client`."""

from __future__ import annotations as _annotations

import copy
from typing import Any, cast, overload, TYPE_CHECKING

from pyrogram import (
    Client as PyroClient,
    enums as pyro_enums,
    types as pyro_types,
    utils as pyro_ut,
)

from ..models import ListenerContext
from ..utils import patch_cls
from ..types import Message, CallbackQuery

if TYPE_CHECKING:
    from datetime import datetime

    from pyrogram.filters import Filter
    from pyrogram.types import InputRichMessage
    from pytrove.typings import (
        Number,
        StrInt,
    )

    from ..dispatcher import Dispatcher
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

    # `patch_cls` يجعل `Dispatcher` الخاص بـ `pyroflow` هو نفسه الخاص بـ `pyrogram` وقت التشغيل
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
        business_connection_id: str | None = None,
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
        listen_context: ListenerContext | None = None,
        listen_filters: Filter | None = None,
        listen_strict: bool = False,
        listen_timeout: Number | None = None,
        listen_update_type: type[UpdateType],
        **kw: Any,
    ) -> UpdateType: ...

    @overload
    async def ask(
        self,
        chat_id: StrInt,
        text: str,
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
        business_connection_id: str | None = None,
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
        listen_context: ListenerContext | None = None,
        listen_filters: Filter | None = None,
        listen_strict: bool = False,
        listen_timeout: Number | None = None,
        listen_update_type: type[Message] = Message,
        **kw: Any,
    ) -> Message: ...

    @overload
    async def ask(
        self,
        chat_id: StrInt,
        text: str,
        message_id: int,
        *,
        parse_mode: pyro_enums.ParseMode | None = None,
        entities: list[pyro_types.MessageEntity] | None = None,
        link_preview_options: pyro_types.LinkPreviewOptions | None = None,
        schedule_date: datetime | None = None,
        business_connection_id: str | None = None,
        reply_markup: pyro_types.InlineKeyboardMarkup | None = None,
        # listen params
        listen_user_id: int | None = None,
        listen_message_id: ListenMessageIdT | None = None,
        listen_context: ListenerContext | None = None,
        listen_filters: Filter | None = None,
        listen_strict: bool = False,
        listen_timeout: Number | None = None,
        listen_update_type: type[UpdateType],
        **kw: Any,
    ) -> UpdateType: ...

    @overload
    async def ask(
        self,
        chat_id: StrInt,
        text: str,
        message_id: int,
        *,
        parse_mode: pyro_enums.ParseMode | None = None,
        entities: list[pyro_types.MessageEntity] | None = None,
        link_preview_options: pyro_types.LinkPreviewOptions | None = None,
        schedule_date: datetime | None = None,
        business_connection_id: str | None = None,
        reply_markup: pyro_types.InlineKeyboardMarkup | None = None,
        # listen params
        listen_user_id: int | None = None,
        listen_message_id: ListenMessageIdT | None = None,
        listen_context: ListenerContext | None = None,
        listen_filters: Filter | None = None,
        listen_strict: bool = False,
        listen_timeout: Number | None = None,
        listen_update_type: type[Message] = Message,
        **kw: Any,
    ) -> Message: ...

    async def ask(
        self,
        chat_id: StrInt,
        text: str,
        message_id: int | None = None,
        *,
        parse_mode: pyro_enums.ParseMode | None = None,
        entities: list[pyro_types.MessageEntity] | None = None,
        link_preview_options: pyro_types.LinkPreviewOptions | None = None,
        schedule_date: datetime | None = None,
        business_connection_id: str | None = None,
        reply_markup: pyro_types.InlineKeyboardMarkup
        | pyro_types.ReplyKeyboardMarkup
        | pyro_types.ReplyKeyboardRemove
        | pyro_types.ForceReply
        | None = None,
        # `send_message` only params
        disable_notification: bool | None = None,
        message_thread_id: int | None = None,
        direct_messages_topic_id: int | None = None,
        effect_id: int | None = None,
        reply_parameters: pyro_types.ReplyParameters | None = None,
        repeat_period: int | None = None,
        protect_content: bool | None = None,
        allow_paid_broadcast: bool | None = None,
        paid_message_star_count: int | None = None,
        suggested_post_parameters: pyro_types.SuggestedPostParameters | None = None,
        # listen params
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
        otherwise a new one is sent with `send_message`. The arguments from
        `disable_notification` to `suggested_post_parameters` apply to sending
        only and are ignored when editing. The update is then awaited in the
        chat of that message, filtered by `listen_user_id` and `listen_message_id`.

        Args:
            chat_id: Chat to send to, or that holds the message to edit.
            text: The text to send or edit.
            message_id: If provided, edit this message instead of sending a new one.
            parse_mode: How `text` is parsed; `None` uses the client default.
            entities: Entities to use instead of `parse_mode`.
            link_preview_options: Link preview options for the message.
            schedule_date: Date to send the message at.
            business_connection_id: Business connection to send or edit through.
            reply_markup: Keyboard to attach; only `InlineKeyboardMarkup` when editing.
            disable_notification: Send the message silently.
            message_thread_id: Target topic.
            direct_messages_topic_id: Target direct messages topic.
            effect_id: Message effect to apply.
            reply_parameters: Reply options.
            repeat_period: Interval in seconds to repeat the message at.
            protect_content: Protect the message from forwarding and saving.
            allow_paid_broadcast: Allow a paid broadcast.
            paid_message_star_count: Telegram Stars paid to send the message.
            suggested_post_parameters: Parameters of a suggested channel post.
            listen_user_id: Filter the awaited update by user.
            listen_message_id: Filter the awaited update by message: an id, or
                a callable that receives the sent or edited message and returns
                the id (or `None` for no filter). The callable runs synchronously
                on the event loop, so it must not block.
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
            ValueError: If `message_id` is given with a `reply_markup` other
                than `InlineKeyboardMarkup`.
            ListenerTimeout: If the timeout expires before the update arrives.
            ListenerCancelled: If the listener is cancelled while waiting.
        """
        listener = self.listeners.get(listen_update_type)

        if listener is None:
            msg = (
                f"No listener registered for {listen_update_type.__name__}. "
                f"Register one via client.register_listener() before calling ask()."
            )
            raise RuntimeError(msg)

        if message_id is not None:
            if reply_markup is not None and not isinstance(
                reply_markup, pyro_types.InlineKeyboardMarkup
            ):
                msg = "Edit mode only supports InlineKeyboardMarkup for reply_markup"
                raise ValueError(msg)

            # `patch_cls` يجعل `Message` الخاصة بـ `pyrogram` هي نفسها الخاصة بـ `pyroflow` وقت التشغيل
            m = cast(
                "Message",
                await self.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=text,
                    parse_mode=parse_mode,
                    entities=entities,
                    link_preview_options=link_preview_options,
                    schedule_date=schedule_date,
                    business_connection_id=business_connection_id,
                    reply_markup=reply_markup,
                    **kw,
                ),
            )
        else:
            # `send_message` قد تُرجع `None` نظرياً، والسلوك (`AttributeError` عند `m.chat`) لم يتغيّر
            m = cast(
                "Message",
                await self.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode=parse_mode,
                    entities=entities,
                    link_preview_options=link_preview_options,
                    disable_notification=disable_notification,
                    message_thread_id=message_thread_id,
                    direct_messages_topic_id=direct_messages_topic_id,
                    effect_id=effect_id,
                    reply_parameters=reply_parameters,
                    schedule_date=schedule_date,
                    repeat_period=repeat_period,
                    protect_content=protect_content,
                    business_connection_id=business_connection_id,
                    allow_paid_broadcast=allow_paid_broadcast,
                    paid_message_star_count=paid_message_star_count,
                    suggested_post_parameters=suggested_post_parameters,
                    reply_markup=reply_markup,
                    **kw,
                ),
            )

        if not isinstance(listen_message_id, int) and callable(listen_message_id):
            # Must be a fast, synchronous, non-blocking call — it runs
            # inline on the event loop, not through `to_thread`/`maybe_awaitable`.
            listen_message_id = listen_message_id(m)

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
        reply_parameters: pyro_types.ReplyParameters | None = None,
        disable_notification: bool | None = None,
        message_thread_id: int | None = None,
        direct_messages_topic_id: int | None = None,
        effect_id: int | None = None,
        protect_content: bool | None = None,
        allow_paid_broadcast: bool | None = None,
        suggested_post_parameters: pyro_types.SuggestedPostParameters | None = None,
        reply_markup: pyro_types.InlineKeyboardMarkup
        | pyro_types.ReplyKeyboardMarkup
        | pyro_types.ReplyKeyboardRemove
        | pyro_types.ForceReply
        | None = None,
        # listen params
        listen_user_id: int | None = None,
        listen_message_id: ListenMessageIdT | None = None,
        listen_context: ListenerContext | None = None,
        listen_filters: Filter | None = None,
        listen_strict: bool = False,
        listen_timeout: Number | None = None,
        listen_update_type: type[UpdateType],
        **kw: Any,
    ) -> UpdateType: ...

    @overload
    async def ask_rich(
        self,
        chat_id: StrInt,
        rich_message: InputRichMessage,
        *,
        reply_parameters: pyro_types.ReplyParameters | None = None,
        disable_notification: bool | None = None,
        message_thread_id: int | None = None,
        direct_messages_topic_id: int | None = None,
        effect_id: int | None = None,
        protect_content: bool | None = None,
        allow_paid_broadcast: bool | None = None,
        suggested_post_parameters: pyro_types.SuggestedPostParameters | None = None,
        reply_markup: pyro_types.InlineKeyboardMarkup
        | pyro_types.ReplyKeyboardMarkup
        | pyro_types.ReplyKeyboardRemove
        | pyro_types.ForceReply
        | None = None,
        # listen params
        listen_user_id: int | None = None,
        listen_message_id: ListenMessageIdT | None = None,
        listen_context: ListenerContext | None = None,
        listen_filters: Filter | None = None,
        listen_strict: bool = False,
        listen_timeout: Number | None = None,
        listen_update_type: type[Message] = Message,
        **kw: Any,
    ) -> Message: ...

    @overload
    async def ask_rich(
        self,
        chat_id: StrInt,
        rich_message: InputRichMessage,
        message_id: int,
        *,
        schedule_date: datetime | None = None,
        business_connection_id: str | None = None,
        reply_markup: pyro_types.InlineKeyboardMarkup | None = None,
        # listen params
        listen_user_id: int | None = None,
        listen_message_id: ListenMessageIdT | None = None,
        listen_context: ListenerContext | None = None,
        listen_filters: Filter | None = None,
        listen_strict: bool = False,
        listen_timeout: Number | None = None,
        listen_update_type: type[UpdateType],
        **kw: Any,
    ) -> UpdateType: ...

    @overload
    async def ask_rich(
        self,
        chat_id: StrInt,
        rich_message: InputRichMessage,
        message_id: int,
        *,
        schedule_date: datetime | None = None,
        business_connection_id: str | None = None,
        reply_markup: pyro_types.InlineKeyboardMarkup | None = None,
        # listen params
        listen_user_id: int | None = None,
        listen_message_id: ListenMessageIdT | None = None,
        listen_context: ListenerContext | None = None,
        listen_filters: Filter | None = None,
        listen_strict: bool = False,
        listen_timeout: Number | None = None,
        listen_update_type: type[Message] = Message,
        **kw: Any,
    ) -> Message: ...

    async def ask_rich(
        self,
        chat_id: StrInt,
        rich_message: InputRichMessage,
        message_id: int | None = None,
        *,
        reply_markup: pyro_types.InlineKeyboardMarkup
        | pyro_types.ReplyKeyboardMarkup
        | pyro_types.ReplyKeyboardRemove
        | pyro_types.ForceReply
        | None = None,
        # `edit_message_text` only params (`send_rich_message` takes neither)
        schedule_date: datetime | None = None,
        business_connection_id: str | None = None,
        # `send_rich_message` only params
        disable_notification: bool | None = None,
        message_thread_id: int | None = None,
        direct_messages_topic_id: int | None = None,
        effect_id: int | None = None,
        reply_parameters: pyro_types.ReplyParameters | None = None,
        protect_content: bool | None = None,
        allow_paid_broadcast: bool | None = None,
        suggested_post_parameters: pyro_types.SuggestedPostParameters | None = None,
        # listen params
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
        with `edit_message_text(rich_message=...)`. `schedule_date` and
        `business_connection_id` apply to editing only, and the arguments from
        `disable_notification` to `suggested_post_parameters` to sending only;
        each is ignored in the other mode.

        Args:
            chat_id: Chat to send to, or that holds the message to edit.
            rich_message: The rich message to send or edit.
            message_id: If provided, edit this message instead of sending a new one.
            reply_markup: Keyboard to attach; only `InlineKeyboardMarkup` when editing.
            schedule_date: Date to send the edited message at.
            business_connection_id: Business connection to edit through.
            disable_notification: Send the message silently.
            message_thread_id: Target topic.
            direct_messages_topic_id: Target direct messages topic.
            effect_id: Message effect to apply.
            reply_parameters: Reply options.
            protect_content: Protect the message from forwarding and saving.
            allow_paid_broadcast: Allow a paid broadcast.
            suggested_post_parameters: Parameters of a suggested channel post.
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
            ValueError: If `message_id` is given with a `reply_markup` other
                than `InlineKeyboardMarkup`.
            ListenerTimeout: If the timeout expires before the update arrives.
            ListenerCancelled: If the listener is cancelled while waiting.
        """
        listener = self.listeners.get(listen_update_type)

        if listener is None:
            msg = (
                f"No listener registered for {listen_update_type.__name__}. "
                f"Register one via client.register_listener() before calling ask()."
            )
            raise RuntimeError(msg)

        if message_id is not None:
            if reply_markup is not None and not isinstance(
                reply_markup, pyro_types.InlineKeyboardMarkup
            ):
                msg = "Edit mode only supports InlineKeyboardMarkup for reply_markup"
                raise ValueError(msg)

            m = cast(
                "Message",
                await self.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    rich_message=rich_message,
                    schedule_date=schedule_date,
                    business_connection_id=business_connection_id,
                    reply_markup=reply_markup,
                    **kw,
                ),
            )
        else:
            m = cast(
                "Message",
                await self.send_rich_message(
                    chat_id=chat_id,
                    rich_message=rich_message,
                    disable_notification=disable_notification,
                    message_thread_id=message_thread_id,
                    direct_messages_topic_id=direct_messages_topic_id,
                    effect_id=effect_id,
                    reply_parameters=reply_parameters,
                    protect_content=protect_content,
                    allow_paid_broadcast=allow_paid_broadcast,
                    suggested_post_parameters=suggested_post_parameters,
                    reply_markup=reply_markup,
                    **kw,
                ),
            )

        if not isinstance(listen_message_id, int) and callable(listen_message_id):
            # Must be a fast, synchronous, non-blocking call — it runs
            # inline on the event loop, not through `to_thread`/`maybe_awaitable`.
            listen_message_id = listen_message_id(m)

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
