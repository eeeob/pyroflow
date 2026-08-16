from typing import ClassVar, Tuple, Optional, Any, Generator, Dict, TYPE_CHECKING
from dataclasses import dataclass, field, fields, is_dataclass, Field
from itertools import combinations, count
from pyrogram.handlers import Handler as PyroHandler

from .utils.typings import JsonValue as JsonValueT, Number
from .utils import KeyDefaultDict, classproperty
from .typings import ListenerCoordinatorIdT

import asyncio
import time
import weakref


def _get_plan(mask: int) -> Tuple[int, ...]:
    optional = [i for i in range(mask.bit_length()) if mask >> i & 1]
    plan = []

    for size in range(len(optional), -1, -1):
        for combo in combinations(optional, size):
            keep = 0

            for i in combo:
                keep |= 1 << i

            plan.append(keep)

    return tuple(plan)


@dataclass(frozen=True, slots=True, eq=True, unsafe_hash=True)
class ListenerKey:
    PLANS: ClassVar[KeyDefaultDict[int, Tuple[int, ...]]] = KeyDefaultDict(_get_plan)
    FIELDS: ClassVar[Tuple[Field[Any], ...]]

    if not TYPE_CHECKING:
        @classproperty(cached=True)
        def FIELDS(cls):
            if not is_dataclass(cls):
                return cls.__dict__["FIELDS"]
            return fields(cls)

    chat_id: int
    user_id: Optional[int] = None
    message_id: Optional[int] = None

    @property
    def to_tuple(self) -> Tuple[int, Optional[int], Optional[int]]:
        return tuple(
            getattr(self, f.name)
            for f in self.FIELDS
        )

    def sub_keys(self, min_dep: int = 1) -> Generator["ListenerKey", None, None]:
        """
        Yield every key a listener for this update could be registered under,
        most specific first.

        ``chat_id`` is always present; the remaining components are each
        independently optional, so the candidates are the *combinations* of the
        components this key actually carries — not merely its prefixes::

            (chat, user, message)
            (chat, user)
            (chat, message)      # any user, but this specific message
            (chat)

        The third rung is the one prefix truncation could never reach: a
        listener registered as ``(chat, None, message)`` — "whoever answers
        *this* message" — used to be registrable but permanently unmatchable.

        Components this key does not carry are never invented, so the same key
        is never yielded twice — which prefix truncation did whenever a
        trailing component was ``None``.

        Priority between selections of equal size follows the order the
        components are declared in, so ``user_id`` outranks ``message_id``.
        That keeps resolution order unchanged for every key that does not use
        the new rung.

        Parameters:
            min_dep: Fewest components to yield down to, counting ``chat_id``.
                     The default of ``1`` includes the chat-only key; ``2``
                     stops before it.
        """

        values = self.to_tuple

        assert values[0] is not None

        mask = 0

        for i, value in enumerate(values):
            if i == 0:
                continue
            if value is not None:
                mask |= 1 << i

        for keep in ListenerKey.PLANS[mask]:
            if keep.bit_count() + 1 < min_dep:
                return

            yield ListenerKey(
                *(
                    value if (i == 0 or keep >> i & 1) else None
                    for i, value in enumerate(values)
                )
            )


@dataclass(slots=True)
class ListenerModel:
    key: ListenerKey
    meta: Optional[JsonValueT] = None
    future: asyncio.Future = field(default_factory=asyncio.Future)

    # Ownership token handed out by the coordinator at registration time.
    # A ListenerKey names *which* conversation slot this is; the id names
    # *which generation* of it. Cancellation travels between sessions
    # asynchronously, so a key alone cannot tell a live listener apart from
    # one that was superseded while a signal was still in flight — both
    # resolve() and _cancel() compare this token to stay on the right one.
    coordinator_id: Optional[ListenerCoordinatorIdT] = None


    def resolve(self, update) -> None:
        self.future.set_result(update)

    def set_exc(self, exc: Exception) -> None:
        self.future.set_exception(exc)

    def done(self) -> bool:
        return self.future.done()


class _WeakSlots:
    __slots__ = "__weakref__",


@dataclass(slots=True)
class UpdateRecord(_WeakSlots):
    _SEQ: ClassVar[int] = count()
    _SEQ_IDS: ClassVar[Dict[int, int]] = {}

    handler: PyroHandler
    data: Optional[Any] = None
    created_at: Number = field(default_factory=time.time)

    def __post_init__(self):
        cls = type(self)
        cls._SEQ_IDS[id(self)] = next(cls._SEQ)
        weakref.finalize(self, cls._SEQ_IDS.pop, id(self), None)

    def __lt__(self, other: "UpdateRecord") -> bool:
        return (
            (self.created_at, type(self)._SEQ_IDS[id(self)])
            < (other.created_at, type(other)._SEQ_IDS[id(other)])
        )
    def __gt__(self, other: "UpdateRecord") -> bool:
        return (
            (self.created_at, type(self)._SEQ_IDS[id(self)])
            > (other.created_at, type(other)._SEQ_IDS[id(other)])
        )



__all__ = (
    "ListenerKey", 
    "ListenerModel", 
    "UpdateRecord", 
)


