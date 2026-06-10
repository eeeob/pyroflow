from typing import Any, Union

import sys
import inspect


if sys.version_info >= (3, 13):
    from typing import TypeIs
elif sys.version_info >= (3, 10):
    from typing_extensions import TypeIs
else:
    from typing_extensions import TypeGuard as TypeIs

from .typings import Container, NotContainer, _T

def is_exception(obj: Any) -> TypeIs[BaseException]:
    return isinstance(obj, BaseException)

def is_container(obj: Any) -> TypeIs[Union['Container[_T]', Any]]:
    return isinstance(obj, Container) and not isinstance(obj, NotContainer)

def iscoroutinefunction_wrapped(f: Any) -> bool:
    return inspect.iscoroutinefunction(inspect.unwrap(f))


__all__ = (
    "is_exception",
    "is_container",
    "iscoroutinefunction_wrapped", 
)