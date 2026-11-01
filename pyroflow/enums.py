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
        """Backport of :class:`enum.StrEnum` for Python 3.10."""

        @staticmethod
        def _generate_next_value_(name: str, start: int, count: int, last_values: list[Any]) -> str:
            """Return the lower-cased member name as the ``auto()`` value."""
            return name.lower()

        def __str__(self) -> str:
            """Return the member's value."""
            return str(self.value)


class DuplicatePolicy(StrEnum):
    """What to do when a listener is registered under a key that is already taken.

    Example:
        >>> DuplicatePolicy.REJECT == "reject"
        True
    """

    REJECT = auto()
    """Refuse the new listener by raising ``ListenerAlreadyExists``."""
    REPLACE = auto()
    """Cancel the existing listener, then register the new one."""


__all__ = ("DuplicatePolicy",)
