"""The :func:`mark_bot_commands` decorator, which declares the bot commands a handler answers to."""

from __future__ import annotations as _annotations

from typing import Final, TYPE_CHECKING

from pyrogram import handlers

from .constants import BOT_COMMANDS_ATTR

if TYPE_CHECKING:
    from collections.abc import Callable

    from pyrogram.handlers import Handler
    from pytrove.typings import _FT

    from .typings import BotCommandEntryT

# The handler types `mark_bot_commands()` is willing to mark. `BusinessMessageHandler`
# is not present in every supported Pyrogram/Kurigram version.
_MESSAGES_HANDLER: Final[tuple[type[Handler], ...]] = tuple(
    getattr(handlers, name)
    for name in ("MessageHandler", "BusinessMessageHandler")
    if hasattr(handlers, name)
)


def mark_bot_commands(*entries: BotCommandEntryT) -> Callable[[_FT], _FT]:
    """Mark a handler function with the bot commands it answers to.

    :class:`~pyroflow.BotCommandsMixin` publishes them to Telegram later, when
    the client starts.

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

    Args:
        *entries: The command declarations, each in one of the shapes
            described by :data:`~pyroflow.typings.BotCommandEntryT`.

    Returns:
        A decorator that stores ``entries`` on the function's message handlers
        and returns the function unchanged.

    Example:
        >>> from pyrogram import Client as PyroClient, filters
        >>> from pyrogram.types import BotCommand
        >>> @mark_bot_commands(BotCommand("start", "Start the bot"))
        ... @PyroClient.on_message(filters.command("start"))
        ... async def on_start(client, message):
        ...     await message.reply("Hi!")
        >>> [c.command for h, _ in on_start.handlers for c in getattr(h, BOT_COMMANDS_ATTR)]
        ['start']
    """

    def decorator(func: _FT) -> _FT:
        """Store ``entries`` on each message handler in ``func.handlers``."""
        for handler, _ in getattr(func, "handlers", []):
            if not isinstance(handler, _MESSAGES_HANDLER):
                continue
            setattr(handler, BOT_COMMANDS_ATTR, entries)
        return func

    return decorator


__all__ = ("mark_bot_commands",)
