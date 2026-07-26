from typing import List, Generator, Any, overload


from .typings import NestedContainer, _T
from .validate_tools import is_container




@overload
def iter_flat_cont(*containers: None) -> Generator[Any, None, None]: ...
@overload
def iter_flat_cont(*containers: NestedContainer[None]) -> Generator[Any, None, None]: ...
@overload
def iter_flat_cont(*containers: NestedContainer[_T]) -> Generator[_T, None, None]: ...
def iter_flat_cont(*containers):
    for item in containers:
        if is_container(item):
            yield from iter_flat_cont(*item)
        elif item is not None:
            yield item

@overload
def flat_cont(*containers: None) -> List: ...
@overload
def flat_cont(*containers: NestedContainer[None]) -> List: ...
@overload
def flat_cont(*containers: NestedContainer[_T]) -> List[_T]: ...
def flat_cont(*containers):
    return list(iter_flat_cont(*containers))


__all__ = (
    "iter_flat_cont", 
    "flat_cont", 
    
)