from ..types import Message
from .update_history import UpdateHistory


class MessageHistory(UpdateHistory[Message]):
    __update_type__ = Message