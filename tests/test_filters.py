"""pyroflow.filters: endswith / startswith / equal / split_text.

Each filter is exercised through Filter.__call__(client, update) — the exact
path pyrogram.handlers.Handler.check() uses — rather than by reaching into
the module's private helpers, so these pin the actual contract other code
relies on.
"""

from __future__ import annotations as _annotations

import inspect
import threading
from concurrent.futures import ThreadPoolExecutor
from enum import Enum
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from pyroflow import filters

if TYPE_CHECKING:
    from pyrogram.filters import Filter
    from pyrogram.types import CallbackQuery, Message

from .conftest import make_callback_query, make_message


FAKE_CLIENT = SimpleNamespace(executor=None)


async def matches(flt: Filter, update: Message | CallbackQuery) -> bool:
    return await flt(FAKE_CLIENT, update)


# --- endswith / startswith / equal: matching --------------------------------


async def test_endswith_matches_message_text() -> None:
    msg = make_message(text="hello world")
    assert await matches(filters.endswith("world"), msg) is True


async def test_endswith_rejects_non_matching_text() -> None:
    msg = make_message(text="hello world")
    assert await matches(filters.endswith("mars"), msg) is False


async def test_startswith_matches_message_text() -> None:
    msg = make_message(text="hello world")
    assert await matches(filters.startswith("hello"), msg) is True


async def test_equal_matches_exact_text_only() -> None:
    msg = make_message(text="hello")
    assert await matches(filters.equal("hello"), msg) is True
    assert await matches(filters.equal("hello world"), msg) is False


async def test_equal_matches_any_of_several_texts() -> None:
    msg = make_message(text="b")
    assert await matches(filters.equal("a", "b", "c"), msg) is True


# --- text extraction: Message.caption fallback, CallbackQuery.data ---------


async def test_falls_back_to_caption_when_text_is_absent() -> None:
    msg = make_message(text=None, caption="a photo of world")
    assert await matches(filters.endswith("world"), msg) is True


async def test_text_takes_priority_over_caption() -> None:
    msg = make_message(text="hello", caption="world")
    assert await matches(filters.equal("hello"), msg) is True
    assert await matches(filters.equal("world"), msg) is False


async def test_message_with_neither_text_nor_caption_matches_nothing() -> None:
    msg = make_message(text=None, caption=None)
    assert await matches(filters.equal(""), msg) is False
    assert await matches(filters.startswith(""), msg) is False


async def test_callback_query_matches_on_data() -> None:
    cbq = make_callback_query(data="confirm")
    assert await matches(filters.equal("confirm"), cbq) is True


async def test_callback_query_with_non_str_data_matches_nothing() -> None:
    """A bad client can send bytes in `data`; a text comparison against bytes
    is meaningless, so it must be treated as no text rather than raising.

    Uses endswith(), not equal(): `bytes != str` makes an equal() check false
    either way, str or not, so it would not actually prove the bytes were
    filtered out. `bytes.endswith(str_tuple)` raises TypeError if the raw
    bytes ever reach it unfiltered — this fails loudly instead of passing by
    coincidence if the str-only guard regresses."""
    cbq = make_callback_query(data=b"\x00\x01")
    assert await matches(filters.endswith("x"), cbq) is False


# --- argument flattening and filtering --------------------------------------


async def test_flattens_nested_containers_of_texts() -> None:
    msg = make_message(text="b")
    assert await matches(filters.equal(["a", "b"], "c"), msg) is True


async def test_ignores_non_string_and_empty_entries() -> None:
    msg = make_message(text="")
    # "" is filtered out of the candidate set, so an empty-text update must
    # not match just because "" was one of the arguments.
    assert await matches(filters.equal("", 123, None, "x"), msg) is False


# --- filters run inline, not via the executor thread pool ------------------


def test_filters_are_recognized_as_coroutine_functions() -> None:
    """Handler.check() inspects `filter.__call__` to decide whether to await
    inline or dispatch to a thread; these are cheap string ops and must take
    the inline path."""
    flt = filters.equal("x")
    assert inspect.iscoroutinefunction(flt.__call__)


# --- split_text: matching ----------------------------------------------------


async def test_split_text_single_rule_no_separator() -> None:
    """A rule is a string/container/Enum/plain `(part: str) -> bool` callable
    — not a Filter. filters.equal()/endswith()/etc. return Filter objects
    shaped for (client, update), which is a different, incompatible contract;
    passing one here would be a misuse of the API, not a case to exercise."""
    msg = make_message(text="hello")
    flt = filters.split_text(("hello", "hi"))
    assert await matches(flt, msg) is True


async def test_split_text_multiple_rules_with_separator() -> None:
    msg = make_message(text="/ban 42")
    flt = filters.split_text("/ban", lambda p: p.isdigit(), separator=" ")
    assert await matches(flt, msg) is True


async def test_split_text_fails_when_part_count_mismatches() -> None:
    msg = make_message(text="/ban 42 extra")
    flt = filters.split_text("/ban", lambda p: p.isdigit(), separator=" ")
    # maxsplit=1 caps at 2 parts, so this becomes ["/ban", "42 extra"]
    assert await matches(flt, msg) is False


async def test_split_text_strip_trims_each_part() -> None:
    msg = make_message(text="/ban  42 ")
    flt = filters.split_text("/ban", lambda p: p == "42", separator=" ", strip=True)
    assert await matches(flt, msg) is True


async def test_split_text_container_rule_checks_membership() -> None:
    msg = make_message(text="/ban 42")
    flt = filters.split_text("/ban", ("41", "42", "43"), separator=" ")
    assert await matches(flt, msg) is True


async def test_split_text_enum_rule_matches_by_value() -> None:
    class Command(Enum):
        BAN = "ban"
        KICK = "kick"

    msg = make_message(text="ban")
    flt = filters.split_text(Command)
    assert await matches(flt, msg) is True


async def test_split_text_async_callable_rule() -> None:
    async def is_digits(part: str) -> bool:
        return part.isdigit()

    msg = make_message(text="/ban 42")
    flt = filters.split_text("/ban", is_digits, separator=" ")
    assert await matches(flt, msg) is True


async def test_split_text_empty_text_matches_nothing() -> None:
    msg = make_message(text=None, caption=None)
    flt = filters.split_text(filters.equal("x"))
    assert await matches(flt, msg) is False


# --- split_text: construction-time validation -------------------------------


def test_split_text_requires_at_least_one_rule() -> None:
    with pytest.raises(ValueError):
        filters.split_text()


def test_split_text_requires_a_separator_for_multiple_rules() -> None:
    with pytest.raises(ValueError):
        filters.split_text("a", "b")


def test_split_text_rejects_an_empty_rule() -> None:
    with pytest.raises(ValueError):
        filters.split_text([], separator=" ")


def test_split_text_rejects_an_unsupported_rule_type() -> None:
    with pytest.raises(TypeError):
        filters.split_text(123)


# --- _raise --------------------------------------------------------------------


def test_raise_raises_the_given_exception_instance() -> None:
    exc = KeyError("boom")
    with pytest.raises(KeyError) as info:
        filters._raise(exc)
    assert info.value is exc


# --- filter identity and composition -------------------------------------------


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


async def test_filters_compose_with_and_or_invert() -> None:
    msg = make_message(text="hello world")
    hello, mars = filters.startswith("hello"), filters.endswith("mars")
    assert await matches(hello & mars, msg) is False
    assert await matches(hello | mars, msg) is True
    assert await matches(~mars, msg) is True


async def test_non_text_update_raises() -> None:
    with pytest.raises(ValueError, match="doesn't work with"):
        await matches(filters.equal("x"), SimpleNamespace(text="x"))  # type: ignore[arg-type]


# --- endswith -----------------------------------------------------------------


async def test_endswith_matches_any_of_several_and_nested_texts() -> None:
    msg = make_message(text="hello world")
    assert await matches(filters.endswith("mars", ["venus", ("world",)]), msg) is True


async def test_endswith_with_only_ignored_texts_matches_nothing() -> None:
    msg = make_message(text="hello world")
    assert await matches(filters.endswith("", 1, None), msg) is False


async def test_endswith_matches_callback_query_data() -> None:
    assert await matches(filters.endswith("_ok"), make_callback_query(data="pay_ok")) is True


# --- startswith ---------------------------------------------------------------


async def test_startswith_rejects_non_matching_text() -> None:
    msg = make_message(text="hello world")
    assert await matches(filters.startswith("world"), msg) is False


async def test_startswith_matches_any_of_several_and_nested_texts() -> None:
    msg = make_message(text="/start 42")
    assert await matches(filters.startswith("/help", ["/start"]), msg) is True


async def test_startswith_with_only_ignored_texts_matches_nothing() -> None:
    msg = make_message(text="hello")
    assert await matches(filters.startswith("", 0), msg) is False


async def test_startswith_falls_back_to_caption() -> None:
    msg = make_message(text=None, caption="hello there")
    assert await matches(filters.startswith("hello"), msg) is True


@pytest.mark.xfail(
    strict=True,
    reason="bytes callback data reaches bytes.startswith(str tuple) and raises "
    "TypeError instead of not matching, pyroflow/filters.py:77",
)
async def test_startswith_callback_query_with_bytes_data_matches_nothing() -> None:
    cbq = make_callback_query(data=b"\x00\x01")
    assert await matches(filters.startswith("x"), cbq) is False


# --- equal --------------------------------------------------------------------


async def test_equal_with_no_texts_matches_nothing() -> None:
    assert await matches(filters.equal(), make_message(text="x")) is False


async def test_equal_is_case_sensitive() -> None:
    assert await matches(filters.equal("Hello"), make_message(text="hello")) is False


async def test_equal_callback_query_with_bytes_data_matches_nothing() -> None:
    cbq = make_callback_query(data=b"confirm")
    assert await matches(filters.equal("confirm"), cbq) is False


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
    # maxsplit=0 لقاعدة واحدة، فيبقى النص جزءًا واحدًا رغم وجود الفاصل
    flt = filters.split_text("a b c", separator=" ")
    assert await matches(flt, make_message(text="a b c")) is True


async def test_split_text_too_few_parts_matches_nothing() -> None:
    flt = filters.split_text("/ban", ("42",), separator=" ")
    assert await matches(flt, make_message(text="/ban")) is False


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


async def test_split_text_sync_callable_rule_runs_on_the_client_executor() -> None:
    threads: list[str] = []

    def is_digits(part: str) -> bool:
        threads.append(threading.current_thread().name)
        return part.isdigit()

    flt = filters.split_text(is_digits)
    with ThreadPoolExecutor(thread_name_prefix="filters-test") as executor:
        client = SimpleNamespace(executor=executor)
        assert await flt(client, make_message(text="42")) is True
        assert await flt(client, make_message(text="4x")) is False
    assert threads and all(name.startswith("filters-test") for name in threads)


async def test_split_text_callable_rule_exception_propagates() -> None:
    def broken(part: str) -> bool:
        msg = "rule failed"
        raise RuntimeError(msg)

    flt = filters.split_text(broken)
    with pytest.raises(RuntimeError, match="rule failed"):
        await matches(flt, make_message(text="x"))


async def test_split_text_matches_callback_query_data() -> None:
    flt = filters.split_text("page", str.isdigit, separator=":")
    assert await matches(flt, make_callback_query(data="page:3")) is True


async def test_split_text_bytes_data_with_separator_matches_nothing() -> None:
    called: list[object] = []
    flt = filters.split_text("page", called.append, separator=":")
    assert await matches(flt, make_callback_query(data=b"page:3")) is False
    assert called == []


async def test_split_text_bytes_data_without_separator_is_one_part() -> None:
    parts: list[object] = []

    async def record(part: object) -> bool:
        parts.append(part)
        return True

    flt = filters.split_text(record)
    assert await matches(flt, make_callback_query(data=b"\x00\x01")) is True
    assert parts == [b"\x00\x01"]


# --- module surface -------------------------------------------------------------


def test_all_lists_the_public_factories() -> None:
    assert filters.__all__ == ("endswith", "startswith", "equal", "split_text")
