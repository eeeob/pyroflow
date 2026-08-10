from typing import TYPE_CHECKING, Any, Callable, Type, Dict, List, Optional, Tuple, Union, overload
from datetime import datetime

from pyrogram import (
    Client as PyroClient,
    enums as pyro_enums,
    types as pyro_types,
    utils as pyro_ut
)

from .utils.typings import Number, JsonValueT, UpdateType, MaybeCoroutineCallable
from .utils import patch_cls, maybe_awaitable

from .types import Message, CallbackQuery

from .dispatcher import Dispatcher
from .update_listener import UpdateListener


# Maps one or more exception types to a handler invoked with (exc, message)
# when that error occurs while awaiting the listener in ask(), before
# listening finishes.
ErrorHandlersT = Dict[
    Union[Type[Exception], Tuple[Type[Exception], ...]],
    MaybeCoroutineCallable[[Exception, Message], Any],
]

# Either an explicit message id, or a synchronous callable receiving the
# sent/edited message (m) and returning the id to listen for (or None).
# Must be fast and non-blocking: it is called inline, not via to_thread.
ListenMessageIdT = Union[int, Callable[[Message], Optional[int]]]


async def _handle_ask_error(
    exc: Exception,
    m: Message,
    call_handlers: Optional[ErrorHandlersT],
    client_handlers: Optional[ErrorHandlersT],
    ) -> bool:
    """Route an exception raised while listening in :meth:`Client.ask` to
    whichever error handler applies.

    ``call_handlers`` (the ``error_handlers`` argument to that specific call)
    takes precedence; ``client_handlers`` (:attr:`Client.ask_error_handlers`)
    only runs when ``call_handlers`` had no match — including when the call
    passed none at all.

    A dict merge of the two would not reliably give the call precedence: for
    keys that overlap by subclassing rather than by being identical (e.g. the
    client registers ``Exception``, the call registers a narrower
    ``ValueError``), whichever key a merged dict happens to order first wins,
    which is not always the call's.
    """

    for hdlrs in (call_handlers, client_handlers):
        if not hdlrs:
            continue

        for exc_types, handler in hdlrs.items():
            if isinstance(exc, exc_types):
                await maybe_awaitable(handler, exc, m, return_exc=True)
                return True
        
    return False




@patch_cls
class Client(PyroClient):
    """
    The main entry point of the library and the only class you need to
    interact with directly.

    Extends :class:`pyrogram.Client` with a conversation-oriented API that
    lets you ``await`` a specific reply from a specific user rather than
    wiring up global handlers for every possible update.

    Why this exists
    ---------------
    Pyrogram's built-in model is handler-based: you register a function and
    it fires for *every* incoming update of that type. That works well for
    broadcast-style bots, but breaks down the moment you need a back-and-forth
    conversation — you end up managing state machines by hand just to know
    whose answer you are waiting for.

    This client solves that by integrating three systems from :class:`Dispatcher`
    and exposing them through a single, convenient interface:

    - **Listeners** — typed queues that let any coroutine ``await`` the next
      update from a particular user/chat. An update claimed by a listener never
      reaches the normal handler pipeline.

    - **Coordinators** — distributed locks attached per update type that ensure
      an update is processed by exactly one session when the bot runs on multiple
      servers simultaneously.

    - **Histories** — per-update-type records of which handlers ran successfully,
      enabling features like ``back`` buttons that replay previous steps.

    What this class provides
    ------------------------
    **Registration** — attach the above systems to the client before it starts:

    .. code-block:: python

        client.register_listener(MyMessageListener())
        client.register_coordinated(MyCoordinated())
        client.register_history(MyHistory())

    **Shortcuts** — read-only properties for the two most common listeners:

    .. code-block:: python

        client.message_listen    # UpdateListener[Message]
        client.callback_listen   # UpdateListener[CallbackQuery]

    **``ask()``** — the core high-level method. Sends (or edits) a message and
    then suspends until a matching reply arrives, all in one ``await``:

    .. code-block:: python

        answer = await client.ask(chat_id, "What is your name?",
                                  listen_user_id=user_id, timeout=30)

    Under the hood ``ask()`` calls :meth:`send_message` (or
    :meth:`edit_message_text` when ``message_id`` is supplied), registers a
    one-shot wait on the appropriate :class:`UpdateListener`, and returns the
    matching update. A :exc:`ListenerTimeout` is raised if no reply arrives
    within ``timeout`` seconds.

    Note on ``@patch_cls``
    ------------------
    The class is decorated with ``@patch_cls``, which passes every ``async`` method
    through ``async_to_sync``. This means all methods can also be called
    synchronously from outside an event loop, matching the behaviour of the
    standard :class:`pyrogram.Client`.

    Examples
    --------
    **Using ``ask()``** — send a question and wait for the reply in one step:

    .. code-block:: python

        from pyroflow import Client, MessageListener

        client = Client("my_session")
        client.register_listener(MessageListener())

        @client.on_message()
        async def on_start(client, message):
            if message.text != "/start":
                return

            answer = await message.ask(
                text="What is your name?",
                listen_user_id=message.from_user.id,
                timeout=60,
            )
            await answer.reply(f"Hello, {answer.text}!")

        client.run()

    **Using ``listen`` directly** — wait for an update anywhere in your code
    without sending a message first:

    .. code-block:: python

        from pyroflow import Client, MessageListener
        from pyroflow.errors import ListenerTimeout

        client = Client("my_session")
        client.register_listener(MessageListener())

        @client.on_message()
        async def on_confirm(client, message):
            if message.text != "/confirm":
                return

            await message.reply("Please send your confirmation code:")

            try:
                code_msg = await client.message_listen(
                    chat_id=message.chat.id,
                    user_id=message.from_user.id,
                    timeout=120,
                )
            except ListenerTimeout:
                await message.reply("Timed out. Please try again.")
                return

            await code_msg.reply(f"Code received: {code_msg.text}")

        client.run()
    """

    dispatcher: Dispatcher
    ask_error_handlers: ErrorHandlersT

    if not TYPE_CHECKING: #for typehints
        def __init__(self, *args, **kw):
            self.old__init__(*args, **kw)
            self.ask_error_handlers = {}

    @property
    def listeners(self) -> Dict[Type[UpdateType], UpdateListener[UpdateType]]:
        """
        Mapping from each update type to its registered :class:`UpdateListener`.

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
        def register_listener(self, *args, **kw):
            return self.dispatcher.register_listener(*args, **kw)
        
        def register_coordinated(self, *args, **kw):
            return self.dispatcher.register_coordinated(*args, **kw)
        
        def register_history(self, *args, **kw):
            return self.dispatcher.register_history(*args, **kw)
        
        async def unregister_listener(self, *args, **kw):
            return await self.dispatcher.unregister_listener(*args, **kw)
        
        async def unregister_coordinated(self, *args, **kw):
            return await self.dispatcher.unregister_coordinated(*args, **kw)
        
        async def unregister_history(self, *args, **kw):
            return await self.dispatcher.unregister_history(*args, **kw)

    def register_ask_error_handler(
        self, 
        exc_types: Union[Type[Exception], Tuple[Type[Exception], ...]], 
        handler: MaybeCoroutineCallable[[Exception, Message], Any], 
        ) -> None:
        """
        Add or replace a client-wide entry in :attr:`ask_error_handlers`.

        Unlike :meth:`register_listener`/:meth:`register_coordinated`/
        :meth:`register_history`, this has no dispatcher lifecycle to respect:
        it is a plain dict write, so it can be called at any time, before or
        after the client starts, and re-registering an ``exc_types`` already
        present replaces its handler rather than raising.

        Parameters:
            exc_types: One exception type, or a tuple of them, matched via
                       ``isinstance(exc, exc_types)``.
            handler:   Awaited as ``handler(exc, m)`` — see :attr:`ask_error_handlers`.
        """

        self.ask_error_handlers[exc_types] = handler

    def unregister_ask_error_handler(
        self,
        exc_types: Union[Type[Exception], Tuple[Type[Exception], ...]],
        ) -> bool:
        """
        Remove the client-wide entry registered under ``exc_types``, if any.

        ``exc_types`` must match the exact key a handler was registered
        under — a tuple is not decomposed, so unregistering ``ValueError``
        does not remove an entry registered as ``(ValueError, TypeError)``.

        Returns:
            ``True`` if an entry was removed, ``False`` if none was registered
            under that exact key.
        """

        return self.ask_error_handlers.pop(exc_types, None) is not None


    @overload
    async def ask(
        self, 
        chat_id: Union[int, str], 
        text: str, 
        *, 
        parse_mode: Optional[pyro_enums.ParseMode] = None, 
        entities: Optional[List[pyro_types.MessageEntity]] = None, 
        link_preview_options: Optional[pyro_types.LinkPreviewOptions] = None, 
        reply_parameters: Optional[pyro_types.ReplyParameters] = None, 
        disable_notification: Optional[bool] = None, 
        message_thread_id: Optional[int] = None, 
        direct_messages_topic_id: Optional[int] = None, 
        effect_id: Optional[int] = None, 
        schedule_date: Optional[datetime] = None, 
        repeat_period: Optional[int] = None, 
        protect_content: Optional[bool] = None, 
        business_connection_id: Optional[str] = None, 
        allow_paid_broadcast: Optional[bool] = None, 
        paid_message_star_count: Optional[int] = None, 
        suggested_post_parameters: Optional[pyro_types.SuggestedPostParameters] = None, 
        reply_markup: Optional[Union[
            pyro_types.InlineKeyboardMarkup,
            pyro_types.ReplyKeyboardMarkup,
            pyro_types.ReplyKeyboardRemove,
            pyro_types.ForceReply,
        ]] = None, 
        # listen params
        listen_user_id: Optional[int] = None,
        listen_message_id: Optional[ListenMessageIdT] = None,
        meta: Optional[JsonValueT] = None,
        timeout: Optional[Number] = None,
        update_type: Type[UpdateType] = Message,
        error_handlers: Optional[ErrorHandlersT] = None,
        **kw
    ) -> UpdateType: ...

    @overload
    async def ask(
        self,
        chat_id: Union[int, str],
        text: str,
        message_id: int,
        *,
        parse_mode: Optional[pyro_enums.ParseMode] = None,
        entities: Optional[List[pyro_types.MessageEntity]] = None,
        link_preview_options: Optional[pyro_types.LinkPreviewOptions] = None,
        schedule_date: Optional[datetime] = None,
        business_connection_id: Optional[str] = None,
        reply_markup: Optional[pyro_types.InlineKeyboardMarkup] = None,
        # listen params
        listen_user_id: Optional[int] = None,
        listen_message_id: Optional[ListenMessageIdT] = None,
        meta: Optional[JsonValueT] = None,
        timeout: Optional[Number] = None,
        update_type: Type[UpdateType] = Message,
        error_handlers: Optional[ErrorHandlersT] = None,
        **kw
    ) -> UpdateType: ...

    async def ask(
        self, 
        chat_id: Union[int, str], 
        text: str, 
        message_id: Optional[int] = None, 
        *,
        parse_mode: Optional[pyro_enums.ParseMode] = None, 
        entities: Optional[List[pyro_types.MessageEntity]] = None, 
        link_preview_options: Optional[pyro_types.LinkPreviewOptions] = None, 
        schedule_date: Optional[datetime] = None, 
        business_connection_id: Optional[str] = None, 
        reply_markup: Optional[Union[
            pyro_types.InlineKeyboardMarkup,
            pyro_types.ReplyKeyboardMarkup,
            pyro_types.ReplyKeyboardRemove,
            pyro_types.ForceReply,
        ]] = None, 
        # send_message only params
        disable_notification: Optional[bool] = None, 
        message_thread_id: Optional[int] = None, 
        direct_messages_topic_id: Optional[int] = None, 
        effect_id: Optional[int] = None, 
        reply_parameters: Optional[pyro_types.ReplyParameters] = None, 
        repeat_period: Optional[int] = None,
        protect_content: Optional[bool] = None,
        allow_paid_broadcast: Optional[bool] = None,
        paid_message_star_count: Optional[int] = None,
        suggested_post_parameters: Optional[pyro_types.SuggestedPostParameters] = None,
        # listen params
        listen_user_id: Optional[int] = None,
        listen_message_id: Optional[ListenMessageIdT] = None,
        meta: Optional[JsonValueT] = None,
        timeout: Optional[Number] = None,
        update_type: Type[UpdateType] = Message,
        error_handlers: Optional[ErrorHandlersT] = None,
        **kw
    ) -> UpdateType:
        """
        Send or edit a message, then wait for a matching update.

        If ``message_id`` is provided, the existing message is edited via
        :meth:`edit_message_text`. Otherwise a new message is sent via
        :meth:`send_message`.

        After sending or editing, the method waits for the next update of
        ``update_type`` matching the given ``chat_id``, ``listen_user_id``, and
        ``listen_message_id``.

        Parameters:
            chat_id:                    Target chat.
            text:                       Message text.
            message_id:                 If provided, edit this message instead
                                        of sending a new one.
            parse_mode:                 Text parse mode.
            entities:                   Message entities.
            link_preview_options:       Link preview settings.
            schedule_date:              Schedule the message.
            business_connection_id:     Business connection id.
            reply_markup:               Keyboard markup.
            disable_notification:       Send silently (send only).
            message_thread_id:          Thread id (send only).
            direct_messages_topic_id:   DM topic id (send only).
            effect_id:                  Message effect (send only).
            reply_parameters:           Reply parameters (send only).
            repeat_period:              Repeat period (send only).
            protect_content:            Protect content (send only).
            allow_paid_broadcast:       Allow paid broadcast (send only).
            paid_message_star_count:    Paid message star count (send only).
            suggested_post_parameters:  Suggested post parameters (send only).

            listen_user_id:             Filter the awaited update by user.
            listen_message_id:          Filter the awaited update by message.
                                        Either an explicit id, or a
                                        synchronous callable receiving the
                                        sent/edited message (``m``) and
                                        returning the id to filter by (or
                                        ``None`` for no filtering). The
                                        callable must be fast and
                                        non-blocking — it runs inline on
                                        the event loop, not in a thread.
            meta:                       Metadata attached to the listener.
            timeout:                    Seconds to wait before raising
                                        :class:`ListenerTimeout`.
            update_type:                The update type to wait for.
                                        Determines the return type.
            error_handlers:              Optional ``{exc_type_or_tuple: handler}``
                                        mapping. If listening raises before
                                        completing, the dict is scanned in
                                        order and the handler for the first
                                        key matching ``isinstance(exc, key)``
                                        is awaited as ``handler(exc, m)``,
                                        where ``m`` is the sent/edited
                                        message. If nothing here matches,
                                        :attr:`Client.ask_error_handlers`
                                        is tried the same way. The original
                                        exception is still re-raised
                                        afterwards either way.
            **kw: Additional keyword arguments passed directly to
                  :meth:`send_message` or :meth:`edit_message_text`
                  depending on which operation is performed.

        Returns:
            The matching update of type ``update_type``.

        Raises:
            ListenerTimeout:  If the timeout expires before the update arrives.
            ListenerCancelled: If the listener is cancelled while waiting.
        """

        listener = self.listeners.get(update_type)

        if listener is None:
            raise RuntimeError(
                f"No listener registered for {update_type.__name__}. "
                f"Register one via client.register_listener() before calling ask()."
            )
    
            
        if message_id is not None:
            if reply_markup is not None and not isinstance(reply_markup, pyro_types.InlineKeyboardMarkup):
                raise ValueError("Edit mode only supports InlineKeyboardMarkup for reply_markup")
            
            m = await self.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                parse_mode=parse_mode,
                entities=entities,
                link_preview_options=link_preview_options,
                schedule_date=schedule_date,
                business_connection_id=business_connection_id,
                reply_markup=reply_markup,
                **kw
            )
        else:
            m = await self.send_message(
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
            )
        
        
        if meta is None or isinstance(meta, dict):
            meta = {} if meta is None else meta.copy()
            if "message_id" not in meta:
                meta["message_id"] = m.id

        if callable(listen_message_id):
            # Must be a fast, synchronous, non-blocking call — it runs
            # inline on the event loop, not through to_thread/maybe_awaitable.
            listen_message_id = listen_message_id(m)

        final_chat_id = m.chat.id if m.chat else chat_id
        
        if isinstance(final_chat_id, str):
            final_chat_id = pyro_ut.get_peer_id(
                await self.resolve_peer(final_chat_id)
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
            await _handle_ask_error(exc, m, error_handlers, self.ask_error_handlers.copy())
            raise