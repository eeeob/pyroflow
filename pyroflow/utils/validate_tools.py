from typing import Any, Union, get_args

import sys
import inspect


if sys.version_info >= (3, 13):
    from typing import TypeIs
else:
    from typing_extensions import TypeIs

from .typings import Container, NotContainer, _T

_CONTAINER_TYPES = get_args(Container)
_NOT_CONTAINER_TYPES = get_args(NotContainer)

def is_exception(obj: Any) -> TypeIs[BaseException]:
    return isinstance(obj, BaseException)

def is_container(obj: Any) -> TypeIs[Union['Container[_T]', Any]]:
    return isinstance(obj, _CONTAINER_TYPES) and not isinstance(obj, _NOT_CONTAINER_TYPES)

def iscoroutinefunction_wrapped(f) -> bool:
    is_coro = False

    def _stop(func):
        nonlocal is_coro

        if inspect.iscoroutinefunction(func):
            is_coro = True
            return True
        
        return False

    unwrapped = inspect.unwrap(f, stop=_stop)
    return is_coro or inspect.iscoroutinefunction(unwrapped)



__all__ = (
    "is_exception",
    "is_container",
    "iscoroutinefunction_wrapped", 
)