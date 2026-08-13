"""Custom text-matching filters, in the same style as ``pyrogram.filters``.

Each of :func:`endswith`, :func:`startswith`, :func:`equal` and
:func:`split_text` returns a :class:`~pyrogram.filters.Filter`, so they
compose with pyrogram's own filters via ``&``/``|``/``~`` and register the
same way::

    @app.on_message(filters.equal("hi", "hello"))
    async def handler(client, message): ...

"Text" here means whichever field carries the update's user-typed content:
:class:`~pyrogram.types.Message` uses ``.text`` (falling back to
``.caption``), :class:`~pyrogram.types.CallbackQuery` uses ``.data``.
"""

from typing import Optional, Union, NoReturn, Callable, Coroutine, TYPE_CHECKING
from enum import Enum, EnumMeta as EnumType
from functools import wraps 

from pyrogram.filters import Filter, create

from .types import Message, CallbackQuery as Query
from .utils import iter_flat_cont, is_container, maybe_awaitable
from .utils.typings import MaybeCoroutineCallable, NestedContainer

if TYPE_CHECKING:
    from .client import Client

def _to_coroutine(func) -> Callable[..., Coroutine]:
    """Wrap a cheap synchronous predicate as a coroutine function.

    ``pyrogram.handlers.Handler.check()`` decides how to run a filter by
    checking ``inspect.iscoroutinefunction(filter.__call__)``: an async
    filter is awaited inline on the event loop, a sync one is dispatched to
    the client's executor thread pool. The predicates built below are a
    handful of string comparisons — cheap enough that the thread-pool round
    trip would cost more than the check itself — so they are wrapped to run
    inline instead of going through the executor.
    """

    @wraps(func)
    async def wrapper(*args, **kw):
        return func(*args, **kw)

    return wrapper

def _raise(exc: Exception) -> NoReturn:
    """``raise`` as an expression, for use inside a comprehension."""
    raise exc

def _extract_text(update: Union[Message, Query]) -> str:
    """
    The text-like payload of a ``Message`` or ``CallbackQuery``, or ``""``
    if it has none.

    ``Message`` uses ``.text``, falling back to ``.caption`` — matching how
    pyrogram's own built-in ``filters.text`` treats messages. ``CallbackQuery``
    uses ``.data``, but only if it is a ``str``: a bad client can send
    arbitrary bytes there, and a text comparison against bytes makes no sense.

    Never returns ``None``, so callers can chain ``.endswith()``/
    ``.startswith()``/membership checks directly without a null check —
    ``"".endswith(())`` and ``"".startswith(())`` are both simply ``False``
    for an empty tuple, matching "no text means no match".
    """

    if isinstance(update, Message):
        return update.text or update.caption or ""

    return data if isinstance(data := update.data, str) else ""


def endswith(*texts: "NestedContainer[str]") -> Filter:
    """Match when the update's text ends with any of ``texts``."""

    flat_texts = tuple({t for t in iter_flat_cont(texts) if isinstance(t, str) and t})
    caller = _to_coroutine(
        lambda _, __, update: _extract_text(update).endswith(flat_texts)
    )

    return create(caller, "EndsWith")

def startswith(*texts: "NestedContainer[str]") -> Filter:
    """Match when the update's text starts with any of ``texts``."""

    flat_texts = tuple({t for t in iter_flat_cont(texts) if isinstance(t, str) and t})
    caller = _to_coroutine(
        lambda _, __, update: _extract_text(update).startswith(flat_texts)
    )

    return create(caller, "StartsWith")

def equal(*texts: "NestedContainer[str]") -> Filter:
    """Match when the update's text is exactly one of ``texts``."""

    flat_texts = frozenset(t for t in iter_flat_cont(texts) if isinstance(t, str) and t)
    caller = _to_coroutine(lambda _, __, update: _extract_text(update) in flat_texts)

    return create(caller, "Equal")


def split_text(
    *rules: Union["MaybeCoroutineCallable[[str], bool]", "NestedContainer[str]", EnumType], 
    strip: bool = False, 
    separator: Optional[str] = None, 
    ) -> Filter:
    """
    Split the update's text by ``separator`` and match each part against the
    corresponding ``rules`` entry.

    Each rule is one of:

    - a container of strings, a bare string, or an :class:`~enum.Enum` class
      (whose *values* are used) — the part must equal one of them;
    - a callable — awaited (or run inline, if sync) as ``rule(part)`` and
      must return truthy.

    ``separator=None`` (the default) is only valid with exactly one rule: the
    whole text is treated as a single, unsplit part.

    Example:
        .. code-block:: python

            # "/ban <user_id> <reason>"
            filters.split_text(
                equal("/ban"), lambda p: p.isdigit(), lambda p: bool(p),
                separator=" ",
            )

    Raises:
        ValueError: If no rules are given, a rule resolves to an empty set of
                    strings, or more than one rule is given without a
                    ``separator``.
        TypeError:  If a rule is neither a container, a string, an Enum class,
                    nor a callable.
    """

    if not rules:
        raise ValueError("split_text filter must be given at least one rule")

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
            raise ValueError("split_text rules must not be empty")

    if len(normalized_rules) > 1 and separator is None:
        raise ValueError(
            "separator is required when split_text is given more than one rule"
        )

    async def caller(_, client: "Client", update: Union[Message, Query]) -> bool:
        text = _extract_text(update)

        if not text:
            return False

        parts = (
            [text] if separator is None
            else text.split(separator, maxsplit=len(normalized_rules) - 1)
        )

        if strip:
            parts = [p.strip() for p in parts]

        if len(parts) != len(normalized_rules):
            return False

        for part, rule in zip(parts, normalized_rules):
            if is_container(rule):
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
