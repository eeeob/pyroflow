"""The dispatchers: Pyrogram's patched `Dispatcher`, and the opt-in `CoordinatedDispatcher`."""

from .dispatcher import *
from .coordinated_dispatcher import *


__all__ = (
    *dispatcher.__all__,
    *coordinated_dispatcher.__all__,
)
