from typing import Any, Callable, Optional, Tuple, overload
from pyrogram.sync import async_to_sync

from .typings import _CT
from .validate_tools import iscoroutinefunction_wrapped



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

    def _apply(patch_class: type):
        bases = [b for b in patch_class.__bases__ if b is not object]

        if len(bases) != 1:
            raise TypeError(
                f"{patch_class.__name__} must inherit from exactly one base, "
                f"got {[b.__name__ for b in bases]}"
            )

        target = bases[0]

        for name, member in patch_class.__dict__.items():
            if name.startswith("__") and name.endswith("__"):
                if name not in include_dunders:
                    continue

            if preserve_old:
                if hasattr(target, name):
                    setattr(target, f"old{name}", getattr(target, name))

            setter(target, name, member)

        return target

    
    if patch_class is not None:
        return _apply(patch_class)

    return _apply


__all__ = (
    "patch_setter", 
    "patch_cls", 
    
)