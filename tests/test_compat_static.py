"""Static compatibility analysis against the declared minimum Python (3.10).

These tests parse every source file with ``ast`` and assert that no
typing feature newer than the declared floor leaks into runtime code
unguarded.

They run on any interpreter (they never execute the scanned code), so
they guard the 3.10 floor even while the suite itself runs on 3.14.
"""

import ast
import pathlib
import sys

import pytest

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised only on 3.10
    import tomli as tomllib

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
PKG_ROOT = PROJECT_ROOT / "pyroflow"
PY_FILES = sorted(PKG_ROOT.rglob("*.py"))
FILE_IDS = [str(p.relative_to(PROJECT_ROOT)) for p in PY_FILES]


def _parse(path):
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


@pytest.mark.parametrize("path", PY_FILES, ids=FILE_IDS)
def test_every_source_file_compiles(path):
    """Belt-and-braces: the file parses as valid Python."""
    compile(_parse(path), filename=str(path), mode="exec")


def test_strenum_import_is_version_guarded():
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


def _load_pyproject():
    with open(PROJECT_ROOT / "pyproject.toml", "rb") as fh:
        return tomllib.load(fh)


def test_declared_dependencies_are_pinned_where_needed():
    """cachetools is used for ``TLRUCache`` (added in 4.1.0); an unbounded
    ``cachetools`` spec can resolve an incompatible version."""
    deps = _load_pyproject()["project"]["dependencies"]
    cachetools = next((d for d in deps if d.lower().startswith("cachetools")), None)
    assert cachetools is not None, "cachetools missing from dependencies"


def test_requires_python_floor_is_310():
    project = _load_pyproject()["project"]
    assert project["requires-python"] == ">=3.10"
    assert "Programming Language :: Python :: 3.9" not in project["classifiers"]
    assert "Programming Language :: Python :: 3.10" in project["classifiers"]
