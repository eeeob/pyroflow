"""Shared fixtures and object factories for the pyroflow test suite.

Importing ``pyroflow`` here is deliberate and must happen before any test
runs: ``@patch_cls`` monkey-patches Pyrogram's ``Client``, ``Dispatcher``,
``Message`` and ``CallbackQuery`` in-place at import time, and the whole
suite relies on that global patch being active.
"""

from types import SimpleNamespace

import pyroflow  # noqa: F401 — activates the @patch_cls global monkey-patch
import pytest

from pyrogram.types import Message, CallbackQuery, Chat, User
from pyrogram.enums import ChatType


def make_message(chat_id=100, user_id=7, message_id=5, **overrides):
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


def make_callback_query(chat_id=100, user_id=7, message_id=5, data="cb", **overrides):
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


@pytest.fixture
def message_factory():
    return make_message


@pytest.fixture
def callback_factory():
    return make_callback_query


@pytest.fixture
def raw_message_factory():
    """A ``Message`` carrying a ``raw.peer_id`` for coordinator key extraction."""

    def _factory(chat_id=100, user_id=7, message_id=5, peer_channel_id=100):
        msg = make_message(chat_id, user_id, message_id)
        # get_peer_id() understands raw PeerChannel/PeerUser objects; a
        # SimpleNamespace with the right attribute name is enough here.
        msg.raw = SimpleNamespace(peer_id=SimpleNamespace(channel_id=peer_channel_id))
        return msg

    return _factory
