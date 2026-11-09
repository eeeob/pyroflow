"""What the `parse` of the `ask_*_until` methods returns to ask again, and the type of `parse`."""

from __future__ import annotations as _annotations

from dataclasses import dataclass, field
from typing import Any, Generic, TypeAlias

from pytrove.typings import MaybeCoroutineCallable

from ..typings import QuestionT, ResultT, UpdateType


@dataclass(frozen=True, slots=True)
class AskAgain(Generic[QuestionT]):
    """Rejects an answer: the `ask_*_until` method asks `question` next.

    Example:
        >>> AskAgain("Try again:")
        AskAgain(question='Try again:', kw={})
    """

    question: QuestionT
    """The next question: a text, or an `InputRichMessage` in the rich methods."""
    kw: dict[str, Any] = field(default_factory=dict)
    """The arguments of the next question; empty sends it with none."""


AskParser: TypeAlias = MaybeCoroutineCallable[
    [UpdateType, dict[str, Any]], AskAgain[QuestionT] | ResultT
]
"""The `parse` of the `ask_*_until` methods: `AskAgain` asks again, anything else is returned."""


__all__ = (
    "AskAgain",
    "AskParser",
)
