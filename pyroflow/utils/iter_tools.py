from typing import List, overload, Any, Generator

from .typings import NestedContainer, _T
from .validate_tools import is_container


@overload
def flat_cont(*containers: None) -> List: ...
@overload
def flat_cont(*containers: NestedContainer[_T]) -> List[_T]: ...
def flat_cont(*containers):

    def _flat_generator(item: Any) -> Generator[Any, None, None]:
        if is_container(item):
            for i in item:
                yield from _flat_generator(i)
        elif item is not None:
            yield item

    result = []
    
    for item in containers:
        result.extend(_flat_generator(item))
        
    return result


__all__ = (
    "flat_cont", 
)