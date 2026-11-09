"""Tests for `pyroflow.keyboards.callback_data`: `CallbackData`."""

from __future__ import annotations as _annotations

import dataclasses
import enum
import re
from collections import namedtuple
from types import SimpleNamespace
from typing import Any, NamedTuple, cast

import pytest
from pyrogram.filters import Filter
from pyrogram.types import InlineKeyboardButton

from pyroflow.keyboards import CallbackData, CallbackFields, parsed
from pyroflow.keyboards import callback_data as module

from ..conftest import make_callback_query, make_message


class Item(CallbackFields):
    id: Any = parsed(str)
    action: str


class One(CallbackFields):
    a: Any = parsed(str)


class WithDefault(CallbackFields):
    id: int = parsed(int)
    action: str = "view"


class Empty(CallbackFields):
    pass


class OddSelf(CallbackFields):
    self: int = parsed(int)


class Labeled(CallbackFields):
    text: str


class Color(enum.Enum):
    RED = "red"


class Level(enum.IntEnum):
    HIGH = 3


class Perm(enum.Flag):
    READ = 1
    WRITE = 2


class Bits(enum.IntFlag):
    A = 1


Pair = namedtuple("Pair", "id action")  # noqa: PYI024  # the form `from_fields` is built for

WithPage = namedtuple("WithPage", "id page", defaults=[1])  # noqa: PYI024


class Slotted(CallbackFields, slots=True, frozen=True):
    id: int = parsed(int)
    page: int = parsed(int, default=1)


class KeywordOnly(CallbackFields, kw_only=True):
    id: int = parsed(int)


class Typed(CallbackFields):
    id: int = parsed(int)
    color: Color = parsed(Color)
    active: bool = parsed(lambda text: text == "True")
    page: int = parsed(int, default=1)
    note: str = ""


CLIENT = SimpleNamespace(executor=None)


@pytest.fixture
def item() -> CallbackData:
    return CallbackData("item", Item)


def test_module_all() -> None:
    assert module.__all__ == ("CallbackData", "CallbackFields", "parsed")


# --- the fields -------------------------------------------------------------


def test_fields_leave_a_value_without_a_function_as_text() -> None:
    class Hinted(CallbackFields):
        id: int

    assert CallbackData("h", Hinted).unpack("h:7") == Hinted("7")


def test_fields_take_a_text_field_whose_type_is_not_a_string() -> None:
    fields = type("Real", (CallbackFields,), {"__annotations__": {"a": str}})

    assert tuple(fields(a="x")) == ("x",)


def test_fields_take_the_options_of_a_dataclass() -> None:
    value = Slotted(1)

    assert not hasattr(value, "__dict__")
    with pytest.raises(dataclasses.FrozenInstanceError):
        value.id = 2


def test_fields_refuse_an_option_of_no_dataclass() -> None:
    with pytest.raises(TypeError, match="nope"):

        class Bad(CallbackFields, nope=True):
            a: str


def test_fields_with_slots_can_use_super() -> None:
    class WithSuper(CallbackFields, slots=True):
        a: str

        def parent_repr(self) -> str:
            return super().__repr__()

        def own_class(self) -> type:
            return __class__

    value = WithSuper("x")

    assert value.own_class() is WithSuper
    assert "object at" in value.parent_repr()


def test_fields_take_their_own_options_when_inherited() -> None:
    class Child(WithDefault, slots=True):
        extra: str = ""

    assert Child(1, "a", "b").extra == "b"
    assert "__slots__" in vars(Child)


def test_fields_iterate_in_field_order() -> None:
    assert tuple(Item(action="buy", id="7")) == ("7", "buy")


# --- the constructor --------------------------------------------------------


@pytest.mark.parametrize("schema", [dict, "id", Item(1, "a"), lambda id: (id,)])
def test_constructor_refuses_what_is_not_a_fields_class(schema: Any) -> None:
    with pytest.raises(TypeError, match="CallbackFields class"):
        CallbackData("p", schema)


@pytest.mark.parametrize(("value", "passes"), [("x", True), ("y", False)])
async def test_a_field_can_be_named_exact(value: str, passes: bool) -> None:
    class Named(CallbackFields):
        exact: str

    data = CallbackData("p", Named)
    query = make_callback_query(data="p:x")

    assert data.pack(exact="x") == "p:x"
    assert await data.filter(exact=value)(CLIENT, query) is passes
    assert await data.filter_equal(exact=value)(CLIENT, query) is passes


@pytest.mark.parametrize("sep", ["", "::"])
def test_constructor_refuses_a_separator_of_other_than_one_character(sep: str) -> None:
    with pytest.raises(ValueError, match="one character"):
        CallbackData("p", One, sep=sep)


@pytest.mark.parametrize(
    ("prefix", "sep"), [("", ":"), ("a:b", ":"), ("a|b", "|"), ("x" * 65, ":"), ("é" * 33, ":")]
)
def test_constructor_refuses_a_bad_prefix(prefix: str, sep: str) -> None:
    with pytest.raises(ValueError, match="prefix must be"):
        CallbackData(prefix, One, sep=sep)


def test_constructor_keeps_what_it_is_given() -> None:
    data = CallbackData("p", Item, sep="|")

    assert (data.prefix, data.schema, data.fields, data.sep) == ("p", Item, ("id", "action"), "|")


def test_callback_data_has_no_instance_dict(item: CallbackData) -> None:
    assert not hasattr(item, "__dict__")


# --- pack -------------------------------------------------------------------


def test_pack_joins_the_values_in_field_order(item: CallbackData) -> None:
    assert item.pack(action="buy", id=7) == "item:7:buy"


def test_pack_takes_the_values_in_order(item: CallbackData) -> None:
    assert item.pack(7, "buy") == "item:7:buy"


def test_pack_uses_the_separator() -> None:
    assert CallbackData("p", Item, sep="|").pack(id="x", action="y") == "p|x|y"


def test_pack_uses_the_defaults_of_the_schema() -> None:
    assert CallbackData("p", WithDefault).pack(id=1) == "p:1:view"


def test_pack_uses_the_default_of_a_function_field() -> None:
    assert CallbackData("t", Typed).pack(1, Color.RED, False) == "t:1:red:False:1:"


@pytest.mark.parametrize(
    ("value", "text"),
    [(Perm.READ, "1"), (Perm.READ | Perm.WRITE, "3"), (Perm(0), "0"), (Bits.A, "1")],
)
async def test_a_flag_goes_in_by_its_value(value: enum.Enum, text: str) -> None:
    data = CallbackData("p", One)
    query = make_callback_query(data=f"p:{text}")

    assert data.pack(a=value) == f"p:{text}"
    assert await data.filter(a=value)(CLIENT, query) is True
    assert await data.filter_equal(a=value)(CLIENT, query) is True


def test_pack_of_no_fields_is_the_prefix() -> None:
    assert CallbackData("menu", Empty).pack() == "menu"


@pytest.mark.parametrize("values", [{"id": 1}, {"id": 1, "action": "x", "other": 2}, {}])
def test_pack_refuses_missing_or_unknown_names(
    item: CallbackData, values: dict[str, object]
) -> None:
    with pytest.raises(TypeError):
        item.pack(**values)


def test_pack_refuses_a_value_with_the_separator(item: CallbackData) -> None:
    with pytest.raises(ValueError, match="must not contain"):
        item.pack(id="1:2", action="x")


@pytest.mark.parametrize(("value", "text"), [(Color.RED, "red"), (Level.HIGH, "3")])
def test_pack_writes_an_enum_by_its_value(value: enum.Enum, text: str) -> None:
    assert CallbackData("p", One).pack(a=value) == f"p:{text}"


@pytest.mark.parametrize(("value", "size"), [("x" * 62, 64), ("é" * 31, 64)])
def test_pack_takes_up_to_64_bytes(value: str, size: int) -> None:
    assert len(CallbackData("p", One).pack(a=value).encode()) == size


@pytest.mark.parametrize("value", ["x" * 63, "é" * 32])
def test_pack_refuses_more_than_64_bytes(value: str) -> None:
    with pytest.raises(ValueError, match="limited to 64 bytes"):
        CallbackData("p", One).pack(a=value)


def test_pack_takes_a_field_named_self() -> None:
    assert CallbackData("p", OddSelf).pack(self=1) == "p:1"


# --- button -----------------------------------------------------------------


def test_button_holds_the_packed_data(item: CallbackData) -> None:
    button = item.button("Buy", id=7, action="buy")

    assert isinstance(button, InlineKeyboardButton)
    assert (button.text, button.callback_data) == ("Buy", "item:7:buy")


def test_button_takes_a_field_named_text() -> None:
    assert CallbackData("p", Labeled).button("L", text="v").callback_data == "p:v"


# --- unpack -----------------------------------------------------------------


@pytest.mark.parametrize("data", ["item:7:buy", b"item:7:buy"])
def test_unpack_reads_str_and_bytes(item: CallbackData, data: str | bytes) -> None:
    assert item.unpack(data) == Item("7", "buy")


def test_unpack_reads_what_pack_built(item: CallbackData) -> None:
    assert item.unpack(item.pack(id="", action="x")) == Item("", "x")


def test_unpack_reads_every_field_by_its_function() -> None:
    data = CallbackData("t", Typed)

    assert data.unpack(data.pack(7, Color.RED, True, 2, "n")) == Typed(7, Color.RED, True, 2, "n")


def test_unpack_builds_a_class_with_slots() -> None:
    data = CallbackData("s", Slotted)

    assert data.unpack(data.pack(id=7)) == Slotted(7, 1)


def test_unpack_builds_a_class_of_keyword_only_fields() -> None:
    assert CallbackData("k", KeywordOnly).unpack("k:7") == KeywordOnly(id=7)


def test_pack_refuses_values_in_order_for_keyword_only_fields() -> None:
    with pytest.raises(TypeError):
        CallbackData("k", KeywordOnly).pack(7)


def test_unpack_dict_holds_what_unpack_reads() -> None:
    assert CallbackData("t", Typed).unpack_dict("t:7:red:True:2:n") == {
        "id": 7,
        "color": Color.RED,
        "active": True,
        "page": 2,
        "note": "n",
    }


def test_unpack_dict_refuses_another_shape(item: CallbackData) -> None:
    with pytest.raises(ValueError, match="Not callback data"):
        item.unpack_dict("other:7:buy")


def test_unpack_lets_the_error_of_a_function_through() -> None:
    with pytest.raises(ValueError, match="invalid literal"):
        CallbackData("t", Typed).unpack("t:x:red:True:1:")


@pytest.mark.parametrize("data", ["other:7:buy", "item:7", "item:7:buy:more", "item", ""])
def test_unpack_refuses_another_shape(item: CallbackData, data: str) -> None:
    with pytest.raises(ValueError, match="Not callback data"):
        item.unpack(data)


def test_unpack_refuses_bytes_that_do_not_decode(item: CallbackData) -> None:
    with pytest.raises(UnicodeDecodeError):
        item.unpack(b"\xff")


# --- filter -----------------------------------------------------------------


def test_filter_is_a_pyrogram_filter(item: CallbackData) -> None:
    assert isinstance(item.filter(), Filter)


@pytest.mark.parametrize(
    ("values", "passes"),
    [
        ({}, True),
        ({"action": "buy"}, True),
        ({"id": 7}, True),
        ({"id": "7", "action": "buy"}, True),
        ({"action": "sell"}, False),
        ({"id": 8, "action": "buy"}, False),
    ],
)
async def test_filter_compares_the_given_values_as_text(
    item: CallbackData, values: dict[str, object], passes: bool
) -> None:
    query = make_callback_query(data="item:7:buy")

    assert await item.filter(**values)(CLIENT, query) is passes


async def test_filter_matches_an_empty_value(item: CallbackData) -> None:
    assert await item.filter(id="")(CLIENT, make_callback_query(data="item::buy")) is True


async def test_filter_treats_a_value_as_literal_text(item: CallbackData) -> None:
    assert await item.filter(id=".")(CLIENT, make_callback_query(data="item:7:buy")) is False


@pytest.mark.parametrize(("value", "text"), [(Color.RED, "red"), (Level.HIGH, "3")])
async def test_filter_compares_an_enum_by_its_value(value: enum.Enum, text: str) -> None:
    query = make_callback_query(data=f"p:{text}")

    assert await CallbackData("p", One).filter(a=value)(CLIENT, query) is True


@pytest.mark.parametrize(
    "data",
    [None, b"\xff", b"item:7:buy", "", "other:7:buy"],
)
async def test_filter_refuses_data_of_another_layout(
    item: CallbackData, data: str | bytes | None
) -> None:
    assert await item.filter()(CLIENT, make_callback_query(data=data)) is False


async def test_filter_refuses_an_update_that_is_not_a_callback_query(item: CallbackData) -> None:
    assert await item.filter()(CLIENT, make_message(text="item:7:buy")) is False


@pytest.mark.parametrize(("action", "passes"), [("buy", True), ("sell", False)])
async def test_filter_takes_the_values_in_order(
    item: CallbackData, action: str, passes: bool
) -> None:
    query = make_callback_query(data="item:7:buy")

    assert await item.filter(7, action)(CLIENT, query) is passes


def test_filter_refuses_values_in_order_that_do_not_fit(item: CallbackData) -> None:
    with pytest.raises(TypeError):
        item.filter(7)


def test_filter_refuses_unknown_names_when_created(item: CallbackData) -> None:
    with pytest.raises(TypeError, match="Not fields"):
        item.filter(nope=1)


@pytest.mark.parametrize(
    ("data", "passes"),
    [
        ("item:7:buy", True),
        ("item:7:buy:extra", True),
        ("item:7:", True),
        ("item:7", True),
        ("item:8:buy", False),
        ("item", False),
    ],
)
async def test_filter_needs_only_the_fields_it_names(
    item: CallbackData, data: str, passes: bool
) -> None:
    assert await item.filter(id=7)(CLIENT, make_callback_query(data=data)) is passes


async def test_filter_refuses_data_that_ends_before_a_field_it_names(item: CallbackData) -> None:
    assert await item.filter(action="buy")(CLIENT, make_callback_query(data="item:7")) is False


# --- filter_equal -----------------------------------------------------------


@pytest.mark.parametrize(
    ("data", "passes"),
    [
        ("item:7:buy", True),
        ("item:7:buy:extra", False),
        ("item:7:", False),
        ("item:7", False),
        ("item:8:buy", False),
        ("other:7:buy", False),
        (None, False),
        (b"item:7:buy", False),
    ],
)
async def test_filter_equal_passes_only_what_pack_builds(
    item: CallbackData, data: str | bytes | None, passes: bool
) -> None:
    query = make_callback_query(data=data)

    assert await item.filter_equal(id=7, action="buy")(CLIENT, query) is passes


async def test_filter_equal_takes_the_values_in_order(item: CallbackData) -> None:
    assert await item.filter_equal(7, "buy")(CLIENT, make_callback_query(data="item:7:buy")) is True


async def test_filter_equal_fills_the_defaults() -> None:
    query = make_callback_query(data="p:1:view")

    assert await CallbackData("p", WithDefault).filter_equal(id=1)(CLIENT, query) is True


async def test_filter_equal_compares_an_enum_by_its_value() -> None:
    query = make_callback_query(data="p:3")

    assert await CallbackData("p", One).filter_equal(a=Level.HIGH)(CLIENT, query) is True


async def test_filter_equal_refuses_an_update_that_is_not_a_callback_query(
    item: CallbackData,
) -> None:
    update = make_message(text="item:7:buy")

    assert await item.filter_equal(id=7, action="buy")(CLIENT, update) is False


@pytest.mark.parametrize("values", [{}, {"id": 1}, {"id": 1, "action": "x", "other": 2}])
def test_filter_equal_refuses_missing_or_unknown_names_when_created(
    item: CallbackData, values: dict[str, object]
) -> None:
    with pytest.raises(TypeError):
        item.filter_equal(**values)


def test_filter_equal_refuses_what_pack_refuses_when_created(item: CallbackData) -> None:
    with pytest.raises(ValueError, match="must not contain"):
        item.filter_equal(id="1:2", action="x")


# --- from_fields ------------------------------------------------------------


def test_from_fields_builds_a_layout_of_text_fields() -> None:
    data = CallbackData.from_fields("item", Pair)

    assert data.fields == ("id", "action")
    assert issubclass(cast("type", data.schema), CallbackFields)
    assert data.pack(7, "buy") == data.pack(id=7, action="buy") == "item:7:buy"
    assert data.unpack("item:7:buy").id == "7"
    assert data.unpack_dict("item:7:buy") == {"id": "7", "action": "buy"}


def test_from_fields_uses_the_separator() -> None:
    assert CallbackData.from_fields("p", Pair, sep="|").pack("a", "b") == "p|a|b"


def test_from_fields_takes_no_fields() -> None:
    assert CallbackData.from_fields("menu", NamedTuple("Menu", [])).pack() == "menu"


def test_from_fields_takes_a_typed_named_tuple_and_keeps_the_text() -> None:
    data = CallbackData.from_fields("t", NamedTuple("T", [("id", int)]))

    assert data.pack(id=1) == "t:1"
    assert data.unpack("t:1").id == "1"


def test_from_fields_keeps_the_defaults() -> None:
    assert CallbackData.from_fields("d", WithPage).pack(id=7) == "d:7:1"


def test_from_fields_takes_the_options_of_a_dataclass() -> None:
    value = CallbackData.from_fields("p", Pair, slots=True, frozen=True).unpack("p:x:y")

    assert not hasattr(value, "__dict__")
    with pytest.raises(dataclasses.FrozenInstanceError):
        value.id = "z"


async def test_from_fields_filters_like_a_class() -> None:
    data = CallbackData.from_fields("item", Pair)
    query = make_callback_query(data="item:7:buy")

    assert await data.filter(action="buy")(CLIENT, query) is True
    assert await data.filter_equal(7, "buy")(CLIENT, query) is True


def test_from_fields_refuses_an_option_of_no_dataclass() -> None:
    with pytest.raises(TypeError, match="nope"):
        CallbackData.from_fields("p", Pair, nope=True)


@pytest.mark.parametrize(
    "schema",
    [dict, "id", tuple, Pair("a", "b"), lambda id: (id,), type("Fake", (), {"_fields": ("a",)})],
)
def test_from_fields_refuses_what_is_not_a_named_tuple_class(schema: Any) -> None:
    with pytest.raises(TypeError, match="namedtuple class"):
        CallbackData.from_fields("p", schema)


def test_from_fields_refuses_a_bad_prefix() -> None:
    with pytest.raises(ValueError, match="prefix must be"):
        CallbackData.from_fields("", Pair)


# --- filter_rules -----------------------------------------------------------


@pytest.mark.parametrize(
    ("rules", "passes"),
    [
        ({"action": "buy"}, True),
        ({"action": ["buy", "sell"]}, True),
        ({"action": ["sell", "rent"]}, False),
        ({"id": re.compile(r"\d+")}, True),
        ({"id": re.compile(r"[a-z]+")}, False),
        ({"id": str.isdigit, "action": ["buy"]}, True),
        ({"id": str.isalpha}, False),
    ],
)
async def test_filter_rules_applies_a_rule_per_field(
    item: CallbackData, rules: dict[str, Any], passes: bool
) -> None:
    assert (
        await item.filter_rules(**rules)(CLIENT, make_callback_query(data="item:7:buy")) is passes
    )


async def test_filter_rules_takes_an_enum_class() -> None:
    data = CallbackData("p", One)

    assert await data.filter_rules(a=Color)(CLIENT, make_callback_query(data="p:red")) is True
    assert await data.filter_rules(a=Color)(CLIENT, make_callback_query(data="p:blue")) is False


async def test_filter_rules_awaits_an_async_rule(item: CallbackData) -> None:
    async def rule(value: str) -> bool:
        return value == "buy"

    query = make_callback_query(data="item:7:buy")

    assert await item.filter_rules(action=rule)(CLIENT, query) is True


async def test_filter_rules_leaves_a_field_not_named_free(item: CallbackData) -> None:
    query = make_callback_query(data="item:anything at all:buy")

    assert await item.filter_rules(action="buy")(CLIENT, query) is True


@pytest.mark.parametrize("rule", [re.compile(".+"), lambda _: True])
async def test_filter_rules_refuses_extra_parts_even_with_a_loose_last_rule(
    item: CallbackData, rule: Any
) -> None:
    query = make_callback_query(data="item:7:buy:more")

    assert await item.filter_rules(action=rule)(CLIENT, query) is False


async def test_filter_rules_refuses_a_message(item: CallbackData) -> None:
    assert await item.filter_rules()(CLIENT, make_message(text="item:7:buy")) is False


def test_filter_rules_refuses_unknown_names_when_created(item: CallbackData) -> None:
    with pytest.raises(TypeError, match="Not fields"):
        item.filter_rules(nope="a")


def test_filter_rules_refuses_a_rule_of_no_supported_kind(item: CallbackData) -> None:
    with pytest.raises(TypeError, match="Unsupported"):
        item.filter_rules(id=7)
