"""pyroflow.filters: endswith / startswith / equal / split_text / registered_command.

Each filter is exercised through Filter.__call__(client, update) — the exact
path pyrogram.handlers.Handler.check() uses — rather than by reaching into
the module's private helpers, so these pin the actual contract other code
relies on.
"""

from __future__ import annotations as _annotations

import asyncio
import gc
import inspect
import re
import threading
import weakref
from concurrent.futures import ThreadPoolExecutor
from enum import Enum
from types import SimpleNamespace
from typing import Any, TYPE_CHECKING

import pytest

from pyrogram import filters as pyrogram_filters
from pyrogram.handlers import MessageHandler
from pyrogram.types import (
    BotCommand,
    BotCommandScopeAllChatAdministrators,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeDefault,
    Message,
)

from pyroflow import filters
from pyroflow.dispatcher import Dispatcher
from pyroflow.enums import CommandUsernamePolicy
from pyroflow.errors import ListenerRejected
from pyroflow.models import MessageKey
from pyroflow.update_listener import MessageListener

if TYPE_CHECKING:
    from pyrogram.filters import Filter
    from pyrogram.types import BotCommandScope, CallbackQuery

from .conftest import bind_listener, make_callback_query, make_message


FAKE_CLIENT = SimpleNamespace(executor=None)


async def matches(flt: Filter, update: Message | CallbackQuery) -> bool:
    return await flt(FAKE_CLIENT, update)


# --- endswith / startswith / equal: matching --------------------------------


async def test_endswith_rejects_non_matching_text() -> None:
    msg = make_message(text="hello world")
    assert await matches(filters.endswith("mars"), msg) is False


async def test_equal_matches_exact_text_only() -> None:
    msg = make_message(text="hello")
    assert await matches(filters.equal("hello"), msg) is True
    assert await matches(filters.equal("hello world"), msg) is False


# --- text extraction: Message.caption fallback, CallbackQuery.data ---------


async def test_falls_back_to_caption_when_text_is_absent() -> None:
    msg = make_message(text=None, caption="a photo of world")
    assert await matches(filters.endswith("world"), msg) is True


async def test_text_takes_priority_over_caption() -> None:
    msg = make_message(text="hello", caption="world")
    assert await matches(filters.equal("hello"), msg) is True
    assert await matches(filters.equal("world"), msg) is False


async def test_callback_query_matches_on_data() -> None:
    cbq = make_callback_query(data="confirm")
    assert await matches(filters.equal("confirm"), cbq) is True


# --- filters run inline, not via the executor thread pool ------------------


def test_filters_are_recognized_as_coroutine_functions() -> None:
    """Handler.check() inspects `filter.__call__` to decide whether to await
    inline or dispatch to a thread; these are cheap string ops and must take
    the inline path."""
    flt = filters.equal("x")
    assert inspect.iscoroutinefunction(flt.__call__)


# --- split_text: matching ----------------------------------------------------


async def test_split_text_multiple_rules_with_separator() -> None:
    msg = make_message(text="/ban 42")
    flt = filters.split_text("/ban", lambda p: p.isdigit(), separator=" ")
    assert await matches(flt, msg) is True


async def test_split_text_fails_when_part_count_mismatches() -> None:
    # `maxsplit` prevents more parts than rules, so the only possible mismatch is fewer parts.
    # Both rules accept any part, so only the part count check can reject the text.
    flt = filters.split_text(lambda p: True, lambda p: True, separator=" ")
    assert await matches(flt, make_message(text="/ban")) is False


async def test_split_text_strip_trims_each_part() -> None:
    msg = make_message(text="/ban  42 ")
    flt = filters.split_text("/ban", lambda p: p == "42", separator=" ", strip=True)
    assert await matches(flt, msg) is True


async def test_split_text_container_rule_checks_membership() -> None:
    msg = make_message(text="/ban 42")
    flt = filters.split_text("/ban", ("41", "42", "43"), separator=" ")
    assert await matches(flt, msg) is True


async def test_split_text_async_callable_rule() -> None:
    async def is_digits(part: str) -> bool:
        return part.isdigit()

    msg = make_message(text="/ban 42")
    flt = filters.split_text("/ban", is_digits, separator=" ")
    assert await matches(flt, msg) is True


async def test_split_text_empty_text_matches_nothing() -> None:
    msg = make_message(text=None, caption=None)
    flt = filters.split_text("x")
    assert await matches(flt, msg) is False


# --- filter identity -------------------------------------------------------------


@pytest.mark.parametrize(
    ("flt", "name"),
    [
        (filters.endswith("x"), "EndsWith"),
        (filters.startswith("x"), "StartsWith"),
        (filters.equal("x"), "Equal"),
        (filters.split_text("x"), "SplitText"),
    ],
)
def test_each_factory_names_its_filter(flt: Filter, name: str) -> None:
    assert type(flt).__name__ == name


# --- startswith ---------------------------------------------------------------


async def test_startswith_rejects_non_matching_text() -> None:
    msg = make_message(text="hello world")
    assert await matches(filters.startswith("world"), msg) is False


async def test_startswith_callback_query_with_bytes_data_matches_nothing() -> None:
    cbq = make_callback_query(data=b"\x00\x01")
    assert await matches(filters.startswith("x"), cbq) is False


# --- equal --------------------------------------------------------------------


async def test_equal_with_no_texts_matches_nothing() -> None:
    assert await matches(filters.equal(), make_message(text="x")) is False


async def test_equal_is_case_sensitive() -> None:
    assert await matches(filters.equal("Hello"), make_message(text="hello")) is False


async def test_equal_callback_query_with_bytes_data_matches_bytes_only() -> None:
    cbq = make_callback_query(data=b"confirm")
    assert await matches(filters.equal(b"confirm"), cbq) is True
    assert await matches(filters.equal("confirm"), cbq) is False


# --- endswith / startswith / equal: str and bytes ---------------------------

TEXT_FILTERS = [
    pytest.param(filters.endswith, "hello world", "world", id="endswith"),
    pytest.param(filters.startswith, "hello world", "hello", id="startswith"),
    pytest.param(filters.equal, "hello world", "hello world", id="equal"),
]


@pytest.mark.parametrize(("factory", "text", "pattern"), TEXT_FILTERS)
async def test_str_pattern_matches_str_text(factory: Any, text: str, pattern: str) -> None:
    assert await matches(factory(pattern), make_message(text=text)) is True


@pytest.mark.parametrize(("factory", "text", "pattern"), TEXT_FILTERS)
async def test_bytes_pattern_never_matches_str_text(factory: Any, text: str, pattern: str) -> None:
    assert await matches(factory(pattern.encode()), make_message(text=text)) is False


@pytest.mark.parametrize(("factory", "text", "pattern"), TEXT_FILTERS)
async def test_str_pattern_never_matches_bytes_data(factory: Any, text: str, pattern: str) -> None:
    cbq = make_callback_query(data=text.encode())
    assert await matches(factory(pattern), cbq) is False


@pytest.mark.parametrize(("factory", "text", "pattern"), TEXT_FILTERS)
async def test_bytes_pattern_matches_bytes_data(factory: Any, text: str, pattern: str) -> None:
    cbq = make_callback_query(data=text.encode())
    assert await matches(factory(pattern.encode()), cbq) is True


async def test_only_bytes_patterns_match_non_utf8_bytes_data() -> None:
    cbq = make_callback_query(data=b"cb:\xff")
    assert await matches(filters.startswith("cb:"), cbq) is False
    assert await matches(filters.startswith(b"cb:"), cbq) is True
    assert await matches(filters.endswith(b"\xff"), cbq) is True
    assert await matches(filters.equal(b"cb:\xff"), cbq) is True


@pytest.mark.parametrize("factory", [filters.endswith, filters.startswith, filters.equal])
@pytest.mark.parametrize("update", [make_message(text=None), make_callback_query(data=b"")])
async def test_empty_text_never_matches(factory: Any, update: Message | CallbackQuery) -> None:
    assert await matches(factory("x", b"x", "", b""), update) is False


@pytest.mark.parametrize("factory", [filters.endswith, filters.startswith, filters.equal])
async def test_mixed_nested_containers_keep_each_kind(factory: Any) -> None:
    flt = factory(["a", (b"b", [None, 1])], b"")
    assert await matches(flt, make_message(text="a")) is True
    assert await matches(flt, make_callback_query(data=b"b")) is True
    assert await matches(flt, make_message(text="b")) is False
    assert await matches(flt, make_message(text="c")) is False


# --- _normalize_rule -----------------------------------------------------------


def test_normalize_rule_turns_each_kind_into_its_matcher_form() -> None:
    class Command(Enum):
        BAN = "ban"
        NUMBER = 1
        EMPTY = ""

    pattern = re.compile(r"\d+")
    assert filters._normalize_rule(pattern) is pattern
    assert filters._normalize_rule(Command) == frozenset({"ban"})
    assert filters._normalize_rule("ban") == frozenset({"ban"})
    assert filters._normalize_rule(["a", ("b", ["", 1])]) == frozenset({"a", "b"})  # type: ignore[arg-type]
    assert filters._normalize_rule(str.isdigit) is str.isdigit
    with pytest.raises(TypeError, match="Unsupported split_text rule"):
        filters._normalize_rule(1.5)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="must not be empty"):
        filters._normalize_rule(["", None])  # type: ignore[arg-type]


# --- split_text: rule normalization ------------------------------------------


async def test_split_text_string_rule_matches_only_that_string() -> None:
    flt = filters.split_text("/ban")
    assert await matches(flt, make_message(text="/ban")) is True
    assert await matches(flt, make_message(text="/kick")) is False


async def test_split_text_container_rule_rejects_a_missing_part() -> None:
    flt = filters.split_text("/ban", ("41", "43"), separator=" ")
    assert await matches(flt, make_message(text="/ban 42")) is False


async def test_split_text_nested_container_rule_is_flattened() -> None:
    flt = filters.split_text(["a", ("b", ["c"])])
    assert await matches(flt, make_message(text="c")) is True


async def test_split_text_enum_rule_ignores_non_string_and_empty_values() -> None:
    class Mixed(Enum):
        TEXT = "go"
        NUMBER = 1
        EMPTY = ""

    flt = filters.split_text(Mixed)
    assert await matches(flt, make_message(text="go")) is True
    assert await matches(flt, make_message(text="1")) is False


async def test_split_text_enum_rule_rejects_a_name_that_is_not_a_value() -> None:
    class Command(Enum):
        BAN = "ban"

    assert await matches(filters.split_text(Command), make_message(text="BAN")) is False


def test_split_text_rejects_an_enum_without_string_values() -> None:
    class Numbers(Enum):
        ONE = 1

    with pytest.raises(ValueError, match="must not be empty"):
        filters.split_text(Numbers)


@pytest.mark.parametrize("rule", ["", ["", None, 1], ()])
def test_split_text_rejects_rules_that_resolve_to_no_strings(rule: object) -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        filters.split_text(rule)  # type: ignore[arg-type]


def test_split_text_validation_messages() -> None:
    with pytest.raises(ValueError, match="at least one rule"):
        filters.split_text()
    with pytest.raises(ValueError, match="separator is required"):
        filters.split_text("a", "b")
    with pytest.raises(ValueError, match="separator must not be empty"):
        filters.split_text("a", "b", separator="")
    with pytest.raises(TypeError, match="Unsupported split_text rule"):
        filters.split_text(1.5)  # type: ignore[arg-type]


def test_split_text_validates_each_rule_not_only_the_first() -> None:
    with pytest.raises(TypeError):
        filters.split_text("a", object(), separator=" ")  # type: ignore[arg-type]


# --- split_text: matching -----------------------------------------------------


async def test_split_text_without_separator_keeps_the_whole_text() -> None:
    flt = filters.split_text("/ban 42")
    assert await matches(flt, make_message(text="/ban 42")) is True


async def test_split_text_single_rule_with_separator_does_not_split() -> None:
    # A single rule means `maxsplit=0`, so the text stays one part despite the separator.
    flt = filters.split_text("a b c", separator=" ")
    assert await matches(flt, make_message(text="a b c")) is True


async def test_split_text_without_strip_keeps_whitespace() -> None:
    flt = filters.split_text("/ban", "42", separator=",")
    assert await matches(flt, make_message(text="/ban, 42")) is False
    assert await matches(flt, make_message(text="/ban,42")) is True


async def test_split_text_strip_applies_without_separator() -> None:
    flt = filters.split_text("hello", strip=True)
    assert await matches(flt, make_message(text="  hello\n")) is True


async def test_split_text_stops_at_the_first_failing_rule() -> None:
    seen: list[str] = []

    async def record(part: str) -> bool:
        seen.append(part)
        return True

    flt = filters.split_text("/ban", record, separator=" ")
    assert await matches(flt, make_message(text="/kick 42")) is False
    assert seen == []


async def test_split_text_async_callable_rule_rejects_falsy_result() -> None:
    async def never(part: str) -> int:
        return 0

    flt = filters.split_text(never)
    assert await matches(flt, make_message(text="x")) is False


async def test_split_text_sync_callable_rule_runs_on_the_event_loop() -> None:
    threads: list[threading.Thread] = []

    def is_digits(part: str) -> bool:
        threads.append(threading.current_thread())
        return part.isdigit()

    flt = filters.split_text(is_digits)
    with ThreadPoolExecutor(thread_name_prefix="filters-test") as executor:
        client = SimpleNamespace(executor=executor)
        assert await flt(client, make_message(text="42")) is True
        assert await flt(client, make_message(text="4x")) is False
    assert threads == [threading.current_thread()] * 2


async def test_split_text_callable_rule_exception_propagates() -> None:
    def broken(part: str) -> bool:
        msg = "rule failed"
        raise RuntimeError(msg)

    flt = filters.split_text(broken)
    with pytest.raises(RuntimeError, match="rule failed"):
        await matches(flt, make_message(text="x"))


async def test_split_text_bytes_data_with_separator_matches_nothing() -> None:
    called: list[object] = []
    flt = filters.split_text("page", called.append, separator=":")
    assert await matches(flt, make_callback_query(data=b"page:3")) is False
    assert called == []


async def test_split_text_bytes_data_without_separator_matches_nothing() -> None:
    called: list[object] = []
    flt = filters.split_text(called.append)
    assert await matches(flt, make_callback_query(data=b"\x00\x01")) is False
    assert called == []


async def test_split_text_regex_rule_must_fullmatch_the_part() -> None:
    flt = filters.split_text("/ban", re.compile(r"\d+"), separator=" ")
    assert await matches(flt, make_message(text="/ban 42")) is True
    assert await matches(flt, make_message(text="/ban 42a")) is False


# --- _COMMAND_RE ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "groups"),
    [
        ("/start", ("start", None)),
        ("/Start_2 now", ("Start_2", None)),
        ("/start\nnow", ("start", None)),
        ("/start@my_bot now", ("start", "my_bot")),
        ("/start@bot2 now", ("start", "bot2")),
        ("/2fa now", ("2fa", None)),
        ("/_debug", ("_debug", None)),
        (f"/{'a' * 32}", ("a" * 32, None)),
    ],
)
def test_command_re_captures_the_name_and_the_username(
    text: str, groups: tuple[str, str | None]
) -> None:
    match = filters._COMMAND_RE.match(text)
    assert match is not None
    assert match.groups() == groups


@pytest.mark.parametrize(
    "text",
    ["start", " /start", "/", "/usr/bin", "/start@", "/start.", f"/{'a' * 33}"],
)
def test_command_re_refuses_what_is_not_a_command(text: str) -> None:
    assert filters._COMMAND_RE.match(text) is None


# --- registered_command ---------------------------------------------------------


class FakeMe:
    """A `client.me` stand-in that, like a Pyrogram `User`, holds its client."""

    def __init__(self, client: object, username: str | None, usernames: tuple[str, ...]) -> None:
        self._client = client
        self.username = username
        self.usernames = [SimpleNamespace(username=name) for name in usernames] or None


class FakeBot:
    """A client stand-in, hashable unlike `SimpleNamespace`, that records its fetches.

    `commands` are those of the default scope with no language; `scoped` gives
    other scopes and languages theirs, keyed by scope class name and language.
    `fetches` counts the fetches of the default scope with no language, one per
    round of a filter with the default `scopes` and `language_codes`.
    """

    def __init__(
        self,
        *commands: str,
        username: str | None = "this_bot",
        usernames: tuple[str, ...] = (),
        error: Exception | None = None,
        ephemeral: tuple[str, ...] = (),
        scoped: dict[tuple[str, str], tuple[str, ...]] | None = None,
    ) -> None:
        self.commands = commands
        self.ephemeral = ephemeral
        self.scoped = scoped or {}
        self.me: FakeMe | None = FakeMe(self, username, usernames)
        self.error = error
        self.fetches = 0
        self.calls: list[tuple[str, str]] = []

    async def get_bot_commands(
        self, scope: BotCommandScope | None = None, language_code: str = ""
    ) -> list[BotCommand]:
        key = (type(scope).__name__, language_code)
        self.calls.append(key)
        default = key == ("BotCommandScopeDefault", "")
        self.fetches += default
        if self.error is not None:
            raise self.error
        names = self.scoped.get(key, self.commands if default else ())
        return [BotCommand(name, f"{name} description", name in self.ephemeral) for name in names]

    def restart(self, username: str | None = None) -> None:
        """Give the bot a new `me`, as Pyrogram's `start` does."""
        assert self.me is not None
        self.me = FakeMe(self, username or self.me.username, ())


@pytest.mark.parametrize("text", ["/start", "/start now", "/start\nnow", "/START"])
async def test_registered_command_matches_with_or_without_arguments(text: str) -> None:
    flt = filters.registered_command()
    assert await flt(FakeBot("start"), make_message(text=text)) is True


async def test_registered_command_lowercases_the_fetched_names() -> None:
    flt = filters.registered_command()
    assert await flt(FakeBot("Start"), make_message(text="/start")) is True


async def test_registered_command_reads_the_caption() -> None:
    flt = filters.registered_command()
    assert await flt(FakeBot("start"), make_message(text=None, caption="/start now")) is True


async def test_registered_command_prefers_the_text_over_the_caption() -> None:
    flt = filters.registered_command()
    msg = make_message(text="hello", caption="/start")
    assert await flt(FakeBot("start"), msg) is False


@pytest.mark.parametrize(
    "text", ["/start@this_bot", "/start@this_bot now", "/start@THIS_BOT", "/start@alias_bot"]
)
async def test_registered_command_matches_a_command_aimed_at_this_bot(text: str) -> None:
    bot = FakeBot("start", username="This_Bot", usernames=("Alias_Bot",))
    assert await filters.registered_command()(bot, make_message(text=text)) is True


async def test_registered_command_matches_the_username_of_a_bot_with_no_aliases() -> None:
    bot = FakeBot("start")
    assert await filters.registered_command()(bot, make_message(text="/start@this_bot")) is True


async def test_registered_command_matches_an_alias_of_a_bot_with_no_username() -> None:
    bot = FakeBot("start", username=None, usernames=("alias_bot",))
    assert await filters.registered_command()(bot, make_message(text="/start@alias_bot")) is True


async def test_registered_command_refuses_a_command_aimed_at_another_bot() -> None:
    bot = FakeBot("start")
    assert await filters.registered_command()(bot, make_message(text="/start@other_bot")) is False


async def test_registered_command_refuses_a_username_while_the_client_has_no_me() -> None:
    bot = FakeBot("start")
    bot.me = None
    assert await filters.registered_command()(bot, make_message(text="/start@this_bot")) is False


async def test_registered_command_refuses_an_unknown_command() -> None:
    assert await filters.registered_command()(FakeBot("start"), make_message(text="/help")) is False


@pytest.mark.parametrize("text", ["hello", "/usr/bin", None])
async def test_registered_command_fetches_nothing_for_text_that_is_no_command(
    text: str | None,
) -> None:
    bot = FakeBot("start")
    assert await filters.registered_command()(bot, make_message(text=text)) is False
    assert bot.fetches == 0


@pytest.mark.parametrize("data", ["/start", b"/start"])
async def test_registered_command_raises_type_error_for_a_callback_query(data: str | bytes) -> None:
    bot = FakeBot("start")
    with pytest.raises(TypeError, match="Message updates only, not CallbackQuery"):
        await filters.registered_command()(bot, make_callback_query(data=data))
    assert bot.fetches == 0


async def test_registered_command_raises_what_fetching_the_commands_raises() -> None:
    error = RuntimeError("bots only")
    with pytest.raises(RuntimeError) as info:
        await filters.registered_command()(FakeBot(error=error), make_message(text="/start"))
    assert info.value is error


async def test_registered_command_keeps_the_clients_sharing_a_filter_apart() -> None:
    flt = filters.registered_command()
    first, second = FakeBot("start"), FakeBot("help")

    assert await flt(first, make_message(text="/start")) is True
    assert await flt(second, make_message(text="/start")) is False
    assert await flt(second, make_message(text="/help")) is True
    assert await flt(first, make_message(text="/help")) is False
    assert (first.fetches, second.fetches) == (1, 1)


async def test_registered_command_get_commands_returns_the_usernames_and_both_kinds_of_names() -> (
    None
):
    bot = FakeBot("Start", "note", ephemeral=("note",))
    commands = await filters.registered_command()._get_commands(bot)
    assert commands._replace(user_client=None) == filters._BotCommands(
        user_client=None,
        usernames=frozenset({"this_bot"}),
        regular=frozenset({"start"}),
        ephemeral=frozenset({"note"}),
    )


async def test_registered_command_get_commands_keeps_them_on_the_filter_for_this_start() -> None:
    flt, bot = filters.registered_command(), FakeBot("start")
    commands = await flt._get_commands(bot)

    assert commands.user_client is not None
    assert commands.user_client() is bot.me
    assert flt.fetched[bot] is commands
    assert await flt._get_commands(bot) is commands
    assert bot.fetches == 1


async def test_registered_command_get_commands_shares_one_fetch_between_concurrent_calls() -> None:
    flt, bot = filters.registered_command(), FakeBot("start")

    results = await asyncio.gather(*(flt._get_commands(bot) for _ in range(4)))

    assert bot.fetches == 1
    assert all(result is flt.fetched[bot] for result in results)
    assert bot not in flt.fetching


async def test_registered_command_get_commands_fetches_again_after_a_restart() -> None:
    flt, bot = filters.registered_command(), FakeBot("start")
    await flt._get_commands(bot)
    bot.commands = ("help",)
    bot.restart()

    assert (await flt._get_commands(bot)).regular == frozenset({"help"})
    assert flt.fetched[bot][0]() is bot.me
    assert bot.fetches == 2


async def test_registered_command_get_commands_fetches_on_every_call_while_the_client_has_no_me() -> (
    None
):
    flt, bot = filters.registered_command(), FakeBot("start")
    bot.me = None
    await flt._get_commands(bot)
    await flt._get_commands(bot)

    assert bot.fetches == 2


async def test_registered_command_get_commands_of_each_filter_fetches_apart() -> None:
    bot = FakeBot("start")
    await filters.registered_command()._get_commands(bot)
    await filters.registered_command()._get_commands(bot)
    assert bot.fetches == 2


async def test_registered_command_get_commands_raises_unchanged_and_keeps_nothing() -> None:
    flt, error = filters.registered_command(), RuntimeError("bots only")
    bot = FakeBot("start", error=error)

    with pytest.raises(RuntimeError) as info:
        await flt._get_commands(bot)

    assert info.value is error
    assert bot not in flt.fetched
    bot.error = None
    assert (await flt._get_commands(bot)).regular == frozenset({"start"})


async def test_registered_command_get_commands_cancels_the_other_fetches_when_one_fails() -> None:
    error, cancelled = RuntimeError("flood"), []

    class FailingBot(FakeBot):
        async def get_bot_commands(
            self, scope: BotCommandScope | None = None, language_code: str = ""
        ) -> list[BotCommand]:
            if isinstance(scope, BotCommandScopeAllChatAdministrators):
                await asyncio.sleep(0)
                raise error
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.append(type(scope).__name__)
                raise
            return []

    with pytest.raises(RuntimeError) as info:
        await asyncio.wait_for(filters.registered_command()._get_commands(FailingBot()), 1)
    await asyncio.sleep(0)  # the cancelled fetches finish on the next loop step

    assert info.value is error
    assert sorted(cancelled) == [
        "BotCommandScopeAllGroupChats",
        "BotCommandScopeAllPrivateChats",
        "BotCommandScopeDefault",
    ]


async def test_registered_command_get_commands_raises_after_a_restart_instead_of_the_old_ones() -> (
    None
):
    flt, bot = filters.registered_command(), FakeBot("start")
    await flt._get_commands(bot)
    bot.error = RuntimeError("flood")
    bot.restart()

    with pytest.raises(RuntimeError):
        await flt._get_commands(bot)


async def test_registered_command_get_commands_does_not_keep_a_client_alive() -> None:
    bot = FakeBot("start")
    ref, flt = weakref.ref(bot), filters.registered_command()
    await flt._get_commands(bot)

    del bot
    gc.collect()

    assert ref() is None


def test_registered_command_is_a_filter_that_counts_ephemeral_commands_and_has_fetched_nothing() -> (
    None
):
    flt = filters.registered_command()
    assert isinstance(flt, pyrogram_filters.Filter)
    assert flt.ephemeral is True
    assert flt.username_policy is CommandUsernamePolicy.OPTIONAL
    assert flt.scopes == filters.registered_command.DEFAULT_SCOPES
    assert flt.language_codes == ("",)
    assert dict(flt.fetched) == {}


async def test_registered_command_counts_an_ephemeral_command_by_default() -> None:
    bot = FakeBot("note", ephemeral=("note",))
    assert await filters.registered_command()(bot, make_message(text="/note")) is True


async def test_registered_command_without_ephemeral_leaves_out_an_ephemeral_command() -> None:
    flt, bot = (
        filters.registered_command(ephemeral=False),
        FakeBot("start", "note", ephemeral=("note",)),
    )
    assert await flt(bot, make_message(text="/note")) is False
    assert await flt(bot, make_message(text="/start")) is True


async def test_registered_command_reads_ephemeral_on_every_call() -> None:
    flt, bot = filters.registered_command(), FakeBot("note", ephemeral=("note",))
    assert await flt(bot, make_message(text="/note")) is True
    flt.ephemeral = False
    assert await flt(bot, make_message(text="/note")) is False
    assert bot.fetches == 1


async def test_registered_command_get_commands_keeps_the_lowercased_usernames_and_aliases() -> None:
    bot = FakeBot("start", username="This_Bot", usernames=("Alias_Bot",))
    commands = await filters.registered_command()._get_commands(bot)
    assert commands.usernames == frozenset({"this_bot", "alias_bot"})


async def test_registered_command_get_commands_has_no_usernames_while_the_client_has_no_me() -> (
    None
):
    bot = FakeBot("start")
    bot.me = None
    assert (await filters.registered_command()._get_commands(bot)).usernames == frozenset()


async def test_registered_command_get_commands_takes_the_new_usernames_after_a_restart() -> None:
    flt, bot = filters.registered_command(), FakeBot("start")
    await flt._get_commands(bot)
    bot.restart(username="renamed_bot")
    assert (await flt._get_commands(bot)).usernames == frozenset({"renamed_bot"})


def test_bot_commands_holds_me_then_the_usernames_then_the_regular_then_the_ephemeral_names() -> (
    None
):
    assert filters._BotCommands._fields == ("user_client", "usernames", "regular", "ephemeral")


@pytest.mark.parametrize(
    ("policy", "text", "passes"),
    [
        (CommandUsernamePolicy.REQUIRED, "/start", False),
        (CommandUsernamePolicy.REQUIRED, "/start@this_bot", True),
        (CommandUsernamePolicy.REQUIRED, "/start@other_bot", False),
        (None, "/start", True),
        (None, "/start@this_bot", True),
        (None, "/start@other_bot", True),
        (CommandUsernamePolicy.ANY_REQUIRED, "/start", False),
        (CommandUsernamePolicy.ANY_REQUIRED, "/start@this_bot", True),
        (CommandUsernamePolicy.ANY_REQUIRED, "/start@other_bot", True),
        (CommandUsernamePolicy.FORBIDDEN, "/start", True),
        (CommandUsernamePolicy.FORBIDDEN, "/start@this_bot", False),
        (CommandUsernamePolicy.FORBIDDEN, "/start@other_bot", False),
    ],
)
async def test_registered_command_username_policy_decides_which_username_passes(
    policy: CommandUsernamePolicy | None, text: str, passes: bool
) -> None:
    flt = filters.registered_command(username_policy=policy)
    assert await flt(FakeBot("start"), make_message(text=text)) is passes


@pytest.mark.parametrize(
    ("policy", "text"),
    [
        (CommandUsernamePolicy.REQUIRED, "/start"),
        (CommandUsernamePolicy.ANY_REQUIRED, "/start"),
        (CommandUsernamePolicy.FORBIDDEN, "/start@this_bot"),
    ],
)
async def test_registered_command_refuses_what_the_username_policy_forbids_without_fetching(
    policy: CommandUsernamePolicy, text: str
) -> None:
    bot = FakeBot("start")
    assert (
        await filters.registered_command(username_policy=policy)(bot, make_message(text=text))
        is False
    )
    assert bot.fetches == 0


def test_registered_command_default_scopes_are_the_four_that_need_no_chat_or_user() -> None:
    assert [type(scope) for scope in filters.registered_command.DEFAULT_SCOPES] == [
        BotCommandScopeDefault,
        BotCommandScopeAllPrivateChats,
        BotCommandScopeAllGroupChats,
        BotCommandScopeAllChatAdministrators,
    ]


async def test_registered_command_get_commands_fetches_every_scope_in_every_language() -> None:
    flt = filters.registered_command(
        scopes=(BotCommandScopeDefault(), BotCommandScopeAllGroupChats()),
        language_codes=("", "ar"),
    )
    bot = FakeBot("start")
    await flt._get_commands(bot)
    assert bot.calls == [
        ("BotCommandScopeDefault", ""),
        ("BotCommandScopeDefault", "ar"),
        ("BotCommandScopeAllGroupChats", ""),
        ("BotCommandScopeAllGroupChats", "ar"),
    ]


async def test_registered_command_counts_the_commands_of_every_scope_and_language() -> None:
    bot = FakeBot(
        scoped={
            ("BotCommandScopeAllGroupChats", ""): ("stats",),
            ("BotCommandScopeDefault", "ar"): ("ayuda",),
        }
    )
    assert await filters.registered_command()(bot, make_message(text="/stats")) is True
    assert await filters.registered_command()(bot, make_message(text="/ayuda")) is False
    flt = filters.registered_command(language_codes=("", "ar"))
    assert await flt(bot, make_message(text="/ayuda")) is True


async def test_registered_command_leaves_out_the_scopes_it_is_not_given() -> None:
    bot = FakeBot(scoped={("BotCommandScopeAllGroupChats", ""): ("stats",)})
    flt = filters.registered_command(scopes=(BotCommandScopeDefault(),))
    assert await flt(bot, make_message(text="/stats")) is False


# --- registered_command: a whole wait through the dispatcher ---------------------


class FakeRawUpdate:
    pass


async def dispatch(listener: MessageListener, msg: Message) -> list[Message]:
    """Run `msg` through a real `handler_worker` and return what the handlers received."""
    handled: list[Message] = []

    async def on_message(_: object, update: Message) -> None:
        handled.append(update)

    async def parser(*_: object) -> tuple[Message, type[MessageHandler]]:
        return msg, MessageHandler

    dispatcher = Dispatcher(
        SimpleNamespace(
            workers=0,
            executor=None,
            start_handler=None,
            stop_handler=None,
            no_updates=True,
            skip_updates=True,
        )
    )
    dispatcher.listeners[Message] = listener
    dispatcher.groups[0] = [MessageHandler(on_message)]
    dispatcher.update_parsers = {FakeRawUpdate: parser}
    dispatcher.updates_queue.put_nowait((FakeRawUpdate(), {}, {}))
    dispatcher.updates_queue.put_nowait(None)

    await asyncio.wait_for(dispatcher.handler_worker(), 1)

    return handled


async def test_inverted_strict_filter_ends_the_wait_and_reaches_the_handlers() -> None:
    listener = bind_listener(MessageListener(strict_filter=~filters.registered_command()))
    waiter = asyncio.ensure_future(listener.listen(MessageKey(chat_id=100, user_id=7)))
    await asyncio.sleep(0)
    msg = make_message(text="/start now", _client=FakeBot("start"))

    assert await dispatch(listener, msg) == [msg]
    with pytest.raises(ListenerRejected):
        await waiter


@pytest.mark.parametrize("text", ["my answer", "/help"])
async def test_inverted_strict_filter_gives_anything_else_to_the_wait(text: str) -> None:
    listener = bind_listener(MessageListener(strict_filter=~filters.registered_command()))
    waiter = asyncio.ensure_future(listener.listen(MessageKey(chat_id=100, user_id=7)))
    await asyncio.sleep(0)
    msg = make_message(text=text, _client=FakeBot("start"))

    assert await dispatch(listener, msg) == []
    assert await waiter is msg


async def test_inverted_filter_in_the_filters_of_a_strict_wait_ends_it() -> None:
    listener = bind_listener(MessageListener())
    flt = pyrogram_filters.text & ~filters.registered_command()
    waiter = asyncio.ensure_future(
        listener.listen(MessageKey(chat_id=100, user_id=7), filters=flt, strict=True)
    )
    await asyncio.sleep(0)
    msg = make_message(text="/start", _client=FakeBot("start"))

    assert await dispatch(listener, msg) == [msg]
    with pytest.raises(ListenerRejected):
        await waiter


async def test_a_wider_wait_with_filters_takes_a_command_a_strict_wait_rejected() -> None:
    listener = bind_listener(MessageListener(strict_filter=~filters.registered_command()))
    rejected = asyncio.ensure_future(listener.listen(MessageKey(chat_id=100, user_id=7)))
    wider = asyncio.ensure_future(
        listener.listen(MessageKey(chat_id=100), filters=pyrogram_filters.text)
    )
    await asyncio.sleep(0)
    msg = make_message(text="/start", _client=FakeBot("start"))

    assert await dispatch(listener, msg) == []
    with pytest.raises(ListenerRejected):
        await rejected
    assert await wider is msg


# --- module surface -------------------------------------------------------------


def test_all_lists_the_public_factories() -> None:
    assert filters.__all__ == (
        "endswith",
        "startswith",
        "equal",
        "split_text",
        "registered_command",
    )
