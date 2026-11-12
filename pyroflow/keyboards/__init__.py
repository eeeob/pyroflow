"""Inline keyboards: rows of buttons, typed `callback_data` and pagination.

Telegram documents no limit on buttons per row or per keyboard, so none is
checked here, though Telegram refuses an oversized markup with
`REPLY_MARKUP_TOO_LONG`. It does limit `callback_data` to 64 bytes.
"""

from .layout import *
from .callback_data import *
from .pagination import *


__all__ = (
    *layout.__all__,
    *callback_data.__all__,
    *pagination.__all__,
)
