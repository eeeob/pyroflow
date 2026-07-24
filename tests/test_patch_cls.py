"""Tests for the ``@patch_cls`` machinery and ``UpdateBound`` enforcement.

These cover the library's most load-bearing and least obvious mechanism:
monkey-patching Pyrogram base classes in-place.
"""

from abc import ABC

import pytest

from pyroflow.utils import patch_cls, UpdateBound
from pyrogram.types import Message


def test_patch_cls_moves_members_onto_base_and_returns_base():
    class Base:
        def foo(self):
            return "base-foo"

    @patch_cls
    class Patch(Base):
        def foo(self):
            return "patched-foo"

        def bar(self):
            return "patched-bar"

    # The decorator returns the *base* class, not the subclass.
    assert Patch is Base
    assert Base().foo() == "patched-foo"
    assert Base().bar() == "patched-bar"


def test_patch_cls_preserves_old_members():
    class Base:
        def greet(self):
            return "old"

    @patch_cls
    class Patch(Base):
        def greet(self):
            return "new"

    instance = Base()
    assert instance.greet() == "new"
    assert instance.oldgreet() == "old"  # preserve_old=True default


def test_patch_cls_rejects_multiple_bases():
    class A:
        pass

    class B:
        pass

    with pytest.raises(TypeError):

        @patch_cls
        class C(A, B):  # pragma: no cover - decoration raises
            pass


def test_patch_cls_only_patches_init_among_dunders_by_default():
    class Base:
        pass

    @patch_cls
    class Patch(Base):
        def __init__(self):
            self.marked = True

        def __repr__(self):  # pragma: no cover - should NOT be copied
            return "patched-repr"

    assert Base().marked is True
    # __repr__ is a dunder outside include_dunders, so it was skipped.
    assert "patched-repr" not in repr(Base())


# --- UpdateBound ----------------------------------------------------------


def test_update_bound_accepts_valid_pyrogram_update_type():
    class Good(UpdateBound):
        __update_type__ = Message

    assert Good.__update_type__ is Message


def test_update_bound_requires_update_type():
    with pytest.raises(TypeError):

        class Missing(UpdateBound):  # pragma: no cover - class body raises
            pass


def test_update_bound_rejects_non_update_type():
    with pytest.raises(TypeError):

        class BadType(UpdateBound):  # pragma: no cover - class body raises
            __update_type__ = int


def test_update_bound_abstract_subclass_is_exempt():
    # An ABC subclass is allowed to omit __update_type__ (it is abstract).
    class StillAbstract(ABC, UpdateBound):
        pass

    assert not hasattr(StillAbstract, "__update_type__")


def test_validate_update_type_check():
    class Good(UpdateBound):
        __update_type__ = Message

    Good.validate_update(Message(id=1))  # no raise
    with pytest.raises(TypeError):
        Good.validate_update(object())
