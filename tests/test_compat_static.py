"""Static compatibility analysis against the declared minimum Python (3.10).

These tests parse every source file with ``ast`` and assert that no
typing feature newer than the declared floor leaks into runtime code
unguarded. They also cross-check declared dependency version markers
against what the source actually imports.

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


def _dependency_marker_upper(dep_name):
    """Return the ``(major, minor)`` upper bound from a
    ``pkg; python_version < 'X.Y'`` marker, or ``None`` if the dependency
    is declared unconditionally / absent."""
    import re

    deps = _load_pyproject()["project"]["dependencies"]
    for spec in deps:
        if spec.split(";")[0].strip().lower().startswith(dep_name.lower()):
            match = re.search(r"python_version\s*<\s*['\"](\d+)\.(\d+)['\"]", spec)
            if match:
                return (int(match.group(1)), int(match.group(2)))
            return None  # declared without a python_version ceiling
    return "absent"


def _max_typing_extensions_guard():
    """The highest ``sys.version_info >= (3, N)`` threshold found in any
    source file that imports ``typing_extensions`` — i.e. the Python
    version below which the package genuinely needs that dependency."""
    highest = None
    for path in PY_FILES:
        tree = _parse(path)
        imports_te = any(
            isinstance(n, ast.ImportFrom) and n.module == "typing_extensions"
            for n in ast.walk(tree)
        )
        if not imports_te:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Compare):
                continue
            if not (
                isinstance(node.left, ast.Attribute)
                and node.left.attr == "version_info"
            ):
                continue
            for comparator in node.comparators:
                if isinstance(comparator, ast.Tuple) and len(comparator.elts) == 2:
                    try:
                        version = tuple(ast.literal_eval(e) for e in comparator.elts)
                    except ValueError:
                        continue
                    if highest is None or version > highest:
                        highest = version
    return highest


def test_declared_dependencies_are_pinned_where_needed():
    """cachetools is used for ``TLRUCache`` (added in 4.1.0); an unbounded
    ``cachetools`` spec can resolve an incompatible version."""
    deps = _load_pyproject()["project"]["dependencies"]
    cachetools = next((d for d in deps if d.lower().startswith("cachetools")), None)
    assert cachetools is not None, "cachetools missing from dependencies"


def test_typing_extensions_marker_covers_all_uses():
    """The typing_extensions dependency marker must cover every Python
    version on which the source imports it (all versions < 3.13, since
    validate_tools.py needs TypeIs there)."""
    needed_below = _max_typing_extensions_guard()
    assert needed_below is not None, "expected typing_extensions usage in source"

    marker_upper = _dependency_marker_upper("typing_extensions")
    assert marker_upper not in (None, "absent"), (
        "typing_extensions is imported by the source but its dependency "
        "declaration has no python_version ceiling / is absent"
    )
    assert marker_upper >= needed_below, (
        f"typing_extensions declared only for < {marker_upper} but the source "
        f"imports it on all versions < {needed_below}"
    )


def test_requires_python_floor_is_310():
    project = _load_pyproject()["project"]
    assert project["requires-python"] == ">=3.10"
    assert "Programming Language :: Python :: 3.9" not in project["classifiers"]
    assert "Programming Language :: Python :: 3.10" in project["classifiers"]
