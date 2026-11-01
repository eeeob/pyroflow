"""pyroflow's patched :class:`pyrogram.Client` and the opt-in :class:`BotCommandsMixin`."""

from __future__ import annotations as _annotations

import asyncio
from functools import cached_property
from typing import Any, cast, overload, TYPE_CHECKING

from pyrogram import (
    Client as PyroClient,
    enums as pyro_enums,
    types as pyro_types,
    utils as pyro_ut,
)
from pyrogram.sync import wrap as async_to_sync
from pytrove import (
    to_list,
    gather_abort,
    clean_none_kw,
    safe_call,
    safe_await,
    yield_control,
)

from .constants import BOT_COMMANDS_ATTR
from .utils import (
    patch_cls,
    split_bot_command_entry,
    handle_ask_error,
    mark_bot_commands,
)
from .types import Message, CallbackQuery

if TYPE_CHECKING:
    from datetime import datetime

    from pyrogram.handlers.handler import Handler
    from pyrogram.types import BotCommand, BotCommandScope
    from pytrove.typings import Number, JsonValue as JsonValueT, MaybeCoroutineCallable, MaybeList

    from .dispatcher import Dispatcher
    from .typings import BotCommandGroupKeyT, AskErrorHandlersT, ListenMessageIdT, UpdateType
    from .update_listener import UpdateListener


@patch_cls
class Client(PyroClient):
    """The main entry point of the library and the only class you interact with directly.

    Extends :class:`pyrogram.Client` with a conversation-oriented API that
    lets you ``await`` a specific reply from a specific user rather than
    wiring up global handlers for every possible update.

    Pyrogram's built-in model is handler-based: a registered function fires for
    *every* incoming update of its type, so a back-and-forth conversation needs
    a hand-written state machine just to know whose answer you are waiting for.
    This client integrates three systems from :class:`Dispatcher` instead:

    - **Listeners** — typed queues that let any coroutine ``await`` the next
      update from a particular user/chat. An update claimed by a listener never
      reaches the normal handler pipeline.

    - **Coordinators** — distributed locks attached per update type that ensure
      an update is processed by exactly one session when the bot runs on multiple
      servers simultaneously.

    - **Histories** — per-update-type records of which handlers ran successfully,
      enabling features like ``back`` buttons that replay previous steps.

    Attach them before the client starts with :meth:`register_listener`,
    :meth:`register_coordinated` and :meth:`register_history`. The two most
    common listeners are exposed as the read-only :attr:`message_listen` and
    :attr:`callback_listen` properties.

    :meth:`ask` sends (or edits) a message and then suspends until a matching
    reply arrives, all in one ``await``. It calls :meth:`send_message` (or
    :meth:`edit_message_text` when ``message_id`` is supplied), registers a
    one-shot wait on the appropriate :class:`UpdateListener`, and returns the
    matching update. A :exc:`ListenerTimeout` is raised if no reply arrives
    within ``timeout`` seconds.

    The class is decorated with ``@patch_cls``, which passes every ``async`` method
    through ``async_to_sync``. This means all methods can also be called
    synchronously from outside an event loop, matching the behaviour of the
    standard :class:`pyrogram.Client`.
    """

    # `patch_cls` يجعل `Dispatcher` الخاص بـ `pyroflow` هو نفسه الخاص بـ `pyrogram` وقت التشغيل
    dispatcher: Dispatcher  # ty: ignore[invalid-mutable-override]  # same class at runtime via `patch_cls`
    ask_error_handlers: dict[type[pyro_types.Update], AskErrorHandlersT]

    if not TYPE_CHECKING:  # for typehints

        def __init__(self, *args: Any, **kw: Any) -> None:
            """Run Pyrogram's own ``__init__``, then start with no ask error handlers."""
            self.old__init__(*args, **kw)
            self.ask_error_handlers = {}

    @property
    def listeners(self) -> dict[type[pyro_types.Update], UpdateListener[Any]]:
        """Mapping from each update type to its registered :class:`UpdateListener`.

        The key is the update type (e.g. ``Message`` or ``CallbackQuery``),
        and the value is the listener responsible for awaiting that type.
        """
        return self.dispatcher.listeners

    @property
    def message_listen(self) -> UpdateListener[Message]:
        """Shortcut to the :class:`UpdateListener` registered for :class:`Message` updates."""
        return self.listeners[Message]

    @property
    def callback_listen(self) -> UpdateListener[CallbackQuery]:
        """Shortcut to the :class:`UpdateListener` registered for :class:`CallbackQuery` updates."""
        return self.listeners[CallbackQuery]

    if TYPE_CHECKING:
        register_listener = Dispatcher.register_listener
        register_coordinated = Dispatcher.register_coordinated
        register_history = Dispatcher.register_history

        unregister_listener = Dispatcher.unregister_listener
        unregister_coordinated = Dispatcher.unregister_coordinated
        unregister_history = Dispatcher.unregister_history

    else:

        def register_listener(self, *args: Any, **kw: Any) -> None:
            """Forward to :meth:`Dispatcher.register_listener`."""
            return self.dispatcher.register_listener(*args, **kw)

        def register_coordinated(self, *args: Any, **kw: Any) -> None:
            """Forward to :meth:`Dispatcher.register_coordinated`."""
            return self.dispatcher.register_coordinated(*args, **kw)

        def register_history(self, *args: Any, **kw: Any) -> None:
            """Forward to :meth:`Dispatcher.register_history`."""
            return self.dispatcher.register_history(*args, **kw)

        async def unregister_listener(self, *args: Any, **kw: Any) -> None:
            """Forward to :meth:`Dispatcher.unregister_listener`."""
            return await self.dispatcher.unregister_listener(*args, **kw)

        async def unregister_coordinated(self, *args: Any, **kw: Any) -> None:
            """Forward to :meth:`Dispatcher.unregister_coordinated`."""
            return await self.dispatcher.unregister_coordinated(*args, **kw)

        async def unregister_history(self, *args: Any, **kw: Any) -> None:
            """Forward to :meth:`Dispatcher.unregister_history`."""
            return await self.dispatcher.unregister_history(*args, **kw)

    def register_ask_error_handler(
        self,
        exc_types: type[Exception] | tuple[type[Exception], ...],
        handler: MaybeCoroutineCallable[[Exception, Message], Any],
        update_type: type[pyro_types.Update] = Message,
    ) -> None:
        """Add or replace a client-wide entry in :attr:`ask_error_handlers` for one ``update_type``.

        Unlike :meth:`register_listener`/:meth:`register_coordinated`/
        :meth:`register_history`, this has no dispatcher lifecycle to respect:
        it is a plain dict write, so it can be called at any time, before or
        after the client starts, and re-registering an ``exc_types`` already
        present under the same ``update_type`` replaces its handler rather
        than raising.

        Args:
            exc_types: One exception type, or a tuple of them, matched via
                ``isinstance(exc, exc_types)``.
            handler: Awaited as ``handler(exc, m)`` — see :attr:`ask_error_handlers`.
            update_type: Which :meth:`ask` update type this entry applies to.
                Matches the ``update_type`` argument of :meth:`ask`, defaulting
                the same way.
        """
        self.ask_error_handlers.setdefault(update_type, {})[exc_types] = handler

    def unregister_ask_error_handler(
        self,
        exc_types: type[Exception] | tuple[type[Exception], ...],
        update_type: type[pyro_types.Update] = Message,
    ) -> bool:
        """Remove the client-wide entry registered under ``exc_types`` for ``update_type``, if any.

        ``exc_types`` must match the exact key a handler was registered
        under — a tuple is not decomposed, so unregistering ``ValueError``
        does not remove an entry registered as ``(ValueError, TypeError)``.
        Likewise ``update_type`` must match: unregistering under ``Message``
        never touches an entry registered under ``CallbackQuery``.

        Returns:
            ``True`` if an entry was removed, ``False`` if none was registered
            under that exact ``(update_type, exc_types)`` pair.
        """
        handlers = self.ask_error_handlers.get(update_type)

        if not handlers:
            return False

        return handlers.pop(exc_types, None) is not None

    @overload
    async def ask(
        self,
        chat_id: int | str,
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
        meta: JsonValueT | None = None,
        timeout: Number | None = None,
        update_type: type[UpdateType],
        error_handlers: AskErrorHandlersT | None = None,
        **kw: Any,
    ) -> UpdateType: ...

    @overload
    async def ask(
        self,
        chat_id: int | str,
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
        meta: JsonValueT | None = None,
        timeout: Number | None = None,
        update_type: type[Message] = Message,
        error_handlers: AskErrorHandlersT | None = None,
        **kw: Any,
    ) -> Message: ...

    @overload
    async def ask(
        self,
        chat_id: int | str,
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
        meta: JsonValueT | None = None,
        timeout: Number | None = None,
        update_type: type[UpdateType],
        error_handlers: AskErrorHandlersT | None = None,
        **kw: Any,
    ) -> UpdateType: ...

    @overload
    async def ask(
        self,
        chat_id: int | str,
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
        meta: JsonValueT | None = None,
        timeout: Number | None = None,
        update_type: type[Message] = Message,
        error_handlers: AskErrorHandlersT | None = None,
        **kw: Any,
    ) -> Message: ...

    async def ask(
        self,
        chat_id: int | str,
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
        meta: JsonValueT | None = None,
        timeout: Number | None = None,
        update_type: type[pyro_types.Update] = Message,
        error_handlers: AskErrorHandlersT | None = None,
        **kw: Any,
    ) -> pyro_types.Update:
        """Send or edit a message, then wait for a matching update.

        If ``message_id`` is provided, the existing message is edited via
        :meth:`edit_message_text`. Otherwise a new message is sent via
        :meth:`send_message`.

        After sending or editing, the method waits for the next update of
        ``update_type`` matching the given ``chat_id``, ``listen_user_id``, and
        ``listen_message_id``.

        Args:
            chat_id: Target chat.
            text: Message text.
            message_id: If provided, edit this message instead of sending a new one.
            parse_mode: Text parse mode.
            entities: Message entities.
            link_preview_options: Link preview settings.
            schedule_date: Schedule the message.
            business_connection_id: Business connection id.
            reply_markup: Keyboard markup.
            disable_notification: Send silently (send only).
            message_thread_id: Thread id (send only).
            direct_messages_topic_id: DM topic id (send only).
            effect_id: Message effect (send only).
            reply_parameters: Reply parameters (send only).
            repeat_period: Repeat period (send only).
            protect_content: Protect content (send only).
            allow_paid_broadcast: Allow paid broadcast (send only).
            paid_message_star_count: Paid message star count (send only).
            suggested_post_parameters: Suggested post parameters (send only).
            listen_user_id: Filter the awaited update by user.
            listen_message_id: Filter the awaited update by message. Either an
                explicit id, or a synchronous callable receiving the sent/edited
                message (``m``) and returning the id to filter by (or ``None``
                for no filtering). The callable must be fast and non-blocking —
                it runs inline on the event loop, not in a thread.
            meta: Metadata attached to the listener.
            timeout: Seconds to wait before raising :class:`ListenerTimeout`.
            update_type: The update type to wait for. Determines the return type.
            error_handlers: Optional ``{exc_type_or_tuple: handler}`` mapping. If
                listening raises before completing, the dict is scanned in order
                and the handler for the first key matching ``isinstance(exc, key)``
                is awaited as ``handler(exc, m)``, where ``m`` is the sent/edited
                message. If nothing here matches, the entry in
                :attr:`Client.ask_error_handlers` for this call's ``update_type``
                is tried the same way — a handler registered for ``Message`` is
                never consulted for a ``CallbackQuery``-flavoured call, or vice
                versa. The original exception is still re-raised afterwards
                either way.
            **kw: Additional keyword arguments passed directly to
                :meth:`send_message` or :meth:`edit_message_text` depending on
                which operation is performed.

        Returns:
            The matching update of type ``update_type``.

        Raises:
            RuntimeError: If no listener is registered for ``update_type``.
            ValueError: If ``message_id`` is given with a ``reply_markup`` other
                than :class:`~pyrogram.types.InlineKeyboardMarkup`.
            ListenerTimeout: If the timeout expires before the update arrives.
            ListenerCancelled: If the listener is cancelled while waiting.
        """
        listener = self.listeners.get(update_type)

        if listener is None:
            msg = (
                f"No listener registered for {update_type.__name__}. "
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

        if meta is None or isinstance(meta, dict):
            meta = {} if meta is None else meta.copy()
            if "message_id" not in meta:
                meta["message_id"] = m.id

        if not isinstance(listen_message_id, int) and callable(listen_message_id):
            # Must be a fast, synchronous, non-blocking call — it runs
            # inline on the event loop, not through `to_thread`/`maybe_awaitable`.
            listen_message_id = listen_message_id(m)

        final_chat_id = m.chat.id if m.chat and m.chat.id is not None else chat_id

        if isinstance(final_chat_id, str):
            final_chat_id = pyro_ut.get_peer_id(
                await self.resolve_peer(final_chat_id)  # ty: ignore[invalid-argument-type]  # `resolve_peer` returns `None` only for a `None` `peer_id`
            )

        try:
            return await listener(
                chat_id=final_chat_id,
                user_id=listen_user_id,
                message_id=listen_message_id,
                meta=meta,
                timeout=timeout,
            )
        except Exception as exc:
            await handle_ask_error(
                exc,
                m,
                error_handlers,
                client_handlers.copy()
                if (client_handlers := self.ask_error_handlers.get(update_type))
                else None,
            )
            raise exc


if TYPE_CHECKING:
    # Type checking only: the mixin is written as if it were a `Client`, so calls
    # like `self.set_bot_commands()` resolve. At runtime the base is plain `object`
    # — see the class docstring.
    _BotCommandsMixinBase = Client
else:
    _BotCommandsMixinBase = object


class BotCommandsMixin(_BotCommandsMixinBase):
    """Opt-in :class:`Client` mixin that publishes the bot commands of registered handlers.

    The commands are the ones declared with :func:`mark_bot_commands` on the
    handlers you register.

    It is deliberately *not* a :class:`Client` subclass and *not* applied via
    ``@patch_cls``: nothing changes unless you ask for it. Combine it with
    :class:`Client` yourself, mixin first so its overrides win
    (``class MyClient(BotCommandsMixin, Client)``). It overrides:

    - :meth:`add_handler` / :meth:`remove_handler` — defer to the normal
      Pyrogram behaviour, then collect (or drop) the commands marked on the
      handler, in a task of their own so the bookkeeping follows the real
      registration rather than assuming it. Nothing is sent to Telegram yet.
    - :meth:`start` — connect first, then :meth:`push_bot_commands`, so that
      handlers loaded from ``plugins=`` during startup are included too.
    - :meth:`stop` — :meth:`remove_bot_commands` first, then disconnect.

    Commands are grouped by ``(language_code, scope)``, one Telegram call per
    group, so different scopes never overwrite each other.
    """

    @cached_property
    def bot_command_groups(self) -> list[tuple[BotCommandGroupKeyT, list[BotCommand]]]:
        """Collected commands, as ``((language_code, scope), commands)`` pairs."""
        return []

    @cached_property
    def bot_command_groups_lock(self) -> asyncio.Lock:
        """Lock held while :attr:`bot_command_groups` is updated, published or deleted."""
        return asyncio.Lock()

    def add_handler(self, handler: Handler, group: int = 0) -> tuple[Handler, int]:
        """Register ``handler`` as usual, then collect the bot commands marked on it."""
        result = super().add_handler(handler, group)
        self._track_bot_commands(handler, True)
        return result

    def remove_handler(self, handler: Handler, group: int = 0) -> None:
        """Remove ``handler`` as usual, then drop the bot commands marked on it."""
        result = super().remove_handler(handler, group)
        self._track_bot_commands(handler, False)
        return result

    def _track_bot_commands(self, handler: Handler, added: bool) -> None:
        """Queue this registration's bookkeeping behind Pyrogram's own.

        Pyrogram never mutates ``dispatcher.groups`` inline: ``add_handler`` and
        ``remove_handler`` schedule a task that first acquires
        ``dispatcher.locks_list``, and that task may end up doing nothing at all
        — ``remove_handler`` raises ``ValueError`` inside it when the handler was
        not in that group. Collecting the commands inline would therefore record
        changes that never happened, so we schedule our own task right after
        Pyrogram's (the loop runs them in creation order, and both contend for
        the same locks) and let it read the real state.
        """

        async def apply() -> None:
            """Collect or discard the commands of ``handler`` if its registration really changed."""
            if not getattr(handler, BOT_COMMANDS_ATTR, ()):
                return

            if (
                any(handler in handlers for handlers in self.dispatcher.groups.values())
                is not added
            ):
                return

            locks = [self.bot_command_groups_lock] + self.dispatcher.locks_list
            acquired = []

            try:
                for lock in locks:
                    await lock.acquire()
                    acquired.append(lock)

                track = self._collect_bot_commands if added else self._discard_bot_commands

                for entry in getattr(handler, BOT_COMMANDS_ATTR, ()):
                    track(*split_bot_command_entry(entry))
            finally:
                # Only what we took: `asyncio.Lock` has no notion of an owner, so
                # releasing one we are merely *waiting* on — which is where a
                # cancellation lands us — would hand it away from its holder.
                for lock in reversed(acquired):
                    lock.release()

        self.loop.create_task(apply())

    def _collect_bot_commands(
        self,
        language_code: str | None,
        scope: BotCommandScope | None,
        commands: MaybeList[BotCommand],
    ) -> None:
        """Add ``commands`` to the ``(language_code, scope)`` group, creating it if new."""
        key = (language_code, scope)
        bot_command_groups = self.bot_command_groups
        group = next((_commands for _key, _commands in bot_command_groups if _key == key), None)

        if group is None:
            bot_command_groups.append((key, group := []))

        group.extend(to_list(commands))

    def _discard_bot_commands(
        self,
        language_code: str | None,
        scope: BotCommandScope | None,
        commands: MaybeList[BotCommand],
    ) -> None:
        """Remove ``commands`` from the ``(language_code, scope)`` group, dropping it once empty."""
        key = (language_code, scope)

        for i, (_key, _commands) in enumerate(self.bot_command_groups):
            if _key != key:
                continue

            for command in to_list(commands):
                safe_call(_commands.remove, command, include_exc=ValueError)

            if not _commands:
                self.bot_command_groups.pop(i)

            break

    def _prune_bot_commands(self) -> None:
        """Drop every collected command that no registered handler declares any more.

        This way a bookkeeping task that never landed cannot leave a command
        published for a handler that is gone.

        Only removes; adding back is :meth:`_track_bot_commands`'s job. Reads
        ``dispatcher.groups`` without its locks on purpose — the caller has
        already yielded once (queued registrations have landed) and holds
        :attr:`bot_command_groups_lock`, so no bookkeeping task can be running.
        """
        declared: list[tuple[BotCommandGroupKeyT, list[BotCommand]]] = []

        for handlers in list(self.dispatcher.groups.values()):
            for handler in handlers:
                for entry in getattr(handler, BOT_COMMANDS_ATTR, ()):
                    language_code, scope, commands = split_bot_command_entry(entry)
                    key = (language_code, scope)
                    group = next((_commands for _key, _commands in declared if _key == key), None)

                    if group is None:
                        declared.append((key, group := []))

                    group.extend(to_list(commands))

        groups = self.bot_command_groups

        if not declared:
            groups.clear()

        for i in reversed(range(len(groups))):
            key, commands = groups[i]
            live = next((_commands for _key, _commands in declared if _key == key), ())

            commands[:] = [command for command in commands if command in live]

            if not commands:
                groups.pop(i)

    async def push_bot_commands(self) -> None:
        """Send every collected command group to Telegram.

        One :meth:`~pyrogram.Client.set_bot_commands` call is made per
        ``(language_code, scope)`` pair.

        Commands whose handler is no longer registered are pruned first, then
        duplicates within a group are dropped (the same command may legitimately
        be declared on more than one handler) and empty groups are skipped.
        Called automatically by :meth:`start`.
        """
        await safe_await(yield_control(), self.bot_command_groups_lock.acquire(), return_exc=False)

        coros = []

        try:
            self._prune_bot_commands()
            for (language_code, scope), commands in self.bot_command_groups:
                unique: list[BotCommand] = []
                for command in commands:
                    if command not in unique:
                        unique.append(command)

                if not unique:
                    continue

                coros.append(
                    self.set_bot_commands(
                        unique, **clean_none_kw(scope=scope, language_code=language_code)
                    )
                )

            if coros:
                await gather_abort(coros)
        finally:
            self.bot_command_groups_lock.release()

    async def remove_bot_commands(self) -> None:
        """Delete every collected command group from Telegram.

        One :meth:`~pyrogram.Client.delete_bot_commands` call is made per
        ``(language_code, scope)`` pair.

        Called automatically by :meth:`stop` unless told not to.
        """
        await safe_await(yield_control(), self.bot_command_groups_lock.acquire(), return_exc=False)

        try:
            await gather_abort(
                self.delete_bot_commands(**clean_none_kw(language_code=language_code, scope=scope))
                for (language_code, scope), _ in self.bot_command_groups
            )
        finally:
            self.bot_command_groups_lock.release()

    async def start(self, *args: Any, **kw: Any) -> PyroClient:
        """Start the client as usual, then publish the collected commands."""
        result = await super().start(*args, **kw)
        await self.push_bot_commands()
        return result

    async def stop(self, *args: Any, remove_commands: bool = True, **kw: Any) -> PyroClient:
        """Delete the published commands, then stop the client as usual.

        Args:
            *args: Passed to :meth:`pyrogram.Client.stop`.
            remove_commands: Set to ``False`` to leave the commands registered
                on Telegram's side after stopping.
            **kw: Passed to :meth:`pyrogram.Client.stop`.
        """
        if remove_commands:
            await self.remove_bot_commands()
        try:
            return await super().stop(*args, **kw)
        finally:
            self._prune_bot_commands()


async_to_sync(BotCommandsMixin)


__all__ = (
    "Client",
    "BotCommandsMixin",
    # Defined in `pyroflow.utils.bot_commands`; re-exported so `pyroflow` keeps offering it.
    "mark_bot_commands",
)
