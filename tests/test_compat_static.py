"""Static compatibility analysis against the declared minimum Python (3.10).

These tests parse every source file with the 3.10 grammar
(``ast.parse(..., feature_version=(3, 10))``) and assert that no typing
feature newer than the declared floor leaks into runtime code unguarded.

They run on any interpreter (they never execute the scanned code), so
they guard the 3.10 floor even while the suite itself runs on 3.14.
"""

from __future__ import annotations as _annotations

import ast
import pathlib
import sys
from typing import TYPE_CHECKING

import pytest
from packaging.requirements import Requirement

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised only on 3.10
    import tomli as tomllib

if TYPE_CHECKING:
    from typing import Any

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
PKG_ROOT = PROJECT_ROOT / "pyroflow"
PY_FILES = sorted(PKG_ROOT.rglob("*.py"))
FILE_IDS = [str(p.relative_to(PROJECT_ROOT)) for p in PY_FILES]


def _parse(path: pathlib.Path) -> ast.Module:
    # feature_version rejects 3.11+ syntax (except*, PEP 695) on newer interpreters
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path), feature_version=(3, 10))


@pytest.mark.parametrize("path", PY_FILES, ids=FILE_IDS)
def test_every_source_file_parses_with_310_grammar(path: pathlib.Path) -> None:
    compile(_parse(path), filename=str(path), mode="exec")


@pytest.mark.parametrize(
    "source",
    [
        "try:\n    pass\nexcept* ValueError:\n    pass\n",
        "type Alias = int\n",
        "class C[T]:\n    pass\n",
    ],
    ids=["except-star", "type-statement", "type-params"],
)
def test_310_grammar_rejects_newer_syntax(source: str) -> None:
    with pytest.raises(SyntaxError):
        ast.parse(source, feature_version=(3, 10))


def test_strenum_import_is_version_guarded() -> None:
    """``StrEnum`` is 3.11+ — still newer than the 3.10 floor. It must never
    be imported at module top level; a ``sys.version_info`` fallback has to
    guard it (regression guard for C1)."""
    tree = _parse(PKG_ROOT / "enums.py")
    top_level_imports = [
        node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    for node in top_level_imports:
        if isinstance(node, ast.ImportFrom) and node.module == "enum":
            names = {alias.name for alias in node.names}
            assert "StrEnum" not in names, (
                "StrEnum imported unguarded at module level in enums.py "
                "(breaks Python 3.10 — see audit finding C1)"
            )


# --------------------------------------------------------------------------
# Dependency-marker cross-checks
# --------------------------------------------------------------------------


def _load_pyproject() -> dict[str, Any]:
    with open(PROJECT_ROOT / "pyproject.toml", "rb") as fh:
        return tomllib.load(fh)


def test_declared_dependencies_have_floors() -> None:
    """Every runtime dependency declares a lower bound, as pyproject.toml promises."""
    deps = _load_pyproject()["project"]["dependencies"]
    reqs = [Requirement(d) for d in deps]
    assert {r.name.lower() for r in reqs} == {"kurigram", "pytrove"}
    assert all(any(s.operator == ">=" for s in r.specifier) for r in reqs)


def test_requires_python_floor_is_310() -> None:
    project = _load_pyproject()["project"]
    assert project["requires-python"] == ">=3.10"
    assert "Programming Language :: Python :: 3.9" not in project["classifiers"]
    assert "Programming Language :: Python :: 3.10" in project["classifiers"]
