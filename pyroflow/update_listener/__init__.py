"""Per-update-type listeners that resolve `listen` and `ask_*` waits.

Support for a new update type is an `XListener` subclass of `UpdateListener`
that sets `__update_type__` and `__key_type__`, plus its key `XKey(ListenerKey)`
in `pyroflow/models/listener_key.py` with the same `__update_type__`,
`from_update` and `from_sent`.
"""

from .update_listener import *
from .message_listener import *
from .callback_query_listener import *


__all__ = (
    *update_listener.__all__,
    *message_listener.__all__,
    *callback_query_listener.__all__,
)
