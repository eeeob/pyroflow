"""Data models for listeners."""

from __future__ import annotations as _annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import TYPE_CHECKING

from pyrogram.filters import Filter

from .enums import EphemeralUpdates
from .typings import ListenerMessageIdT

if TYPE_CHECKING:
    from collections.abc import Generator

    from .types import Message


log = logging.getLogger(__name__)
"""Logger for errors of the done callbacks of a listener."""


@dataclass(frozen=True, slots=True, eq=True, unsafe_hash=True)
class ListenerKey:
    """Identifies a listener slot: a chat, optionally narrowed to a user and/or a message.

    Raises:
        ValueError: If `message_id` is `EphemeralUpdates.ANY` without a `user_id`.

    Example:
        >>> ListenerKey(1, 2) == ListenerKey(chat_id=1, user_id=2, message_id=None)
        True
    """

    chat_id: int
    """The chat the listener waits in."""
    user_id: int | None = None
    """The user the listener waits for, or `None` for any user."""
    message_id: ListenerMessageIdT | None = None
    """The id the update must carry, `EphemeralUpdates.ANY`, or `None` for any regular message."""

    def __post_init__(self) -> None:
        """Check the values; see the class docstring."""
        if self.message_id is EphemeralUpdates.ANY and self.user_id is None:
            msg = "Waiting on ephemeral updates needs a user_id"
            raise ValueError(msg)

    def to_tuple(self) -> tuple[int, int | None, ListenerMessageIdT | None]:
        """Return the key's components, in field order.

        Example:
            >>> ListenerKey(1, 2).to_tuple()
            (1, 2, None)
        """
        return (self.chat_id, self.user_id, self.message_id)

    def to_dict(self) -> dict[str, ListenerMessageIdT | None]:
        """Return the key's components keyed by field name, in field order.

        Example:
            >>> ListenerKey(1, 2).to_dict()
            {'chat_id': 1, 'user_id': 2, 'message_id': None}
        """
        return {"chat_id": self.chat_id, "user_id": self.user_id, "message_id": self.message_id}

    def sub_keys(self, min_dep: int = 1) -> Generator[ListenerKey, None, None]:
        """Yield every key a listener for this update could be registered under, most specific first.

        `chat_id` is always kept; the other components this key carries are
        combined in every way, so `(chat, None, message)` is reached too. A
        component this key lacks is never added, and no key is yielded twice.
        Between keys of equal size, `user_id` outranks `message_id`. A key of
        an ephemeral update yields only itself: it reaches no other wait.

        Args:
            min_dep: Fewest components to yield down to, counting `chat_id`.
                The default of `1` includes the chat-only key; `2` stops
                before it.

        Raises:
            AssertionError: If `chat_id` is `None`.

        Example:
            >>> for key in ListenerKey(1, 2, 3).sub_keys():
            ...     print(key.to_tuple())
            (1, 2, 3)
            (1, 2, None)
            (1, None, 3)
            (1, None, None)
        """
        chat_id, user_id, message_id = self.chat_id, self.user_id, self.message_id

        if chat_id is None:
            msg = "ListenerKey.chat_id must not be None"
            raise AssertionError(msg)

        # Written out for the three fields: this runs for every update a wait could take.
        size = 1 + (user_id is not None) + (message_id is not None)

        if size < min_dep:
            return

        yield self

        if message_id is EphemeralUpdates.ANY:
            return

        if size == 3:
            if min_dep > 2:
                return

            yield ListenerKey(chat_id, user_id)
            yield ListenerKey(chat_id, None, message_id)

        if size > 1 and min_dep <= 1:
            yield ListenerKey(chat_id)


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
    """The message `ask` sent or edited for the wait."""


@dataclass(slots=True, frozen=True, eq=False)
class ListenerModel:
    """A registered listener: its key, the future its update resolves, its context and filter.

    `done_callbacks` run inside `resolve` and `set_exc`, right after the future
    is set, with the model as their one argument: at once, not on the next loop
    iteration as `asyncio.Future.add_done_callback` does. They run once, as a
    future is set only once. A failing callback is logged, and the next one
    still runs.

    Example:
        >>> async def main():
        ...     future = asyncio.get_running_loop().create_future()
        ...     listener = ListenerModel(ListenerKey(1), future)
        ...     listener.resolve("update")
        ...     return listener.done(), await listener.future
        >>> asyncio.run(main())
        (True, 'update')
    """

    key: ListenerKey
    """The slot the listener is registered under."""
    future: asyncio.Future
    """Resolved with the matching update, or failed with an error."""
    context: ListenerContext | None = None
    """Values attached to the listener, or `None` when none were passed."""
    filters: Filter | None = None
    """Pyrogram filter an update must pass besides the key, or `None` for none."""
    strict: bool = False
    """Whether an update that matches the key but fails `filters` ends the wait."""
    done_callbacks: list[Callable[[ListenerModel], object]] = field(default_factory=list)
    """Called with the model, in order, as soon as it is marked done."""

    def add_done_callback(self, fn: Callable[[ListenerModel], object]) -> None:
        """Call `fn(self)` as soon as the listener is done; at once if it already is.

        Args:
            fn: The callback; its result is ignored.

        Example:
            >>> async def main():
            ...     listener = ListenerModel(ListenerKey(1), asyncio.get_running_loop().create_future())
            ...     seen = []
            ...     listener.add_done_callback(lambda model: seen.append(model.key))
            ...     listener.resolve("update")
            ...     return seen
            >>> asyncio.run(main())
            [ListenerKey(chat_id=1, user_id=None, message_id=None)]
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
    "ListenerKey",
    "ListenerContext",
    "ListenerModel",
)
