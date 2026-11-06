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
    """`NEXT` for a `Message` wait, `SENT` for a `CallbackQuery`, otherwise no filter."""
    SENT = auto()
    """The message `ask` sent or edited; for a `CallbackQuery`, a press on its buttons."""
    NEXT = auto()
    """The message right after the one `ask` sent or edited."""


class EphemeralUpdates(StrEnum):
    """Takes the place of a message id to wait on ephemeral updates, whose ids can repeat.

    Example:
        >>> EphemeralUpdates.ANY == "any"
        True
    """

    ANY = auto()
    """Any ephemeral message, or a press on its buttons."""


class WorkersPolicy(StrEnum):
    """What a wait inside a handler does when the workers run short.

    A handler that waits in `ask` or `listen` holds the worker running it;
    when too many do, no worker is left to read the replies and the bot
    freezes. So one worker always stays out of the waits: once a wait would
    take it, the policy steps in. Set it with `Client.setup_pyroflow`; without
    one, nothing steps in. With one worker, every wait inside a handler is
    refused.

    Example:
        >>> WorkersPolicy.REJECT == "reject"
        True
    """

    REJECT = auto()
    """The wait raises `ListenerWorkersBusy`; suits a deliberate cap on conversations."""
    CANCEL_OLDEST = auto()
    """End the oldest wait and take its place."""


__all__ = (
    "DuplicatePolicy",
    "MessageListenCancelPolicy",
    "ListenerScope",
    "ListenMessageId",
    "EphemeralUpdates",
    "WorkersPolicy",
)
