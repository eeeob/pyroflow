from typing import Literal, Type, get_args
from abc import ABC, abstractmethod

from ..utils.typings import Number, AsyncLockProto, UpdateType
from ..utils.enums import TimeUnit

from ..typings import UpdateCoordinatorKeyT


_SECTION = Literal["lock", "handled"]

class UpdateCoordinator(ABC):
    """
    Abstract base coordinator for distributed update processing.

    Two independent primitives, deliberately kept apart:

    **The lock** (:meth:`lock`) is a plain mutual-exclusion lock — nothing
    more. It serialises whatever scope the caller chose to key it by, and
    once released the very next caller takes it normally. It carries no
    memory of what happened while it was held.

    **The handled registry** (:meth:`is_handled` / :meth:`mark_handled`) is
    the memory: a flat set of update ids that have already been processed.
    Membership is the whole state — an id is either in it (handled, skip)
    or it is not (never processed, go ahead). There is no third state, and
    nothing is ever "in progress" here; that is what the lock is for.

    Keeping them separate is what lets the caller pick the lock's scope
    freely. Lock per chat and register per message, and every update in that
    chat is processed one at a time, in order, with each one still processed
    exactly once. Lock per message instead and the scopes coincide, which is
    the narrower default. Neither choice changes the registry's meaning,
    because the registry never keys on the lock's scope.

    The two are namespaced apart in the backend (see :meth:`build_key`), so
    the same key tuple used for both never collides.

    Parameters:
        update_type:      The Pyrogram update class this coordinator handles.
                          Its name is used to namespace the keys.
        lock_ttl:         How long (seconds) the lock may be held before it
                          expires on its own. Sized for the slowest handler
                          you expect; a session that dies mid-handler keeps
                          the lock until this elapses.
        handled_ttl:      How long (seconds) an update id is remembered as
                          handled. This is the deduplication window: once it
                          lapses the same update would be processed again if
                          it somehow arrived a second time.
        blocking_timeout: Max seconds :meth:`lock` waits before giving up and
                          reporting failure.

                          **Keep this small.** The dispatcher waits on the
                          lock while holding its worker lock, so a contended
                          update stalls every other update on that worker for
                          the full timeout. Waiting out a peer's whole
                          ``lock_ttl`` buys nothing — the peer will have
                          either finished or died long before — and meanwhile
                          the worker sits idle.
        **kw: Passed to the next class in the MRO.
    """

    def __init__(
        self,
        update_type: Type[UpdateType],
        lock_ttl: Number = TimeUnit.HOUR,
        handled_ttl: Number = TimeUnit.HOUR,
        blocking_timeout: Number = 5,
        **kw,
    ) -> None:

        self.lock_ttl = lock_ttl
        self.handled_ttl = handled_ttl
        self.blocking_timeout = blocking_timeout

        self._update_name = update_type.__name__
        self._sep = "|"
        self._key_formats = {
            section: (
                f"update{self._sep}{section}{self._sep}"
                f"{self._update_name}{self._sep}{{key}}"
            )
            for section in get_args(_SECTION)
        }

        super().__init__(**kw)

    def build_key(
        self,
        key: UpdateCoordinatorKeyT,
        section: _SECTION = "lock",
    ) -> str:
        """
        Render a key tuple into its backend key, under ``section``.

        The section is what keeps the two primitives from colliding: by
        default the *same* tuple is used both to lock and to register, and
        without separate namespaces marking an update handled would look
        like a held lock, and vice versa.
        """
        
        return self._key_formats[section].format_map({"key": self._sep.join(str(i) for i in key)})

    @abstractmethod
    def lock(self, key: UpdateCoordinatorKeyT) -> AsyncLockProto:
        """
        Return the mutex for ``key``, as an ``async with``-compatible object.

        Implementations must honour ``blocking_timeout``: ``acquire()``
        returns ``False`` rather than waiting indefinitely, and entering it
        via ``async with`` raises instead of proceeding unlocked.

        The lock must also expire on its own after ``lock_ttl``, so a session
        that dies while holding it does not block the scope permanently.

        Parameters:
            key: Identifies the scope to serialise — whatever the caller
                 chose to key on (a chat, a single update, anything else).

        Returns:
            An async lock compatible with ``async with``.
        """
        raise NotImplementedError

    @abstractmethod
    async def is_handled(self, key: UpdateCoordinatorKeyT) -> bool:
        """
        Whether ``key`` is registered as already handled.

        Parameters:
            key: The update's identity — *not* the lock's scope.

        Returns:
            ``True`` if this update was already processed and should be
            skipped, ``False`` if it has never been processed.
        """
        raise NotImplementedError

    @abstractmethod
    async def mark_handled(self, key: UpdateCoordinatorKeyT) -> None:
        """
        Register ``key`` as handled, for ``handled_ttl`` seconds.

        Idempotent: marking an already-marked key is a no-op beyond
        refreshing its expiry.

        Parameters:
            key: The update's identity — *not* the lock's scope.
        """
        raise NotImplementedError

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass
