"""`CallbackData`: a typed layout for the `callback_data` of inline buttons."""

from __future__ import annotations as _annotations

import dataclasses
import re
import sys
from enum import Enum
from typing import Any, Final, Generic, ParamSpec, cast, overload, TYPE_CHECKING

from pyrogram.filters import create
from pyrogram.types import CallbackQuery, InlineKeyboardButton
from pytrove.typings import _P, _T, _VT

from ..filters import split_text

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from enum import EnumMeta as EnumType

    from pyrogram.filters import Filter
    from pytrove.typings import NestedContainer

    from ..client import Client
    from ..typings import MaybeAwaitableCallable

if sys.version_info >= (3, 11):
    from typing import dataclass_transform
elif TYPE_CHECKING:
    from typing_extensions import dataclass_transform
else:

    def dataclass_transform(**_: object) -> Callable[[type], type]:
        """Leave a class as it is on Python 3.10, where only a type checker reads this."""
        return lambda cls: cls


_MAX_BYTES: Final[int] = 64
"""The size Telegram limits `callback_data` to."""

_ANY: Final[re.Pattern[str]] = re.compile(".*", re.DOTALL)
"""The rule of a field that a filter does not name."""

_FieldsP = ParamSpec("_FieldsP")
"""The fields of the `namedtuple` given to `CallbackData.from_fields`."""


def parsed(convert: Callable[[str], _VT], *, default: Any = dataclasses.MISSING) -> _VT:
    """Declare a field of `CallbackFields` with the function that reads it.

    Args:
        convert: Turns the text of the field into its value.
        default: The value `pack` uses when the field is not given.

    Returns:
        The field, typed as what `convert` returns.
    """
    return dataclasses.field(default=default, metadata={"convert": convert})


@dataclass_transform(field_specifiers=(parsed,))
class _FieldsMeta(type):
    """Make each class built on `CallbackFields` a dataclass, with its class line's options."""

    def __new__(
        mcs, name: str, bases: tuple[type, ...], namespace: dict[str, Any], **options: Any
    ) -> Any:
        """Build the class, and make it a dataclass unless it already is one."""
        cls = super().__new__(mcs, name, bases, namespace)

        # `slots=True` rebuilds the dataclass through this method.
        if bases and "__dataclass_fields__" not in namespace:
            built = dataclasses.dataclass(cast("Any", cls), **options)

            # `slots=True` returns a new class, which `super()` must point to.
            if "__classcell__" in namespace:
                namespace["__classcell__"].cell_contents = built

            return built

        return cls


class CallbackFields(metaclass=_FieldsMeta):
    """The base of the class holding the fields of a `CallbackData`.

    Each subclass becomes a dataclass, and takes the options of `dataclass` on
    its class line, such as `slots=True`. The type of a field is only a hint:
    a field stays text unless it is written with `parsed`.
    """

    __slots__ = ()

    def __iter__(self: Any) -> Iterator[object]:
        """Return the values in field order."""
        return (getattr(self, field.name) for field in dataclasses.fields(self))


class CallbackData(Generic[_P, _T]):
    """A layout of `callback_data`: a prefix and the fields of a class.

    The fields of `schema` show as type hints on `pack` and `button`, and
    `unpack` returns `schema`, with the fields written with `parsed` converted.

    Args:
        prefix: Marks the data as this layout's.
        schema: The `CallbackFields` class whose fields are the values.
        sep: The one character that joins the parts.

    Raises:
        TypeError: If `schema` is not a `CallbackFields` class.
        ValueError: If `sep` is not one character, or `prefix` is empty,
            contains `sep` or is over 64 bytes.

    Example:
        >>> import asyncio
        >>> from pyrogram.types import User
        >>> class Item(CallbackFields):
        ...     id: int = parsed(int)
        ...     action: str
        >>> item = CallbackData("item", Item)
        >>> item.pack(id=7, action="buy")
        'item:7:buy'
        >>> item.button("Buy", id=7, action="buy").callback_data
        'item:7:buy'
        >>> item.unpack(b"item:7:buy")
        Item(id=7, action='buy')
        >>> query = CallbackQuery(id="1", from_user=User(id=1), data="item:7:buy")
        >>> asyncio.run(item.filter(action="buy")(None, query))
        True
        >>> asyncio.run(item.filter_equal(7, "sell")(None, query))
        False
        >>> asyncio.run(item.filter_rules(action=["sell", "rent"])(None, query))
        False
    """

    __slots__ = ("prefix", "schema", "fields", "converters", "sep")

    def __init__(self, prefix: str, schema: Callable[_P, _T], *, sep: str = ":") -> None:
        """Keep the layout; see the class docstring."""
        if not isinstance(schema, type) or not issubclass(schema, CallbackFields):
            msg = f"schema must be a CallbackFields class: {schema!r}"
            raise TypeError(msg)

        fields = dataclasses.fields(cast("Any", schema))
        names = tuple(field.name for field in fields)

        if len(sep) != 1:
            msg = f"sep must be one character: {sep!r}"
            raise ValueError(msg)

        if not prefix or sep in prefix or len(prefix.encode()) > _MAX_BYTES:
            msg = f"The prefix must be 1 to {_MAX_BYTES} bytes without {sep!r}: {prefix!r}"
            raise ValueError(msg)

        self.prefix = prefix
        """Marks the data as this layout's."""
        self.schema: Callable[_P, Any] = cast("Any", schema)
        """The `CallbackFields` class whose fields are the values."""
        self.fields = names
        """The names of the values."""
        self.converters = tuple(field.metadata.get("convert", str) for field in fields)
        """What reads each value from its text, in field order."""
        self.sep = sep
        """What joins the parts."""

    @staticmethod
    def from_fields(
        prefix: str, schema: Callable[_FieldsP, _VT], /, *, sep: str = ":", **options: Any
    ) -> CallbackData[_FieldsP, _VT]:
        """Create a layout from a `namedtuple`, without writing a class.

        The names of `schema` show as type hints. It only names the fields:
        they are built as a dataclass, and every field is text.

        Args:
            prefix: As in `CallbackData`.
            schema: The `namedtuple` class naming the fields; its defaults are
                kept.
            sep: As in `CallbackData`.
            **options: The options of `dataclass`, such as `slots=True`.

        Returns:
            The layout.

        Raises:
            TypeError: If `schema` is not a `namedtuple` class, or an option is
                not one of `dataclass`.
            ValueError: As in `CallbackData`.

        Example:
            >>> from collections import namedtuple
            >>> menu = CallbackData.from_fields("menu", namedtuple("Menu", "page tab"), slots=True)
            >>> menu.pack(page=2, tab="a")
            'menu:2:a'
            >>> menu.unpack("menu:2:a")
            Menu(page='2', tab='a')
        """
        names = getattr(schema, "_fields", None)
        defaults = getattr(schema, "_field_defaults", None)

        if names is None or defaults is None or not isinstance(schema, type):
            msg = f"schema must be a namedtuple class: {schema!r}"
            raise TypeError(msg)

        namespace = {"__annotations__": dict.fromkeys(names, str), **defaults}
        fields: Any = _FieldsMeta(schema.__name__, (CallbackFields,), namespace, **options)
        return CallbackData(prefix, fields, sep=sep)

    def pack(self, /, *args: _P.args, **kwargs: _P.kwargs) -> str:
        """Build the `callback_data` of the values, as `schema` takes them.

        Args:
            *args: The values, in field order.
            **kwargs: The values, by field name. An `Enum` member goes in by
                its value, and anything else with `str`.

        Returns:
            The data.

        Raises:
            TypeError: If a field is missing or a name is not a field.
            ValueError: If a value contains the separator, or the data is over
                64 bytes.
        """
        sep = self.sep.encode()
        data = self.prefix.encode()

        for value in self.schema(*args, **kwargs):
            part = str(value.value if isinstance(value, Enum) else value).encode()

            if sep in part:
                msg = f"A value must not contain {self.sep!r}: {value!r}"
                raise ValueError(msg)

            data += sep + part

            if len(data) > _MAX_BYTES:
                msg = f"callback_data is limited to {_MAX_BYTES} bytes: {data!r}"
                raise ValueError(msg)

        return data.decode()

    def button(self, text: str, /, *args: _P.args, **kwargs: _P.kwargs) -> InlineKeyboardButton:
        """Build a button whose `callback_data` is what `pack` builds.

        Args:
            text: The label of the button.
            *args: As in `pack`.
            **kwargs: As in `pack`.

        Returns:
            The button.

        Raises:
            TypeError: As in `pack`.
            ValueError: As in `pack`.
        """
        return InlineKeyboardButton(text, callback_data=self.pack(*args, **kwargs))

    def unpack(self, data: str | bytes) -> _T:
        """Read the values out of `callback_data`.

        Args:
            data: What `pack` built, or the same as `bytes`.

        Returns:
            `schema`, each field written with `parsed` read by its function
            and the others left as text.

        Raises:
            ValueError: If the prefix or the number of parts does not match, or
                `bytes` do not decode.
            Exception: Whatever the function of a field raises on its text.
        """
        text = data.decode() if isinstance(data, bytes) else data
        prefix, *parts = text.split(self.sep)

        if prefix != self.prefix or len(parts) != len(self.fields):
            msg = f"Not callback data of {self.prefix!r}: {text!r}"
            raise ValueError(msg)

        make: Callable[..., _T] = self.schema
        return make(
            **{
                name: read(part)
                for name, read, part in zip(self.fields, self.converters, parts, strict=True)
            }
        )

    def unpack_dict(self, data: str | bytes) -> dict[str, Any]:
        """Read the values out of `callback_data` into a `dict`.

        Args:
            data: As in `unpack`.

        Returns:
            What `unpack` reads, by field name.

        Raises:
            ValueError: As in `unpack`.
            Exception: As in `unpack`.
        """
        return dict(zip(self.fields, cast("Any", self.unpack(data)), strict=True))

    @overload
    def filter(self, /, *args: _P.args, **kwargs: _P.kwargs) -> Filter: ...

    @overload
    def filter(self, /, **values: object) -> Filter: ...

    def filter(self, /, *args: Any, **values: Any) -> Filter:
        """Create a filter on the fields given, allowing anything else in the data.

        The fields of `schema` show as type hints. A type checker can only
        check values passed in order, since naming some fields is also allowed.

        Args:
            *args: The values in field order, as `pack` takes them, which give
                every field a value.
            **values: The fields to match, compared as text, an `Enum` member
                by its value.

        Returns:
            The filter. An update that is not a `CallbackQuery`, has another
            prefix or lacks a field matched does not pass.

        Raises:
            TypeError: If a name is not a field, or `args` do not fit `schema`.
        """
        if args:
            values = dict(zip(self.fields, self.schema(*args, **values), strict=True))

        unknown = values.keys() - set(self.fields)

        if unknown:
            msg = f"Not fields of {self.prefix!r}: {sorted(unknown)}"
            raise TypeError(msg)

        wanted = [
            None
            if name not in values
            else str(value.value if isinstance(value := values[name], Enum) else value)
            for name in self.fields
        ]
        needed = max((i for i, want in enumerate(wanted, 1) if want is not None), default=0)

        async def caller(_: Filter, __: Client, update: object) -> bool:
            """Return whether the update is a callback query holding the values."""
            if not isinstance(update, CallbackQuery) or not isinstance(update.data, str):
                return False

            prefix, *parts = update.data.split(self.sep)

            if prefix != self.prefix or len(parts) < needed:
                return False

            return all(
                want is None or part == want for part, want in zip(parts, wanted, strict=False)
            )

        return create(caller, "CallbackData")

    def filter_equal(self, /, *args: _P.args, **kwargs: _P.kwargs) -> Filter:
        """Create a filter passing only data equal to what `pack` builds.

        Args:
            *args: As in `pack`.
            **kwargs: As in `pack`.

        Returns:
            The filter. An update that is not a `CallbackQuery` does not pass.

        Raises:
            TypeError: As in `pack`.
            ValueError: As in `pack`.
        """
        expected = self.pack(*args, **kwargs)

        async def caller(_: Filter, __: Client, update: object) -> bool:
            """Return whether the update is a callback query with exactly this data."""
            return isinstance(update, CallbackQuery) and update.data == expected

        return create(caller, "CallbackData")

    def filter_rules(
        self,
        /,
        **rules: MaybeAwaitableCallable[[str], bool]
        | NestedContainer[str]
        | EnumType
        | re.Pattern[str],
    ) -> Filter:
        """Create a filter whose fields each take a rule, as `filters.split_text` does.

        Args:
            **rules: Per field: a string, a container of strings or an `Enum`
                class of text values, which the value must equal one of; a
                compiled `re.Pattern`, which must `fullmatch` it; or a callable,
                called with it, which must return truthy. A field not named can
                be anything.

        Returns:
            The filter. An update that is not a `CallbackQuery`, or has data
            that does not fit, does not pass.

        Raises:
            TypeError: If a name is not a field, or a rule is of no supported
                kind.
            ValueError: If a rule resolves to no strings.
        """
        unknown = rules.keys() - set(self.fields)

        if unknown:
            msg = f"Not fields of {self.prefix!r}: {sorted(unknown)}"
            raise TypeError(msg)

        matcher = split_text(
            self.prefix, *(rules.get(name, _ANY) for name in self.fields), separator=self.sep
        )

        async def caller(_: Filter, client: Client, update: object) -> bool:
            """Return whether the update is a callback query of this layout passing the rules."""
            # `split_text` keeps a separator in its last part, and reads messages too.
            if (
                not isinstance(update, CallbackQuery)
                or not isinstance(update.data, str)
                or update.data.count(self.sep) != len(self.fields)
            ):
                return False

            return await matcher(client, update)

        return create(caller, "CallbackData")


__all__ = ("CallbackData", "CallbackFields", "parsed")
