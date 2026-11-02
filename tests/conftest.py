"""Shared object factories for the pyroflow test suite.

Importing ``pyroflow`` here is deliberate and must happen before any test
runs: ``@patch_cls`` monkey-patches Pyrogram's ``Client``, ``Dispatcher``,
``Message`` and ``CallbackQuery`` in-place at import time, and the whole
suite relies on that global patch being active.
"""

from __future__ import annotations as _annotations

import pyroflow  # noqa: F401 — activates the @patch_cls global monkey-patch

from pyrogram.types import Message, CallbackQuery, Chat, User
from pyrogram.enums import ChatType


def make_message(
    chat_id: int = 100, user_id: int = 7, message_id: int = 5, **overrides: object
) -> Message:
    """Build a minimal, listenable :class:`Message` instance.

    Defaults produce a private, incoming, non-service message that
    ``MessageListener._is_listenable`` accepts. Any field can be
    overridden via keyword to exercise edge cases.
    """
    msg = Message(
        id=message_id,
        chat=Chat(id=chat_id, type=ChatType.PRIVATE),
        from_user=User(id=user_id, is_self=False),
    )
    for key, value in overrides.items():
        setattr(msg, key, value)
    return msg


def make_callback_query(
    chat_id: int = 100,
    user_id: int = 7,
    message_id: int = 5,
    data: str | bytes = "cb",
    **overrides: object,
) -> CallbackQuery:
    """Build a minimal :class:`CallbackQuery` whose ``message`` is listenable."""
    cbq = CallbackQuery(
        id="cbq-1",
        from_user=User(id=user_id, is_self=False),
        chat_instance="chat-instance",
        message=make_message(chat_id, user_id, message_id),
        data=data,
    )
    for key, value in overrides.items():
        setattr(cbq, key, value)
    return cbq
