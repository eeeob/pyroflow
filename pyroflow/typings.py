from typing import Union, Tuple

import sys

if sys.version_info >= (3, 10):
    from typing import TypeAlias
else:
    from typing_extensions import TypeAlias

UpdateCoordinatorKeyT: TypeAlias = Tuple[Union[int, str], ...]
UpdateHistoryKeyT = UpdateCoordinatorKeyT
ListenerCoordinatorIdT: TypeAlias = Union[str, int]



__all__ = (
    "UpdateCoordinatorKeyT",
    "UpdateHistoryKeyT",  
    "ListenerCoordinatorIdT", 
)


