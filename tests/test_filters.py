"""pyroflow.filters: endswith / startswith / equal / split_text.

Each filter is exercised through Filter.__call__(client, update) — the exact
path pyrogram.handlers.Handler.check() uses — rather than by reaching into
the module's private helpers, so these pin the actual contract other code
relies on.
"""

import inspect
from enum import Enum
from types import SimpleNamespace

import pytest

from pyroflow import filters

from .conftest import make_callback_query, make_message


FAKE_CLIENT = SimpleNamespace(executor=None)


async def matches(flt, update) -> bool:
    return await flt(FAKE_CLIENT, update)


# --- endswith / startswith / equal: matching --------------------------------


async def test_endswith_matches_message_text():
    msg = make_message(text="hello world")
    assert await matches(filters.endswith("world"), msg) is True


async def test_endswith_rejects_non_matching_text():
    msg = make_message(text="hello world")
    assert await matches(filters.endswith("mars"), msg) is False


async def test_startswith_matches_message_text():
    msg = make_message(text="hello world")
    assert await matches(filters.startswith("hello"), msg) is True


async def test_equal_matches_exact_text_only():
    msg = make_message(text="hello")
    assert await matches(filters.equal("hello"), msg) is True
    assert await matches(filters.equal("hello world"), msg) is False


async def test_equal_matches_any_of_several_texts():
    msg = make_message(text="b")
    assert await matches(filters.equal("a", "b", "c"), msg) is True


# --- text extraction: Message.caption fallback, CallbackQuery.data ---------


async def test_falls_back_to_caption_when_text_is_absent():
    msg = make_message(text=None, caption="a photo of world")
    assert await matches(filters.endswith("world"), msg) is True


async def test_text_takes_priority_over_caption():
    msg = make_message(text="hello", caption="world")
    assert await matches(filters.equal("hello"), msg) is True
    assert await matches(filters.equal("world"), msg) is False


async def test_message_with_neither_text_nor_caption_matches_nothing():
    msg = make_message(text=None, caption=None)
    assert await matches(filters.equal(""), msg) is False
    assert await matches(filters.startswith(""), msg) is False


async def test_callback_query_matches_on_data():
    cbq = make_callback_query(data="confirm")
    assert await matches(filters.equal("confirm"), cbq) is True


async def test_callback_query_with_non_str_data_matches_nothing():
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


async def test_flattens_nested_containers_of_texts():
    msg = make_message(text="b")
    assert await matches(filters.equal(["a", "b"], "c"), msg) is True


async def test_ignores_non_string_and_empty_entries():
    msg = make_message(text="")
    # "" is filtered out of the candidate set, so an empty-text update must
    # not match just because "" was one of the arguments.
    assert await matches(filters.equal("", 123, None, "x"), msg) is False


# --- filters run inline, not via the executor thread pool ------------------


def test_filters_are_recognized_as_coroutine_functions():
    """Handler.check() inspects `filter.__call__` to decide whether to await
    inline or dispatch to a thread; these are cheap string ops and must take
    the inline path."""
    flt = filters.equal("x")
    assert inspect.iscoroutinefunction(flt.__call__)


# --- split_text: matching ----------------------------------------------------


async def test_split_text_single_rule_no_separator():
    """A rule is a string/container/Enum/plain `(part: str) -> bool` callable
    — not a Filter. filters.equal()/endswith()/etc. return Filter objects
    shaped for (client, update), which is a different, incompatible contract;
    passing one here would be a misuse of the API, not a case to exercise."""
    msg = make_message(text="hello")
    flt = filters.split_text(("hello", "hi"))
    assert await matches(flt, msg) is True


async def test_split_text_multiple_rules_with_separator():
    msg = make_message(text="/ban 42")
    flt = filters.split_text("/ban", lambda p: p.isdigit(), separator=" ")
    assert await matches(flt, msg) is True


async def test_split_text_fails_when_part_count_mismatches():
    msg = make_message(text="/ban 42 extra")
    flt = filters.split_text("/ban", lambda p: p.isdigit(), separator=" ")
    # maxsplit=1 caps at 2 parts, so this becomes ["/ban", "42 extra"]
    assert await matches(flt, msg) is False


async def test_split_text_strip_trims_each_part():
    msg = make_message(text="/ban  42 ")
    flt = filters.split_text("/ban", lambda p: p == "42", separator=" ", strip=True)
    assert await matches(flt, msg) is True


async def test_split_text_container_rule_checks_membership():
    msg = make_message(text="/ban 42")
    flt = filters.split_text("/ban", ("41", "42", "43"), separator=" ")
    assert await matches(flt, msg) is True


async def test_split_text_enum_rule_matches_by_value():
    class Command(Enum):
        BAN = "ban"
        KICK = "kick"

    msg = make_message(text="ban")
    flt = filters.split_text(Command)
    assert await matches(flt, msg) is True


async def test_split_text_async_callable_rule():
    async def is_digits(part: str) -> bool:
        return part.isdigit()

    msg = make_message(text="/ban 42")
    flt = filters.split_text("/ban", is_digits, separator=" ")
    assert await matches(flt, msg) is True


async def test_split_text_empty_text_matches_nothing():
    msg = make_message(text=None, caption=None)
    flt = filters.split_text(filters.equal("x"))
    assert await matches(flt, msg) is False


# --- split_text: construction-time validation -------------------------------


def test_split_text_requires_at_least_one_rule():
    with pytest.raises(ValueError):
        filters.split_text()


def test_split_text_requires_a_separator_for_multiple_rules():
    with pytest.raises(ValueError):
        filters.split_text("a", "b")


def test_split_text_rejects_an_empty_rule():
    with pytest.raises(ValueError):
        filters.split_text([], separator=" ")


def test_split_text_rejects_an_unsupported_rule_type():
    with pytest.raises(TypeError):
        filters.split_text(123)
