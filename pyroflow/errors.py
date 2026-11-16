"""Exceptions raised by pyroflow.

A new error lives here and subclasses its family: `ListenerError` for waits
and the `ask_*` methods, or `PyroflowError` when it does not fit. Its class
docstring is the message template, formatted with the value at raise time.
Any `__init__` parameter after `value` needs a default, as `copy` and
`pickle` rebuild the error from `value` alone.
"""

from __future__ import annotations as _annotations

from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    import sys

    from pyrogram.types import Update as PyroUpdate

    if sys.version_info >= (3, 11):
        from typing import Self
    else:
        from typing_extensions import Self

    from .models import ListenerKey


class PyroflowError(Exception):
    """pyroflow error"""  # noqa: D415  # the docstring is the runtime message template

    def __init__(self, value: object = None) -> None:
        """Format the class docstring with `value` as the error message.

        Args:
            value: The subject of the error, substituted for `{value}`.

        Example:
            >>> str(ListenerTimeout(5))
            'Listener for 5 timed out'
        """
        self.value = value
        """The subject of the error."""
        # Messages are class docstrings, which `python -OO` strips and a subclass may lack:
        # fall back to the class name rather than raise `AttributeError`.
        template = self.__class__.__doc__ or (self.__class__.__name__ + " {value}")
        super().__init__(template.format(value=value))

    def __reduce__(self) -> tuple[type[Self], tuple[object], dict[str, Any]]:
        """Rebuild the error from `value`, so `copy` and `pickle` do not format the message twice.

        Returns:
            The class, `(value,)` and the attributes, as `copy` and `pickle` take them.

        Example:
            >>> import copy
            >>> str(copy.copy(ListenerTimeout(5)))
            'Listener for 5 timed out'
        """
        return type(self), (self.value,), self.__dict__


class ListenerError(PyroflowError):
    """Listener error"""  # noqa: D415  # the docstring is the runtime message template

    value: ListenerKey | None
    """The key of the wait the error is about."""


class ListenerCancelled(ListenerError):
    """Listener for {value} was cancelled"""  # noqa: D415  # the docstring is the runtime message template


class ListenerReplaced(ListenerCancelled):
    """Listener for {value} was replaced by a newer one on the same key"""  # noqa: D415  # the docstring is the runtime message template


class ListenerClosed(ListenerCancelled):
    """The listener is closed: it was stopped and not started again"""  # noqa: D415  # the docstring is the runtime message template


class ListenerRejected(ListenerCancelled):
    """Listener for {value} was rejected by its filters"""  # noqa: D415  # the docstring is the runtime message template


class ListenerTimeout(ListenerError):
    """Listener for {value} timed out"""  # noqa: D415  # the docstring is the runtime message template


class ListenerEvicted(ListenerCancelled):
    """Listener for {value} was cancelled to free the worker its handler held"""  # noqa: D415  # the docstring is the runtime message template


class ListenerWorkersBusy(ListenerError):
    """No free worker for a wait on {value}"""  # noqa: D415  # the docstring is the runtime message template


class ListenerAlreadyExists(ListenerError):
    """A listener already exists for {value}"""  # noqa: D415  # the docstring is the runtime message template


class ListenerNotSent(ListenerError):
    """Telegram returned no message for the question, so there is nothing to wait on"""  # noqa: D415  # the docstring is the runtime message template


class ListenerAttemptsExhausted(ListenerError):
    """No attempts left out of {value}"""  # noqa: D415  # the docstring is the runtime message template

    value: int | None  # ty: ignore[invalid-attribute-override]  # raised by the `ask_*_until` loop, which holds no key
    """How many questions were asked."""

    def __init__(self, value: int | None = None, update: PyroUpdate | None = None) -> None:
        """Keep the last rejected answer next to the number of attempts.

        Args:
            value: How many questions were asked.
            update: The last rejected answer.

        Example:
            >>> str(ListenerAttemptsExhausted(5))
            'No attempts left out of 5'
        """
        super().__init__(value)
        self.update = update
        """The last rejected answer."""


__all__ = (
    "PyroflowError",
    "ListenerError",
    "ListenerCancelled",
    "ListenerReplaced",
    "ListenerClosed",
    "ListenerRejected",
    "ListenerTimeout",
    "ListenerEvicted",
    "ListenerWorkersBusy",
    "ListenerAlreadyExists",
    "ListenerNotSent",
    "ListenerAttemptsExhausted",
)
