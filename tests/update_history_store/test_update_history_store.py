"""Tests for the ``UpdateHistoryStore`` abstract base."""

from __future__ import annotations as _annotations

from typing import Any

import pytest

from pyrogram.types import Message

from pyroflow.models import UpdateRecord
from pyroflow.update_history_store.update_history_store import UpdateHistoryStore


class _SuperStore(UpdateHistoryStore):
    """Concrete store whose methods defer to the abstract bodies."""

    async def update(self, key: Any, *records: UpdateRecord) -> None:
        await super().update(key, *records)

    async def get(self, key: Any) -> list[UpdateRecord]:
        return list(await super().get(key))

    async def pop(self, key: Any) -> list[UpdateRecord]:
        return list(await super().pop(key))

    async def delete(self, key: Any) -> None:
        await super().delete(key)


def test_init_passes_extra_kwargs_along_the_mro() -> None:
    class _Mixin:
        def __init__(self, *, extra: int, **kw: Any) -> None:
            self.extra = extra
            super().__init__(**kw)

    class _MixedStore(_SuperStore, _Mixin):
        pass

    store = _MixedStore(Message, extra=3)
    assert (store.update_type, store.extra) == (Message, 3)


@pytest.mark.parametrize(
    ("method", "args"),
    [
        ("update", ("k", UpdateRecord(handler="h"))),
        ("get", ("k",)),
        ("pop", ("k",)),
        ("delete", ("k",)),
    ],
)
async def test_abstract_bodies_raise_not_implemented(method: str, args: tuple[Any, ...]) -> None:
    with pytest.raises(NotImplementedError):
        await getattr(_SuperStore(Message), method)(*args)
