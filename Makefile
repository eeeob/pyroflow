# The one place the development commands are written down: CI, pre-commit and
# CONTRIBUTING.md call these recipes rather than repeating them.

UV := uv
RUN := $(UV) run
# Keep in sync with requires-python and the classifiers in pyproject.toml.
PYTHON_FLOOR := 3.10
PYTHON_CEIL := 3.14

# Throwaway environments built from pyproject.toml, never from uv.lock;
# `.gitignore` covers `.venv*`. `uv sync` is unusable for them: asked for
# another resolution, it rewrites uv.lock.
VENV_MIN := $(CURDIR)/.venv-minimal
VENV_FLOOR := $(CURDIR)/.venv-floor
VENV_CEIL := $(CURDIR)/.venv-ceil
# `OS` is set on Windows, where a venv keeps its executables in Scripts.
BIN := $(if $(OS),Scripts,bin)

VERSION = $(shell $(UV) run --no-project --with hatchling hatchling version)
TAG = v$(VERSION)

.PHONY: sync hooks format lint typecheck test test-doctest \
	test-minimal test-floor test-ceil build version tag clean

# Other recipes sync on their own; this exists so CI can install in its own step.
sync:
	$(UV) sync

hooks:
	$(RUN) pre-commit install

format:
	$(RUN) ruff format pyroflow tests

lint:
	$(RUN) ruff check pyroflow tests
	$(RUN) ruff format --check pyroflow tests

# tests/typing holds static type tests: assert_type checks, and calls that must
# fail, marked with a `ty: ignore` that --error-on-warning turns into a failure
# once unused. Skipped until the directory exists.
typecheck:
	$(RUN) ty check pyroflow
	$(if $(wildcard tests/typing),$(RUN) ty check --error-on-warning tests/typing)

test:
	$(RUN) pytest

# Every `Example` section in a docstring is a doctest and must be correct.
# Exit 5 is pytest's "no tests collected": no docstring has an example yet.
test-doctest:
	$(RUN) pytest --doctest-modules pyroflow || [ $$? -eq 5 ]

# The bare package plus the test runner, built from source rather than the lock.
test-minimal:
	$(UV) venv --clear $(VENV_MIN)
	VIRTUAL_ENV=$(VENV_MIN) $(UV) pip install . --group test
	$(VENV_MIN)/$(BIN)/python -c "import pyroflow; print(len(pyroflow.__all__), 'symbols exported OK')"
	$(VENV_MIN)/$(BIN)/python -m pytest

# The lowest version every floor in pyproject.toml allows, on the oldest Python.
test-floor:
	$(UV) venv --clear --python $(PYTHON_FLOOR) $(VENV_FLOOR)
	VIRTUAL_ENV=$(VENV_FLOOR) $(UV) pip install --resolution lowest-direct --group test -r pyproject.toml
	VIRTUAL_ENV=$(VENV_FLOOR) $(UV) pip install --no-deps -e .
	$(VENV_FLOOR)/$(BIN)/python -m pytest

# The newest release of every dependency, on the newest Python.
test-ceil:
	$(UV) venv --clear --python $(PYTHON_CEIL) $(VENV_CEIL)
	VIRTUAL_ENV=$(VENV_CEIL) $(UV) pip install --group test -r pyproject.toml
	VIRTUAL_ENV=$(VENV_CEIL) $(UV) pip install --no-deps -e .
	$(VENV_CEIL)/$(BIN)/python -m pytest

build:
	$(UV) build

version:
	@printf '%s\n' "$(VERSION)"

tag:
	git tag $(TAG)
	git push origin $(TAG)

clean:
	rm -rf .venv .venv-minimal .venv-floor .venv-ceil dist build *.egg-info
