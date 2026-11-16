"""Custom text-matching filters, in the same style as `pyrogram.filters`.

Each factory returns a `pyrogram.filters.Filter`, and `registered_command` and
`too_fast` are ones themselves, so each composes with `&`, `|` and `~` and
registers like any Pyrogram filter. The text of a `Message` is its `text`,
falling back to its `caption`; the text of a `CallbackQuery` is its `data`; the
text of an `InlineQuery` or a `ChosenInlineResult` is its `query`. Any other
update raises `TypeError`. A `str` pattern matches a `str` text only, and a
`bytes` pattern `bytes` data only; Pyrogram leaves `data` as `bytes` only when
it is not valid UTF-8.

`too_fast` is not about text: it matches an update that came within an
interval of the last one let through with its key, such as a button pressed
again quickly by the same user, so `on_spam` answers it and the real handler
skips it.
"""

from __future__ import annotations as _annotations

import asyncio
import logging
import re
import time
import weakref
from collections.abc import Hashable
from dataclasses import dataclass, field
from typing import ClassVar, Final, Generic, NamedTuple, Protocol, AnyStr, TYPE_CHECKING
from enum import Enum, EnumMeta as EnumType

from pyrogram.errors import QueryIdInvalid
from pyrogram.filters import Filter, create
from pyrogram.types import (
    BotCommandScope,
    BotCommandScopeAllChatAdministrators,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeDefault,
)
from pytrove import (
    DefaultWeakKeyDict,
    call_sync_or_await,
    gather_abort,
    iter_flat_cont,
    is_container,
)

from .enums import CommandUsernamePolicy
from .types import CallbackQuery, Message
from .typings import UpdateType
from .utils import get_update_text

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from pyrogram.types import ChosenInlineResult, InlineQuery, User
    from pytrove.typings import NestedContainer, Number

    from .client import Client
    from .typings import MaybeAwaitableCallable


log = logging.getLogger(__name__)
"""Logger for `too_fast` `on_spam` errors."""

# Not `pytrove.TG_BOT_COMMAND_PATTERN`: it refuses arguments and names starting with a digit
# or `_`, which Bot API allows, and captures neither the name nor the username.
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


@dataclass(slots=True)
class _TooFastState:
    """What `too_fast` keeps of one client."""

    until: dict[Hashable, tuple[float, float]] = field(default_factory=dict)
    """Per key: when the interval of its last update not matched ends, counted from its arrival and from its check."""

    is_spam: dict[int, bool] = field(default_factory=dict)
    """Per `id()` of an update checked and still in memory: whether it came too soon."""

    kept: int = 0
    """How many keys the last sweep kept; the next one waits for more than twice as many."""


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
            default `""`, the list for users whose language has no list of
            its own.

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
        """Initialize the filter with nothing fetched; see the class docstring for the parameters."""
        self.ephemeral = ephemeral
        """Whether a command marked `is_ephemeral` counts."""
        self.username_policy = username_policy
        """Which `@username` after the command name passes; `None` takes none or any."""
        self.scopes = tuple(scopes)
        """The scopes whose commands are fetched."""
        self.language_codes = tuple(language_codes)
        """The languages whose commands are fetched in each scope."""
        self.fetched: weakref.WeakKeyDictionary[Client, _BotCommands] = weakref.WeakKeyDictionary()
        """Per client: what its last fetch kept."""
        self.fetching: weakref.WeakKeyDictionary[Client, asyncio.Future[_BotCommands]] = (
            weakref.WeakKeyDictionary()
        )
        """Per client: the fetch in progress, which concurrent calls share."""

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
        usernames of `client.me`. Calls made while a fetch runs share it. A
        client with no `me` fetches on every call.

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

        fetch = self.fetching.get(client)

        if fetch is None:
            self.fetching[client] = fetch = asyncio.ensure_future(self._fetch_commands(client))
            fetch.add_done_callback(lambda _: self.fetching.pop(client, None))

        # Shielded: a cancelled caller must not cancel the fetch the others wait on.
        return await asyncio.shield(fetch)

    async def _fetch_commands(self, client: Client) -> _BotCommands:
        """Fetch the commands for `_get_commands`, and keep them in `fetched`.

        Args:
            client: The client whose commands to fetch.

        Returns:
            The usernames and the regular and ephemeral command names.
        """
        me = client.me
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


class too_fast(Filter, Generic[UpdateType]):  # lowercase: used like the factories in this module
    """Match an update that came too soon: within `interval` seconds of the last one let through with its key.

    An update is let through (not matched) if it arrived once the interval of
    the last update let through with its key had ended, and it starts a new
    interval; one that came sooner is matched and does not extend it.
    The arrival is `arrived_at`, which the dispatcher sets when the update
    reaches it, so presses that waited behind a running handler, in the
    updates queue or in a `CoordinatedDispatcher` lane, still count from the
    moment the dispatcher received them. An update that did not come through
    a dispatcher has no `arrived_at` and is never matched.

    By default the key is `extract_key`: the chat, the user and the message
    of a button press, or its inline or ephemeral message, so each user is
    counted apart on each message; any other update is never matched without
    `key`. An update checked again, by another handler or after a wait, gets
    the same decision, and `on_spam` runs once at most for it; each decision
    is forgotten when its update is deleted from memory.

    The state is kept per client object, in memory, and each filter keeps its
    own: a key is kept until its interval has ended both from the arrival of
    its last update let through and from that update's check, and is dropped
    at a later sweep; only the arrival end decides a match. So a press checked
    later than the interval after that check, as behind a handler slower than
    the interval, may be let through. It survives the client stopping and
    starting, and is lost only when the client object is freed or the
    process ends. So make one filter for
    each update type and use it on every handler of that type, as it is on
    the handler that takes the fast updates and with `~` on the ones that do
    the work, not a new one per handler: two filters each let the same
    update through on their own, so both handlers run, and `on_spam` may run
    twice for one update.

    The filter is generic on the update it takes, so `interval`, `key` and
    `on_spam` are typed as taking that update:
    `too_fast[CallbackQuery](2, key=...)`, or let the type come from the
    functions passed.

    Warning:
        Put it last in `&`: an update it lets through starts the interval even
        when a filter after it fails and no handler runs. A press that arrives
        after the interval is let through, so with a handler slower than the
        interval a second press runs it again: pick an interval longer than the
        handler. Orders, payments and other actions that must not repeat need
        a guard of their own too.

    Args:
        interval: The seconds after an update let through within which one
            with the same key is matched, or a sync function that takes the
            update and returns them; zero or less matches nothing.
        key: A sync function that takes the update and returns its key;
            `None` from it leaves that update unmatched. By default
            `extract_key`, which keys button presses only.
        on_spam: A function (sync or async) called with each update it
            matches, once per update; what it raises is logged, and the update
            still counts as too soon. A sync one runs on the event loop, so
            keep it light.
            By default `answer_press`, which answers a button press with no
            text to end its loading indicator; `None` calls nothing.

    Raises:
        TypeError: If `key` is not callable.

    Example:
        >>> import asyncio, time
        >>> from pyrogram.types import Message, User
        >>> class Bot:
        ...     pass
        >>> per_user = too_fast(2, key=lambda message: message.from_user.id)
        >>> start = time.monotonic()
        >>> def arriving_after(seconds):
        ...     message = Message(id=1, from_user=User(id=7))
        ...     message.arrived_at = start + seconds
        ...     return message
        >>> bot = Bot()
        >>> [asyncio.run(per_user(bot, arriving_after(seconds))) for seconds in (0, 1, 2.5)]
        [False, True, False]
    """

    @staticmethod
    def extract_key(update: object) -> Hashable | None:
        """Return the default key of `update`: who pressed, and on which message.

        Args:
            update: The update to key.

        Returns:
            For a press on a message in a chat, its chat, user, message id,
            ephemeral message id and business connection; for one on an inline
            message, its user and inline message id; otherwise `None`. An
            ephemeral message has the id `0` and its own in the ephemeral id,
            so it never shares a key with an ordinary one.
        """
        if not isinstance(update, CallbackQuery):
            return None

        user_id = update.from_user.id
        message = update.message

        if message is None or message.chat is None:
            if update.inline_message_id is None:
                return None

            return user_id, update.inline_message_id

        return (
            message.chat.id,
            user_id,
            message.id,
            message.ephemeral_message_id,
            message.business_connection_id,
        )

    @staticmethod
    async def answer_press(update: object) -> None:
        """Answer `update` with no text if it is a button press, which ends its loading indicator.

        Args:
            update: The update `too_fast` matched; any other than a `CallbackQuery` is left.
        """
        if not isinstance(update, CallbackQuery):
            return

        try:
            await update.answer()
        except QueryIdInvalid:
            pass  # the press expired; there is nothing left to answer

    def __init__(
        self,
        interval: Number | Callable[[UpdateType], Number],
        key: Callable[[UpdateType], Hashable | None] = extract_key,
        on_spam: MaybeAwaitableCallable[[UpdateType], object] | None = answer_press,
    ) -> None:
        """Initialize the filter with nothing kept; see the class docstring for the parameters."""
        if not callable(key):
            msg = f"too_fast key must be callable, not {type(key).__name__}"
            raise TypeError(msg)

        self.interval = interval
        """The seconds after an update let through within which one with its key is matched, or the function that gives them."""
        self.key = key
        """The function that gives an update's key."""
        self.on_spam = on_spam
        """The function called with each update it matches, or `None`."""
        self.states: DefaultWeakKeyDict[Client, _TooFastState] = DefaultWeakKeyDict(_TooFastState)
        """Per client: what this filter keeps of it."""

    async def __call__(self, client: Client, update: UpdateType) -> bool:  # ty: ignore[invalid-method-override]  # pyroflow's `Client` is pyrogram's at runtime via `patch_cls`
        """Return whether the update came too soon, calling `on_spam` with it if so.

        Args:
            client: The client that received the update.
            update: The update to test.

        Returns:
            Whether it came within the interval of the last update let through with its key.

        Raises:
            Exception: Whatever `key` or `interval` raises on the update, unchanged; what
                `on_spam` raises is logged instead.
        """
        arrived_at: float | None = getattr(update, "arrived_at", None)

        if arrived_at is None:
            return False

        state = self.states[client]

        # An update checked before keeps that decision, and `on_spam` ran for it then.
        if (spam := state.is_spam.get(id(update))) is not None:
            return spam

        # Nothing is awaited from the lookup above through `_decide`, so no concurrent check
        # of this update decides in between.
        spam = self._decide(state, update, arrived_at)

        if spam and self.on_spam is not None:
            try:
                await call_sync_or_await(self.on_spam, update)
            except Exception:
                # Logged, not raised: the dispatcher would skip the handler and lose the decision.
                log.exception("Error in too_fast on_spam %r", self.on_spam)

        return spam

    def _decide(self, state: _TooFastState, update: UpdateType, arrived_at: float) -> bool:
        """Decide whether an update not checked before came too soon, and record it in `state`.

        A key is kept until its interval has ended both from the arrival of
        its last update let through and from that update's check, so a press
        checked late, behind a backlog or a busy lane, still meets the key of
        the press before it when that press was checked less than the
        interval before.

        Args:
            state: What this filter keeps of the update's client.
            update: The update to decide on.
            arrived_at: When the update reached the dispatcher.

        Returns:
            Whether it came within the interval of the last update let through
            with its key; `False` for one with no key, or an interval of zero
            or less, which is not recorded.

        Raises:
            Exception: Whatever `key` or `interval` raises on the update, unchanged.
        """
        key = self.key(update)

        if key is None:
            return False

        interval = (
            self.interval if isinstance(self.interval, (int, float)) else self.interval(update)
        )

        if interval <= 0:
            return False

        now = time.monotonic()
        last = state.until.get(key)
        spam = last is not None and arrived_at < last[0]

        if not spam:
            state.until[key] = (arrived_at + interval, now + interval)

        decision_id = id(update)
        state.is_spam[decision_id] = spam
        # The id is reused only once the update is freed, after this, so no newer decision is popped.
        weakref.finalize(update, state.is_spam.pop, decision_id, None)

        # Forget the keys whose interval ended both by this update's arrival and by now, once
        # the keys more than doubled since the last sweep.
        if len(state.until) > 2 * state.kept:
            state.until = {
                key: ends
                for key, ends in state.until.items()
                if ends[0] > arrived_at or ends[1] > now
            }
            state.kept = len(state.until)

        return spam


def _normalize_rule(
    rule: MaybeAwaitableCallable[[str], bool] | NestedContainer[str] | EnumType | re.Pattern[str],
) -> frozenset[str] | re.Pattern[str] | MaybeAwaitableCallable[[str], bool]:
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

    async def caller(
        _: Filter, __: Client, update: Message | CallbackQuery | InlineQuery | ChosenInlineResult
    ) -> bool:
        """Return whether the update's text matches the patterns of its own kind."""
        text = get_update_text(update)

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
    *rules: MaybeAwaitableCallable[[str], bool] | NestedContainer[str] | EnumType | re.Pattern[str],
    strip: bool = False,
    separator: str | None = None,
) -> Filter:
    r"""Split the update's text by `separator` and match each part against its `rules` entry.

    The update matches only when the text splits into exactly one part per
    rule and every part satisfies its rule. A callable rule runs on the event
    loop, sync or not, so keep it light. Callback data left as `bytes` never
    matches.

    Args:
        *rules: One per part: a string, a container of strings or an `Enum`
            class (its values), which the part must equal one of; a compiled
            `re.Pattern`, which must `fullmatch` the part; or a callable,
            called as `rule(part)`, which must return truthy.
        strip: Whether to strip whitespace from each part before matching.
        separator: What to split the text on, at most `len(rules) - 1`
            times. `None` (the default) is only valid with exactly one rule:
            the whole text is then a single part. It must not be empty.

    Returns:
        The filter.

    Raises:
        ValueError: If no rules are given, a rule resolves to an empty set of
            strings, more than one rule is given without a `separator`, or
            `separator` is empty.
        TypeError: If a rule is neither a container, a string, an `Enum`
            class, a compiled pattern, nor a callable.
        Exception: Whatever a callable rule raises when the filter checks an
            update, unchanged.

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

    if separator == "":
        msg = "split_text separator must not be empty"
        raise ValueError(msg)

    async def caller(
        _: Filter,
        client: Client,
        update: Message | CallbackQuery | InlineQuery | ChosenInlineResult,
    ) -> bool:
        """Return whether the update's text splits into parts that each satisfy their rule."""
        text = get_update_text(update)

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
            elif not await call_sync_or_await(rule, part):
                return False

        return True

    return create(caller, "SplitText")


__all__ = (
    "endswith",
    "startswith",
    "equal",
    "split_text",
    "registered_command",
    "too_fast",
)
