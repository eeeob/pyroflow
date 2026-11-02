# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Every breaking change lists what changed, who is affected and how to migrate.

## [Unreleased]

### Added

- `pyroflow.filters`: text-matching filters such as `split_text`.
- `pyroflow.constants`, the home of public constants (`BOT_COMMANDS_ATTR`).
- `BotCommandsMixin` and `mark_bot_commands`: an opt-in `Client` mixin that
  publishes the bot commands declared on registered handlers.
- `mark_handled()`: settles the current coordinated update early and releases
  its lock while the handler keeps running.
- `Update.context`: a per-update dict for arbitrary data.
- `error_handlers=` on `ask()`, plus `Client.ask_error_handlers` and
  `Client.register_ask_error_handler`/`unregister_ask_error_handler` for
  client-wide handlers.
- `listen_message_id` also accepts a callable that receives the sent message
  and returns the id to listen for.
- `User.lang_code` and `Message.editable`.
- `py.typed`: the package ships its type hints.
- `ListenerKey.to_dict()`: the key's fields by name.
- `split_text` rules can be compiled `re.Pattern` objects; a part matches when
  the pattern fullmatches it.
- `pyroflow.utils.get_update_executor(update)`: the executor of the client an
  update is bound to, or `None`.
- `PyroflowError`, the root of every pyroflow error, and `CoordinationError`,
  the family of coordination signals.

### Changed

- **BREAKING:** `ListenerKey.to_tuple` is a method. Affects code reading
  `key.to_tuple` as a property.
  Migration: call `key.to_tuple()`.
- **BREAKING:** the error hierarchy. `PyroflowError` is the root;
  `ListenerError` keeps `ListenerCancelled`, `ListenerTimeout`,
  `ListenerAlreadyExists` and `UnresolvedUpdate`; `UnhandledUpdate` now
  subclasses `CoordinationError`, not `ListenerError`. Every message changed,
  e.g. "Listener for {value} timed out" instead of
  "UpdateListener {value} timed out". Affects code that catches
  `ListenerError` to catch `UnhandledUpdate`, or matches message text.
  Migration: catch `CoordinationError`/`UnhandledUpdate` (or `PyroflowError`
  for everything) and match on the class, not the message.
- `split_text` never matches `bytes` callback data, even without a
  `separator` (it used to pass the bytes to a single callable rule).
- pyroflow now depends on `pytrove>=2.0` and `kurigram>=2.2.24`, and
  `cachetools` gained a `>=4.1.0` floor. It no longer depends on
  `sortedcontainers` or `typing_extensions`.
- `pyroflow.typings` now also holds `UpdateType`, `AsyncLockProto` and
  `LockKeyT`.
- Every module defines `__all__`; `pyroflow.typings`, `pyroflow.errors`,
  `pyroflow.models`, `pyroflow.enums` and `pyroflow.constants` are the entry
  points for each kind of name.
- `MemoryListenerCoordinator.register`/`unregister`/`cancel`/`registered` and
  `MemoryUpdateHistoryStore.update`/`get`/`pop`/`delete` take explicit
  parameters instead of `*args, **kwargs`.
  Migration: none for calls that use the documented arguments.
- Contributors: development runs through `uv` and the `Makefile`, with `ruff`
  and `ty` enforced; see `CONTRIBUTING.md`.

### Removed

- **BREAKING:** the general-purpose helpers in `pyroflow.utils` are gone,
  together with the modules `pyroflow.utils.async_tools`,
  `pyroflow.utils.iter_tools`, `pyroflow.utils.validate_tools` and
  `pyroflow.utils.enums`. Affects code that imported helpers such as
  `safe_await`, `maybe_awaitable`, `to_thread` or `gather_helper` from
  `pyroflow.utils`.
  Migration: import them from `pytrove` directly, e.g. `from pytrove import safe_await`.
- **BREAKING:** `pyroflow.utils.typings` is gone, and `pyroflow.utils` no
  longer exposes `typings`. Affects code that imported from it, from the
  `pyroflow.utils` submodules (`classes`, `misc_tools`, ...), or `LockKeyT`
  from `pyroflow.listener_coordinator.listener_coordinator`.
  Migration:
  - `UpdateType`, `AsyncLockProto`, `LockKeyT` -> `pyroflow.typings`.
  - `MaybeCoroutineCallable`, `MaybeAwaitable`, `NestedContainer`,
    `NotContainer`, `Number` -> `pytrove.typings`; `JsonValueT` ->
    `pytrove.typings.JsonValue`.
  - Helpers (`patch_cls`, `UpdateBound`, `AsyncioLock`, ...) -> import them
    from `pyroflow.utils` directly; its submodule paths are not public.
- **BREAKING:** the `UpdateLockState` enum. Coordination now uses a lock and a
  handled registry instead of a lock state.
  Migration: drop the import; nothing replaces it.
- **BREAKING** (contributors and packagers): the `dev` and `test` extras.
  Tooling now lives in dependency groups.
  Migration: run `uv sync` (or `make sync`) instead of `pip install pyroflow[dev]`.
- `pyroflow/__meta__.py`.
  Migration: use `pyroflow.__version__`.

### Fixed

- `RedisListenerCoordinator.stop()` propagates its caller's cancellation
  instead of swallowing it.
- `MessageListener` no longer raises `AttributeError` for messages without
  `from_user` (anonymous admins, channel posts); the listener key's user is `None`.

## [0.2.1] - 2026-07-26

Initial changelog; see the GitHub releases for earlier history.

[Unreleased]: https://github.com/eeeob/pyroflow/compare/v0.2.1...HEAD
[0.2.1]: https://github.com/eeeob/pyroflow/releases/tag/v0.2.1
