"""Exceptions raised by pyroflow."""

from __future__ import annotations as _annotations


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


class ListenerCancelled(ListenerError):
    """Listener for {value} was cancelled"""  # noqa: D415  # the docstring is the runtime message template

    def __init__(self, value: object = None, is_duplicate: bool = False) -> None:
        """Build the error and record whether a newer listener caused it.

        Args:
            value: The subject of the error, substituted for `{value}`.
            is_duplicate: Whether a newer listener for the same key caused the cancellation.

        Example:
            >>> err = ListenerCancelled("k", is_duplicate=True)
            >>> str(err), err.is_duplicate
            ('Listener for k was cancelled', True)
        """
        super().__init__(value)
        self.is_duplicate = is_duplicate
        """Whether a newer listener for the same key caused the cancellation."""


class ListenerRejected(ListenerCancelled):
    """Listener for {value} was rejected by its filters"""  # noqa: D415  # the docstring is the runtime message template

    def __init__(self, value: object = None, update: object = None) -> None:
        """Build the error and keep the update a strict filter rejected.

        Args:
            value: The subject of the error, substituted for `{value}`.
            update: The update whose key matched but that failed the filter.

        Example:
            >>> err = ListenerRejected("k", "update")
            >>> str(err), err.update, isinstance(err, ListenerCancelled)
            ('Listener for k was rejected by its filters', 'update', True)
        """
        super().__init__(value)
        self.update = update
        """The update whose key matched but that failed the filter."""


class ListenerTimeout(ListenerError):
    """Listener for {value} timed out"""  # noqa: D415  # the docstring is the runtime message template


class ListenerAlreadyExists(ListenerError):
    """A listener already exists for {value}"""  # noqa: D415  # the docstring is the runtime message template


__all__ = (
    "PyroflowError",
    "ListenerError",
    "ListenerCancelled",
    "ListenerRejected",
    "ListenerTimeout",
    "ListenerAlreadyExists",
)
