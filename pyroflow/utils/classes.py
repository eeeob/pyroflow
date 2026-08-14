from abc import ABC
from typing import (
    Generic, Type, ClassVar, 
    Callable, TypeVar, Dict, 
    Hashable, Optional, Any, 
    overload
)

try:
    from typing import Self
except ImportError:
    from typing_extensions import Self

from functools import partial
from pyrogram.types import Update as PyroUpdate
from .typings import UpdateType, _T

import asyncio
import weakref

_KT = TypeVar("_KT", bound=Hashable)
_VT = TypeVar("_VT")

class AsyncioLock(asyncio.Lock):
    async def release(self):
        return super().release()
    
    async def __aexit__(self, exc_type, exc, tb):
        await self.release()

class UpdateBound(Generic[UpdateType]):
    """
    binds a class to a specific Pyrogram update type.

    Enforces that any concrete subclass declares a valid Pyrogram update
    type via __update_type__, and provides a validation helper to ensure
    incoming updates match the declared type.

    This class is not meant to be used directly — inherit from it only.

    Attributes:
        __update_type__: The Pyrogram update class this subclass is bound to.
    """

    __update_type__: ClassVar[Type[UpdateType]]

    def __init_subclass__(cls, **kw) -> None:
        super().__init_subclass__(**kw)

        if ABC in cls.__bases__:
            return
        
        if not hasattr(cls, "__update_type__"):
            raise TypeError(
                f"{cls.__name__} must define __update_type__"
            )

        update_type = cls.__update_type__

        if not (
            isinstance(update_type, type)
            and issubclass(update_type, PyroUpdate)
        ):
            raise TypeError(
                f"{cls.__name__}.__update_type__ must be a subclass of "
                f"{PyroUpdate.__name__}"
            )

    def __init__(self, **kw) -> None:
        update_type = getattr(self.__class__, "__update_type__", None)

        if update_type is None:
            raise TypeError(
                f"{self.__class__.__name__} must define __update_type__"
            )

        if not (
            isinstance(update_type, type)
            and issubclass(update_type, PyroUpdate)
        ):
            raise TypeError(
                f"{self.__class__.__name__}.__update_type__ must be a subclass of "
                f"{PyroUpdate.__name__}"
            )

        super().__init__(**kw)

    @classmethod
    def validate_update(cls, update: UpdateType) -> None:
        """
        Validate that the given update matches the declared __update_type__.

        Parameters:
            update: The incoming Pyrogram update object.

        Raises:
            TypeError: If the update is not an instance of __update_type__.
        """

        if not isinstance(update, cls.__update_type__):
            raise TypeError(
                f"Expected {cls.__update_type__.__name__}, got {type(update).__name__}"
            )

class KeyDefaultWeakValueDict(weakref.WeakValueDictionary[_KT, _VT]):
    def __init__(self, default_factory: Callable[[_KT], _VT]) -> None:
        if not callable(default_factory):
            raise TypeError("default_factory must be callable")
        
        super().__init__()

        self.default_factory = default_factory

    def __getitem__(self, key: _KT) -> _VT:
        try:
            return super().__getitem__(key)
        except KeyError:
            value = self.default_factory(key)
            self[key] = value
            return value
    
    __call__ = __getitem__

class DefaultWeakValueDict(KeyDefaultWeakValueDict[_KT, _VT]):
    def __init__(self, default_factory: Callable[[], _VT]) -> None:
        if not callable(default_factory):
            raise TypeError("default_factory must be callable")

        def wrapper(_: _KT) -> _VT:
            return default_factory()

        super().__init__(wrapper)

class KeyDefaultDict(Dict[_KT, _VT]):
    def __init__(self, default_factory: Callable[[_KT], _VT]) -> None:
        super().__init__()
        self.default_factory = default_factory

    def __missing__(self, key: _KT) -> _VT:
        value = self.default_factory(key)
        self[key] = value
        return value

class KeyDefaultWeakKeyDict(weakref.WeakKeyDictionary[_KT, _VT]):
    def __init__(self, default_factory: Callable[[_KT], _VT]) -> None:
        if not callable(default_factory):
            raise TypeError("default_factory must be callable")

        super().__init__()
        self.default_factory = default_factory

    def __getitem__(self, key: _KT) -> _VT:
        try:
            return super().__getitem__(key)
        except KeyError:
            value = self.default_factory(key)
            self[key] = value
            return value

    __call__ = __getitem__


class classproperty(Generic[_T, _VT]):
    """Like @property, but the getter receives the class instead of an
    instance, and works when accessed on the class itself (`Cls.attr`, not
    just `Cls().attr`).

    Can be used bare (`@classproperty`) or called with kwargs first
    (`@classproperty(cached=True)`) -- __new__ tells the two apart by
    whether `fget` was passed positionally: no `fget` means it was invoked
    as `classproperty(...)`, so a `functools.partial` standing in for the
    decorator is returned instead of an instance, to be called again once
    the actual getter function is available.

    `cached=True` memoizes the getter's return value per owning class in
    `_cache`, keyed by the class itself -- so a subclass gets its own cached
    computation rather than inheriting the base class's cached value.
    """

    __slots__ = "call", "doc"

    @overload
    def __new__(
        cls, 
        fget: Callable[[Type[_T]], _VT], 
        *, 
        doc: Optional[str] = None, 
        cached: bool = False 
    ) -> "classproperty[_T, _VT]": ...
    @overload
    def __new__(
        cls, 
        fget: None = None, 
        *,
        doc: Optional[str] = None, 
        cached: bool = False 
    ) -> Callable[[Callable[[Type[_T]], _VT]], "classproperty[_T, _VT]"]: ...
    def __new__(cls, fget = None, *, doc = None, cached = False): 
        if fget is None:
            return partial(cls, doc=doc, cached=cached)

        return super().__new__(cls)

    def __init__(
        self, 
        fget: Callable[[Type[_T]], _VT], 
        *, 
        doc: Optional[str] = None, 
        cached: bool = False 
    ) -> None:
        
        self.call = KeyDefaultWeakKeyDict(fget) if cached else fget
        self.doc = fget.__doc__ if doc is None else doc

    @property
    def __doc__(self) -> str:
        return self.doc

    @overload
    def __get__(self, _: Any, owner: None) -> Self: ...
    @overload
    def __get__(self, _: Any, owner: Type[_T]) -> _VT: ...
    def __get__(self, _, owner):
        if owner is None:
            return self

        value = self.call(owner)
        try:
            return value
        finally:
            if value is self and isinstance(self.call, KeyDefaultWeakKeyDict):
                self.call.pop(owner, None)

__all__ = (
    "AsyncioLock", 
    "UpdateBound", 
    "KeyDefaultWeakValueDict", 
    "DefaultWeakValueDict", 
    "KeyDefaultDict", 
    "KeyDefaultWeakKeyDict", 
    "classproperty", 
)