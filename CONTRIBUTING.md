# Contributing to `pyroflow`

An Arabic translation is kept in [`CONTRIBUTING.ar.md`](CONTRIBUTING.ar.md); this English text is the reference when the two differ.

This file is the single source of the project's rules. It has two parts:

- **The workflow:** takes a change from a fresh clone to a merged pull request.
- **The rules:** the ones the workflow points at.

Rules keep their numbers so reviews, commits and code comments can cite them.

The mechanical rules are enforced by `ruff` and `ty`, configured only in `pyproject.toml` under `[tool.ruff]` and `[tool.ty]`. Each selected rule set names the rule it enforces, and each ignore says why. The rest are checked in review.

## The workflow

### 1. Set up once

`uv` and `make` are the only prerequisites. `uv` provisions the interpreter and the locked environment.

Every command is a `make` recipe. The `Makefile` is the one place commands are written down, and CI and the pre-commit hooks call the same recipes.

```bash
make sync    # the locked environment, with every tooling group
make hooks   # run `make lint` and `make typecheck` before each commit
```

### 2. Start a branch

Branch from `main`, one cohesive change per branch, ending in its own pull request (6.8).

### 3. Put each piece where it belongs

| What you are adding | Where it goes | Rule |
|---|---|---|
| A method or property on a Pyrogram type | inside the `@patch_cls` class that patches that type | 2.1, 2.2 |
| Support for a new update type | a listener in `pyroflow.update_listener` | 2.3 |
| An enum, type alias, model, error or public constant | `pyroflow.enums`, `pyroflow.typings`, `pyroflow.models`, `pyroflow.errors`, `pyroflow.constants` (created with the first one) | 1.4, 2.4 |
| A helper | `pyroflow.utils` when sections share it, the section's `_internal.py` when one section uses it; `pytrove` first | 1.5 |
| Type hints of the Pyrogram arguments the `ask_*` methods take | `pyroflow._internal`, never exported | 1.7–1.9 |
| A dependency | an extra, unless every feature needs it | 3.1–3.3 |
| A test | the `tests/` path that mirrors the module; static type tests in `tests/typing/` | 0.1 |

Every new public name goes into its module's `__all__` and reaches users through its package's `__init__.py` (1.7–1.9).

Files are cut by responsibility, not by element type, and stay cohesive (4.1, 4.2).

### 4. Write the code

- Lay each module out in the fixed order (4.3).
- Annotate completely, with modern syntax and deferred annotations (5.1, 5.2, 5.6).
- Declare constants as `Final` (5.3).
- Guard and raise as 5.5 says.
- Keep `import pyroflow` free of any effect beyond the patch (1.6).
- Every suppression names its code and reason (5.7), and every log call goes through the module logger (5.8).
- Write for the reader (6.1, 6.2).

### 5. Test it

Test every element you added or changed, at the path that mirrors its module (0.1, 0.2).

Nothing touches a real server, the network or Telegram (0.3).

### 6. Document it

- Give every function and class a Google-style docstring (6.3).
- Give every module-level variable, field, enum member and attribute its own docstring (6.4).
- Add an `Example` doctest where a usage example helps (6.5).
- Public documentation explains concepts and links to the single source of anything that changes (6.6).

### 7. Run the checks

| Recipe | Runs | When |
|---|---|---|
| `make format` | `ruff format` on the library and the tests | before committing |
| `make lint` | `ruff check` and the format check | on each commit (hook) |
| `make typecheck` | `ty` on the library, and on `tests/typing/` with warnings as errors | on each commit (hook) |
| `make test` | the suite in the locked environment | on every change |
| `make test-doctest` | every docstring `Example` as a doctest | when adding or changing an example |
| `make test-minimal` | import and the suite in a fresh environment installed from source | when touching imports or dependencies |
| `make test-floor` | the suite with every dependency at the lowest version its floor allows, on the oldest Python | when adding a dependency or changing a bound |
| `make test-ceil` | the suite with every dependency at its newest release, on the newest Python | when adding a dependency or changing a bound |
| `make build` | the sdist and the wheel | when touching packaging |

CI runs every check above except `make format` and `make build` on each pull request, with `make test` and `make test-minimal` on every supported Python, and `make test-floor` and `make test-ceil` on the oldest and the newest (1.1).

A rule set is never narrowed, nor an ignore widened, in `pyproject.toml` to make a change pass (1.10).

### 8. Commit and open the pull request

Write Conventional Commits. A breaking change carries its `!` and its `BREAKING CHANGE` note with the migration (1.3, 6.7).

Open the pull request from your branch into `main` (6.8).

## The rules

### Priority 0 — Tests

**0.1 Test tree.** `tests/` mirrors the library's package structure: one test file per module, in the directory of its package. `tests/typing/` holds the static type tests (`assert_type` checks, and calls that must fail `ty`), checked by `make typecheck`. Unrelated tests are never grouped in a general file.

**0.2 Every element is tested.** Every function, class, method, property, helper, constant, enum and module-level definition has a test of its own: its behaviour, its branches, its edge cases and its error paths. Coverage that happens incidentally through another element's test does not count. The public entry points (1.2) are tested too.

**0.3 No outside world.** Tests never use a real server, the network or Telegram, and the suite passes on a fresh install of the package with only the test tools (`make test-minimal`).

### Priority 1 — Compatibility and the public interface

**1.1 Python versions.** The library supports Python 3.10 through 3.14, because the classifiers and the CI matrix promise them. Syntax stays within 3.10; a newer standard-library API is used only behind a `sys.version_info` check, with its backport on older versions.

**1.2 Entry points.** Users import from these, each of which collects the public elements of its kind and nothing internal:

```python
from pyroflow import *        # every public tool
import pyroflow.typings       # type aliases
import pyroflow.errors        # exceptions
import pyroflow.models        # data models
import pyroflow.enums         # enums

from pyroflow.errors import ListenerTimeout   # a single name stays importable
```

Helpers are imported from `pyroflow.utils` directly.

**1.3 Compatibility.** The names in `__all__`, their signatures and their observable behaviour are the public interface. Nothing in it is removed or broken without documentation, an assessment of the impact and a migration path. Gradual deprecation is preferred over an immediate break, and a break is never silent.

**1.4 Sections by responsibility.** Every element belongs to one section: enums, typings, models, errors, constants, or the tools. Enum, type, model and error code never lives in a tool or helper file. Every public constant lives in `pyroflow.constants`, created with the first one, under a name that says what it is; a private constant (`_NAME`) stays beside the code that uses it.

**1.5 Helpers.** Helpers shared by sections live in `pyroflow.utils`, grouped by responsibility into cohesive modules, not one tiny module per function. A helper that only one section uses lives in that section's own `_internal.py`. Before writing a general-purpose helper, check `pytrove`, which is already a dependency, and import it from `pytrove` directly. A type or helper `pytrove` already provides (`StrInt`, `Number`, `MaybeList`, `MaybeCoroutineCallable`, ...) is imported from `pytrove`, never spelled out again; `pyroflow` may still keep a public alias name defined through it. External names are never re-exported through `pyroflow`.

**1.6 Import has one side effect.** `import pyroflow` patches Pyrogram's classes in place (`pyroflow.Client is pyrogram.Client`) and does nothing else: no I/O, no network.

**1.7 Public versus internal.** Every module lists its exports in `__all__`, and only those names are public. An internal helper never reaches the public interface by accident.

**1.8 Aggregated interfaces.** A package exposes one unified interface from its `__init__.py`. Users never need to know the internal file layout.

**1.9 `__all__` and wildcard imports.** `__all__` comes last in every module. Wildcard imports appear only in aggregation `__init__.py` files, which contain nothing but the docstring, `from .<module> import *` lines and `__all__ = (*<module>.__all__, ...)`. The star import already binds each submodule's name, so no `from . import <module>` is needed to reach its `__all__`, and these files carry no `__future__` import. The top-level `pyroflow/__init__.py` also holds the `__version__` line the build backend reads, right after the module docstring and before the imports.

**1.10 Code versus rule.** Code that violates a rule is fixed. A rule is never weakened to justify code.

### Priority 2 — Pyrogram integration

**2.1 Patch, don't subclass.** Methods added to Pyrogram types (`Client`, `Message`, `User`, ...) go inside the class decorated with `@patch_cls`, never in a subclass, so users keep using Pyrogram's own classes.

**2.2 Override signatures.** An override that calls its kurigram original takes `*args, **kw` and passes them on, with pyroflow's own parameters keyword-only between them (`def __init__(self, *args, key_functions=(), **kw)`), so a kurigram signature change needs no change here. One that replaces the original without calling it (`Dispatcher.handler_worker(self)`) and a filter's `__call__(self, client, update)` keep kurigram's signature; change one only after checking it against the installed `kurigram`.

**2.3 A new update type gets its listener.** Support for it is an `XListener` bound to the type with `__update_type__`.

**2.4 Errors.** A new error lives in `pyroflow.errors` and subclasses its family: `ListenerError` for waiting and the `ask_*` methods, or `PyroflowError` when it does not fit. Its class docstring is the message template, formatted with the value at raise time.

### Priority 3 — Dependencies

**3.1 Optional by default.** A dependency that only one feature needs is an extra, never required by the rest of the library.

**3.2 Version bounds.** Every dependency has a floor and, by default, no ceiling. The reason for each bound is a comment beside it in `pyproject.toml`. A ceiling is added only for a real break in a major version, with its reason.

**3.3 Adding a dependency.** Add it to its extra, or to `[project] dependencies` if every feature needs it, with the reason for its bound (3.2). Run `uv lock` and commit `uv.lock` with it. Tooling goes into a `[dependency-groups]` group, never an extra.

### Priority 4 — Files and layout

**4.1 Files by responsibility.** Files are grouped by function and logic, never by element type.

**4.2 File size.** Keep a module under about 300 lines; past that, prefer splitting it into cohesive submodules. This is a recommendation, not a hard limit: a split that only spreads lines around is worse than a long cohesive file.

**4.3 Module order.** Every module follows this order:

1. The module docstring.
2. `from __future__ import annotations as _annotations`.
3. Imports: standard library, then external, then internal, separated by blank lines.
4. Constants and type definitions.
5. Classes.
6. Functions.
7. `__all__`.

A definition that something above it needs at import time moves up, with a comment saying why. Inside one `from ... import (...)`, names go in this order: classes, functions, constants, ordinary variables.

```python
from logging import Handler, Logger, getLogger, DEBUG, root
```

### Priority 5 — Types, constants and runtime behaviour

**5.1 Type syntax.** Built-in generics (`list[str]`) and `|` unions, never the deprecated `typing` aliases (`UP`).

**5.2 Deferred annotations.** Every module starts with `from __future__ import annotations as _annotations` after its docstring; the `_annotations` alias marks it as an import kept for its side effect. Names imported under `TYPE_CHECKING` are then used unquoted, and quoted annotations are prohibited (`I002`, `UP037`). The exceptions: aggregation `__init__.py` files, which have no annotations, and the target of `typing.cast`, which is quoted (`TC006`).

**5.3 Constants.** A module constant is `NAME: Final[T] = value`. A class constant is `NAME: ClassVar[T] = value`, never `ClassVar[Final[T]]`. `__version__` takes no `Final`, because the build backend reads it as a plain assignment. An attribute meant to be overridden is a setting, not a constant: lower-case, with a plain annotation.

**5.4 Omitted versus `None`.** When omitting an argument must differ from passing `None`, its default is the `object` class itself, tested with `is object`; `None` stays a value the caller can pass on purpose.

**5.5 Guards and exceptions.** `assert` is never a runtime guard: `python -O` strips it (`S101`). An exception's message is assigned to a variable before the `raise`, so the traceback does not print it twice (`EM`).

```python
# Correct
if timeout <= 0:
    msg = f"timeout must be positive, got {timeout}"
    raise ValueError(msg)

# Incorrect
assert timeout > 0
raise ValueError(f"timeout must be positive, got {timeout}")
```

**5.6 Complete type hints.** Every parameter and return value is annotated (`ANN`). `Any` is allowed only where it is the honest type, never as a way around a type error. Hints pass `ty`.

**5.7 Suppressions carry reasons.** Every `type: ignore`, `ty: ignore` and `noqa` names its code, followed by the reason (`PGH`).

```python
"""Listener for {value} timed out"""  # noqa: D415  # the docstring is the runtime message template
```

**5.8 Logging.** Each module logs through `log = logging.getLogger(__name__)`. Messages are in English. An unexpected error is logged with `log.exception`, which keeps the traceback.

### Priority 6 — Style, documentation and Git

**6.1 Clarity.** Names say what a thing is or does. A comment says why; it never repeats what the code already says.

**6.2 Code in comments.** Code named in a comment is wrapped in backticks.

```python
# Correct
# `cancel` may run before `resolve` returns, so check the future first.

# Incorrect
# cancel may run before resolve returns, so check the future first.
```

**6.3 Docstrings.** Every function and class has a Google-style docstring, however small (`D`, `convention = "google"`). Docstrings, log messages and error messages are in English.

**6.4 Variables and fields.** Every module-level variable, public or private (constants, type aliases, type variables), and every element of a model-like structure (dataclass, `TypedDict` and `NamedTuple` fields, enum members, class attributes, and the instance attributes a stateful class sets in `__init__`) has a one-line docstring on the line right under it. The docstring says what it holds, never repeating its name or type. The class docstring has no `Attributes` section repeating them.

```python
_DEFAULT_TIMEOUT: Final[float] = 30.0
"""Seconds `listen` waits when the caller gives no timeout."""


class ChatKind(Enum):
    """Kind of chat a listener waits in."""

    PRIVATE = "private"
    """A one-to-one chat with a user."""

    GROUP = "group"
    """A group or supergroup."""
```

**6.5 Docstring sections.** A brief line first, then `Args`, `Returns` and `Raises` when they apply. An `Example` section is a doctest that `make test-doctest` runs, so it needs no network, filesystem, Telegram client or optional dependency.

```python
def chunk(text: str, size: int) -> list[str]:
    """Split text into pieces of at most `size` characters.

    Args:
        text: The text to split.
        size: The maximum length of a piece.

    Returns:
        The pieces, in order.

    Raises:
        ValueError: If `size` is not positive.

    Example:
        >>> chunk("abcde", 2)
        ['ab', 'cd', 'e']
    """
```

**6.6 Public documentation.** Public documentation explains concepts, never data that changes with every addition (counts, file lists, line numbers). A detail that changes has one source, and other documents link to it rather than copy it.

**6.7 Commits and pull requests.** Commit messages follow Conventional Commits. A breaking change adds `!` to the type and a `BREAKING CHANGE` note that states the migration; the release notes on GitHub are generated from the pull requests, so there is no changelog file.

**6.8 Branches.** Every change is made on its own branch and merged through a pull request, never committed directly to `main`.

## Scope of application

Every rule applies to the whole library: existing code as well as new. Code that does not comply is brought into compliance on its own branch and pull request, not folded into an unrelated change.

## Extending the rules

Reread these rules before working in a domain they do not yet cover. When a new rule is needed, add it at the priority it belongs to, and update the tests and documentation it affects. No rule is assumed for a domain that has not been worked on yet.
