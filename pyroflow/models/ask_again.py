"""What the `parse` of the `ask_*_until` methods returns to ask again, and the type of `parse`."""

from __future__ import annotations as _annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Generic, TypeAlias

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
    """The keyword arguments of the next question, in place of the previous ones; the `listen_*` arguments stay."""


# pytrove's `MaybeAwaitableCallable` spelled out: it loses `UpdateType` at runtime on Python 3.12 and 3.13.
AskParser: TypeAlias = Callable[
    [UpdateType, dict[str, Any]],
    AskAgain[QuestionT] | ResultT | Awaitable[AskAgain[QuestionT] | ResultT],
]
"""The `parse` of the `ask_*_until` methods: `AskAgain` asks again, anything else is returned; light, as it runs on the loop."""


__all__ = (
    "AskAgain",
    "AskParser",
)
