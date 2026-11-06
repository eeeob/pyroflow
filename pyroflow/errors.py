"""Exceptions raised by pyroflow."""

from __future__ import annotations as _annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
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
        # Subclasses carry their message as the class docstring. Fall back to
        # the class name when it is missing, so a malformed subclass degrades
        # to a plain message instead of raising `AttributeError` here.
        template = self.__class__.__doc__ or (self.__class__.__name__ + " {value}")
        super().__init__(template.format(value=value))


class ListenerError(PyroflowError):
    """Listener error"""  # noqa: D415  # the docstring is the runtime message template

    value: ListenerKey | None
    """The key of the wait the error is about."""


class ListenerCancelled(ListenerError):
    """Listener for {value} was cancelled"""  # noqa: D415  # the docstring is the runtime message template


class ListenerReplaced(ListenerCancelled):
    """Listener for {value} was replaced by a newer one on the same key"""  # noqa: D415  # the docstring is the runtime message template


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


__all__ = (
    "PyroflowError",
    "ListenerError",
    "ListenerCancelled",
    "ListenerReplaced",
    "ListenerRejected",
    "ListenerTimeout",
    "ListenerEvicted",
    "ListenerWorkersBusy",
    "ListenerAlreadyExists",
)
