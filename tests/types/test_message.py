"""Tests for `pyroflow.types.message`: the patched `Message`."""

from __future__ import annotations as _annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock, call

import pyrogram
import pytest
from pyrogram.enums import ChatType
from pyrogram.types import Chat

from pyroflow.errors import (
    ListenerAttemptsExhausted,
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


def make_client(me_id: int | None = ME_ID) -> pyroflow.Client:
    client = pyroflow.Client("probe", api_id=1, api_hash="x", in_memory=True)
    client.setup_pyroflow(ask_context_message=True)
    client.me = None if me_id is None else SimpleNamespace(id=me_id)
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


async def test_ask_keys_the_wait_with_the_key_type_of_the_listener() -> None:
    class OwnKey(MessageKey):
        pass

    m = make_ask_msg()
    m._client.dispatcher.listeners[Message].__key_type__ = OwnKey

    await m.ask("hi")

    assert type(m._client.dispatcher.listeners[Message].listen.await_args.args[0]) is OwnKey


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
    m._client.dispatcher.listeners.clear()
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


# --- the ask_*_until() methods ----------------------------------------------

RICH = object()
"""Stands in for an `InputRichMessage`."""
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
