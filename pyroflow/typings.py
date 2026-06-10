from typing import Union, TypeAlias, Tuple

UpdateCoordinatorKeyT: TypeAlias = Tuple[Union[int, str], ...]
UpdateHistoryKeyT = UpdateCoordinatorKeyT
ListenerCoordinatorIdT: TypeAlias = Union[str, int]



__all__ = (
    "UpdateCoordinatorKeyT",
    "UpdateHistoryKeyT",  
    "ListenerCoordinatorIdT", 
)


