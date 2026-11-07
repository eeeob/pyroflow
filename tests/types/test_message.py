"""Tests for `pyroflow.types.message`: the patched `Message`."""

from __future__ import annotations as _annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, call

import pyrogram
import pytest
from pyrogram.enums import ChatType
from pyrogram.types import Chat

from pyroflow.models import CallbackQueryKey, ListenerContext, MessageKey
from pyroflow.types import CallbackQuery, Message, User
from pyroflow.update_listener import UpdateListener
from pyroflow.types import message as message_module

from ..conftest import CALLBACK_MARKUP

ME_ID = 42
SENTINEL = object()
SENT = Message(id=9, chat=Chat(id=100, type=ChatType.PRIVATE), reply_markup=CALLBACK_MARKUP)
EPHEMERAL_SENT = Message(
    id=0,
    chat=Chat(id=100, type=ChatType.PRIVATE),
    ephemeral_message_id=4,
    reply_markup=CALLBACK_MARKUP,
)
CONTEXT = ListenerContext(step=1)


@pytest.fixture(autouse=True)
def _waits_reach_the_fake_listener(monkeypatch: pytest.MonkeyPatch) -> None:
    # `ask_*` call `UpdateListener.listen` itself, past any override; send a fake's wait to the fake.
    real = UpdateListener.listen

    def listen(self: object, key: object, **kw: object) -> object:
        if isinstance(self, UpdateListener):
            return real(self, key, **kw)  # ty: ignore[invalid-argument-type]
        return self.listen(key, **kw)  # ty: ignore[unresolved-attribute]

    monkeypatch.setattr(UpdateListener, "listen", listen)


def make_client(me_id: int | None = ME_ID) -> SimpleNamespace:
    me = None if me_id is None else SimpleNamespace(id=me_id)
    listener = SimpleNamespace(listen=AsyncMock(return_value=SENTINEL))
    listeners = {Message: listener, CallbackQuery: listener}
    return SimpleNamespace(
        me=me,
        ask_context_message=True,
        listeners=listeners,
        get_listener=listeners.get,
    )


def make_msg(
    *,
    is_self: bool = False,
    client: SimpleNamespace | None = None,
    **fields: Any,
) -> Message:
    return Message(
        id=5,
        client=client or make_client(),
        chat=Chat(id=100, type=ChatType.PRIVATE),
        from_user=User(id=ME_ID if is_self else 7, is_self=is_self),
        **fields,
    )


# --- module surface -------------------------------------------------------


def test_message_all() -> None:
    assert message_module.__all__ == ("Message",)


def test_message_patches_pyrogram_in_place() -> None:
    assert Message is pyrogram.types.Message


# --- Message.editable -----------------------------------------------------


def test_editable_when_sent_by_self_user() -> None:
    assert make_msg(is_self=True).editable is True


def test_not_editable_for_other_user() -> None:
    assert make_msg().editable is False


def test_editable_when_outgoing_without_a_sender() -> None:
    # The client's own channel post: no `from_user`, and the channel's id is no user's.
    m = make_msg(sender_chat=Chat(id=-1001, type=ChatType.CHANNEL), outgoing=True)
    m.from_user = None
    assert m.editable is True


def test_not_editable_when_ephemeral_even_if_sent_by_self() -> None:
    assert make_msg(is_self=True, ephemeral_message_id=3).editable is False


def test_not_editable_when_sender_chat_is_another_chat() -> None:
    m = make_msg(sender_chat=Chat(id=999, type=ChatType.CHANNEL))
    m.from_user = None
    assert m.editable is False


def test_not_editable_without_sender_or_me() -> None:
    m = make_msg(client=make_client(me_id=None))
    m.from_user = None
    assert m.editable is False


# --- Message.respond ------------------------------------------------------


@pytest.mark.parametrize(
    "respond",
    [
        pytest.param(lambda m: m.respond("hi", parse_mode=None), id="instance"),
        pytest.param(lambda m: Message.respond(m, "hi", parse_mode=None), id="class"),
    ],
)
@pytest.mark.parametrize(
    ("is_self", "used", "unused"), [(True, "edit", "reply"), (False, "reply", "edit")]
)
async def test_respond_edits_or_replies_through_the_instance_and_the_class(
    respond: Any, is_self: bool, used: str, unused: str
) -> None:
    m = make_msg(is_self=is_self)
    m.edit = AsyncMock(return_value=SENTINEL)
    m.reply = AsyncMock(return_value=SENTINEL)

    assert await respond(m) is SENTINEL

    getattr(m, used).assert_awaited_once_with("hi", parse_mode=None)
    getattr(m, unused).assert_not_awaited()


# --- Message.ask_* --------------------------------------------------------

RICH = object()

# One row per `ask_*` method: its name, the method that sends, the content it
# takes, how `edit` is called with that content, and the key it waits on.
ASK_METHODS = [
    pytest.param("ask", "reply", "hi", call("hi"), MessageKey, id="message"),
    pytest.param(
        "ask_rich",
        "reply_rich",
        RICH,
        call(rich_message=RICH),
        MessageKey,
        id="message_rich",
    ),
    pytest.param(
        "ask_callback_query", "reply", "hi", call("hi"), CallbackQueryKey, id="callback_query"
    ),
    pytest.param(
        "ask_callback_query_rich",
        "reply_rich",
        RICH,
        call(rich_message=RICH),
        CallbackQueryKey,
        id="callback_query_rich",
    ),
]
ASK_ARGS = "method, sender, content, edit_call, key_type"


def make_ask_msg(*, is_self: bool = False, **fields: Any) -> Any:
    m = make_msg(is_self=is_self, **fields)
    m.reply = AsyncMock(return_value=SENT)
    m.edit = AsyncMock(return_value=SENT)
    m.reply_rich = AsyncMock(return_value=SENT)
    return m


def wait_of(m: Any) -> AsyncMock:
    # Both update types share the one fake listener of `make_client`.
    return m._client.listeners[Message].listen


def assert_listened(m: Any, key: object, **expected: Any) -> None:
    wait = {
        "context": ListenerContext(message=SENT),
        "filters": None,
        "strict": False,
        "timeout": None,
    }
    assert wait_of(m).await_args == call(key, **{**wait, **expected})


@pytest.mark.parametrize(ASK_ARGS, ASK_METHODS)
async def test_ask_rejects_an_empty_message(
    method: str, sender: str, content: object, edit_call: Any, key_type: type
) -> None:
    m = make_ask_msg()
    m.empty = True

    with pytest.raises(ValueError, match="on an empty message"):
        await getattr(m, method)(content)

    getattr(m, sender).assert_not_awaited()


@pytest.mark.parametrize(ASK_ARGS, ASK_METHODS)
async def test_ask_takes_a_service_message(
    method: str, sender: str, content: object, edit_call: Any, key_type: type
) -> None:
    m = make_ask_msg()
    m.service = True

    assert await getattr(m, method)(content) is SENTINEL
    getattr(m, sender).assert_awaited_once()


@pytest.mark.parametrize(ASK_ARGS, ASK_METHODS)
async def test_ask_replies_when_not_editable_and_waits_on_any_user(
    method: str, sender: str, content: object, edit_call: Any, key_type: type
) -> None:
    m = make_ask_msg()
    result = await getattr(m, method)(
        content,
        listen_context=CONTEXT,
        listen_filters=pyrogram.filters.text,
        listen_strict=True,
        listen_timeout=1,
        extra="kw",
    )

    assert result is SENTINEL
    assert getattr(m, sender).await_args == call(content, extra="kw")
    m.edit.assert_not_awaited()
    assert_listened(
        m,
        key_type.from_sent(SENT),
        context=ListenerContext(step=1, message=SENT),
        filters=pyrogram.filters.text,
        strict=True,
        timeout=1,
    )


@pytest.mark.parametrize(ASK_ARGS, ASK_METHODS)
async def test_ask_edits_when_editable_and_waits_on_any_user(
    method: str, sender: str, content: object, edit_call: Any, key_type: type
) -> None:
    m = make_ask_msg(is_self=True)

    assert await getattr(m, method)(content, reply_markup=None) is SENTINEL

    assert m.edit.await_args == call(*edit_call.args, **edit_call.kwargs, reply_markup=None)
    getattr(m, sender).assert_not_awaited()
    assert_listened(m, key_type.from_sent(SENT))


@pytest.mark.parametrize(ASK_ARGS, ASK_METHODS)
async def test_ask_force_send_replies_even_when_editable(
    method: str, sender: str, content: object, edit_call: Any, key_type: type
) -> None:
    m = make_ask_msg(is_self=True)
    await getattr(m, method)(content, True, disable_notification=True)

    assert getattr(m, sender).await_args == call(content, disable_notification=True)
    m.edit.assert_not_awaited()
    assert_listened(m, key_type.from_sent(SENT))


@pytest.mark.parametrize(ASK_ARGS, ASK_METHODS)
@pytest.mark.parametrize("is_self", [False, True])
async def test_ask_waits_on_listen_user_id(
    method: str, sender: str, content: object, edit_call: Any, key_type: type, is_self: bool
) -> None:
    m = make_ask_msg(is_self=is_self)
    await getattr(m, method)(content, listen_user_id=42)

    assert_listened(m, key_type.from_sent(SENT, 42))


@pytest.mark.parametrize(ASK_ARGS, ASK_METHODS)
async def test_ask_waits_on_any_user_after_a_message_without_a_sender(
    method: str, sender: str, content: object, edit_call: Any, key_type: type
) -> None:
    m = make_ask_msg(sender_chat=Chat(id=999, type=ChatType.CHANNEL))
    m.from_user = None
    await getattr(m, method)(content)

    assert_listened(m, key_type.from_sent(SENT))


@pytest.mark.parametrize(ASK_ARGS, ASK_METHODS)
async def test_ask_sends_nothing_without_a_listener(
    method: str, sender: str, content: object, edit_call: Any, key_type: type
) -> None:
    m = make_ask_msg()
    m._client.listeners.clear()
    update_type = "Message" if key_type is MessageKey else "CallbackQuery"

    with pytest.raises(RuntimeError, match=f"No listener registered for {update_type}"):
        await getattr(m, method)(content)

    getattr(m, sender).assert_not_awaited()


@pytest.mark.parametrize(ASK_ARGS, ASK_METHODS[:2])
async def test_ask_message_keys_the_answer_by_the_topics_of_the_sent_message(
    method: str, sender: str, content: object, edit_call: Any, key_type: type
) -> None:
    m = make_ask_msg()
    getattr(m, sender).return_value = Message(
        id=9, chat=Chat(id=-1001), message_thread_id=3, direct_messages_topic_id=4
    )
    await getattr(m, method)(content)

    assert wait_of(m).await_args.args == (MessageKey(-1001, None, 3, 4),)


@pytest.mark.parametrize(ASK_ARGS, ASK_METHODS[2:])
async def test_ask_callback_query_keys_the_press_by_the_sent_message(
    method: str, sender: str, content: object, edit_call: Any, key_type: type
) -> None:
    m = make_ask_msg()
    await getattr(m, method)(content)

    assert wait_of(m).await_args.args == (CallbackQueryKey(100, None, 9),)


@pytest.mark.parametrize(ASK_ARGS, ASK_METHODS)
async def test_ask_passes_a_context_holding_a_message_as_it_is(
    method: str, sender: str, content: object, edit_call: Any, key_type: type
) -> None:
    m = make_ask_msg()
    context = ListenerContext(message="mine")
    await getattr(m, method)(content, listen_context=context)

    assert wait_of(m).await_args.kwargs["context"] is context


@pytest.mark.parametrize(ASK_ARGS, ASK_METHODS)
@pytest.mark.parametrize("context", [None, CONTEXT])
async def test_ask_without_ask_context_message_passes_the_context_as_it_is(
    method: str,
    sender: str,
    content: object,
    edit_call: Any,
    key_type: type,
    context: ListenerContext | None,
) -> None:
    m = make_ask_msg()
    m._client.ask_context_message = False
    await getattr(m, method)(content, listen_context=context)

    assert wait_of(m).await_args.kwargs["context"] is context


# --- ephemeral messages ---------------------------------------------------


def make_ephemeral_msg(*, is_self: bool = False) -> Any:
    m = make_ask_msg(is_self=is_self, ephemeral_message_id=3)
    m.id = 0
    m.reply.return_value = EPHEMERAL_SENT
    m.edit.return_value = EPHEMERAL_SENT
    m.reply_rich.return_value = EPHEMERAL_SENT
    return m


@pytest.mark.parametrize(ASK_ARGS, ASK_METHODS)
async def test_ask_on_the_clients_own_ephemeral_message_replies_instead_of_editing(
    method: str, sender: str, content: object, edit_call: Any, key_type: type
) -> None:
    m = make_ephemeral_msg(is_self=True)
    await getattr(m, method)(content)

    getattr(m, sender).assert_awaited_once()
    m.edit.assert_not_awaited()


@pytest.mark.parametrize(ASK_ARGS, ASK_METHODS)
async def test_ask_replying_to_an_ephemeral_message_waits_ephemerally_on_any_user(
    method: str, sender: str, content: object, edit_call: Any, key_type: type
) -> None:
    m = make_ephemeral_msg()
    await getattr(m, method)(content)

    key = wait_of(m).await_args.args[0]
    assert key == key_type.from_sent(EPHEMERAL_SENT)
    assert (key.user_id, key.ephemeral) == (None, True)


@pytest.mark.parametrize(ASK_ARGS, ASK_METHODS)
async def test_ask_on_an_ephemeral_message_without_a_sender_takes_listen_user_id(
    method: str, sender: str, content: object, edit_call: Any, key_type: type
) -> None:
    m = make_ephemeral_msg()
    m.from_user = None
    await getattr(m, method)(content, listen_user_id=42)

    key = wait_of(m).await_args.args[0]
    assert key == key_type.from_sent(EPHEMERAL_SENT, 42)
    assert (key.user_id, key.ephemeral) == (42, True)
