"""Inline keyboards: rows of buttons, typed `callback_data` and pagination.

Telegram documents no limit on buttons per row or per keyboard, so none is
checked here. It does limit `callback_data` to 64 bytes.
"""

from .layout import *
from .pagination import *


__all__ = (
    *layout.__all__,
    *pagination.__all__,
)
