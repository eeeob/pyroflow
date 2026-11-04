"""Tests for ``MessageListener``: listenability, key extraction and the bot-command bypass."""

from __future__ import annotations as _annotations

import asyncio
import gc
from datetime import datetime
from types import SimpleNamespace
from typing import Any, TYPE_CHECKING

import pytest

from pyroflow import MessageListener
from pyroflow.errors import ListenerCancelled
from pyroflow.models import ListenerKey, ListenerModel
from pyroflow.update_listener import message_listener

from ..conftest import make_message

if TYPE_CHECKING:
    from pyroflow.types import Message


class _FakeClient:
    """Stands in for a `Client`: only `me` and `get_bot_commands` are used."""

    def __init__(
        self,
        commands: list[str] | None = None,
        exc: Exception | None = None,
        me: Any = None,
    ) -> None:
        self.commands = commands or []
        self.exc = exc
        self.me = me
        self.calls = 0

    async def get_bot_commands(self) -> list[SimpleNamespace]:
        self.calls += 1
        if self.exc is not None:
            raise self.exc
        return [SimpleNamespace(command=c) for c in self.commands]


def _bot(username: str | None = "MyBot", usernames: list[str] | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        username=username, usernames=[SimpleNamespace(username=u) for u in usernames or []]
    )


# --- module level -----------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("/start", ("start", None)),
        ("/start arg", ("start", None)),
        ("/start\nnext", ("start", None)),
        ("/Start_1@my_bot", ("Start_1", "my_bot")),
        ("/start@my_bot rest", ("start", "my_bot")),
        ("/a", ("a", None)),
        ("/" + "a" * 32, ("a" * 32, None)),
    ],
)
def test_command_re_matches_command_syntax(text: str, expected: tuple[str, str | None]) -> None:
    match = message_listener._COMMAND_RE.match(text)
    assert match is not None
    assert match.groups() == expected


@pytest.mark.parametrize(
    "text",
    [
        "",
        "start",
        " /start",
        "/1start",
        "/_start",
        "/usr/bin",
        "/start@",
        "/start-now",
        "/" + "a" * 33,
        "hello /start",
    ],
)
def test_command_re_rejects_non_commands(text: str) -> None:
    assert message_listener._COMMAND_RE.match(text) is None


# --- class / __init__ --------------------------------------------------------


def test_init_defaults_to_builtin_key_functions() -> None:
    lis = MessageListener()
    assert lis.extract_key_func == lis._extract_key
    assert lis.is_bypass_func is None
    assert lis._bot_commands_cache == {}


def test_init_keeps_given_functions_and_forwards_kwargs() -> None:
    def extract_key(update: Message) -> ListenerKey:
        return ListenerKey(1)

    lis = MessageListener(extract_key_func=extract_key, timeout=3)
    assert lis.extract_key_func is extract_key
    assert lis.timeout == 3


def test_init_cache_is_per_instance() -> None:
    assert MessageListener()._bot_commands_cache is not MessageListener()._bot_commands_cache


# --- stop ---------------------------------------------------------------------


async def test_stop_clears_bot_commands_cache_and_cancels_listeners() -> None:
    lis = MessageListener()
    await lis.start()
    lis._bot_commands_cache[1] = frozenset({"start"})
    waiter = asyncio.create_task(lis.listen(100))
    await asyncio.sleep(0)

    await lis.stop()

    assert lis._bot_commands_cache == {}
    with pytest.raises(ListenerCancelled):
        await waiter


async def test_stop_clears_cache_even_when_base_stop_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lis = MessageListener()
    lis._bot_commands_cache[1] = frozenset({"start"})

    def boom(key: ListenerKey, **kw: object) -> bool:
        msg = "boom"
        raise RuntimeError(msg)

    lis.listeners[ListenerKey(1)] = ListenerModel(ListenerKey(1))
    monkeypatch.setattr(lis, "cancel", boom)

    with pytest.raises(RuntimeError, match="boom"):
        await lis.stop()
    assert lis._bot_commands_cache == {}


# --- _is_listenable -------------------------------------------------------------


async def test_is_listenable_accepts_incoming_message() -> None:
    assert await MessageListener()._is_listenable(make_message()) is True


async def test_is_listenable_accepts_message_without_sender() -> None:
    assert await MessageListener()._is_listenable(make_message(from_user=None)) is True


@pytest.mark.parametrize(
    "overrides",
    [
        {"outgoing": True},
        {"service": True},
        {"empty": True},
        {"edit_date": datetime(2024, 1, 1)},
        {"edit_hidden": True},
        {"chat": None},
    ],
)
async def test_is_listenable_rejects(overrides: dict[str, Any]) -> None:
    assert await MessageListener()._is_listenable(make_message(**overrides)) is False


async def test_is_listenable_rejects_own_messages() -> None:
    msg = make_message()
    msg.from_user.is_self = True
    assert await MessageListener()._is_listenable(msg) is False


# --- _extract_key -----------------------------------------------------------------


async def test_extract_key_uses_chat_sender_and_id() -> None:
    msg = make_message(chat_id=-100, user_id=9, message_id=42)
    assert await MessageListener()._extract_key(msg) == ListenerKey(-100, 9, 42)


async def test_extract_key_without_sender_has_no_user() -> None:
    msg = make_message(chat_id=100, message_id=5, from_user=None)
    assert await MessageListener()._extract_key(msg) == ListenerKey(100, None, 5)


async def test_extract_key_is_none_for_an_unlistenable_message() -> None:
    assert await MessageListener()._extract_key(make_message(outgoing=True)) is None


# --- _is_bypass -------------------------------------------------------------------


async def test_is_bypass_true_for_registered_command() -> None:
    client = _FakeClient(["start"])
    msg = make_message(text="/start now", _client=client)
    assert await MessageListener()._is_bypass(msg) is True


async def test_is_bypass_is_case_insensitive() -> None:
    client = _FakeClient(["Help"])
    msg = make_message(text="/HELP", _client=client)
    assert await MessageListener()._is_bypass(msg) is True


async def test_is_bypass_reads_caption_when_no_text() -> None:
    client = _FakeClient(["start"])
    msg = make_message(caption="/start", _client=client)
    assert await MessageListener()._is_bypass(msg) is True


async def test_is_bypass_false_for_unregistered_command() -> None:
    client = _FakeClient(["start"])
    msg = make_message(text="/stop", _client=client)
    assert await MessageListener()._is_bypass(msg) is False


@pytest.mark.parametrize("overrides", [{}, {"text": "hello"}, {"caption": "/usr/bin"}])
async def test_is_bypass_false_without_command_and_skips_fetch(
    overrides: dict[str, Any],
) -> None:
    client = _FakeClient(["start", "usr"])
    msg = make_message(_client=client, **overrides)
    assert await MessageListener()._is_bypass(msg) is False
    assert client.calls == 0


@pytest.mark.parametrize("target", ["MyBot", "mybot", "AltBot"])
async def test_is_bypass_accepts_command_aimed_at_this_bot(target: str) -> None:
    client = _FakeClient(["start"], me=_bot("MyBot", ["AltBot"]))
    msg = make_message(text=f"/start@{target}", _client=client)
    assert await MessageListener()._is_bypass(msg) is True


async def test_is_bypass_rejects_command_aimed_at_another_bot_without_fetch() -> None:
    client = _FakeClient(["start"], me=_bot("MyBot", ["AltBot"]))
    msg = make_message(text="/start@OtherBot", _client=client)
    assert await MessageListener()._is_bypass(msg) is False
    assert client.calls == 0


@pytest.mark.parametrize("me", [None, _bot(None, None), SimpleNamespace()])
async def test_is_bypass_rejects_targeted_command_when_identity_unknown(me: Any) -> None:
    client = _FakeClient(["start"], me=me)
    msg = make_message(text="/start@MyBot", _client=client)
    assert await MessageListener()._is_bypass(msg) is False


async def test_is_bypass_false_when_fetch_fails() -> None:
    client = _FakeClient(exc=RuntimeError("not a bot"))
    msg = make_message(text="/start", _client=client)
    assert await MessageListener()._is_bypass(msg) is False


# --- _get_bot_commands ---------------------------------------------------------


async def test_get_bot_commands_lowercases_and_caches_per_client() -> None:
    lis = MessageListener()
    client = _FakeClient(["Start", "help"])

    assert await lis._get_bot_commands(client) == frozenset({"start", "help"})
    assert await lis._get_bot_commands(client) == frozenset({"start", "help"})
    assert client.calls == 1
    assert lis._bot_commands_cache[id(client)] == frozenset({"start", "help"})


async def test_get_bot_commands_is_separate_per_client() -> None:
    lis = MessageListener()
    a, b = _FakeClient(["a"]), _FakeClient(["b"])

    assert await lis._get_bot_commands(a) == frozenset({"a"})
    assert await lis._get_bot_commands(b) == frozenset({"b"})


async def test_get_bot_commands_caches_failure_as_empty() -> None:
    lis = MessageListener()
    client = _FakeClient(exc=RuntimeError("not a bot"))

    assert await lis._get_bot_commands(client) == frozenset()
    assert await lis._get_bot_commands(client) == frozenset()
    assert client.calls == 1


async def test_get_bot_commands_refetches_after_stop() -> None:
    lis = MessageListener()
    client = _FakeClient(["start"])

    await lis._get_bot_commands(client)
    await lis.stop()
    await lis._get_bot_commands(client)
    assert client.calls == 2


async def test_get_bot_commands_entry_dropped_when_client_collected() -> None:
    lis = MessageListener()
    client = _FakeClient(["start"])
    await lis._get_bot_commands(client)
    assert len(lis._bot_commands_cache) == 1

    del client
    gc.collect()

    assert lis._bot_commands_cache == {}
