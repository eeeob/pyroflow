"""Static type tests for `pyroflow.keyboards.callback_data`."""

from __future__ import annotations as _annotations

from typing import TYPE_CHECKING, Any, NamedTuple

if TYPE_CHECKING:
    from collections import namedtuple

    from typing_extensions import assert_type

    from pyrogram.filters import Filter
    from pyrogram.types import InlineKeyboardButton

    from pyroflow.keyboards import CallbackData, CallbackFields, parsed

    class _Item(CallbackFields):
        id: int = parsed(int)
        action: str = "view"

    class _Slotted(CallbackFields, slots=True, frozen=True):
        id: int = parsed(int)

    def _check_fields_options() -> None:
        data = CallbackData("item", _Slotted)
        assert_type(data.pack(id=1), str)
        assert_type(data.unpack("item:1").id, int)
        data.pack(id="1")  # ty: ignore[invalid-argument-type]  # `id` is an `int`

    def _check_from_fields() -> None:
        data = CallbackData.from_fields(
            "item",
            namedtuple("Item", "id action"),  # noqa: PYI024  # the form `from_fields` is built for
            sep="|",
            slots=True,
        )
        assert_type(data.pack(id=1, action="buy"), str)
        assert_type(data.pack(1, "buy"), str)
        assert_type(data.unpack_dict("item:1:buy"), dict[str, Any])
        data.pack(id=1)  # ty: ignore[missing-argument]  # `action` has no default
        data.pack(id=1, action="buy", nope=2)  # ty: ignore[unknown-argument]  # there is no field `nope`
        print(data.unpack("item:1:buy").nope)  # ty: ignore[unresolved-attribute]  # there is no field `nope`

        typed = CallbackData.from_fields("item", NamedTuple("Item", [("id", int), ("action", str)]))
        assert_type(typed.unpack("item:1:buy").id, int)
        typed.pack(id="1", action="buy")  # ty: ignore[invalid-argument-type]  # `id` is an `int`

    def _check_callback_data() -> None:
        data = CallbackData("item", _Item)
        assert_type(data.pack(id=1), str)
        assert_type(data.pack(1, "buy"), str)
        assert_type(data.button("Buy", id=1, action="buy"), InlineKeyboardButton)
        assert_type(data.unpack(b"a:1"), _Item)
        assert_type(data.unpack_dict(b"a:1"), dict[str, Any])
        assert_type(data.unpack(b"a:1").id, int)
        assert_type(data.unpack(b"a:1").action, str)
        assert_type(data.filter(action="buy"), Filter)
        assert_type(data.filter_equal(id=1), Filter)
        assert_type(data.filter_equal(1, "buy"), Filter)
        data.filter_equal(id="1")  # ty: ignore[invalid-argument-type]  # `id` is an `int`
        data.filter_equal()  # ty: ignore[missing-argument]  # `id` has no default
        assert_type(data.filter(id=1, action="buy"), Filter)
        assert_type(data.filter(1, "buy"), Filter)
        data.filter("1", "buy")  # ty: ignore[invalid-argument-type]  # `id` is an `int`
        assert_type(data.filter_rules(id=str.isdigit, action=["buy"]), Filter)
        data.pack(id="1")  # ty: ignore[invalid-argument-type]  # `id` is an `int`
        data.pack()  # ty: ignore[missing-argument]  # `id` has no default
        data.pack(id=1, nope=2)  # ty: ignore[unknown-argument]  # there is no field `nope`
        data.button("Buy", id="1")  # ty: ignore[invalid-argument-type]  # `id` is an `int`
        data.unpack(1)  # ty: ignore[invalid-argument-type]  # `unpack` takes `str` or `bytes`
        CallbackData("item", "id")  # ty: ignore[invalid-argument-type]  # the schema is a `CallbackFields` class
