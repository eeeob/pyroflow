"""Internal class patching helpers: `patch_cls` with Pyrogram's sync wrapper as its setter."""

from __future__ import annotations as _annotations

from typing import Any, overload, TYPE_CHECKING

from pyrogram.sync import async_to_sync
from pytrove import iscoroutinefunction_wrapped, patch_cls as _patch_cls

if TYPE_CHECKING:
    from collections.abc import Callable

    from pytrove.typings import _CT


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

    Args:
        patch_class: The class holding the patches; omit it to get a decorator.
        preserve_old: Whether to keep a replaced member as `old<name>`.
        setter: How to set each member.
        include_dunders: Dunder members to copy as well.

    Returns:
        The patched base, or a decorator when `patch_class` is omitted.

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
    decorator = _patch_cls(
        preserve_old=preserve_old,
        setter=setter,
        include_dunders=include_dunders,
    )
    return decorator if patch_class is None else decorator(patch_class)


__all__ = (
    "patch_setter",
    "patch_cls",
)
