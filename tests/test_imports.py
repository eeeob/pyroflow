"""Import-surface tests: every module imports cleanly and the global
``@patch_cls`` monkey-patch is applied to Pyrogram.

If any module pulled in an unguarded newer-Python feature (e.g. a bare
``StrEnum`` import) or an undeclared dependency, importing it here fails.
"""

from __future__ import annotations as _annotations

import importlib
import pkgutil
import re
import subprocess
import sys
from pathlib import Path

import pyrogram.dispatcher
import pyrogram.types
import pytest

import pyroflow

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

PROJECT_ROOT = Path(__file__).resolve().parent.parent

MODULES = [
    "pyroflow",
    "pyroflow.client",
    "pyroflow.dispatcher",
    "pyroflow.enums",
    "pyroflow.errors",
    "pyroflow.filters",
    "pyroflow.models",
    "pyroflow.types",
    "pyroflow.typings",
    "pyroflow.listener_coordinator",
    "pyroflow.listener_coordinator.listener_coordinator",
    "pyroflow.listener_coordinator.memory_listener_coordinator",
    "pyroflow.listener_coordinator.redis_listener_coordinator",
    "pyroflow.update_coordinated",
    "pyroflow.update_coordinated.update_coordinated",
    "pyroflow.update_coordinated.message_coordinated",
    "pyroflow.update_coordinated.callback_query_coordinated",
    "pyroflow.update_coordinator",
    "pyroflow.update_coordinator.update_coordinator",
    "pyroflow.update_coordinator.memory_update_coordinator",
    "pyroflow.update_coordinator.redis_update_coordinator",
    "pyroflow.update_history",
    "pyroflow.update_history.update_history",
    "pyroflow.update_history.message_history",
    "pyroflow.update_history.callback_query_history",
    "pyroflow.update_history_store",
    "pyroflow.update_history_store.update_history_store",
    "pyroflow.update_history_store.memory_update_history_store",
    "pyroflow.update_listener",
    "pyroflow.update_listener.update_listener",
    "pyroflow.update_listener.message_listener",
    "pyroflow.update_listener.callback_query_listener",
    "pyroflow.utils",
    "pyroflow.utils.classes",
    "pyroflow.utils.constants",
    "pyroflow.utils.misc_tools",
    "pyroflow.utils.typings",
]


@pytest.mark.parametrize("module", MODULES)
def test_module_imports(module: str) -> None:
    assert importlib.import_module(module) is not None


def test_redis_import_does_not_require_redis_installed() -> None:
    """The Redis backends must import even without ``redis`` present:
    every ``redis`` import is guarded by ``TYPE_CHECKING`` / local import."""
    importlib.import_module("pyroflow.listener_coordinator.redis_listener_coordinator")
    importlib.import_module("pyroflow.update_coordinator.redis_update_coordinator")


def test_global_monkey_patch_applied() -> None:
    # types.py patches replaced the Pyrogram classes themselves
    assert pyroflow.Message is pyrogram.types.Message
    assert pyroflow.CallbackQuery is pyrogram.types.CallbackQuery
    assert hasattr(pyrogram.types.Message, "ask")

    # client.py / dispatcher.py patches
    assert hasattr(pyroflow.Client, "ask")
    assert hasattr(pyrogram.dispatcher.Dispatcher, "register_listener")
    # preserve_old kept the originals around
    assert hasattr(pyrogram.dispatcher.Dispatcher, "old__init__")


def test_public_exports_present() -> None:
    for name in (
        "Client",
        "Dispatcher",
        "Message",
        "CallbackQuery",
        "MessageListener",
        "CallbackQueryListener",
        "MessageCoordinated",
        "CallbackQueryCoordinated",
        "MessageHistory",
        "CallbackQueryHistory",
    ):
        assert hasattr(pyroflow, name), f"pyroflow.{name} is not exported"


PACKAGES_WITH_ALL = [
    "pyroflow",
    *(
        info.name
        for info in pkgutil.walk_packages(pyroflow.__path__, "pyroflow.")
        if info.ispkg and hasattr(importlib.import_module(info.name), "__all__")
    ),
]

# hatchling's default `[tool.hatch.version]` regex for a `path` source.
HATCH_VERSION_PATTERN = r"^(__version__|VERSION) *= *(['\"])v?(?P<version>.+?)\2"


@pytest.mark.parametrize("package", PACKAGES_WITH_ALL)
def test_package_all_is_well_formed(package: str) -> None:
    module = importlib.import_module(package)
    exported = module.__all__

    assert isinstance(exported, tuple), f"{package}.__all__ is not a tuple"
    assert len(exported) == len(set(exported)), f"{package}.__all__ has duplicates"
    assert not [name for name in exported if name.startswith("_")]
    missing = [name for name in exported if not hasattr(module, name)]
    assert not missing, f"{package}.__all__ names missing attributes: {missing}"


@pytest.mark.parametrize("package", PACKAGES_WITH_ALL)
def test_star_import_matches_all(package: str) -> None:
    namespace: dict[str, object] = {}
    exec(f"from {package} import *", namespace)
    imported = {name for name in namespace if not name.startswith("__")}

    assert imported == set(importlib.import_module(package).__all__)


def test_version_line_matches_hatch_pattern() -> None:
    source = (PROJECT_ROOT / "pyroflow" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(HATCH_VERSION_PATTERN, source, re.MULTILINE)

    assert match is not None, "hatchling cannot find the version in pyroflow/__init__.py"
    assert match.group("version") == pyroflow.__version__


def test_all_modules_import_without_redis() -> None:
    """Every module imports when the optional ``redis`` extra is absent."""
    script = (
        "import importlib, pkgutil, sys\n"
        "sys.modules['redis'] = None\n"
        "import pyroflow\n"
        "for info in pkgutil.walk_packages(pyroflow.__path__, 'pyroflow.'):\n"
        "    importlib.import_module(info.name)\n"
        "print('ok')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=PROJECT_ROOT,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout, result.stderr


def test_only_redis_extra_is_declared() -> None:
    with open(PROJECT_ROOT / "pyproject.toml", "rb") as fh:
        extras = tomllib.load(fh)["project"].get("optional-dependencies", {})

    assert set(extras) == {"redis"}
