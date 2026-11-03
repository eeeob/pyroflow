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
  the family of coordination errors.
- `Client.ask_rich` and `Message.ask_rich`: `ask` for rich messages, sent with
  `send_rich_message` or edited with `edit_message_text(rich_message=...)`.

### Changed

- **BREAKING:** `ListenerKey.to_tuple` is a method. Affects code reading
  `key.to_tuple` as a property.
  Migration: call `key.to_tuple()`.
- **BREAKING:** the error hierarchy. `PyroflowError` is the root;
  `ListenerError` keeps `ListenerCancelled`, `ListenerTimeout`,
  `ListenerAlreadyExists` and `UnresolvedUpdate`. Every message changed,
  e.g. "Listener for {value} timed out" instead of
  "UpdateListener {value} timed out". Affects code that matches message text.
  Migration: match on the class (or catch `PyroflowError` for everything),
  not the message.
- **BREAKING:** an `UpdateCoordinated` is two extractors. `extract_key` is the
  lock that coordinates updates and returns `None` for an update that is not
  coordinated; `extract_update_id` is the update's unique identity and must
  never return `None` (a `None` identity raises `TypeError`).
  `is_coordinatable`, `is_coordinatable_func` and `UpdateCoordinated.lock()`
  are removed. Affects code that passes `is_coordinatable_func`, overrides
  `is_coordinatable`/`_is_coordinatable`, or calls `coordinated.lock(update)`.
  Migration: return `None` from `extract_key_func` instead of `False` from
  `is_coordinatable_func`, and call `coordinated.coordinator.lock(key)`.
- **BREAKING:** a coordinated update counts as handled, and its lock is
  released, as soon as a listener resolves it or one handler's filter passes
  it, before the handler runs. It used to stay locked until every group had
  run, and counted as handled only if a handler ran. An update no listener
  or filter took is still released unmarked for another session. Affects
  handlers that relied on holding the lock while they run.
  Migration: serialise that work yourself, e.g. with your own lock.
- **BREAKING:** `UnhandledUpdate` is removed: the update is already marked as
  handled before the handler runs, so it can no longer hand the update back.
  Affects handlers that raise it or code that catches it.
  Migration: move the condition into the handler's filter; a filter that
  rejects the update leaves it to another session.
- **BREAKING:** the default lock keys are per chat. `MessageCoordinated` locks
  on `(peer_id,)` instead of `(peer_id, message_id)`, and
  `CallbackQueryCoordinated` on the chat of the query's message (the query id
  for an inline message) instead of the query id. Updates of one chat now wait
  for each other until each is handled. Affects bots relying on concurrent
  processing within a chat.
  Migration: pass `extract_key_func` with the old key, e.g.
  `lambda m: (get_peer_id(m.raw.peer_id), m.id)`.
- **BREAKING:** `MessageCoordinated` identifies a message by
  `(peer_id, message_id, edit_ts)`, where `edit_ts` is the edit time in
  seconds or `0`. An edited message is no longer dropped as a duplicate of the
  original. Affects code that reads or marks these identities directly.
  Migration: none for handlers; build identities with `extract_update_id`.
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
