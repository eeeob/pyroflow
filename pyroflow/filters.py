"""Custom text-matching filters, in the same style as `pyrogram.filters`.

Each factory returns a `pyrogram.filters.Filter`, so it composes with `&`, `|`
and `~` and registers like any Pyrogram filter. The text of a `Message` is its
`text`, falling back to its `caption`; the text of a `CallbackQuery` is its
`data`. A `str` pattern matches a `str` text only, and a `bytes` pattern `bytes`
data only; Pyrogram leaves `data` as `bytes` only when it is not valid UTF-8.
"""

from __future__ import annotations as _annotations

import re
from typing import Protocol, AnyStr, TYPE_CHECKING
from enum import Enum, EnumMeta as EnumType

from pyrogram.filters import Filter, create
from pytrove import (
    iter_flat_cont,
    is_container,
    extract_pyro_update_text,
)

from .utils import call_maybe_async

if TYPE_CHECKING:
    from pytrove.typings import MaybeCoroutineCallable, NestedContainer

    from .client import Client
    from .types import Message, CallbackQuery as Query


class _TextMatch(Protocol):
    """A text test called with patterns of the text's own kind."""

    def __call__(self, text: AnyStr, patterns: tuple[AnyStr, ...], /) -> bool:
        """Return whether `text` matches `patterns`."""
        ...


def _normalize_rule(
    rule: MaybeCoroutineCallable[[str], bool] | NestedContainer[str] | EnumType | re.Pattern[str],
) -> frozenset[str] | re.Pattern[str] | MaybeCoroutineCallable[[str], bool]:
    """Turn one `split_text` rule into the form its matcher checks.

    Args:
        rule: A compiled pattern or a callable (kept as is), an `Enum` class
            (its non-empty `str` values), or a string or nested container of
            strings (its non-empty `str` items).

    Returns:
        The pattern or callable itself, or a frozenset of the allowed strings.

    Raises:
        ValueError: If the rule resolves to no strings.
        TypeError: If the rule is none of the supported kinds.

    Example:
        >>> sorted(_normalize_rule(["a", ("b", "")]))
        ['a', 'b']
    """
    if isinstance(rule, re.Pattern):
        return rule

    if isinstance(rule, type) and issubclass(rule, Enum):
        strings = frozenset(e.value for e in rule if isinstance(e.value, str) and e.value)
    elif is_container(rule) or isinstance(rule, str):
        strings = frozenset(v for v in iter_flat_cont(rule) if isinstance(v, str) and v)
    elif callable(rule):
        return rule  # ty: ignore[invalid-return-type]  # `is_container` does not narrow, so ty keeps callable containers in the union
    else:
        msg = f"Unsupported split_text rule: {type(rule)!r}"
        raise TypeError(msg)

    if not strings:
        msg = "split_text rules must not be empty"
        raise ValueError(msg)

    return strings


def _text_filter(
    name: str,
    texts: tuple[NestedContainer[str | bytes], ...],
    match: _TextMatch,
) -> Filter:
    """Create a filter that matches the update's text against `texts` with `match`.

    Each pattern matches a text of its own kind only. Empty values and other
    types are ignored, and an empty text never matches.

    Args:
        name: The name of the filter's class.
        texts: The patterns, as given to the public filter.
        match: Called as `match(text, patterns)` with patterns of the text's
            own kind; returns whether the text matches.

    Returns:
        The filter.
    """
    str_view: set[str] = set()
    bytes_view: set[bytes] = set()

    for text in iter_flat_cont(texts):
        if not text:
            continue

        if isinstance(text, str):
            str_view.add(text)
        elif isinstance(text, bytes):
            bytes_view.add(text)

    str_texts, bytes_texts = tuple(str_view), tuple(bytes_view)

    async def caller(_: Filter, __: Client, update: Message | Query) -> bool:
        """Return whether the update's text matches the patterns of its own kind."""
        text = extract_pyro_update_text(update)

        if isinstance(text, bytes):
            return match(text, bytes_texts)

        return match(text, str_texts)

    return create(caller, name)


def endswith(*texts: NestedContainer[str | bytes]) -> Filter:
    """Match when the update's text ends with any of `texts`.

    Args:
        *texts: Strings or bytes, or nested containers of them.

    Returns:
        The filter.

    Example:
        >>> import asyncio
        >>> from pyrogram.types import Message
        >>> asyncio.run(endswith("world", ["!"])(None, Message(id=1, text="hello world")))
        True
        >>> asyncio.run(endswith(b"world")(None, Message(id=1, text="hello world")))
        False
    """
    return _text_filter("EndsWith", texts, lambda text, patterns: text.endswith(patterns))


def startswith(*texts: NestedContainer[str | bytes]) -> Filter:
    r"""Match when the update's text starts with any of `texts`.

    Args:
        *texts: Strings or bytes, or nested containers of them.

    Returns:
        The filter.

    Example:
        >>> import asyncio
        >>> from pyrogram.types import CallbackQuery, Message
        >>> asyncio.run(startswith("/start")(None, Message(id=1, text="/start 42")))
        True
        >>> query = CallbackQuery(id="1", from_user=None, chat_instance="", data=b"cb:\xff")
        >>> asyncio.run(startswith("cb:")(None, query))
        False
        >>> asyncio.run(startswith(b"cb:")(None, query))
        True
    """
    return _text_filter("StartsWith", texts, lambda text, patterns: text.startswith(patterns))


def equal(*texts: NestedContainer[str | bytes]) -> Filter:
    """Match when the update's text is exactly one of `texts`.

    Args:
        *texts: Strings or bytes, or nested containers of them.

    Returns:
        The filter.

    Example:
        >>> import asyncio
        >>> from pyrogram.types import Message
        >>> asyncio.run(equal("hi", "hello")(None, Message(id=1, text="hello world")))
        False
        >>> asyncio.run(equal(b"hello")(None, Message(id=1, text="hello")))
        False
    """
    return _text_filter("Equal", texts, lambda text, patterns: text in patterns)


def split_text(
    *rules: MaybeCoroutineCallable[[str], bool] | NestedContainer[str] | EnumType | re.Pattern[str],
    strip: bool = False,
    separator: str | None = None,
) -> Filter:
    r"""Split the update's text by `separator` and match each part against its `rules` entry.

    The update matches only when the text splits into exactly one part per
    rule and every part satisfies its rule. A synchronous callable rule runs
    in a thread on the client's executor. Callback data left as `bytes` never
    matches.

    Args:
        *rules: One per part: a string, a container of strings or an `Enum`
            class (its values), which the part must equal one of; a compiled
            `re.Pattern`, which must `fullmatch` the part; or a callable,
            called as `rule(part)`, which must return truthy.
        strip: Whether to strip whitespace from each part before matching.
        separator: What to split the text on, at most `len(rules) - 1`
            times. `None` (the default) is only valid with exactly one rule:
            the whole text is then a single part.

    Returns:
        The filter.

    Raises:
        ValueError: If no rules are given, a rule resolves to an empty set of
            strings, or more than one rule is given without a `separator`.
        TypeError: If a rule is neither a container, a string, an `Enum`
            class, a compiled pattern, nor a callable.

    Example:
        >>> import asyncio
        >>> from pyrogram.types import Message
        >>> f = split_text("/ban", ["user", "chat"], separator=" ")
        >>> asyncio.run(f(None, Message(id=1, text="/ban chat")))
        True
        >>> import re
        >>> f = split_text("/ban", re.compile(r"\d+"), separator=" ")
        >>> asyncio.run(f(None, Message(id=1, text="/ban 42")))
        True
        >>> split_text("/ban", str.isdigit)
        Traceback (most recent call last):
        ...
        ValueError: separator is required when split_text is given more than one rule
    """
    normalized_rules = tuple(map(_normalize_rule, rules))

    if not normalized_rules:
        msg = "split_text filter must be given at least one rule"
        raise ValueError(msg)

    if len(normalized_rules) > 1 and separator is None:
        msg = "separator is required when split_text is given more than one rule"
        raise ValueError(msg)

    async def caller(_: Filter, client: Client, update: Message | Query) -> bool:
        """Return whether the update's text splits into parts that each satisfy their rule."""
        text = extract_pyro_update_text(update)

        if not text or isinstance(text, bytes):
            return False

        parts = (
            [text]
            if separator is None
            else text.split(separator, maxsplit=len(normalized_rules) - 1)
        )

        if strip:
            parts = list(map(str.strip, parts))

        if len(parts) != len(normalized_rules):
            return False

        for part, rule in zip(parts, normalized_rules, strict=True):
            if isinstance(rule, frozenset):
                if part not in rule:
                    return False
            elif isinstance(rule, re.Pattern):
                if rule.fullmatch(part) is None:
                    return False
            elif not await call_maybe_async(rule, part, executor=client.executor):
                return False

        return True

    return create(caller, "SplitText")


__all__ = (
    "endswith",
    "startswith",
    "equal",
    "split_text",
)
