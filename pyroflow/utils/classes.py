from abc import ABC
from typing import Generic, Type, ClassVar, Callable, TypeVar, Dict

from pyrogram.types import Update as PyroUpdate
from .typings import UpdateType

import asyncio
import weakref

_KT = TypeVar("_KT")
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

__all__ = (
    "AsyncioLock", 
    "UpdateBound", 
    "KeyDefaultWeakValueDict", 
    "DefaultWeakValueDict", 
    "KeyDefaultDict", 
)