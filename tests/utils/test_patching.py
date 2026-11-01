"""Tests for the ``@patch_cls`` machinery.

These cover the library's most load-bearing and least obvious mechanism:
monkey-patching Pyrogram base classes in-place.
"""

from __future__ import annotations as _annotations

import inspect

import pytest

from pyroflow.utils import patch_cls, patch_setter
from pyroflow.utils import patching


def test_patch_cls_moves_members_onto_base_and_returns_base() -> None:
    class Base:
        def foo(self) -> str:
            return "base-foo"

    @patch_cls
    class Patch(Base):
        def foo(self) -> str:
            return "patched-foo"

        def bar(self) -> str:
            return "patched-bar"

    # The decorator returns the *base* class, not the subclass.
    assert Patch is Base
    assert Base().foo() == "patched-foo"
    assert Base().bar() == "patched-bar"


def test_patch_cls_preserves_old_members() -> None:
    class Base:
        def greet(self) -> str:
            return "old"

    @patch_cls
    class Patch(Base):
        def greet(self) -> str:
            return "new"

    instance = Base()
    assert instance.greet() == "new"
    assert instance.oldgreet() == "old"  # preserve_old=True default


def test_patch_cls_rejects_multiple_bases() -> None:
    class A:
        pass

    class B:
        pass

    with pytest.raises(TypeError):

        @patch_cls
        class C(A, B):  # pragma: no cover - decoration raises
            pass


def test_patch_cls_only_patches_init_among_dunders_by_default() -> None:
    class Base:
        pass

    @patch_cls
    class Patch(Base):
        def __init__(self) -> None:
            self.marked = True

        def __repr__(self) -> str:  # pragma: no cover - should NOT be copied
            return "patched-repr"

    assert Base().marked is True
    # __repr__ is a dunder outside include_dunders, so it was skipped.
    assert "patched-repr" not in repr(Base())


def test_patch_cls_decorator_form_without_patch_class() -> None:
    class Base:
        pass

    decorator = patch_cls(preserve_old=False)
    assert callable(decorator)

    class Patch(Base):
        def added(self) -> str:
            return "added"

    assert decorator(Patch) is Base
    assert Base().added() == "added"


def test_patch_cls_preserve_old_false_drops_the_old_member() -> None:
    class Base:
        def greet(self) -> str:
            return "old"

    @patch_cls(preserve_old=False)
    class Patch(Base):
        def greet(self) -> str:
            return "new"

    assert Base().greet() == "new"
    assert not hasattr(Base, "oldgreet")


def test_patch_cls_uses_a_custom_setter() -> None:
    calls: list[tuple[type, str]] = []

    def setter(cls: type, name: str, attr: object) -> None:
        calls.append((cls, name))
        setattr(cls, name, attr)

    class Base:
        pass

    @patch_cls(setter=setter)
    class Patch(Base):
        async def run(self) -> str:
            return "ran"

    assert (Base, "run") in calls
    # The custom setter replaced patch_setter, so no sync wrapper was added.
    assert not hasattr(Base.run, "__wrapped__")


def test_patch_cls_include_dunders_copies_listed_dunders() -> None:
    class Base:
        pass

    @patch_cls(include_dunders=("__repr__",))
    class Patch(Base):
        def __repr__(self) -> str:
            return "patched-repr"

    assert repr(Base()) == "patched-repr"


async def test_patch_cls_default_setter_wraps_coroutine_methods() -> None:
    class Base:
        pass

    @patch_cls
    class Patch(Base):
        async def run(self) -> str:
            return "ran"

    assert inspect.iscoroutinefunction(Base.run.__wrapped__)
    assert await Base().run() == "ran"


# --- patch_setter ---------------------------------------------------------


async def test_patch_setter_wraps_a_coroutine_function() -> None:
    class Greeter:
        pass

    async def greet(self: object) -> str:
        return "hi"

    patch_setter(Greeter, "greet", greet)

    assert Greeter.greet is not greet
    assert Greeter.greet.__wrapped__ is greet
    # Inside a running loop the wrapper hands back the coroutine to await.
    assert await Greeter().greet() == "hi"


def test_patch_setter_sets_a_sync_function_unchanged() -> None:
    class Greeter:
        pass

    def greet(self: object) -> str:
        return "hi"

    patch_setter(Greeter, "greet", greet)

    assert Greeter.greet is greet
    assert Greeter().greet() == "hi"


def test_patch_setter_sets_a_plain_value_unchanged() -> None:
    class Holder:
        pass

    patch_setter(Holder, "value", 42)

    assert Holder.value == 42


def test_module_all_lists_public_names() -> None:
    assert patching.__all__ == ("patch_setter", "patch_cls")
    assert all(hasattr(patching, name) for name in patching.__all__)
