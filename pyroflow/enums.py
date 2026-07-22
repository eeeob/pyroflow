import sys

if sys.version_info >= (3, 11):
    from enum import StrEnum
else:
    from enum import Enum
    
    class StrEnum(str, Enum):
        def _generate_next_value_(self, *args):
            return self.lower()

from enum import IntEnum, auto


class UpdateLockState(IntEnum):
    PROCESSING = 0
    HANDLED    = 1

class DuplicatePolicy(StrEnum):
    REJECT = auto()
    REPLACE = auto()