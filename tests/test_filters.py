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
from typing import Any, TYPE_CHECKING

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
    # maxsplit يمنع أجزاءً أكثر من القواعد، فالاختلاف الممكن هو أجزاء أقل فقط.
    # القاعدتان تقبلان أي جزء، فلا يرفض النص إلا فحص عدد الأجزاء
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


async def test_equal_callback_query_with_bytes_data_matches_its_utf8_text() -> None:
    cbq = make_callback_query(data=b"confirm")
    assert await matches(filters.equal("confirm"), cbq) is True
    assert await matches(filters.equal("cancel"), cbq) is False


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
async def test_bytes_pattern_matches_str_text(factory: Any, text: str, pattern: str) -> None:
    assert await matches(factory(pattern.encode()), make_message(text=text)) is True


@pytest.mark.parametrize(("factory", "text", "pattern"), TEXT_FILTERS)
async def test_str_pattern_matches_bytes_data(factory: Any, text: str, pattern: str) -> None:
    cbq = make_callback_query(data=text.encode())
    assert await matches(factory(pattern), cbq) is True


@pytest.mark.parametrize(("factory", "text", "pattern"), TEXT_FILTERS)
async def test_bytes_pattern_matches_bytes_data(factory: Any, text: str, pattern: str) -> None:
    cbq = make_callback_query(data=text.encode())
    assert await matches(factory(pattern.encode()), cbq) is True


async def test_str_pattern_matches_non_utf8_bytes_data() -> None:
    cbq = make_callback_query(data=b"cb:\xff")
    assert await matches(filters.startswith("cb:"), cbq) is True
    assert await matches(filters.endswith(b"\xff"), cbq) is True
    assert await matches(filters.equal(b"cb:\xff"), cbq) is True


@pytest.mark.parametrize("factory", [filters.endswith, filters.startswith, filters.equal])
async def test_non_utf8_bytes_pattern_never_matches_str_text(factory: Any) -> None:
    # `b"\xff"` لا يُفك بـ UTF-8، فلا يدخل في أنماط `str`
    assert await matches(factory(b"\xff"), make_message(text="\xff")) is False


@pytest.mark.parametrize("factory", [filters.endswith, filters.startswith, filters.equal])
@pytest.mark.parametrize("update", [make_message(text=None), make_callback_query(data=b"")])
async def test_empty_text_never_matches(factory: Any, update: Message | CallbackQuery) -> None:
    assert await matches(factory("x", b"x", "", b""), update) is False


@pytest.mark.parametrize(
    ("factory", "text"),
    [(filters.endswith, "b"), (filters.startswith, "b"), (filters.equal, "b")],
)
async def test_mixed_nested_containers_match_both_kinds(factory: Any, text: str) -> None:
    flt = factory(["a", (b"b", [None, 1])], b"")
    assert await matches(flt, make_message(text=text)) is True
    assert await matches(flt, make_callback_query(data=b"b")) is True
    assert await matches(flt, make_message(text="c")) is False


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
