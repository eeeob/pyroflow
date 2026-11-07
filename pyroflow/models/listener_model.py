"""Listener models: a registered wait and the values attached to it."""

from __future__ import annotations as _annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Generic, TYPE_CHECKING

from pyrogram.filters import Filter

from ..typings import KeyT

if TYPE_CHECKING:
    from ..types import Message


log = logging.getLogger(__name__)
"""Logger for errors of the done callbacks of a listener."""


class ListenerContext(SimpleNamespace):
    """Values attached to a wait: typed base fields, plus any the caller adds.

    Every value, declared or added, is read and set as an attribute. A field
    that is not set reads its class default. Subclass to declare and type
    fields of your own.

    Example:
        >>> class OrderContext(ListenerContext):
        ...     step: int = 0
        >>> context = OrderContext(step=2, note="x")
        >>> context.step, context.note, context.message
        (2, 'x', None)
    """

    message: Message | None = None
    """The message an `ask_*` method sent or edited for the wait."""


@dataclass(slots=True, eq=False)
class ListenerModel(Generic[KeyT]):
    """A registered listener: its key, the future its update resolves, its context and filter.

    `done_callbacks` run inside `resolve` and `set_exc`, right after the future
    is set, with the model as their one argument: at once, not on the next loop
    iteration as `asyncio.Future.add_done_callback` does. A cancelled task leaves
    the future done without them, so `run_done_callbacks` runs them then. They
    run once, as running drops them. A failing callback is logged, and the next
    one still runs.

    Example:
        >>> from pyroflow.models import MessageKey
        >>> async def main():
        ...     future = asyncio.get_running_loop().create_future()
        ...     listener = ListenerModel(MessageKey(1), future)
        ...     listener.resolve("update")
        ...     return listener.done(), await listener.future
        >>> asyncio.run(main())
        (True, 'update')
    """

    key: KeyT
    """The slot the listener is registered under."""
    future: asyncio.Future
    """Resolved with the matching update, or failed with an error."""
    context: ListenerContext | None = None
    """Values attached to the listener, or `None` when none were passed."""
    filters: Filter | None = None
    """Pyrogram filter an update must pass besides the key, or `None` for none."""
    strict: bool = False
    """Whether an update that matches the key but fails `filters` ends the wait."""
    done_callbacks: list[Callable[[ListenerModel[KeyT]], object]] = field(default_factory=list)
    """Called with the model, in order, as soon as it is marked done."""

    def add_done_callback(self, fn: Callable[[ListenerModel[KeyT]], object]) -> None:
        """Call `fn(self)` as soon as the listener is done; at once if it already is.

        Args:
            fn: The callback; its result is ignored.

        Example:
            >>> from pyroflow.models import ListenerKey
            >>> async def main():
            ...     listener = ListenerModel(ListenerKey(1), asyncio.get_running_loop().create_future())
            ...     seen = []
            ...     listener.add_done_callback(lambda model: seen.append(model.key))
            ...     listener.resolve("update")
            ...     return seen
            >>> asyncio.run(main())
            [ListenerKey(chat_id=1)]
        """
        if self.done():
            fn(self)
        else:
            self.done_callbacks.append(fn)

    def resolve(self, update: object) -> None:
        """Complete the listener's future with `update`, then run `done_callbacks`."""
        self.future.set_result(update)
        self.run_done_callbacks()

    def set_exc(self, exc: Exception) -> None:
        """Fail the listener's future with `exc`, then run `done_callbacks`."""
        self.future.set_exception(exc)
        self.run_done_callbacks()

    def run_done_callbacks(self) -> None:
        """Call every callback in `done_callbacks` with the model, in order, and drop them."""
        callbacks, self.done_callbacks = self.done_callbacks, []

        for fn in callbacks:
            try:
                fn(self)
            except Exception:
                log.exception("Error in a done callback of the listener for %s", self.key)

    def done(self) -> bool:
        """Return whether the listener's future is done."""
        return self.future.done()


__all__ = (
    "ListenerContext",
    "ListenerModel",
)
