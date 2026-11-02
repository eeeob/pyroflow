"""Static type tests for ``pyroflow.utils.patching``."""

from __future__ import annotations as _annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyroflow.utils import patch_cls

    def _check_patch_cls_rejects() -> None:
        patch_cls(1)  # ty: ignore[invalid-argument-type]
        patch_cls(preserve_old=True)(1)  # ty: ignore[invalid-argument-type]
        patch_cls(include_dunders=["__init__"])  # ty: ignore[invalid-argument-type]
