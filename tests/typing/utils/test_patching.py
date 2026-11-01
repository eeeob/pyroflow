"""Static type tests for ``pyroflow.utils.patching``."""

from __future__ import annotations as _annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing_extensions import assert_type

    from pyroflow.utils import patch_cls

    class _Base:
        pass

    @patch_cls
    class _Patch(_Base):
        pass

    @patch_cls(preserve_old=False, include_dunders=())
    class _OptionsPatch(_Base):
        pass

    def _check_patch_cls() -> None:
        assert_type(_Patch(), _Patch)
        assert_type(_OptionsPatch(), _OptionsPatch)
        assert_type(patch_cls(preserve_old=True)(_Base)(), _Base)

    def _check_patch_cls_rejects() -> None:
        patch_cls(1)  # ty: ignore[invalid-argument-type]
        patch_cls(preserve_old=True)(1)  # ty: ignore[invalid-argument-type]
        patch_cls(include_dunders=["__init__"])  # ty: ignore[invalid-argument-type]


def test_type_checks_are_not_defined_at_runtime() -> None:
    assert "_check_patch_cls" not in globals()
