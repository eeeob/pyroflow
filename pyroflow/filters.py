"""Custom text-matching filters, in the same style as `pyrogram.filters`.

Each factory returns a `pyrogram.filters.Filter`, and `registered_command` is
one itself, so each composes with `&`, `|` and `~` and registers like any
Pyrogram filter. The text of a `Message` is its
`text`, falling back to its `caption`; the text of a `CallbackQuery` is its
`data`. A `str` pattern matches a `str` text only, and a `bytes` pattern `bytes`
data only; Pyrogram leaves `data` as `bytes` only when it is not valid UTF-8.
"""

from __future__ import annotations as _annotations

import re
import weakref
from typing import ClassVar, Final, NamedTuple, Protocol, AnyStr, TYPE_CHECKING
from enum import Enum, EnumMeta as EnumType

from pyrogram.filters import Filter, create
from pyrogram.types import (
    BotCommandScope,
    BotCommandScopeAllChatAdministrators,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeDefault,
)
from pytrove import (
    gather_abort,
    iter_flat_cont,
    is_container,
    extract_pyro_update_text,
)

from .enums import CommandUsernamePolicy
from .types import Message
from .utils import call_maybe_async

if TYPE_CHECKING:
    from collections.abc import Iterable

    from pyrogram.types import User
    from pytrove.typings import MaybeCoroutineCallable, NestedContainer

    from .client import Client
    from .types import CallbackQuery as Query


# Not `pytrove.TG_BOT_COMMAND_PATTERN`: it refuses arguments, a name not starting with a
# letter, as Bot API allows, and captures neither the name nor the username.
_COMMAND_RE: Final[re.Pattern[str]] = re.compile(r"^/([a-zA-Z0-9_]{1,32})(?:@(\w+))?(?:\s|$)")
"""Telegram command syntax: `/name` with an optional `@username`, capturing both."""


class _TextMatch(Protocol):
    """A text test called with patterns of the text's own kind."""

    def __call__(self, text: AnyStr, patterns: tuple[AnyStr, ...], /) -> bool:
        """Return whether `text` matches `patterns`."""
        ...


class _BotCommands(NamedTuple):
    """What `registered_command` keeps of one client for one start."""

    user_client: weakref.ref[User] | None
    """The `me` of the start these were fetched in, or `None` for a client with no `me`."""

    usernames: frozenset[str]
    """The bot's lowercased usernames, which `/name@username` may aim at."""

    regular: frozenset[str]
    """Lowercased names of the commands Telegram does not mark `is_ephemeral`."""

    ephemeral: frozenset[str]
    """Lowercased names of the commands Telegram marks `is_ephemeral`."""


class registered_command(Filter):  # lowercase: used like the factories in this module
    """Match a message whose text or caption is a registered command of this bot.

    `/name`, in any case, with any arguments and an `@username` that
    `username_policy` accepts, passes if one of `scopes` in one of
    `language_codes` has it.
    The fetched commands and the bot's usernames are kept per client until it
    starts again; a failed fetch raises unchanged, and an update that is not a
    message raises `TypeError`.

    `MessageListener(strict_filter=~registered_command())` lets such a command
    end a wait with no `filters` and reach the handlers.

    Args:
        ephemeral: Whether a command marked `is_ephemeral` counts.
        username_policy: Which `@username` after the name passes; by default
            none or one of the bot's, and with `None` none or any.
        scopes: The scopes whose commands count; by default `DEFAULT_SCOPES`.
        language_codes: The languages whose commands count in each scope; by
            default `""`, the commands of users with no language of their own.

    Example:
        >>> import asyncio
        >>> from pyrogram.types import BotCommand, Message
        >>> class Bot:
        ...     me = None
        ...     async def get_bot_commands(self, scope=None, language_code=""):
        ...         return [BotCommand("start", "Start the bot"), BotCommand("note", "A note", True)]
        >>> bot = Bot()
        >>> asyncio.run(registered_command()(bot, Message(id=1, text="/start now")))
        True
        >>> asyncio.run(registered_command()(bot, Message(id=1, text="/help")))
        False
        >>> asyncio.run(registered_command(ephemeral=False)(bot, Message(id=1, text="/note")))
        False
        >>> any_bot = registered_command(username_policy=None)
        >>> asyncio.run(any_bot(bot, Message(id=1, text="/start@other_bot")))
        True
    """

    DEFAULT_SCOPES: ClassVar[tuple[BotCommandScope, ...]] = (
        BotCommandScopeDefault(),
        BotCommandScopeAllPrivateChats(),
        BotCommandScopeAllGroupChats(),
        BotCommandScopeAllChatAdministrators(),
    )
    """The scopes `scopes` defaults to: the four that need no chat or user."""

    def __init__(
        self,
        *,
        ephemeral: bool = True,
        username_policy: CommandUsernamePolicy | None = CommandUsernamePolicy.OPTIONAL,
        scopes: Iterable[BotCommandScope] = DEFAULT_SCOPES,
        language_codes: Iterable[str] = ("",),
    ) -> None:
        """Initialise the filter with nothing fetched; see the class docstring for the parameters."""
        self.ephemeral = ephemeral
        """Whether a command marked `is_ephemeral` counts."""
        self.username_policy = username_policy
        """Which `@username` after the command name passes; `None` takes any."""
        self.scopes = tuple(scopes)
        """The scopes whose commands are fetched."""
        self.language_codes = tuple(language_codes)
        """The languages whose commands are fetched in each scope."""
        self.fetched: weakref.WeakKeyDictionary[Client, _BotCommands] = weakref.WeakKeyDictionary()
        """Per client: what its last fetch kept."""

    async def __call__(self, client: Client, update: Message) -> bool:  # ty: ignore[invalid-method-override]  # pyroflow's `Client` is pyrogram's at runtime via `patch_cls`
        """Return whether the message is a command of this bot and registered.

        Args:
            client: The client that received the update.
            update: The update to test.

        Returns:
            Whether it is such a command.

        Raises:
            TypeError: If `update` is not a `Message`.
            Exception: Whatever `client.get_bot_commands()` raises, unchanged.
        """
        if not isinstance(update, Message):
            msg = f"registered_command supports Message updates only, not {type(update).__name__}"
            raise TypeError(msg)

        match = _COMMAND_RE.match(update.content)

        if match is None:
            return False

        command, target = match.group(1).lower(), (match.group(2) or "").lower()
        policy = self.username_policy

        if not target:
            if policy in (CommandUsernamePolicy.REQUIRED, CommandUsernamePolicy.ANY_REQUIRED):
                return False
        elif policy is CommandUsernamePolicy.FORBIDDEN:
            return False

        commands = await self._get_commands(client)

        if (
            target
            and policy in (CommandUsernamePolicy.OPTIONAL, CommandUsernamePolicy.REQUIRED)
            and target not in commands.usernames
        ):
            return False

        return command in commands.regular or (self.ephemeral and command in commands.ephemeral)

    async def _get_commands(self, client: Client) -> _BotCommands:
        """Return the bot's usernames and command names that `fetched` keeps for `client`.

        They are returned from `fetched` while the client has not started
        again since; otherwise the commands of every scope in every language
        of this filter are fetched at once, one call each, and kept with the
        usernames of `client.me`. A client with no `me` fetches on every call.

        Args:
            client: The client whose commands to return.

        Returns:
            The usernames and the regular and ephemeral command names.

        Raises:
            Exception: Whatever `client.get_bot_commands()` raises first, unchanged;
                the other fetches are cancelled.
        """
        # Pyrogram sets a new `me` on every start, so a changed `me` means a restart.
        me, entry = client.me, self.fetched.get(client)

        if entry is not None and entry.user_client is not None and entry.user_client() is me:
            return entry

        results = await gather_abort(
            client.get_bot_commands(scope=scope, language_code=language_code)
            for scope in self.scopes
            for language_code in self.language_codes
        )
        fetched = [bot_command for result in results for bot_command in result]
        names = (
            ()
            if me is None
            else iter_flat_cont(me.username, (u.username for u in me.usernames or ()))
        )

        self.fetched[client] = commands = _BotCommands(
            # A weak reference: a Pyrogram `User` holds its client, which would stay alive.
            user_client=None if me is None else weakref.ref(me),
            usernames=frozenset(name.lower() for name in names if name),
            regular=frozenset(c.command.lower() for c in fetched if not c.is_ephemeral),
            ephemeral=frozenset(c.command.lower() for c in fetched if c.is_ephemeral),
        )

        return commands


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
    "registered_command",
)
