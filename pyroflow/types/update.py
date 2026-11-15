"""Pyrogram's `Update`, with the moment the dispatcher received it."""

from __future__ import annotations as _annotations

from pyrogram.types import Update as PyroUpdate

from ..utils import patch_cls


@patch_cls
class Update(PyroUpdate):
    """Pyrogram `Update` with `arrived_at`, set by the dispatcher."""

    @property
    def arrived_at(self) -> float | None:
        """When the dispatcher received the update, on `time.monotonic()`; `None` if it did not come through one.

        The dispatcher notes it in `enqueue`, before the update waits for a
        worker or a lane, so it is the arrival even for an update that ran
        late. It is kept under a private name, which kurigram leaves out of
        `==`, `repr` and `str`.
        """
        return getattr(self, "_arrived_at", None)

    @arrived_at.setter
    def arrived_at(self, value: float | None) -> None:
        """Set when the dispatcher received the update.

        Args:
            value: The `time.monotonic()` reading, or `None`.
        """
        self._arrived_at = value


__all__ = ("Update",)
