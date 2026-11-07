"""Static type tests for `pyroflow.typings`."""

from __future__ import annotations as _annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing_extensions import assert_type

    from pyroflow.models import ListenerModel, MessageKey
    from pyroflow.typings import KeyT

    def _key_of(model: ListenerModel[KeyT]) -> KeyT:
        return model.key

    def _check_key_type(model: ListenerModel[MessageKey]) -> None:
        assert_type(_key_of(model), MessageKey)
        ListenerModel[str]  # ty: ignore[invalid-type-arguments]
