"""Enumerations used by pyroflow."""

from __future__ import annotations as _annotations

import sys
from enum import auto
from typing import Any

if sys.version_info >= (3, 11):
    from enum import StrEnum
else:
    from enum import Enum

    class StrEnum(str, Enum):
        """Backport of `enum.StrEnum` for Python 3.10: members are strings, `auto()` is the lowercase name."""

        @staticmethod
        def _generate_next_value_(name: str, start: int, count: int, last_values: list[Any]) -> str:
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


class ListenOutcome(StrEnum):
    """What `UpdateListener.resolve` decided for an update.

    Example:
        >>> ListenOutcome.FOREIGN == "foreign"
        True
    """

    RESOLVED = auto()
    """A listener of this session took the update: it is handled and no handler runs."""
    FOREIGN = auto()
    """A listener of another session owns the update: this session leaves it to that session."""
    UNMATCHED = auto()
    """No listener takes the update, so it goes on to the handlers."""


__all__ = ("DuplicatePolicy", "ListenOutcome")
