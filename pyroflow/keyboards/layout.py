"""`arrange`: split buttons into the rows of a keyboard."""

from __future__ import annotations as _annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from pytrove.typings import _T


def arrange(
    buttons: Sequence[_T],
    *,
    columns: int | None = None,
    layout: Sequence[int] | None = None,
    repeat: bool = False,
) -> list[list[_T]]:
    """Split buttons into rows, one button per row without `columns` or `layout`.

    Args:
        buttons: The buttons, in order.
        columns: Buttons per row.
        layout: Row sizes; after the last one, its size goes on.
        repeat: Whether `layout` starts over after its last size instead.

    Returns:
        The rows.

    Raises:
        ValueError: If `columns` and `layout` come together, or a width is not
            positive.

    Example:
        >>> arrange(["a", "b", "c", "d"], layout=[1, 2])
        [['a'], ['b', 'c'], ['d']]
    """
    if columns is not None and layout is not None:
        msg = "Pass columns or layout, not both"
        raise ValueError(msg)

    if (columns is not None and columns <= 0) or (
        layout is not None and (not layout or min(layout) <= 0)
    ):
        msg = "columns and layout sizes must be positive"
        raise ValueError(msg)

    result: list[list[_T]] = []
    start = 0

    while start < len(buttons):
        if layout is not None:
            index = len(result) % len(layout) if repeat else min(len(result), len(layout) - 1)
            width = layout[index]
        else:
            width = columns or 1

        result.append(list(buttons[start : start + width]))
        start += width

    return result


__all__ = ("arrange",)
