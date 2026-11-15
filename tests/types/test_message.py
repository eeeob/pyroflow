"""Tests for `pyroflow.types.message`: the patched `Message`."""

from __future__ import annotations as _annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock, call

import pyrogram
import pytest
from pyrogram.enums import ChatType
from pyrogram.types import Chat, EphemeralMessageParameters, ReplyParameters

from pyroflow.errors import (
    ListenerAttemptsExhausted,
    ListenerNotSent,
    ListenerRejected,
    ListenerReplaced,
    ListenerTimeout,
)
import pyroflow
from pyroflow.models import AskAgain, CallbackQueryKey, ListenerContext, MessageKey
from pyroflow.types import CallbackQuery, Message, User
from pyroflow.types import message as message_module

from ..conftest import CALLBACK_MARKUP, make_callback_query, make_message

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


def make_client() -> pyroflow.Client:
    client = pyroflow.Client("probe", api_id=1, api_hash="x", in_memory=True)
    client.setup_pyroflow(ask_context_message=True)
    listen = AsyncMock(return_value=SENTINEL)
    client.dispatcher.listeners[Message] = SimpleNamespace(listen=listen, __key_type__=MessageKey)
    client.dispatcher.listeners[CallbackQuery] = SimpleNamespace(
        listen=listen, __key_type__=CallbackQueryKey
    )
    return client


def make_msg(
    *,
    is_self: bool = False,
    client: pyroflow.Client | None = None,
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
    # The client's own channel post: no `from_user`; only `outgoing` marks it as the client's.
    m = make_msg(sender_chat=Chat(id=-1001, type=ChatType.CHANNEL), outgoing=True)
    m.from_user = None
    assert m.editable is True


def test_editable_when_ephemeral_and_sent_by_self() -> None:
    assert make_msg(is_self=True, ephemeral_message_id=3).editable is True


def test_not_editable_when_ephemeral_and_incoming() -> None:
    assert make_msg(ephemeral_message_id=3).editable is False


def test_not_editable_without_sender_when_not_outgoing() -> None:
    m = make_msg()
    m.from_user = None
    assert m.editable is False


# --- Message.flow_* --------------------------------------------------------

RICH = object()
"""Stands in for an `InputRichMessage`."""
RECEIVER_ID = 8
"""The user who received the client's own ephemeral message."""


def mock_sending(m: Any) -> Any:
    client = m._client
    client.send_message = AsyncMock(return_value=SENT)
    client.send_rich_message = AsyncMock(return_value=SENT)
    client.edit_message_text = AsyncMock(return_value=SENT)
    client.edit_ephemeral_message_text = AsyncMock(return_value=SENT)
    return client


def replied_with(**kw: Any) -> dict[str, Any]:
    """What `flow_reply*` sends besides the content, on a message of `make_msg`, updated with `kw`."""
    return {
        "chat_id": 100,
        "message_thread_id": None,
        "direct_messages_topic_id": None,
        "ephemeral_message_parameters": None,
        "reply_parameters": ReplyParameters(message_id=5),
        "business_connection_id": None,
        **kw,
    }


FLOW_EDITS = [
    pytest.param("flow_edit", "text", "hi", id="text"),
    pytest.param("flow_edit_rich", "rich_message", RICH, id="rich"),
]
"""Each `flow_edit*` method, the argument that carries the content, and the content."""
FLOW_REPLIES = [
    pytest.param("flow_reply", "send_message", "text", "hi", id="text"),
    pytest.param("flow_reply_rich", "send_rich_message", "rich_message", RICH, id="rich"),
]
"""Each `flow_reply*` method, the client method it sends with, its content argument, and the content."""


@pytest.mark.parametrize(("method", "content_kw", "content"), FLOW_EDITS)
async def test_flow_edit_edits_this_message_through_its_business_connection(
    method: str, content_kw: str, content: object
) -> None:
    m = make_msg(is_self=True, business_connection_id="biz")
    client = mock_sending(m)

    assert await getattr(m, method)(content, reply_markup=None) is SENT

    client.edit_message_text.assert_awaited_once_with(
        chat_id=100,
        message_id=5,
        business_connection_id="biz",
        reply_markup=None,
        **{content_kw: content},
    )
    client.edit_ephemeral_message_text.assert_not_awaited()


@pytest.mark.parametrize(("method", "content_kw", "content"), FLOW_EDITS)
async def test_flow_edit_edits_the_clients_own_ephemeral_message_for_its_receiver(
    method: str, content_kw: str, content: object
) -> None:
    m = make_msg(is_self=True, ephemeral_message_id=3, receiver_user=User(id=RECEIVER_ID))
    m.id = 0
    client = mock_sending(m)
    client.edit_ephemeral_message_text.return_value = None

    assert await getattr(m, method)(content, reply_markup=None) is None

    client.edit_ephemeral_message_text.assert_awaited_once_with(
        chat_id=100,
        receiver_user_id=RECEIVER_ID,
        ephemeral_message_id=3,
        reply_markup=None,
        **{content_kw: content},
    )
    client.edit_message_text.assert_not_awaited()


@pytest.mark.parametrize(("method", "content_kw", "content"), FLOW_EDITS)
async def test_flow_edit_refuses_an_ephemeral_message_without_a_receiver(
    method: str, content_kw: str, content: object
) -> None:
    m = make_msg(is_self=True, ephemeral_message_id=3)
    client = mock_sending(m)

    with pytest.raises(ValueError, match="its receiver is unknown"):
        await getattr(m, method)(content)

    client.edit_ephemeral_message_text.assert_not_awaited()


@pytest.mark.parametrize(("method", "sender", "content_kw", "content"), FLOW_REPLIES)
async def test_flow_reply_replies_in_the_chat_topics_and_business_connection(
    method: str, sender: str, content_kw: str, content: object
) -> None:
    m = make_msg(message_thread_id=3, direct_messages_topic_id=4, business_connection_id="biz")
    client = mock_sending(m)

    assert await getattr(m, method)(content, disable_notification=True) is SENT

    getattr(client, sender).assert_awaited_once_with(
        **{content_kw: content},
        **replied_with(
            message_thread_id=3,
            direct_messages_topic_id=4,
            business_connection_id="biz",
            disable_notification=True,
        ),
    )


@pytest.mark.parametrize(("method", "sender", "content_kw", "content"), FLOW_REPLIES)
@pytest.mark.parametrize("outgoing", [False, True], ids=["from_self", "outgoing"])
async def test_flow_reply_sends_to_the_receiver_of_the_clients_own_ephemeral_message(
    method: str, sender: str, content_kw: str, content: object, outgoing: bool
) -> None:
    m = make_msg(
        is_self=not outgoing,
        outgoing=outgoing,
        ephemeral_message_id=3,
        receiver_user=User(id=RECEIVER_ID),
    )
    if outgoing:
        m.from_user = None
    client = mock_sending(m)

    await getattr(m, method)(content)

    getattr(client, sender).assert_awaited_once_with(
        **{content_kw: content},
        **replied_with(
            reply_parameters=ReplyParameters(ephemeral_message_id=3),
            ephemeral_message_parameters=EphemeralMessageParameters(receiver_user_id=RECEIVER_ID),
        ),
    )


@pytest.mark.parametrize(("method", "sender", "content_kw", "content"), FLOW_REPLIES)
async def test_flow_reply_sends_to_the_sender_of_an_incoming_ephemeral_message(
    method: str, sender: str, content_kw: str, content: object
) -> None:
    m = make_msg(ephemeral_message_id=3, receiver_user=User(id=ME_ID))
    client = mock_sending(m)

    await getattr(m, method)(content)

    sent = getattr(client, sender).await_args.kwargs
    assert sent["ephemeral_message_parameters"] == EphemeralMessageParameters(receiver_user_id=7)


@pytest.mark.parametrize(("method", "sender", "content_kw", "content"), FLOW_REPLIES)
async def test_flow_reply_refuses_an_ephemeral_message_without_a_user_to_reply_to(
    method: str, sender: str, content_kw: str, content: object
) -> None:
    m = make_msg(ephemeral_message_id=3)
    m.from_user = None
    client = mock_sending(m)

    with pytest.raises(ValueError, match="the user to reply to is unknown"):
        await getattr(m, method)(content)

    getattr(client, sender).assert_not_awaited()


# --- Message.respond* and flow_respond* -------------------------------------


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


@pytest.mark.parametrize(
    ("is_self", "expected"),
    [
        (True, call.edit(rich_message=RICH, reply_markup=None)),
        (False, call.reply_rich(RICH, reply_markup=None)),
    ],
)
async def test_respond_rich_edits_or_replies(is_self: bool, expected: Any) -> None:
    m = make_msg(is_self=is_self)
    sender = Mock(
        edit=AsyncMock(return_value=SENTINEL), reply_rich=AsyncMock(return_value=SENTINEL)
    )
    m.edit, m.reply_rich = sender.edit, sender.reply_rich

    assert await m.respond_rich(RICH, reply_markup=None) is SENTINEL

    assert sender.mock_calls == [expected]


@pytest.mark.parametrize(
    ("is_self", "used", "unused"),
    [(True, "flow_edit", "flow_reply"), (False, "flow_reply", "flow_edit")],
)
async def test_flow_respond_edits_or_replies(is_self: bool, used: str, unused: str) -> None:
    m = make_msg(is_self=is_self)
    m.flow_edit = AsyncMock(return_value=SENTINEL)
    m.flow_reply = AsyncMock(return_value=SENTINEL)

    assert await m.flow_respond("hi", reply_markup=None) is SENTINEL

    getattr(m, used).assert_awaited_once_with("hi", reply_markup=None)
    getattr(m, unused).assert_not_awaited()


@pytest.mark.parametrize(
    ("is_self", "used", "unused"),
    [(True, "flow_edit_rich", "flow_reply_rich"), (False, "flow_reply_rich", "flow_edit_rich")],
)
async def test_flow_respond_rich_edits_or_replies(is_self: bool, used: str, unused: str) -> None:
    m = make_msg(is_self=is_self)
    m.flow_edit_rich = AsyncMock(return_value=SENTINEL)
    m.flow_reply_rich = AsyncMock(return_value=SENTINEL)

    assert await m.flow_respond_rich(RICH, reply_markup=None) is SENTINEL

    getattr(m, used).assert_awaited_once_with(RICH, reply_markup=None)
    getattr(m, unused).assert_not_awaited()


# --- Message.ask_* --------------------------------------------------------

ASK_METHODS = [
    pytest.param("ask", "send_message", "text", "hi", MessageKey, id="message"),
    pytest.param(
        "ask_rich", "send_rich_message", "rich_message", RICH, MessageKey, id="message_rich"
    ),
    pytest.param(
        "ask_callback_query",
        "send_message",
        "text",
        "hi",
        CallbackQueryKey,
        id="callback_query",
    ),
    pytest.param(
        "ask_callback_query_rich",
        "send_rich_message",
        "rich_message",
        RICH,
        CallbackQueryKey,
        id="callback_query_rich",
    ),
]
"""Each `ask_*` method, the client method that replies, its content argument, the content and key type."""
ASK_ARGS = "method, sender, content_kw, content, key_type"


def make_ask_msg(*, is_self: bool = False, **fields: Any) -> Any:
    m = make_msg(is_self=is_self, **fields)
    mock_sending(m)
    return m


def wait_of(m: Any) -> AsyncMock:
    # Both update types share the one fake listener of `make_client`.
    return m._client.dispatcher.listeners[Message].listen


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
    method: str, sender: str, content_kw: str, content: object, key_type: type
) -> None:
    m = make_ask_msg()
    m.empty = True

    with pytest.raises(ValueError, match="on an empty message"):
        await getattr(m, method)(content)

    getattr(m._client, sender).assert_not_awaited()


@pytest.mark.parametrize(ASK_ARGS, ASK_METHODS)
async def test_ask_takes_a_service_message(
    method: str, sender: str, content_kw: str, content: object, key_type: type
) -> None:
    m = make_ask_msg()
    m.service = True

    assert await getattr(m, method)(content) is SENTINEL
    getattr(m._client, sender).assert_awaited_once()


@pytest.mark.parametrize(ASK_ARGS, ASK_METHODS)
async def test_ask_replies_when_not_editable_and_waits_on_any_user(
    method: str, sender: str, content_kw: str, content: object, key_type: type
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
    assert getattr(m._client, sender).await_args == call(
        **{content_kw: content}, **replied_with(extra="kw")
    )
    m._client.edit_message_text.assert_not_awaited()
    assert_listened(
        m,
        key_type.from_sent(SENT),
        context=ListenerContext(step=1, message=SENT),
        filters=pyrogram.filters.text,
        strict=True,
        timeout=1,
    )


async def test_ask_keys_the_wait_with_the_key_type_of_the_listener() -> None:
    class OwnKey(MessageKey):
        pass

    m = make_ask_msg()
    m._client.dispatcher.listeners[Message].__key_type__ = OwnKey

    await m.ask("hi")

    assert type(m._client.dispatcher.listeners[Message].listen.await_args.args[0]) is OwnKey


@pytest.mark.parametrize(ASK_ARGS, ASK_METHODS)
async def test_ask_edits_when_editable_and_waits_on_any_user(
    method: str, sender: str, content_kw: str, content: object, key_type: type
) -> None:
    m = make_ask_msg(is_self=True)

    assert await getattr(m, method)(content, reply_markup=None) is SENTINEL

    assert m._client.edit_message_text.await_args == call(
        chat_id=100,
        message_id=5,
        business_connection_id=None,
        reply_markup=None,
        **{content_kw: content},
    )
    getattr(m._client, sender).assert_not_awaited()
    assert_listened(m, key_type.from_sent(SENT))


@pytest.mark.parametrize(ASK_ARGS, ASK_METHODS)
async def test_ask_force_send_replies_even_when_editable(
    method: str, sender: str, content_kw: str, content: object, key_type: type
) -> None:
    m = make_ask_msg(is_self=True)
    await getattr(m, method)(content, True, disable_notification=True)

    assert getattr(m._client, sender).await_args == call(
        **{content_kw: content}, **replied_with(disable_notification=True)
    )
    m._client.edit_message_text.assert_not_awaited()
    assert_listened(m, key_type.from_sent(SENT))


@pytest.mark.parametrize(ASK_ARGS, ASK_METHODS)
@pytest.mark.parametrize("is_self", [False, True])
async def test_ask_waits_on_listen_user_id(
    method: str, sender: str, content_kw: str, content: object, key_type: type, is_self: bool
) -> None:
    m = make_ask_msg(is_self=is_self)
    await getattr(m, method)(content, listen_user_id=42)

    assert_listened(m, key_type.from_sent(SENT, 42))


@pytest.mark.parametrize(ASK_ARGS, ASK_METHODS)
async def test_ask_waits_on_any_user_after_a_message_without_a_sender(
    method: str, sender: str, content_kw: str, content: object, key_type: type
) -> None:
    m = make_ask_msg(sender_chat=Chat(id=999, type=ChatType.CHANNEL))
    m.from_user = None
    await getattr(m, method)(content)

    assert_listened(m, key_type.from_sent(SENT))


@pytest.mark.parametrize(ASK_ARGS, ASK_METHODS)
async def test_ask_sends_nothing_without_a_listener(
    method: str, sender: str, content_kw: str, content: object, key_type: type
) -> None:
    m = make_ask_msg()
    m._client.dispatcher.listeners.clear()
    update_type = "Message" if key_type is MessageKey else "CallbackQuery"

    with pytest.raises(RuntimeError, match=f"No listener registered for {update_type}"):
        await getattr(m, method)(content)

    getattr(m._client, sender).assert_not_awaited()


@pytest.mark.parametrize(ASK_ARGS, ASK_METHODS[:2])
async def test_ask_message_keys_the_answer_by_the_topics_of_the_sent_message(
    method: str, sender: str, content_kw: str, content: object, key_type: type
) -> None:
    m = make_ask_msg()
    getattr(m._client, sender).return_value = Message(
        id=9, chat=Chat(id=-1001), message_thread_id=3, direct_messages_topic_id=4
    )
    await getattr(m, method)(content)

    assert wait_of(m).await_args.args == (MessageKey(-1001, None, 3, 4),)


@pytest.mark.parametrize(ASK_ARGS, ASK_METHODS[2:])
async def test_ask_callback_query_keys_the_press_by_the_sent_message(
    method: str, sender: str, content_kw: str, content: object, key_type: type
) -> None:
    m = make_ask_msg()
    await getattr(m, method)(content)

    assert wait_of(m).await_args.args == (CallbackQueryKey(100, None, 9),)


@pytest.mark.parametrize(ASK_ARGS, ASK_METHODS)
async def test_ask_passes_a_context_holding_a_message_as_it_is(
    method: str, sender: str, content_kw: str, content: object, key_type: type
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
    content_kw: str,
    content: object,
    key_type: type,
    context: ListenerContext | None,
) -> None:
    m = make_ask_msg()
    m._client.ask_context_message = False
    await getattr(m, method)(content, listen_context=context)

    assert wait_of(m).await_args.kwargs["context"] is context


# --- ephemeral messages ---------------------------------------------------


def make_ephemeral_msg(*, is_self: bool = False) -> Any:
    m = make_ask_msg(is_self=is_self, ephemeral_message_id=3, receiver_user=User(id=RECEIVER_ID))
    m.id = 0
    client = m._client
    for sender in (
        client.send_message,
        client.send_rich_message,
        client.edit_message_text,
        client.edit_ephemeral_message_text,
    ):
        sender.return_value = EPHEMERAL_SENT
    return m


@pytest.mark.parametrize(ASK_ARGS, ASK_METHODS)
async def test_ask_on_the_clients_own_ephemeral_message_edits_it_for_its_receiver(
    method: str, sender: str, content_kw: str, content: object, key_type: type
) -> None:
    m = make_ephemeral_msg(is_self=True)
    await getattr(m, method)(content)

    edit = m._client.edit_ephemeral_message_text.await_args.kwargs
    assert edit["receiver_user_id"] == RECEIVER_ID != ME_ID
    getattr(m._client, sender).assert_not_awaited()
    m._client.edit_message_text.assert_not_awaited()
    assert_listened(
        m,
        key_type.from_sent(EPHEMERAL_SENT),
        context=ListenerContext(message=EPHEMERAL_SENT),
    )


@pytest.mark.parametrize(ASK_ARGS, ASK_METHODS)
async def test_ask_raises_listener_not_sent_when_the_ephemeral_edit_returns_none(
    method: str, sender: str, content_kw: str, content: object, key_type: type
) -> None:
    m = make_ephemeral_msg(is_self=True)
    m._client.edit_ephemeral_message_text.return_value = None

    with pytest.raises(ListenerNotSent):
        await getattr(m, method)(content)

    wait_of(m).assert_not_awaited()


@pytest.mark.parametrize(ASK_ARGS, ASK_METHODS)
@pytest.mark.parametrize("make", [make_ask_msg, make_ephemeral_msg])
async def test_ask_raises_listener_not_sent_when_the_reply_returns_none(
    method: str,
    sender: str,
    content_kw: str,
    content: object,
    key_type: type,
    make: Any,
) -> None:
    m = make()
    getattr(m._client, sender).return_value = None

    with pytest.raises(ListenerNotSent):
        await getattr(m, method)(content)

    wait_of(m).assert_not_awaited()


@pytest.mark.parametrize(ASK_ARGS, ASK_METHODS)
async def test_ask_force_send_on_the_clients_own_ephemeral_message_replies_to_its_receiver(
    method: str, sender: str, content_kw: str, content: object, key_type: type
) -> None:
    m = make_ephemeral_msg(is_self=True)
    await getattr(m, method)(content, True)

    sent = getattr(m._client, sender).await_args.kwargs
    assert sent["ephemeral_message_parameters"].receiver_user_id == RECEIVER_ID != ME_ID
    m._client.edit_ephemeral_message_text.assert_not_awaited()


@pytest.mark.parametrize(ASK_ARGS, ASK_METHODS)
async def test_ask_replying_to_an_ephemeral_message_waits_ephemerally_on_any_user(
    method: str, sender: str, content_kw: str, content: object, key_type: type
) -> None:
    m = make_ephemeral_msg()
    await getattr(m, method)(content)

    key = wait_of(m).await_args.args[0]
    assert key == key_type.from_sent(EPHEMERAL_SENT)
    assert (key.user_id, key.ephemeral) == (None, True)


@pytest.mark.parametrize(ASK_ARGS, ASK_METHODS)
async def test_ask_refuses_an_incoming_ephemeral_message_without_a_sender(
    method: str, sender: str, content_kw: str, content: object, key_type: type
) -> None:
    m = make_ephemeral_msg()
    m.from_user = None

    with pytest.raises(ValueError, match="the user to reply to is unknown"):
        await getattr(m, method)(content, listen_user_id=42)

    getattr(m._client, sender).assert_not_awaited()
    wait_of(m).assert_not_awaited()


# --- the ask_*_until() methods ----------------------------------------------

RICH_AGAIN = object()
"""Stands in for another `InputRichMessage`."""

UNTIL_METHODS = [
    pytest.param("ask_until", "ask", "hi", "again", make_message, id="message"),
    pytest.param("ask_rich_until", "ask_rich", RICH, RICH_AGAIN, make_message, id="message_rich"),
    pytest.param(
        "ask_callback_query_until",
        "ask_callback_query",
        "hi",
        "again",
        make_callback_query,
        id="callback_query",
    ),
    pytest.param(
        "ask_callback_query_rich_until",
        "ask_callback_query_rich",
        RICH,
        RICH_AGAIN,
        make_callback_query,
        id="callback_query_rich",
    ),
]
"""Each `*_until` method, the method it repeats, two questions, and its answer."""
UNTIL_ARGS = "method, asked, question, other, make_answer"
TEXT_METHODS = [UNTIL_METHODS[0], UNTIL_METHODS[2]]
RICH_METHODS = [UNTIL_METHODS[1], UNTIL_METHODS[3]]
CALLBACK_METHODS = [UNTIL_METHODS[2], UNTIL_METHODS[3]]
ENTITIES = [object()]
"""What a question's `entities` hold; only their presence matters."""


def make_until_msg(asked: str, *results: object) -> Any:
    m = make_msg()
    setattr(m, asked, AsyncMock(side_effect=results))
    return m


def sync_parse(*results: object) -> Any:
    remaining = iter(results)

    def parse(update: object, kw: dict[str, Any]) -> object:
        result = next(remaining)
        return update if result is None else result

    return parse


def async_parse(*results: object) -> Any:
    remaining = iter(results)

    async def parse(update: object, kw: dict[str, Any]) -> object:
        result = next(remaining)
        return update if result is None else result

    return parse


@pytest.mark.parametrize(UNTIL_ARGS, UNTIL_METHODS)
async def test_until_returns_what_parse_returns(
    method: str, asked: str, question: object, other: object, make_answer: Any
) -> None:
    answer = make_answer()
    m = make_until_msg(asked, answer)
    parse = Mock(return_value="parsed")

    assert await getattr(m, method)(question, parse=parse, reply_markup=CALLBACK_MARKUP) == "parsed"

    assert getattr(m, asked).await_count == 1
    parse.assert_called_once_with(answer, {"reply_markup": CALLBACK_MARKUP})


@pytest.mark.parametrize(UNTIL_ARGS, UNTIL_METHODS)
async def test_until_returns_none_when_parse_does(
    method: str, asked: str, question: object, other: object, make_answer: Any
) -> None:
    m = make_until_msg(asked, make_answer())

    assert await getattr(m, method)(question, parse=lambda *_: None) is None


@pytest.mark.parametrize(UNTIL_ARGS, UNTIL_METHODS)
@pytest.mark.parametrize("make_parse", [sync_parse, async_parse])
async def test_until_takes_a_sync_or_async_parse(
    method: str, asked: str, question: object, other: object, make_answer: Any, make_parse: Any
) -> None:
    last = make_answer()
    m = make_until_msg(asked, make_answer(), last)

    assert await getattr(m, method)(question, parse=make_parse(AskAgain(question), None)) is last
    assert getattr(m, asked).await_count == 2


@pytest.mark.parametrize(UNTIL_ARGS, UNTIL_METHODS)
async def test_until_ask_again_without_kw_asks_with_no_arguments(
    method: str, asked: str, question: object, other: object, make_answer: Any
) -> None:
    m = make_until_msg(asked, make_answer(), make_answer())

    await getattr(m, method)(
        question, parse=sync_parse(AskAgain(question), None), reply_markup=CALLBACK_MARKUP
    )

    _, second = getattr(m, asked).await_args_list
    assert second.args == (question, True)
    assert "reply_markup" not in second.kwargs


@pytest.mark.parametrize(UNTIL_ARGS, UNTIL_METHODS)
async def test_until_ask_again_asks_the_new_question_with_its_kw(
    method: str, asked: str, question: object, other: object, make_answer: Any
) -> None:
    m = make_until_msg(asked, make_answer(), make_answer())

    await getattr(m, method)(
        question,
        parse=sync_parse(AskAgain(other, {"reply_markup": CALLBACK_MARKUP}), None),
        reply_markup=CALLBACK_MARKUP,
    )

    first, second = getattr(m, asked).await_args_list
    assert first.args[0] == question
    assert second.args[0] == other
    assert second.kwargs == first.kwargs


@pytest.mark.parametrize(UNTIL_ARGS, TEXT_METHODS)
async def test_until_leaves_the_dict_parse_returned_as_it_was(
    method: str, asked: str, question: object, other: object, make_answer: Any
) -> None:
    m = make_until_msg(asked, make_answer(), make_answer(), make_answer())
    returned = {"entities": ENTITIES}
    parse = sync_parse(AskAgain("next", returned), AskAgain("other"), None)

    await getattr(m, method)(question, parse=parse)

    assert returned == {"entities": ENTITIES}


@pytest.mark.parametrize(UNTIL_ARGS, UNTIL_METHODS)
async def test_until_ask_again_with_kw_replaces_the_question_and_kw(
    method: str, asked: str, question: object, other: object, make_answer: Any
) -> None:
    m = make_until_msg(asked, make_answer(), make_answer())
    parse = sync_parse(AskAgain(other, {"disable_notification": True}), None)

    await getattr(m, method)(question, parse=parse, reply_markup=CALLBACK_MARKUP)

    _, second = getattr(m, asked).await_args_list
    assert second.args[0] == other
    assert second.kwargs["disable_notification"] is True
    assert "reply_markup" not in second.kwargs


@pytest.mark.parametrize(UNTIL_ARGS, UNTIL_METHODS)
async def test_until_the_kw_parse_got_can_be_passed_on(
    method: str, asked: str, question: object, other: object, make_answer: Any
) -> None:
    m = make_until_msg(asked, make_answer(), make_answer())
    rounds = iter([True, False])

    def parse(update: object, kw: dict[str, Any]) -> object:
        kw["disable_notification"] = True
        return AskAgain(question, kw) if next(rounds) else None

    await getattr(m, method)(question, parse=parse)

    first, second = getattr(m, asked).await_args_list
    assert "disable_notification" not in first.kwargs
    assert second.kwargs["disable_notification"] is True


@pytest.mark.parametrize(UNTIL_ARGS, TEXT_METHODS)
@pytest.mark.parametrize(
    ("result", "kept"),
    [
        pytest.param(AskAgain("again"), False, id="no_kw"),
        pytest.param(AskAgain("again", {"entities": ENTITIES}), True, id="new_kw"),
    ],
)
async def test_until_keeps_entities_only_in_the_kw_of_ask_again(
    method: str,
    asked: str,
    question: object,
    other: object,
    make_answer: Any,
    result: object,
    kept: bool,
) -> None:
    m = make_until_msg(asked, make_answer(), make_answer())

    await getattr(m, method)(question, parse=sync_parse(result, None), entities=ENTITIES)

    first, retry = getattr(m, asked).await_args_list
    assert first.kwargs["entities"] is ENTITIES
    assert ("entities" in retry.kwargs) is kept


@pytest.mark.parametrize(UNTIL_ARGS, UNTIL_METHODS)
@pytest.mark.parametrize("force_send", [False, True])
async def test_until_only_the_first_question_can_edit(
    method: str, asked: str, question: object, other: object, make_answer: Any, force_send: bool
) -> None:
    m = make_until_msg(asked, make_answer(), make_answer(), make_answer())

    await getattr(m, method)(
        question, force_send, parse=sync_parse(AskAgain(question), AskAgain(other), None)
    )

    assert [a.args[1] for a in getattr(m, asked).await_args_list] == [force_send, True, True]


@pytest.mark.parametrize(UNTIL_ARGS, UNTIL_METHODS)
@pytest.mark.parametrize("attempts", [1, 2, 3])
async def test_until_raises_attempts_exhausted_after_exactly_attempts_questions(
    method: str, asked: str, question: object, other: object, make_answer: Any, attempts: int
) -> None:
    answers = [make_answer() for _ in range(attempts)]
    m = make_until_msg(asked, *answers)

    with pytest.raises(ListenerAttemptsExhausted) as caught:
        await getattr(m, method)(
            question, parse=lambda *_: AskAgain("again"), attempts=attempts, listen_user_id=7
        )

    assert caught.value.update is answers[-1]
    assert caught.value.value == attempts
    assert getattr(m, asked).await_count == attempts


@pytest.mark.parametrize(UNTIL_ARGS, CALLBACK_METHODS)
async def test_until_attempts_exhausted_on_a_press_without_a_message(
    method: str, asked: str, question: object, other: object, make_answer: Any
) -> None:
    press = make_answer(message=None, inline_message_id="inline")
    m = make_until_msg(asked, press)

    with pytest.raises(ListenerAttemptsExhausted) as caught:
        await getattr(m, method)(question, parse=lambda *_: AskAgain("again"), attempts=1)

    assert caught.value.value == 1
    assert caught.value.update is press


@pytest.mark.parametrize(UNTIL_ARGS, UNTIL_METHODS)
@pytest.mark.parametrize("attempts", [0, -1])
async def test_until_refuses_attempts_that_are_not_positive(
    method: str, asked: str, question: object, other: object, make_answer: Any, attempts: int
) -> None:
    m = make_until_msg(asked)

    with pytest.raises(ValueError, match="attempts must be positive"):
        await getattr(m, method)(question, parse=lambda *_: None, attempts=attempts)

    getattr(m, asked).assert_not_awaited()


@pytest.mark.parametrize(UNTIL_ARGS, UNTIL_METHODS)
@pytest.mark.parametrize("listen_strict", [False, True])
async def test_until_passes_the_listen_arguments_to_the_repeated_method(
    method: str, asked: str, question: object, other: object, make_answer: Any, listen_strict: bool
) -> None:
    m = make_until_msg(asked, make_answer())

    await getattr(m, method)(
        question,
        parse=lambda *_: None,
        listen_user_id=7,
        listen_context=CONTEXT,
        listen_filters=pyrogram.filters.text,
        listen_strict=listen_strict,
        listen_timeout=3,
        reply_markup=CALLBACK_MARKUP,
    )

    getattr(m, asked).assert_awaited_once_with(
        question,
        False,
        listen_user_id=7,
        listen_context=CONTEXT,
        listen_filters=pyrogram.filters.text,
        listen_strict=listen_strict,
        listen_timeout=3,
        reply_markup=CALLBACK_MARKUP,
    )


@pytest.mark.parametrize(UNTIL_ARGS, UNTIL_METHODS)
@pytest.mark.parametrize(
    "error", [ListenerTimeout(), ListenerRejected(), ListenerReplaced(), RuntimeError()]
)
async def test_until_lets_an_error_of_the_repeated_method_through_at_once(
    method: str, asked: str, question: object, other: object, make_answer: Any, error: Exception
) -> None:
    m = make_until_msg(asked, error, make_answer())
    parse = Mock(return_value=AskAgain("again"))

    with pytest.raises(type(error)):
        await getattr(m, method)(question, parse=parse)

    assert getattr(m, asked).await_count == 1
    parse.assert_not_called()


@pytest.mark.parametrize(UNTIL_ARGS, UNTIL_METHODS)
async def test_until_lets_an_error_of_parse_through(
    method: str, asked: str, question: object, other: object, make_answer: Any
) -> None:
    m = make_until_msg(asked, make_answer(), make_answer())

    def parse(update: object, kw: dict[str, Any]) -> object:
        raise RuntimeError

    with pytest.raises(RuntimeError):
        await getattr(m, method)(question, parse=parse)

    assert getattr(m, asked).await_count == 1
