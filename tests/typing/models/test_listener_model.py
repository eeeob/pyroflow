"""Static type tests for `pyroflow.models.listener_model`."""

from __future__ import annotations as _annotations

from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from typing_extensions import assert_type

    from pyroflow.models import ListenerContext, ListenerModel, MessageKey
    from pyroflow.types import Message

    class _OrderContext(ListenerContext):
        step: int = 0

    def _check_context(
        context: ListenerContext, order: _OrderContext, model: ListenerModel
    ) -> None:
        assert_type(context.message, Message | None)
        assert_type(context.note, Any)
        context.note = "x"
        assert_type(order.step, int)
        assert_type(order.message, Message | None)
        assert_type(model.context, ListenerContext | None)

    def _check_model(model: ListenerModel[MessageKey]) -> None:
        assert_type(model.key, MessageKey)
        ListenerModel[int]  # ty: ignore[invalid-type-arguments]
