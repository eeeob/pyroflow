"""Abstract base class for update coordinator backends."""

from __future__ import annotations as _annotations

from abc import ABC, abstractmethod
from typing import Any, TYPE_CHECKING
from uuid import uuid4

from pytrove.enums import TimeUnit

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from pytrove.typings import Number

    from ..models import ListenerKey
    from ..typings import AsyncLockProto, UpdateType, CoordinatedUpdateKeyT, CoordinatedUpdateIdT


class UpdateCoordinator(ABC):
    """Abstract backend holding every piece of state one update type shares across sessions.

    It holds three primitives:

    - `lock`: a plain mutex over the scope the caller chose. It keeps no state
      once released.
    - `is_handled` and `mark_handled`: the handled registry, a set of update
      ids that are either handled (skip them) or not.
    - `register_listener`, `listener_owners`, `unregister_listener` and
      `cancel_listener`: the listener registry, which session's listener owns
      each `ListenerKey`. Each operation is atomic on its own and takes no lock.

    An owner id is `<fingerprint>:<random>`. `fingerprint` names this
    coordinator, so `is_mine` tells this session's registrations from a peer's.

    The `UpdateCoordinated` and the `UpdateListener` of one update type share
    one coordinator, so registering a listener and processing an update take
    the same lock. The dispatcher starts and stops each coordinator once.

    Args:
        update_type: The Pyrogram update class handled; backends that share
            keys namespace them with its name.
        handled_ttl: Seconds an update id stays registered as handled, which
            is the deduplication window.
        blocking_timeout: Maximum seconds `lock` waits before reporting
            failure. Keep it small: the dispatcher waits while holding its
            worker lock, so a contended update stalls that worker meanwhile.
        **kw: Passed to the next class in the MRO.
    """

    def __init__(
        self,
        update_type: type[UpdateType],
        handled_ttl: Number = TimeUnit.HOUR,
        blocking_timeout: Number = 10,
        **kw: Any,
    ) -> None:
        """Initialise the coordinator; see the class docstring for the parameters."""
        self.handled_ttl = handled_ttl
        """Seconds an update id stays registered as handled."""
        self.blocking_timeout = blocking_timeout
        """Maximum seconds `lock` waits before reporting failure."""
        self.update_type = update_type
        """The Pyrogram update class this coordinator handles."""
        self.fingerprint = uuid4().hex
        """Prefix of every owner id and lock value this coordinator writes, unique among the sessions."""
        self.on_listener_lost: Callable[[ListenerKey, str], object] | None = None
        """Called with `(key, owner_id)` when a peer took or cancelled one of this session's registrations; set by the listener."""

        super().__init__(**kw)

    def new_owner_id(self) -> str:
        """Return a fresh owner id for a listener registration of this session.

        Example:
            >>> from pyroflow.types import Message
            >>> from pyroflow.update_coordinator import MemoryUpdateCoordinator
            >>> coordinator = MemoryUpdateCoordinator(Message)
            >>> owner_id = coordinator.new_owner_id()
            >>> owner_id.startswith(coordinator.fingerprint + ":"), coordinator.is_mine(owner_id)
            (True, True)
        """
        return f"{self.fingerprint}:{uuid4().hex}"

    def is_mine(self, owner_id: str) -> bool:
        """Return whether `owner_id` was issued by this coordinator.

        Example:
            >>> from pyroflow.types import Message
            >>> from pyroflow.update_coordinator import MemoryUpdateCoordinator
            >>> MemoryUpdateCoordinator(Message).is_mine("peer:1")
            False
        """
        return owner_id.startswith(f"{self.fingerprint}:")

    @abstractmethod
    def lock(self, key: CoordinatedUpdateKeyT) -> AsyncLockProto:
        """Return the mutex for the scope `key`.

        Implementations honour `blocking_timeout`: `acquire()` returns `False`
        instead of waiting forever, and `async with` raises instead of entering
        unlocked. Distributed backends must also expire the lock on their own,
        as `RedisUpdateCoordinator` does after `lock_ttl`; the in-process
        `TimedLock` never expires.

        Args:
            key: The scope to serialise, such as a chat or a single update.

        Returns:
            An async lock usable with `async with`.
        """
        raise NotImplementedError

    @abstractmethod
    async def is_handled(self, key: CoordinatedUpdateIdT) -> bool:
        """Return whether `key` is registered as handled.

        Args:
            key: The update's identity, not its lock scope.

        Returns:
            `True` if the update was already processed and should be skipped.
        """
        raise NotImplementedError

    @abstractmethod
    async def mark_handled(self, key: CoordinatedUpdateIdT) -> None:
        """Register `key` as handled for `handled_ttl` seconds, unless it already is.

        The caller holds the update's lock and found `key` unhandled, so an
        existing entry means a peer handled the same update meanwhile.

        Args:
            key: The update's identity, not its lock scope.

        Raises:
            UpdateAlreadyHandled: If `key` is already registered; its entry
                and expiry are left unchanged.
        """
        raise NotImplementedError

    @abstractmethod
    async def register_listener(
        self, key: ListenerKey, owner_id: str, *, replace: bool
    ) -> str | None:
        """Record `owner_id` as the owner of `key`.

        Args:
            key: The listener key to claim.
            owner_id: The id from `new_owner_id`.
            replace: Overwrite an existing owner. When `False` and `key` is
                already owned, nothing is written.

        Returns:
            The previous owner id, or `None` if `key` was free.
        """
        raise NotImplementedError

    @abstractmethod
    async def listener_owners(self, keys: Sequence[ListenerKey]) -> list[str | None]:
        """Return the owner id of each key, in order, `None` for a free key.

        Args:
            keys: The listener keys to look up.

        Returns:
            One entry per key.
        """
        raise NotImplementedError

    @abstractmethod
    async def unregister_listener(self, key: ListenerKey, owner_id: str) -> bool:
        """Remove the registration of `key` only if `owner_id` still owns it.

        Resolving an update claims the listener through this call, so two
        updates never resolve the same registration.

        Args:
            key: The listener key to release.
            owner_id: The owner the registration must still hold.

        Returns:
            `True` if this call removed it, `False` if `key` was free or owned
            by another id.
        """
        raise NotImplementedError

    @abstractmethod
    async def cancel_listener(self, key: ListenerKey) -> str | None:
        """Remove the registration of `key`, whoever owns it.

        Args:
            key: The listener key to cancel.

        Returns:
            The removed owner id, or `None` if `key` was free.
        """
        raise NotImplementedError

    async def start(self) -> None:  # noqa: B027  # optional lifecycle hook; subclasses override only when needed
        """Prepare the backend before use. Does nothing by default."""

    async def stop(self) -> None:  # noqa: B027  # optional lifecycle hook; subclasses override only when needed
        """Release the backend's resources. Does nothing by default."""


__all__ = ("UpdateCoordinator",)
