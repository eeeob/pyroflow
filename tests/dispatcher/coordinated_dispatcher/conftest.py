"""Helpers shared by the tests of `pyroflow.dispatcher.coordinated_dispatcher`."""

from __future__ import annotations as _annotations

from typing import TYPE_CHECKING, Any

from pyrogram.handlers import MessageHandler

from pyroflow.models import ListenerModel, MessageKey
from pyroflow.dispatcher.coordinated_dispatcher.models import _UpdateToRun

from ...conftest import make_message

if TYPE_CHECKING:
    from pyroflow.dispatcher import CoordinatedDispatcher
    from pyroflow.dispatcher.coordinated_dispatcher.models import _HandlerHold


def chat_key(update: Any) -> int | None:
    chat = getattr(update, "chat", None)
    return None if chat is None else chat.id


def user_key(update: Any) -> int | None:
    user = getattr(update, "from_user", None)
    return None if user is None else user.id


def make_entry(message_id: int = 1, chat_id: int = 100, user_id: int = 7) -> _UpdateToRun:
    message = make_message(chat_id, user_id, message_id)
    return _UpdateToRun(("raw", {}, {}), message, MessageHandler)  # ty: ignore[invalid-argument-type]


def drain_offers(dispatcher: CoordinatedDispatcher) -> list[_HandlerHold]:
    holds = []
    while not dispatcher.offer_pass_requests.empty():
        holds.append(dispatcher.offer_pass_requests.get_nowait())
    return holds


def take(dispatcher: CoordinatedDispatcher) -> object:
    return dispatcher.worker_instructions.get_nowait()


def make_wait() -> ListenerModel:
    return ListenerModel(MessageKey(1), None)  # ty: ignore[arg-type]
