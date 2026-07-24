from typing import Any, Union

import sys
import inspect


if sys.version_info >= (3, 13):
    from typing import TypeIs
else:
    from typing_extensions import TypeIs

from .typings import Container, NotContainer, _T

def is_exception(obj: Any) -> TypeIs[BaseException]:
    return isinstance(obj, BaseException)

def is_container(obj: Any) -> TypeIs[Union['Container[_T]', Any]]:
    return isinstance(obj, Container) and not isinstance(obj, NotContainer)

def iscoroutinefunction_wrapped(f):
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