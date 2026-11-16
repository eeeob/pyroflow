"""Conversation extensions for Pyrogram: the `ask_*` methods, listeners, the `CoordinatedDispatcher`, filters and inline keyboards.

Importing this package patches Pyrogram's classes in place:
`pyroflow.Client` is `pyrogram.Client`, so existing code keeps working.

Import it before creating any `Client`: a client built earlier lacks
pyroflow's state and fails on `start()`.
"""

__version__ = "1.0.0"
"""The installed release, as a PEP 440 version string."""

from .update_listener import *

from .client import *
from .dispatcher import *
from .types import *
from .filters import *
from .keyboards import *

__all__ = (
    *update_listener.__all__,
    *client.__all__,
    *dispatcher.__all__,
    *types.__all__,
    *filters.__all__,
    *keyboards.__all__,
)
