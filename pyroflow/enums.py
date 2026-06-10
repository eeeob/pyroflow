from enum import StrEnum, IntEnum, auto


class UpdateLockState(IntEnum):
    PROCESSING = 0
    HANDLED    = 1

class DuplicatePolicy(StrEnum):
    REJECT = auto()
    REPLACE = auto()