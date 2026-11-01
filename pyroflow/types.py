"""Pyrogram update types patched with conversation helpers such as ``Message.ask``."""

from __future__ import annotations as _annotations
from typing import (
    TYPE_CHECKING,
    Literal,
    Any,
    overload,
)
import sys

if sys.version_info >= (3, 11):
    from typing import Self
else:
    from typing_extensions import Self

from pyrogram import types as pyro_types, enums as pyro_enums
from pyrogram.types import (
    Message as PyroMessage,
    CallbackQuery as PyroCallbackQuery,
    User as PyroUser,
    Update as PyroUpdate,
)

from .utils import patch_cls


if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping, Iterable
    from datetime import datetime

    from pytrove.typings import Number, JsonValue as JsonValueT

    from .client import Client
    from .typings import UpdateType, AskErrorHandlersT, ListenMessageIdT


@patch_cls
class Update(PyroUpdate):
    """Pyrogram ``Update`` extended with a per-update :attr:`context` dict."""

    @property
    def context(self) -> dict[str, Any] | None:
        """Arbitrary data attached to this update, or ``None`` if none is set.

        Setting it to ``None`` removes it.
        """
        try:
            return self.__context
        except AttributeError:
            return

    @context.setter
    def context(self, value: dict[str, Any] | None) -> None:
        if value is None:
            try:
                del self.__context
            except AttributeError:
                pass
        else:
            self.__context = value

    @context.deleter
    def context(self) -> None:
        del self.__context

    @overload
    def with_ctx(self, m: Mapping[str, Any], /, **kwargs: Any) -> Self: ...
    @overload
    def with_ctx(self, m: Iterable[tuple[str, Any]], /, **kwargs: Any) -> Self: ...
    @overload
    def with_ctx(self, **kwargs: Any) -> Self: ...
    def with_ctx(self, *args: Any, **kwargs: Any) -> Self:
        """Merge into :attr:`context` (same arguments as ``dict.update``) and return ``self``.

        Meant for chaining right after the update is built.
        """
        context = self.context
        if context is None:
            self.context = context = {}
        context.update(*args, **kwargs)

        return self


@patch_cls
class User(PyroUser):
    """Pyrogram ``User`` extended with :attr:`lang_code`."""

    _client: Client

    @property
    def lang_code(self) -> str | None:
        """Primary language subtag of ``language_code``, lowercased, or ``None`` if unknown."""
        return lang.split("-")[0].lower() if (lang := self.language_code) else None


if TYPE_CHECKING:

    class User(User, Update):
        """Typing-only view of :class:`User` that also exposes the patched :class:`Update` members."""


@patch_cls
class Message(PyroMessage):
    """Pyrogram ``Message`` extended with :meth:`ask`, :attr:`editable` and :attr:`respond`."""

    _client: Client
    from_user: User | None

    @overload
    async def ask(
        self,
        text: str,
        force_send: Literal[False] = False,
        *,
        parse_mode: pyro_enums.ParseMode | None = None,
        entities: list[pyro_types.MessageEntity] | None = None,
        link_preview_options: pyro_types.LinkPreviewOptions | None = None,
        reply_markup: pyro_types.InlineKeyboardMarkup | None = None,
        # listen params
        listen_user_id: int | None = None,
        listen_message_id: ListenMessageIdT | None = None,
        meta: JsonValueT | None = None,
        timeout: Number | None = None,
        update_type: type[Message] = ...,
        error_handlers: AskErrorHandlersT | None = None,
        **kw: Any,
    ) -> Message: ...
    @overload
    async def ask(
        self,
        text: str,
        force_send: Literal[False] = False,
        *,
        parse_mode: pyro_enums.ParseMode | None = None,
        entities: list[pyro_types.MessageEntity] | None = None,
        link_preview_options: pyro_types.LinkPreviewOptions | None = None,
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
        text: str,
        force_send: Literal[True],
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
        update_type: type[Message] = ...,
        error_handlers: AskErrorHandlersT | None = None,
        **kw: Any,
    ) -> Message: ...
    @overload
    async def ask(
        self,
        text: str,
        force_send: Literal[True],
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

    async def ask(
        self,
        text: str,
        force_send: bool = False,
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
        update_type: type[PyroUpdate] = PyroMessage,
        error_handlers: AskErrorHandlersT | None = None,
        **kw: Any,
    ) -> PyroUpdate:
        """Send a new message or edit the current one, then wait for a matching update.

        This method dynamically evaluates the context of the current message to determine
        the execution flow:

        1. **Auto-Edit Mode** (Default behavior): If the current message was sent by the bot
           itself and ``force_send`` is ``False``, the method modifies the current message
           in place using ``edit_message_text`` to keep a clean chat interface.
        2. **Send/Reply Mode**: If the message belongs to another user or ``force_send=True``
           is explicitly requested, it sends a brand-new message configured as a direct
           reply to this message.

        Parameters:
            text (``str``):
                The text of the message to be sent or edited.

            force_send (``bool``, *optional*):
                If set to ``True``, forces the bot to send a new reply message even if
                the current message is editable. Defaults to ``False``.

            parse_mode (:obj:`~pyrogram.enums.ParseMode`, *optional*):
                By default, the text is parsed using both HTML and Markdown styles.
                Pass None to disable parsing.

            entities (List of :obj:`~pyrogram.types.MessageEntity`, *optional*):
                A list of special entities to appear in the message text, which can be
                specified instead of *parse_mode*.

            link_preview_options (:obj:`~pyrogram.types.LinkPreviewOptions`, *optional*):
                Link preview generation options for the message.

            reply_parameters (:obj:`~pyrogram.types.ReplyParameters`, *optional*):
                If sending a new message, configuration options for the reply.
                If omitted, it defaults to replying directly to this message.
                *(Forbidden in Auto-Edit Mode)*.

            disable_notification (``bool``, *optional*):
                Sends the message silently if a new message is dispatched. Users will
                receive a notification with no sound. *(Forbidden in Auto-Edit Mode)*.

            message_thread_id (``int``, *optional*):
                Unique identifier for the target message thread/topic. Automatically
                inherited from the current message if not provided.
                *(Forbidden in Auto-Edit Mode)*.

            direct_messages_topic_id (``int``, *optional*):
                Unique identifier for the business connection DM topic. Automatically
                inherited from the current message if not provided.
                *(Forbidden in Auto-Edit Mode)*.

            effect_id (``int``, *optional*):
                Unique identifier of the message effect to be applied.
                *(Forbidden in Auto-Edit Mode)*.

            schedule_date (:obj:`~datetime.datetime`, *optional*):
                Date when the message will be automatically sent.
                *(Forbidden in Auto-Edit Mode)*.

            repeat_period (``int``, *optional*):
                Interval in seconds for message repetition.
                *(Forbidden in Auto-Edit Mode)*.

            protect_content (``bool``, *optional*):
                If set to ``True``, protects the contents of the sent message from
                forwarding and saving. *(Forbidden in Auto-Edit Mode)*.

            allow_paid_broadcast (``bool``, *optional*):
                Pass ``True`` to allow paid broadcast. *(Forbidden in Auto-Edit Mode)*.

            paid_message_star_count (``int``, *optional*):
                Amount of Telegram Stars required to view the message.
                *(Forbidden in Auto-Edit Mode)*.

            suggested_post_parameters (:obj:`~pyrogram.types.SuggestedPostParameters`, *optional*):
                Parameters for suggested channel posts. *(Forbidden in Auto-Edit Mode)*.

            reply_markup (:obj:`~pyrogram.types.InlineKeyboardMarkup` | :obj:`~pyrogram.types.ReplyKeyboardMarkup` | :obj:`~pyrogram.types.ReplyKeyboardRemove` | :obj:`~pyrogram.types.ForceReply`, *optional*):
                Additional interface options. **Note:** Auto-Edit Mode strictly only
                supports :obj:`~pyrogram.types.InlineKeyboardMarkup`.

            listen_user_id (``int``, *optional*):
                Filter the awaited update to listen only to a specific user ID.

            listen_message_id (``int`` | ``Callable[[Message], Optional[int]]``, *optional*):
                Filter the awaited update to listen only to a specific message ID.
                Can also be a synchronous callable receiving the sent/edited
                message and returning the id to filter by (or ``None`` for
                no filtering) — e.g. ``lambda m: m.id + 1``. Must be fast
                and non-blocking: it runs inline on the event loop.

            meta (``JsonValueT``, *optional*):
                Metadata to attach to the created listener.

            timeout (``Number``, *optional*):
                Maximum duration in seconds to wait for a response before raising
                ``ListenerTimeout``.

            update_type (Type[``UpdateType``], *optional*):
                The expected class type of the update to listen for.
                Defaults to :obj:`~pyroflow.types.Message`.

            error_handlers (``AskErrorHandlersT``, *optional*):
                ``{exc_type_or_tuple: handler}`` mapping. If listening raises
                before completing, the dict is scanned in order and the
                handler for the first key matching ``isinstance(exc, key)``
                is awaited as ``handler(exc, m)``, where ``m`` is the
                sent/edited message. The original exception is still
                re-raised afterwards.

            **kw (``Any``):
                Additional keyword arguments passed directly down to the underlying client.

        Returns:
            ``UpdateType``: The matching update object received from the listener.

        Raises:
            ValueError:
                - If invoked on an empty or a service message.
                - If explicit send-only parameters are passed while the function resolves
                  into Auto-Edit Mode.
            ListenerTimeout:
                If the timeout limit is reached before a valid update arrives.
        """
        if self.service or self.empty:
            msg = "Cannot call 'ask' on a service or empty message."
            raise ValueError(msg)

        message_id = None

        if not force_send and self.editable:
            message_id = self.id

        if message_id is None:
            if reply_parameters is None:
                reply_parameters = pyro_types.ReplyParameters(message_id=self.id)

            if message_thread_id is None:
                message_thread_id = self.message_thread_id

            if direct_messages_topic_id is None:
                direct_messages_topic_id = self.direct_messages_topic_id

        else:
            if any(
                v is not None
                for v in (
                    reply_parameters,
                    disable_notification,
                    message_thread_id,
                    direct_messages_topic_id,
                    effect_id,
                    schedule_date,
                    repeat_period,
                    protect_content,
                    allow_paid_broadcast,
                    paid_message_star_count,
                    suggested_post_parameters,
                )
            ):
                msg = (
                    "Cannot pass additional send options when reusing an existing message. "
                    "Use force_send=True to send a new message."
                )
                raise ValueError(msg)

        # Client.ask splits send/edit across overloads on message_id, which is
        # only known here at runtime; Client.ask enforces that contract itself.
        return await self._client.ask(  # ty: ignore[no-matching-overload]
            self.chat.id,  # ty: ignore[unresolved-attribute]  # kurigram types Message.chat as optional; a non-empty message always has one
            text,
            message_id,
            parse_mode=parse_mode,
            entities=entities,
            link_preview_options=link_preview_options,
            reply_parameters=reply_parameters,
            business_connection_id=self.business_connection_id,
            disable_notification=disable_notification,
            message_thread_id=message_thread_id,
            direct_messages_topic_id=direct_messages_topic_id,
            effect_id=effect_id,
            schedule_date=schedule_date,
            repeat_period=repeat_period,
            protect_content=protect_content,
            allow_paid_broadcast=allow_paid_broadcast,
            paid_message_star_count=paid_message_star_count,
            suggested_post_parameters=suggested_post_parameters,
            reply_markup=reply_markup,
            listen_user_id=listen_user_id,
            listen_message_id=listen_message_id,
            meta=meta,
            timeout=timeout,
            update_type=update_type,
            error_handlers=error_handlers,
            **kw,
        )

    @property
    def editable(self) -> bool:
        """``True`` if this message was sent by the client itself, so it can be edited."""
        return getattr(self.from_user, "is_self", False) or getattr(
            self.sender_chat, "id", None
        ) == getattr(self._client.me, "id", 0)

    @property
    def respond(self) -> Callable[..., Awaitable[PyroMessage | None]]:
        """``edit`` if this message is :attr:`editable`, otherwise ``reply``."""
        return self.edit if self.editable else self.reply


if TYPE_CHECKING:

    class Message(Message, Update):
        """Typing-only view of :class:`Message` that also exposes the patched :class:`Update` members."""


@patch_cls
class CallbackQuery(PyroCallbackQuery):
    """Pyrogram ``CallbackQuery`` with its ``message`` and ``from_user`` typed as the patched classes."""

    _client: Client
    message: Message | None
    from_user: User


if TYPE_CHECKING:

    class CallbackQuery(CallbackQuery, Update):
        """Typing-only view of :class:`CallbackQuery` that also exposes the patched :class:`Update` members."""


__all__ = (
    "User",
    "Message",
    "CallbackQuery",
    "Update",
)
