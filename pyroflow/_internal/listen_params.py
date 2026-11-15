"""The arguments of a wait that `Client.listen` and the `listen_*` shortcuts accept, for type checkers."""

from __future__ import annotations as _annotations

from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from pyrogram.filters import Filter
    from pytrove.typings import Number

    from ..models import ListenerContext


class ListenKw(TypedDict, total=False):
    """The arguments of a wait that every `listen` accepts besides its key."""

    context: ListenerContext | None
    """Values attached to the wait; `None` attaches none."""
    filters: Filter | None
    """A Pyrogram filter the update must pass besides its key."""
    strict: bool
    """Whether an update that matches the key but fails `filters` ends the wait."""
    timeout: Number | None
    """Seconds to wait; `None` falls back to the listener's own `timeout`."""


__all__ = ("ListenKw",)
