"""Exceptions raised by listeners and ``ask``."""

from __future__ import annotations as _annotations


class ListenerError(Exception):
    """Listener error"""  # noqa: D415  # the docstring is the runtime message template

    def __init__(self, value: object = None) -> None:
        """Format the class docstring with ``value`` as the error message.

        Args:
            value: The subject of the error, substituted for ``{value}``.
        """
        self.value = value
        # Subclasses carry their message as the class docstring. Fall back to
        # the class name if one is missing — or was shadowed by a statement
        # placed above it — so a malformed subclass degrades to a plain
        # message instead of raising AttributeError from the constructor.
        template = self.__class__.__doc__ or (self.__class__.__name__ + " {value}")
        super().__init__(template.format(value=value))


class ListenerCancelled(ListenerError):
    """UpdateListener {value} was cancelled"""  # noqa: D415  # the docstring is the runtime message template

    def __init__(self, value: object = None, is_duplicate: bool = False) -> None:
        """Build the error and record whether a newer listener caused it.

        Args:
            value: The subject of the error, substituted for ``{value}``.
            is_duplicate: Whether a newer listener for the same key caused the cancellation.
        """
        super().__init__(value)
        self.is_duplicate = is_duplicate


class ListenerTimeout(ListenerError):
    """UpdateListener {value} timed out"""  # noqa: D415  # the docstring is the runtime message template


class ListenerAlreadyExists(ListenerError):
    """UpdateListener already exists for key {value}"""  # noqa: D415  # the docstring is the runtime message template


class UnresolvedUpdate(ListenerError):
    """UnresolvedUpdate {value}"""  # noqa: D415  # the docstring is the runtime message template


class UnhandledUpdate(ListenerError):
    """UnhandledUpdate {value}"""  # noqa: D415  # the docstring is the runtime message template


__all__ = (
    "ListenerError",
    "ListenerCancelled",
    "ListenerTimeout",
    "ListenerAlreadyExists",
    "UnresolvedUpdate",
    "UnhandledUpdate",
)
