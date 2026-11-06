"""Enumerations used by pyroflow."""

from __future__ import annotations as _annotations

import sys
from enum import auto

if sys.version_info >= (3, 11):
    from enum import StrEnum
else:
    from enum import Enum

    class StrEnum(str, Enum):
        """Backport of `enum.StrEnum` for Python 3.10: members are strings, `auto()` is the lowercase name."""

        @staticmethod
        def _generate_next_value_(
            name: str, start: int, count: int, last_values: list[object]
        ) -> str:
            """Return the lowercase member name as the value of an `auto()` member.

            Args:
                name: The member's name.
                start: Unused; part of the `Enum` hook signature.
                count: Unused; part of the `Enum` hook signature.
                last_values: Unused; part of the `Enum` hook signature.

            Returns:
                `name` in lowercase.
            """
            del start, count, last_values  # The hook passes them; only the name decides.
            return name.lower()

        __str__ = str.__str__

        # typeshed makes `format_spec` positional-only in `str.__format__` but names it in
        # `Enum.__format__`, so `ty` sees the alias as an incompatible override.
        __format__ = str.__format__  # ty: ignore[invalid-method-override]


class DuplicatePolicy(StrEnum):
    """What to do when a listener is registered under a key that is already taken.

    Example:
        >>> DuplicatePolicy.REJECT == "reject"
        True
    """

    REJECT = auto()
    """Refuse the new listener by raising `ListenerAlreadyExists`."""
    REPLACE = auto()
    """Cancel the existing listener, then register the new one."""


class MessageListenCancelPolicy(StrEnum):
    """When a press on a message cancels the message listen tied to it.

    Example:
        >>> MessageListenCancelPolicy.UNRESOLVED == "unresolved"
        True
    """

    ALWAYS = auto()
    """On every press, whether or not a callback wait took it."""
    UNRESOLVED = auto()
    """Only on a press that no callback wait took."""
    RESOLVED = auto()
    """Only on a press that a callback wait took."""


class ListenerScope(StrEnum):
    """How many of the waits that match an update an action applies to.

    Example:
        >>> ListenerScope.ALL == "all"
        True
    """

    ALL = auto()
    """Every matching wait."""
    FIRST = auto()
    """Only the most specific one, the first in `ListenerKey.sub_keys` order."""


class ListenMessageId(StrEnum):
    """A `listen_message_id` of `ask` that stands for a message only known once it is sent.

    Example:
        >>> ListenMessageId.NEXT == "next"
        True
    """

    AUTO = auto()
    """The default: `NEXT` for a `Message` wait, `SENT` for a `CallbackQuery`, otherwise no filter."""
    SENT = auto()
    """The message `ask` sent or edited itself; for a `CallbackQuery`, a press on its buttons."""
    NEXT = auto()
    """The message right after the one `ask` sent or edited (its id plus one); for a `Message`.

    In a group another member's message can take that id, and the real answer
    then never matches; pass `listen_message_id=None` there.
    """


class WorkersBusyMode(StrEnum):
    """What a wait inside a handler does when it would leave too few workers free.

    A handler that waits in `ask` or `listen` holds the worker running it, so
    enough such waits leave no worker to read the replies and the bot
    freezes. Each mode steps in once a wait would leave fewer than
    `WorkersPolicy.free_workers` workers free (see `WorkersPolicy`). No mode
    starts another worker, so every handler keeps running under its worker's
    lock, which `add_handler` and `remove_handler` rely on.

    Example:
        >>> WorkersBusyMode.REJECT == "reject"
        True
    """

    REJECT = auto()
    """The wait does not start and raises `ListenerWorkersBusy`.

    For bounded resources or a deliberate cap on conversations, such as a
    support bot with fixed capacity: the handler catches the error and
    answers "busy, try again later". A `busy_timeout` suits short
    conversations that free their worker soon.
    """
    CANCEL_OLDEST = auto()
    """The oldest wait holding a worker ends with `ListenerEvicted`, and the new one takes its place.

    For bots where the newest interaction matters more, such as menus and
    questions users often leave unanswered: the oldest wait is most likely
    abandoned, so ending it beats refusing a user who is there now.
    """
    NONE = auto()
    """No step in, the default; waits always hold their worker, which can freeze the bot.

    When you manage it yourself, such as with far more `workers` than
    conversations can ever be open at once, or with no `ask` inside handlers.
    """


__all__ = (
    "DuplicatePolicy",
    "MessageListenCancelPolicy",
    "ListenerScope",
    "ListenMessageId",
    "WorkersBusyMode",
)
