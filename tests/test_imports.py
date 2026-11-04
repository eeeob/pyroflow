"""Import-surface tests: every module imports cleanly and exports a
well-formed ``__all__``.

If any module pulled in an unguarded newer-Python feature (e.g. a bare
``StrEnum`` import) or an undeclared dependency, importing it here fails.
"""

from __future__ import annotations as _annotations

import ast
import importlib
import pkgutil
import re
import sys
from pathlib import Path

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
    "pyroflow.constants",
    "pyroflow.dispatcher",
    "pyroflow.enums",
    "pyroflow.errors",
    "pyroflow.filters",
    "pyroflow.models",
    "pyroflow.types",
    "pyroflow.typings",
    "pyroflow.update_listener",
    "pyroflow.update_listener.update_listener",
    "pyroflow.update_listener.message_listener",
    "pyroflow.update_listener.callback_query_listener",
    "pyroflow.update_listener.message_listen_cancelling_callback_query_listener",
    "pyroflow.utils",
    "pyroflow.utils.bot_commands",
    "pyroflow.utils.helpers",
    "pyroflow.utils.patching",
]


def test_modules_list_is_complete() -> None:
    walked = {info.name for info in pkgutil.walk_packages(pyroflow.__path__, "pyroflow.")}

    assert walked | {"pyroflow"} == set(MODULES)


def test_public_exports_present() -> None:
    for name in (
        "Client",
        "Dispatcher",
        "Message",
        "CallbackQuery",
        "MessageListener",
        "CallbackQueryListener",
        "MessageListenCancellingCallbackQueryListener",
    ):
        assert hasattr(pyroflow, name), f"pyroflow.{name} is not exported"


PACKAGES = [
    "pyroflow",
    *(info.name for info in pkgutil.walk_packages(pyroflow.__path__, "pyroflow.") if info.ispkg),
]
IMPLEMENTATION_MODULES = [name for name in MODULES if name not in PACKAGES]

# hatchling's default `[tool.hatch.version]` regex for a `path` source.
HATCH_VERSION_PATTERN = r"^(__version__|VERSION) *= *(['\"])v?(?P<version>.+?)\2"


def _module_tree(name: str) -> ast.Module:
    path = importlib.import_module(name).__file__
    assert path is not None
    return ast.parse(Path(path).read_text(encoding="utf-8"))


def _is_all_assignment(node: ast.stmt) -> bool:
    return isinstance(node, ast.Assign) and any(
        isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets
    )


@pytest.mark.parametrize("module_name", MODULES)
def test_all_is_well_formed(module_name: str) -> None:
    module = importlib.import_module(module_name)
    exported = module.__all__

    assert isinstance(exported, tuple), f"{module_name}.__all__ is not a tuple"
    assert len(exported) == len(set(exported)), f"{module_name}.__all__ has duplicates"
    assert not [name for name in exported if name.startswith("_")]
    missing = [name for name in exported if not hasattr(module, name)]
    assert not missing, f"{module_name}.__all__ names missing attributes: {missing}"


@pytest.mark.parametrize("module_name", MODULES)
def test_all_comes_last(module_name: str) -> None:
    assert _is_all_assignment(_module_tree(module_name).body[-1])


@pytest.mark.parametrize("module_name", MODULES)
def test_star_import_matches_all(module_name: str) -> None:
    namespace: dict[str, object] = {}
    exec(f"from {module_name} import *", namespace)
    imported = {name for name in namespace if not name.startswith("__")}

    assert imported == set(importlib.import_module(module_name).__all__)


@pytest.mark.parametrize("module_name", IMPLEMENTATION_MODULES)
def test_implementation_module_has_no_wildcard_import(module_name: str) -> None:
    wildcards = [
        node
        for node in ast.walk(_module_tree(module_name))
        if isinstance(node, ast.ImportFrom) and any(alias.name == "*" for alias in node.names)
    ]

    assert not wildcards


@pytest.mark.parametrize("package", PACKAGES)
def test_package_all_is_the_union_of_its_star_imports(package: str) -> None:
    module = importlib.import_module(package)
    sources = [
        node.module
        for node in _module_tree(package).body
        if isinstance(node, ast.ImportFrom)
        and node.level == 1
        and node.module
        and [alias.name for alias in node.names] == ["*"]
    ]
    expected = [
        name
        for source in sources
        for name in importlib.import_module(f"{package}.{source}").__all__
    ]
    # pyroflow exposes the filters submodule itself, not its contents.
    exported = [
        name for name in module.__all__ if not (package == "pyroflow" and name == "filters")
    ]

    assert sources, f"{package} star-imports nothing"
    assert exported == expected
    assert "__version__" not in module.__all__


def test_version_line_matches_hatch_pattern() -> None:
    source = (PROJECT_ROOT / "pyroflow" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(HATCH_VERSION_PATTERN, source, re.MULTILINE)

    assert match is not None, "hatchling cannot find the version in pyroflow/__init__.py"
    assert match.group("version") == pyroflow.__version__


def test_no_extras_are_declared() -> None:
    with open(PROJECT_ROOT / "pyproject.toml", "rb") as fh:
        project = tomllib.load(fh)["project"]

    assert "optional-dependencies" not in project
