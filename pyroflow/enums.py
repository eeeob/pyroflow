"""Enumerations used by pyroflow."""

from __future__ import annotations as _annotations
import sys
from typing import Any

if sys.version_info >= (3, 11):
    from enum import StrEnum
else:
    from enum import Enum

    class StrEnum(str, Enum):
        """Backport of :class:`enum.StrEnum` for Python 3.10."""

        @staticmethod
        def _generate_next_value_(name: str, start: int, count: int, last_values: list[Any]) -> str:
            return name.lower()

        def __str__(self) -> str:
            """Return the member's value."""
            return str(self.value)


from enum import auto


class DuplicatePolicy(StrEnum):
    """What to do when a listener is registered under a key that is already taken."""

    REJECT = auto()
    REPLACE = auto()


__all__ = ("DuplicatePolicy",)
