"""Internal ``ask`` error dispatch: runs the first error handler matching an exception."""

from __future__ import annotations as _annotations
from typing import TYPE_CHECKING

from pytrove import maybe_awaitable

if TYPE_CHECKING:
    from ..typings import AskErrorHandlersT
    from ..types import Message


async def handle_ask_error(
    exc: Exception,
    m: Message,
    *handlers: AskErrorHandlersT | None,
) -> bool:
    """Dispatch ``exc`` to the first matching entry across ``handlers``, awaited as ``handler(exc, m)``.

    Each mapping is scanned in order, and within a mapping its keys are tried in
    insertion order, so earlier ``handlers`` arguments take precedence — that is
    what makes ``ask(error_handlers=...)`` win over the client-wide
    :attr:`~pyroflow.Client.ask_error_handlers`. ``None`` and empty mappings are
    skipped, and the search stops at the first match.

    Handler failures are swallowed (``return_exc=True``): this runs from an
    ``except`` block whose original exception is about to be re-raised, and a
    failing handler must not replace it.

    Args:
        exc: The exception to dispatch.
        m: The message passed to the handler.
        *handlers: Mappings of exception types to handlers, highest precedence first.

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


__all__ = ("handle_ask_error",)
