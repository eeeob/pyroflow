"""Internal class patching helpers: `patch_cls` with Pyrogram's sync wrapper as its setter.

Methods and properties added to Pyrogram types (`Client`, `Message`, `User`,
...) go inside the class decorated with `patch_cls`, never in a subclass, so
users keep using Pyrogram's own classes.

An override that calls its kurigram original takes `*args, **kw` and passes
them on, with pyroflow's own parameters keyword-only between them
(`def __init__(self, *args, key_functions=(), **kw)`), so a kurigram
signature change needs no change here. One that replaces the original
without calling it (`Dispatcher.handler_worker(self)`) and a filter's
`__call__(self, client, update)` keep kurigram's signature; change one only
after checking it against the installed `kurigram`.
"""

from __future__ import annotations as _annotations

import inspect
from typing import Any, overload, TYPE_CHECKING

from pyrogram.sync import async_to_sync
from pytrove import iscoroutinefunction_wrapped, patch_cls as _patch_cls

if TYPE_CHECKING:
    from collections.abc import Callable

    from pytrove.typings import _CT

_MISSING: Any = object()
"""Marks a member the target did not have before its first patch."""


def patch_setter(cls: type, name: str, attr: Any) -> None:
    """Set `attr` on `cls` as `name`, adding Pyrogram's sync wrapper for coroutine functions.

    Args:
        cls: The class to set the attribute on.
        name: The attribute name.
        attr: The value to set.

    Example:
        >>> class Greeter:
        ...     pass
        >>> async def greet(self):
        ...     return "hi"
        >>> patch_setter(Greeter, "greet", greet)
        >>> Greeter().greet()  # no running loop, so the sync wrapper runs it
        'hi'
    """
    setattr(cls, name, attr)

    if iscoroutinefunction_wrapped(attr):
        async_to_sync(cls, name)


@overload
def patch_cls(patch_class: _CT) -> _CT: ...
@overload
def patch_cls(
    *,
    preserve_old: bool = True,
    setter: Callable[[type, str, object], None] = patch_setter,
    include_dunders: tuple[str, ...] = ("__init__",),
) -> Callable[[_CT], _CT]: ...
def patch_cls(
    patch_class: _CT | None = None,
    *,
    preserve_old: bool = True,
    setter: Callable[[type, str, object], None] = patch_setter,
    include_dunders: tuple[str, ...] = ("__init__",),
) -> _CT | Callable[[_CT], _CT]:
    """Copy a class body onto its single base, as `pytrove.patch_cls` with `patch_setter` as the default setter.

    The default setter gives patched coroutine methods Pyrogram's sync wrapper;
    pass `setter` to override it.

    Each member's original is recorded once, in `_pyroflow_originals` on the
    base itself, and `old<name>` always comes from that record, so patching the
    same base again, as `importlib.reload` of a pyroflow module does, never
    records a patched member as the original. `old<name>` is the member from
    before the first patch, even when a different patch class patches it later.

    Args:
        patch_class: The class holding the patches; omit it to get a decorator.
        preserve_old: Whether to keep a replaced member as `old<name>`.
        setter: How to set each member.
        include_dunders: Dunder members to copy as well.

    Returns:
        The patched base, or a decorator when `patch_class` is omitted.

    Raises:
        TypeError: If `patch_class` does not have exactly one base besides `object`.

    Example:
        >>> class Base:
        ...     def hello(self):
        ...         return "old"
        >>> @patch_cls
        ... class Base(Base):
        ...     def hello(self):
        ...         return "new"
        >>> Base().hello(), Base().oldhello()
        ('new', 'old')
    """

    def install(target: type, name: str, member: object) -> None:
        """Record the original of `name` once, restore `old<name>` from that record, then set `member`.

        Args:
            target: The patched base.
            name: The member's name.
            member: The new member.
        """
        if (originals := vars(target).get("_pyroflow_originals")) is None:
            originals = {}
            target._pyroflow_originals = originals  # ty: ignore[unresolved-attribute]  # the registry lives on the base itself

        old = originals.setdefault(name, inspect.getattr_static(target, name, _MISSING))

        if preserve_old and old is not _MISSING:
            setattr(target, f"old{name}", old)

        setter(target, name, member)

    decorator = _patch_cls(
        preserve_old=False,
        setter=install,
        include_dunders=include_dunders,
    )
    return decorator if patch_class is None else decorator(patch_class)


__all__ = (
    "patch_setter",
    "patch_cls",
)
