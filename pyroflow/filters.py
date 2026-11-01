"""Custom text-matching filters, in the same style as `pyrogram.filters`.

Each factory returns a `pyrogram.filters.Filter`, so it composes with `&`, `|`
and `~` and registers like any Pyrogram filter. The text of a `Message` is its
`text`, falling back to its `caption`; the text of a `CallbackQuery` is its
`data`.
"""

from __future__ import annotations as _annotations

from typing import NoReturn, TYPE_CHECKING
from enum import Enum, EnumMeta as EnumType

from pyrogram.filters import Filter, create
from pytrove import (
    iter_flat_cont,
    is_container,
    maybe_awaitable,
    extract_pyro_update_text,
    to_coroutine,
)

if TYPE_CHECKING:
    from pytrove.typings import MaybeCoroutineCallable, NestedContainer

    from .client import Client
    from .types import Message, CallbackQuery as Query


def _raise(exc: Exception) -> NoReturn:
    """`raise` as an expression, for use inside a comprehension."""
    raise exc


def endswith(*texts: NestedContainer[str]) -> Filter:
    """Match when the update's text ends with any of `texts`.

    Args:
        *texts: Strings, or nested containers of them; empty strings and
            non-strings are ignored.

    Returns:
        The filter.

    Example:
        >>> import asyncio
        >>> from pyrogram.types import Message
        >>> asyncio.run(endswith("world", ["!"])(None, Message(id=1, text="hello world")))
        True
    """
    flat_texts = tuple({t for t in iter_flat_cont(texts) if isinstance(t, str) and t})
    caller = to_coroutine(
        lambda _, __, update: extract_pyro_update_text(update).endswith(flat_texts)
    )

    return create(caller, "EndsWith")


def startswith(*texts: NestedContainer[str]) -> Filter:
    """Match when the update's text starts with any of `texts`.

    Args:
        *texts: Strings, or nested containers of them; empty strings and
            non-strings are ignored.

    Returns:
        The filter.

    Example:
        >>> import asyncio
        >>> from pyrogram.types import Message
        >>> asyncio.run(startswith("/start")(None, Message(id=1, text="/start 42")))
        True
    """
    flat_texts = tuple({t for t in iter_flat_cont(texts) if isinstance(t, str) and t})
    caller = to_coroutine(
        lambda _, __, update: extract_pyro_update_text(update).startswith(flat_texts)
    )

    return create(caller, "StartsWith")


def equal(*texts: NestedContainer[str]) -> Filter:
    """Match when the update's text is exactly one of `texts`.

    Args:
        *texts: Strings, or nested containers of them; empty strings and
            non-strings are ignored.

    Returns:
        The filter.

    Example:
        >>> import asyncio
        >>> from pyrogram.types import Message
        >>> asyncio.run(equal("hi", "hello")(None, Message(id=1, text="hello world")))
        False
    """
    flat_texts = frozenset(t for t in iter_flat_cont(texts) if isinstance(t, str) and t)
    caller = to_coroutine(lambda _, __, update: extract_pyro_update_text(update) in flat_texts)

    return create(caller, "Equal")


def split_text(
    *rules: MaybeCoroutineCallable[[str], bool] | NestedContainer[str] | EnumType,
    strip: bool = False,
    separator: str | None = None,
) -> Filter:
    """Split the update's text by `separator` and match each part against its `rules` entry.

    The update matches only when the text splits into exactly one part per
    rule and every part satisfies its rule. A synchronous callable rule runs
    in a thread on the client's executor. Callback data left as `bytes` never
    matches when a `separator` is given.

    Args:
        *rules: One per part: a string, a container of strings or an `Enum`
            class (its values), which the part must equal one of; or a
            callable, called as `rule(part)`, which must return truthy.
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
            class, nor a callable.

    Example:
        >>> import asyncio
        >>> from pyrogram.types import Message
        >>> f = split_text("/ban", ["user", "chat"], separator=" ")
        >>> asyncio.run(f(None, Message(id=1, text="/ban chat")))
        True
        >>> split_text("/ban", str.isdigit)
        Traceback (most recent call last):
        ...
        ValueError: separator is required when split_text is given more than one rule
    """
    if not rules:
        msg = "split_text filter must be given at least one rule"
        raise ValueError(msg)

    normalized_rules = tuple(
        frozenset(e.value for e in rule if isinstance(e.value, str) and e.value)
        if isinstance(rule, type) and issubclass(rule, Enum)
        else frozenset(v for v in iter_flat_cont(rule) if isinstance(v, str) and v)
        if is_container(rule) or isinstance(rule, str)
        else rule
        if callable(rule)
        else _raise(TypeError(f"Unsupported split_text rule: {type(rule)!r}"))
        for rule in rules
    )

    for rule in normalized_rules:
        if not rule:
            msg = "split_text rules must not be empty"
            raise ValueError(msg)

    if len(normalized_rules) > 1 and separator is None:
        msg = "separator is required when split_text is given more than one rule"
        raise ValueError(msg)

    async def caller(_: Filter, client: Client, update: Message | Query) -> bool:
        """Return whether the update's text splits into parts that each satisfy their rule."""
        text = extract_pyro_update_text(update)

        if not text:
            return False

        if separator is None:
            parts = [text]
        elif isinstance(text, bytes):
            # بيانات callback التي لا تُفك بـ UTF-8 تبقى `bytes`، ولا تنقسم بفاصل نصي
            return False
        else:
            parts = text.split(separator, maxsplit=len(normalized_rules) - 1)

        if strip:
            parts = [p.strip() for p in parts]

        if len(parts) != len(normalized_rules):
            return False

        for part, rule in zip(parts, normalized_rules, strict=True):
            if isinstance(rule, frozenset):
                if part not in rule:
                    return False
            elif not await maybe_awaitable(rule, part, executor=client.executor, log_exc=False):
                return False

        return True

    return create(caller, "SplitText")


__all__ = (
    "endswith",
    "startswith",
    "equal",
    "split_text",
)
