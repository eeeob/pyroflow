"""Conversation extensions for Pyrogram: `ask`, listeners, update coordination and history.

Importing this package patches Pyrogram's classes in place.
"""

from .listener_coordinator import *
from .update_coordinated import *
from .update_coordinator import *
from .update_history import *
from .update_history_store import *
from .update_listener import *

from .client import *
from .dispatcher import *
from .types import *

# The one submodule exposed as an object rather than star-imported: its
# filter factories stay namespaced as `pyroflow.filters.<name>`.
from . import filters

__version__ = "0.2.1"

__all__ = (
    *listener_coordinator.__all__,
    *update_coordinated.__all__,
    *update_coordinator.__all__,
    *update_history.__all__,
    *update_history_store.__all__,
    *update_listener.__all__,
    *client.__all__,
    *dispatcher.__all__,
    *types.__all__,
    "filters",
)
