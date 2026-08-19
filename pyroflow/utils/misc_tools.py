from typing import TYPE_CHECKING, Any, Callable, Optional, Tuple, overload

from pyrogram.sync import async_to_sync
from pyrogram.types import BotCommand
from pyrogram.handlers import MessageHandler

# The handler types mark_bot_commands() is willing to mark. BusinessMessageHandler
# is not present in every supported Pyrogram/Kurigram version.
try:
    from pyrogram.handlers import BusinessMessageHandler
except ImportError:
    _MESSAGES_HANDLER = MessageHandler
else:
    _MESSAGES_HANDLER = (MessageHandler, BusinessMessageHandler)
    del BusinessMessageHandler

del MessageHandler

from pytrove import iscoroutinefunction_wrapped, maybe_awaitable, patch_cls as _patch_cls
from .typings import _CT, _FT
from .constants import BOT_COMMANDS_ATTR

if TYPE_CHECKING:
    from ..typings import BotCommandEntryT, BotCommandPartsT, AskErrorHandlersT
    from ..types import Message



def patch_setter(cls, name, attr) -> None:
    setattr(cls, name, attr)

    if iscoroutinefunction_wrapped(attr):
        async_to_sync(cls, name)


@overload
def patch_cls(patch_class: _CT) -> _CT: ...
@overload
def patch_cls(
    *,
    preserve_old: bool = True,
    setter: Callable[[type, str, Any], None] = patch_setter,
    include_dunders: Tuple[str, ...] = ("__init__",),
    ) -> Callable[[_CT], _CT]: ...
def patch_cls(
    patch_class: Optional[_CT] = None,
    *,
    preserve_old: bool = True,
    setter: Callable[[type, str, Any], None] = patch_setter,
    include_dunders: Tuple[str, ...] = ("__init__",),
    ):
    """pytrove.misc_tools.patch_cls, with pyroflow's own default setter.

    pytrove's own default (``setattr``) has no notion of pyrogram's
    sync/async duality; pyroflow's does, via :func:`patch_setter`, which is
    why every bare ``@patch_cls`` in this codebase needs it as the default
    rather than plain ``setattr``. An explicit ``setter=`` still overrides
    it, same as calling pytrove's version directly.
    """

    return _patch_cls(
        patch_class,
        preserve_old=preserve_old,
        setter=setter,
        include_dunders=include_dunders,
    )


def split_bot_command_entry(entry: "BotCommandEntryT") -> "BotCommandPartsT":
    """
    Expand any :data:`BotCommandEntryT` shape into its
    ``(language_code, scope, commands)`` parts, filling the parts the entry
    left out with ``None``.
    """

    if isinstance(entry, (BotCommand, list)):
        return None, None, entry
    if len(entry) == 2:
        return None, *entry
    return entry

def mark_bot_commands(*entries: "BotCommandEntryT") -> Callable[[_FT], _FT]:
    """
    Decorator that marks a handler function with the bot commands it answers
    to, so :class:`~pyroflow.BotCommandsMixin` can publish them to Telegram
    later, when the client starts.

    Nothing is sent to Telegram here — the declaration is only stored on the
    handler object, under :data:`BOT_COMMANDS_ATTR`. The actual
    ``set_bot_commands`` call happens in
    :meth:`~pyroflow.BotCommandsMixin.push_bot_commands`, which the mixin runs
    from its ``start()``. That deferral is the whole point: the published
    command list is assembled from the handlers you actually registered,
    instead of being written out a second time by hand.

    Stacks on top of Pyrogram's own ``@Client.on_message(...)``-style
    decorators, which are what create ``func.handlers`` — so apply this one
    *above* them (decorators apply bottom-up) to make sure ``handlers`` already
    exists by the time this runs. Only :class:`~pyrogram.handlers.MessageHandler`
    and :class:`~pyrogram.handlers.BusinessMessageHandler` entries are marked;
    anything else in ``func.handlers`` is left untouched.

    Note that ``func.handlers`` is only populated by the *unbound* decorator
    form (``@Client.on_message()``, the plugin-file style). The bound form
    (``@app.on_message()``) registers the handler immediately and sets nothing,
    so there is nothing for this decorator to mark.

    Parameters:
        *entries: The command declarations, each in one of the shapes
                  described by :data:`~pyroflow.typings.BotCommandEntryT`.

    Example:
        .. code-block:: python

            from pyrogram import Client as PyroClient, filters
            from pyrogram.types import BotCommand
            from pyroflow import mark_bot_commands

            @mark_bot_commands(BotCommand("start", "Start the bot"))
            @PyroClient.on_message(filters.command("start"))
            async def on_start(client, message):
                await message.reply("Hi!")
    """

    def decorator(func: _FT) -> _FT:
        for handler, _ in getattr(func, "handlers", []):
            if not isinstance(handler, _MESSAGES_HANDLER):
                continue
            setattr(handler, BOT_COMMANDS_ATTR, entries)
        return func

    return decorator

async def handle_ask_error(
    exc: Exception, 
    m: "Message", 
    *handlers: Optional["AskErrorHandlersT"],
    ) -> bool:
    """
    Dispatch ``exc`` to the first matching entry across ``handlers``, awaited
    as ``handler(exc, m)``.

    Each mapping is scanned in order, and within a mapping its keys are tried in
    insertion order, so earlier ``handlers`` arguments take precedence — that is
    what makes ``ask(error_handlers=...)`` win over the client-wide
    :attr:`~pyroflow.Client.ask_error_handlers`. ``None`` and empty mappings are
    skipped, and the search stops at the first match.

    Handler failures are swallowed (``return_exc=True``): this runs from an
    ``except`` block whose original exception is about to be re-raised, and a
    failing handler must not replace it.

    Returns:
        ``True`` if a handler matched and ran, ``False`` otherwise.
    """

    for hdlrs in handlers:
        if not hdlrs:
            continue

        for exc_types, handler in hdlrs.items():
            if isinstance(exc, exc_types):
                await maybe_awaitable(handler, exc, m, return_exc=True)
                return True

    return False


__all__ = (
    "patch_setter",
    "patch_cls",
    "split_bot_command_entry",
    "mark_bot_commands",
    "handle_ask_error",
)
