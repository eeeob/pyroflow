import sys

if sys.version_info >= (3, 11):
    from enum import StrEnum
else:
    from enum import Enum
    
    class StrEnum(str, Enum):
        def _generate_next_value_(name, *args):
            return name.lower()
        def __str__(self):
            return str(self.value)

from enum import IntEnum, auto


class UpdateLockState(IntEnum):
    PROCESSING = 0
    HANDLED    = 1

class DuplicatePolicy(StrEnum):
    REJECT = auto()
    REPLACE = auto()


__all__ = (
    "UpdateLockState", 
    "DuplicatePolicy", 
)
