from typing import Any, Callable, Optional, Tuple, overload
from pyrogram.sync import async_to_sync

from pytrove import iscoroutinefunction_wrapped, patch_cls as _patch_cls
from .typings import _CT


def patch_setter(cls, name, attr) -> None:
    setattr(cls, name, attr)

    if iscoroutinefunction_wrapped(attr):
        async_to_sync(cls, name)


@overload
def patch_cls(patch_class: _CT) -> _CT: ...
@overload
def patch_cls(
    *,
    preserve_old: bool = True,
    setter: Callable[[type, str, Any], None] = patch_setter,
    include_dunders: Tuple[str, ...] = ("__init__",),
    ) -> Callable[[_CT], _CT]: ...
def patch_cls(
    patch_class: Optional[_CT] = None,
    *,
    preserve_old: bool = True,
    setter: Callable[[type, str, Any], None] = patch_setter,
    include_dunders: Tuple[str, ...] = ("__init__",),
    ):
    """pytrove.misc_tools.patch_cls, with pyroflow's own default setter.

    pytrove's own default (``setattr``) has no notion of pyrogram's
    sync/async duality; pyroflow's does, via :func:`patch_setter`, which is
    why every bare ``@patch_cls`` in this codebase needs it as the default
    rather than plain ``setattr``. An explicit ``setter=`` still overrides
    it, same as calling pytrove's version directly.
    """

    return _patch_cls(
        patch_class,
        preserve_old=preserve_old,
        setter=setter,
        include_dunders=include_dunders,
    )


__all__ = (
    "patch_setter", 
    "patch_cls", 
)
