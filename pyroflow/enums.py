import sys

if sys.version_info >= (3, 11):
    from enum import StrEnum
else:
    from enum import Enum
    
    class StrEnum(str, Enum):
        def _generate_next_value_(name, start, count, last_values):
            return name.lower()

from enum import IntEnum, auto


class UpdateLockState(IntEnum):
    PROCESSING = 0
    HANDLED    = 1

class DuplicatePolicy(StrEnum):
    REJECT = auto()
    REPLACE = auto()