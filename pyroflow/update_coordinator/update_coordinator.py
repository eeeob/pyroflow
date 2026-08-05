from typing import Optional, Type
from abc import ABC, abstractmethod

from ..utils.typings import Number, UpdateType
from ..utils.enums import TimeUnit

from ..enums import UpdateLockState
from ..typings import UpdateCoordinatorKeyT

import asyncio
import time

class UpdateCoordinator(ABC):
    """
    Abstract base coordinator for distributed update deduplication.

    Ensures that a given update is processed exactly once across
    multiple sessions or servers.

    Parameters:
        update_type:      The Pyrogram update class this coordinator handles.
                          Its name is used to namespace the lock keys.
        lock_ttl:         How long (seconds) the lock is held before expiring.
                          Stored internally as milliseconds. Sized for the
                          slowest handler you expect; a session that dies
                          mid-handler keeps the lock until this elapses.
        sleep:            Polling interval (seconds) while waiting for a lock.
        blocking_timeout: Max seconds to wait before raising TimeoutError.

                          **Keep this small.** :meth:`acquire` polls, and the
                          dispatcher calls it while holding its worker lock,
                          so a contended update stalls every other update on
                          that worker for the full timeout. The default is
                          deliberately a few seconds rather than a fraction of
                          ``lock_ttl``: waiting out a peer's whole lock buys
                          nothing, since the peer will have either finished or
                          died long before, and meanwhile the worker is idle.
        **kw: Passed to the next class in the MRO.
    """

    def __init__(
        self,
        update_type: Type[UpdateType],
        lock_ttl: Number = TimeUnit.HOUR,
        sleep: Number = 0.01,
        blocking_timeout: Number = 5,
        **kw,
    ) -> None:
        
        self.lock_ttl = lock_ttl
        self.sleep = sleep
        self.blocking_timeout = blocking_timeout

        self._update_name = update_type.__name__
        self._sep = "|"
        self._key_format = (
            f"update{self._sep}lock{self._sep}"
            f"{self._update_name}{self._sep}{{key}}"
        )

        super().__init__(**kw)

    def build_key(self, key: UpdateCoordinatorKeyT) -> str:
        return self._key_format.format_map(
            {"key": self._sep.join(str(i) for i in key)}
        )

    @abstractmethod
    async def _try_acquire(self, key: str) -> Optional[bool]:
        """
        Single atomic attempt to acquire the lock.

        Returns:
            bool | None:
                - ``True``  — lock acquired, this session should process the update.
                - ``False`` — update already handled, skip it.
                - ``None``  — another session is processing, caller should retry.
        """
        raise NotImplementedError

    @abstractmethod
    async def release(self, key: UpdateCoordinatorKeyT, result: Optional[UpdateLockState] = None) -> None:
        """
        Release the lock after processing.

        Parameters:
            key: The same key passed to acquire().
            result: ``UpdateLockState.HANDLED`` if processing succeeded,
                    ``None`` if it failed — key is deleted so another
                    session can retry.
        """
        raise NotImplementedError

    async def acquire(self, key: UpdateCoordinatorKeyT) -> bool:
        """
        Acquire the lock for the given key, blocking until the outcome
        of any concurrent processing is known.

        Parameters:
            key: A tuple of identifiers that uniquely identifies the update.

        Returns:
            bool:
                - ``True`` — lock acquired, process the update then call release().
                - ``False`` — already handled by another session, skip it.

        Raises:
            TimeoutError: if blocking_timeout is exceeded.
        """
        built_key = self.build_key(key)
        stop_at = time.monotonic() + self.blocking_timeout
        

        while True:
            result = await self._try_acquire(built_key)

            if result is not None:
                return result
            
            if time.monotonic() + self.sleep > stop_at:
                raise TimeoutError(f"Timeout waiting for lock on {built_key!r}")

            await asyncio.sleep(self.sleep)


    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass