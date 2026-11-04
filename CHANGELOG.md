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
- `UpdateCoordinator.update_type`: the update class a coordinator handles.
- `RedisUpdateCoordinator.fingerprint`: a per-coordinator id that prefixes the
  value of every lock it takes. `start()` replaces it if a lock in Redis
  already carries it, and `stop()` deletes the locks the coordinator still
  holds. Other sessions' locks and every handled key are left alone. The Redis
  client stays owned by the caller, who closes it after `stop()`.
- `pyroflow.utils.redis_token_lock`: a redis-py async lock that takes its value
  as `token` instead of a random UUID.
- `Client.ask_rich` and `Message.ask_rich`: `ask` for rich messages, sent with
  `send_rich_message` or edited with `edit_message_text(rich_message=...)`.
- `ListenOutcome` (`RESOLVED`, `FOREIGN`, `UNMATCHED`): what
  `UpdateListener.resolve` decided for an update.
- The listener registry lives in `UpdateCoordinator`: `register_listener`,
  `listener_owners`, `unregister_listener`, `cancel_listener`, plus
  `new_owner_id`, `is_mine` and `on_listener_lost`. Each call is atomic and
  takes no lock. `RedisUpdateCoordinator` keeps each registration as a lease
  of `listener_ttl` seconds (60 by default), renewed by `refresh_listeners`
  every third of it while the coordinator runs.
- `UpdateListener.extract_lock_key` (and `extract_lock_key_func`): the
  coordinator lock `listen` registers under, the chat by default.
- `UpdateListener.discard`: cancel a local listener without touching the
  registry; `is_closed` tells whether `stop` ran since the last `start`.

### Changed

- **BREAKING:** a listener and the coordinated of its update type share one
  `UpdateCoordinator`, passed as `coordinator=` to both;
  `UpdateCoordinated(coordinator_factory=...)` is now
  `UpdateCoordinated(coordinator=...)`. Registering a listener and a
  coordinated of one type with different coordinators raises `ValueError`,
  and a coordinator serves one listener only. The dispatcher starts and stops
  each coordinator once; `UpdateListener.start`/`stop` no longer touch it.
  Affects code passing `coordinator_factory` to either.
  Migration:
  `coordinator = RedisUpdateCoordinator(redis, Message)`, then
  `MessageCoordinated(coordinator=coordinator)` and
  `MessageListener(coordinator=coordinator)`.
- **BREAKING:** `UpdateListener.resolve` returns a `ListenOutcome` instead of
  raising `UnresolvedUpdate`. When the update matches a listener another
  session registered, it returns `FOREIGN` and the dispatcher stops the update
  without handlers and without marking it, for that session to take. An
  `is_bypass` match cancels the listener in whatever session waits on it.
  Affects code calling or overriding `resolve`.
  Migration: compare the result with `ListenOutcome`; an `on_unresolved`
  override becomes a `resolve` override that acts on `UNMATCHED`.
- **BREAKING:** `listen` registers under the coordinator lock of
  `extract_lock_key` and takes only updates settled after it registered;
  `cancel(key)` cancels the listener in every session and its only argument
  is the key. `ListenerModel.coordinator_id` is `owner_id`, a
  `<fingerprint>:<random>` string. A peer's waiter learns its registration
  was taken over or cancelled at its next renewal (within `listener_ttl / 3`).
  Affects code passing `cancel_coordinator`, `is_duplicate` or
  `coordinator_id` to `cancel`, or reading `coordinator_id`.
  Migration: call `cancel(key)`, or `discard(key, owner_id)` for the local
  listener only; read `owner_id`.
- **BREAKING:** `ask` no longer copies `meta` or adds the sent message id
  under `meta["message_id"]`; it passes `meta` through unchanged and records
  the sent or edited message as the listener's new `prompt_id`
  (`listen(..., prompt_id=...)`, `ListenerModel.prompt_id`). A button pressed
  on that message cancels the ask when no callback listener takes the press;
  the ask is found from the presser and the pressed message, so an ask aimed
  at another user is left alone. Affects code reading `meta["message_id"]`.
  Migration: read `listener_model.prompt_id`.

- **BREAKING:** `UpdateCoordinator.mark_handled` raises the new
  `UpdateAlreadyHandled` (a `CoordinationError`) when the id is already
  registered, instead of refreshing its expiry. The dispatcher logs it and
  drops the update before any handler runs; a listener that already resolved
  it still stops propagation. Affects custom `UpdateCoordinator` backends and
  code that marked an id twice.
  Migration: in a custom backend, set the id only if absent (Redis `SET NX`)
  and raise `UpdateAlreadyHandled(key)` otherwise.

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
  never return `None`.
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
  on `(chat_id,)` instead of `(peer_id, message_id)`, and a message without
  a chat is uncoordinated; and
  `CallbackQueryCoordinated` on the chat of the query's message instead of
  the query id, leaving a query from an inline message uncoordinated. Updates of one chat now wait
  for each other until each is handled. Affects bots relying on concurrent
  processing within a chat.
  Migration: pass `extract_key_func` with the old key, e.g.
  `lambda m: (m.chat.id, m.id)`.
- **BREAKING:** `LockKeyT` is removed and `ListenerCoordinator.lock` takes a
  `ListenerKey` only; `RedisListenerCoordinator.lock` no longer wraps a chat
  id or a tuple of ids. Affects code that calls a listener coordinator's
  `lock` with an int or a tuple, or imports `LockKeyT`.
  Migration: pass `ListenerKey(chat_id)` (or the full key) and annotate with
  `ListenerKey`.
- **BREAKING:** `lock_ttl` moved from `UpdateCoordinator` to
  `RedisUpdateCoordinator`, the only backend whose lock expires, and the
  default `blocking_timeout` is 10 seconds instead of 5. Affects code passing
  `lock_ttl` to `MemoryUpdateCoordinator`, or `UpdateCoordinator` arguments
  positionally (the second positional argument is now `handled_ttl`).
  Migration: pass `lock_ttl` only to `RedisUpdateCoordinator`, pass the
  coordinator settings by keyword, and pass `blocking_timeout=5` to keep the
  old wait.
- **BREAKING:** `build_key` moved from `UpdateCoordinator` to
  `RedisUpdateCoordinator`; `MemoryUpdateCoordinator` keys its locks and its
  handled registry by the key tuple itself. Affects code that calls
  `build_key` on a memory coordinator or reads its `handled` keys as strings.
  Migration: use the key tuple directly with `MemoryUpdateCoordinator`.
- **BREAKING:** `UpdateCoordinatorKeyT` is renamed `CoordinatedUpdateKeyT`
  (the lock key), and update ids have their own alias, `CoordinatedUpdateIdT`,
  used by `extract_update_id` and the coordinators' `is_handled` and
  `mark_handled`.
  Affects code that imports `UpdateCoordinatorKeyT`.
  Migration: import `CoordinatedUpdateKeyT`, or `CoordinatedUpdateIdT` for
  update ids, from `pyroflow.typings`.
- **BREAKING:** `MessageCoordinated` identifies a message by
  `(business_connection_id, scheduled, chat_id, message_id, edit_ts)`:
  `business_connection_id` is `""` outside a business connection, `scheduled`
  is `1` for a scheduled message, `edit_ts` is the edit time in seconds or
  `0`, and an ephemeral message (id `0`) uses `"e<ephemeral id>:<send time>"`
  as its message id. Edited, business, scheduled and ephemeral messages are no
  longer dropped as duplicates of unrelated ones. Affects code that reads or marks these identities directly.
  Migration: none for handlers; build identities with `extract_update_id`.
- `split_text` never matches `bytes` callback data, even without a
  `separator` (it used to pass the bytes to a single callable rule).
- pyroflow now depends on `pytrove>=2.0` and `kurigram>=2.2.24`, and
  `cachetools` gained a `>=4.1.0` floor. It no longer depends on
  `sortedcontainers` or `typing_extensions`.
- `pyroflow.typings` now also holds `UpdateType` and `AsyncLockProto`.
- Every module defines `__all__`; `pyroflow.typings`, `pyroflow.errors`,
  `pyroflow.models`, `pyroflow.enums` and `pyroflow.constants` are the entry
  points for each kind of name.
- `MemoryListenerCoordinator.register`/`unregister`/`cancel`/`registered` take
  explicit parameters instead of `*args, **kwargs`.
  Migration: none for calls that use the documented arguments.
- Contributors: development runs through `uv` and the `Makefile`, with `ruff`
  and `ty` enforced; see `CONTRIBUTING.md`.

- **BREAKING:** `UpdateListener.is_listenable` and `is_listenable_func` are
  gone: `extract_key` (and `extract_key_func`) returns `None` for an update
  that should not be listened to. `bypass_func` is renamed `is_bypass_func`.
  `on_unresolved(update)` drops its `key` argument and also runs when
  `extract_key` returns `None` or `is_bypass` cancels the matched listener,
  instead of `resolve` raising `UnresolvedUpdate` directly. Affects custom
  listeners and code passing these arguments.
  Migration: return `None` from `extract_key_func` where `is_listenable_func`
  returned `False`; pass `is_bypass_func=` instead of `bypass_func=`; drop
  `key` from `on_unresolved` overrides and call `await self.extract_key(update)`
  if it is still needed.

### Removed

- **BREAKING:** `pyroflow.listener_coordinator` (`ListenerCoordinator`,
  `MemoryListenerCoordinator`, `RedisListenerCoordinator`), with its per-chat
  Redis lock, `lock_timeout`, `lock_blocking_timeout` and cancel pub/sub
  channel; `UpdateListener.coordinator_factory`, `on_unresolved` and
  `_cancel`; `UnresolvedUpdate`; `ListenerCoordinatorIdT`; and
  `UpdateCoordinated.start`/`stop`. Affects code using any of them.
  Migration: pass an `UpdateCoordinator` as `coordinator=` (see Changed);
  Redis keys `listen|registry|...` and `listen|lock|...` are no longer read,
  so delete them once every session runs this version.
- **BREAKING:** handler histories are gone: `UpdateHistory`, `MessageHistory`,
  `CallbackQueryHistory`, `UpdateHistoryStore`, `MemoryUpdateHistoryStore`,
  `UpdateRecord`, `UpdateHistoryKeyT`, `Client`/`Dispatcher.register_history`
  and `unregister_history`, and `Dispatcher.histories`, with the packages
  `pyroflow.update_history` and `pyroflow.update_history_store`. Nothing in
  pyroflow read the records, they lived in one process only, and a handler
  cannot be stored and rebuilt with its filters. Affects code that registered
  a history or read its records.
  Migration: carry the step a button leads back to in its `callback_data`
  (such as `back:menu`), which survives restarts and works across sessions,
  or keep a conversation's state in one `ask()` flow.
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
  - `UpdateType`, `AsyncLockProto` -> `pyroflow.typings`; `LockKeyT` is
    gone, see below.
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

- `Dispatcher.stop` stops the listeners first, then drains the workers, then
  stops the coordinators. A handler blocked in `ask` no longer holds up the
  shutdown until its timeout, and the coordinators no longer delete the locks
  of updates still being processed.
- A reply that reached another session first no longer goes to that
  session's handlers while the `listen` that waits for it hangs: every session
  checks the shared registry, and the one that does not own the listener
  stands down.
- An update being processed while a listener registers is decided once:
  either it goes to the handlers and the listener waits for the next one, or
  the listener takes it.
- A failed unregister at the end of `listen` is logged instead of hiding the
  result or error of the wait, and a lost cancel signal no longer raises
  `RuntimeError("... out of sync")` on the next `listen`.
- Redis listener registrations of a session that died expire within
  `listener_ttl` instead of staying forever.
- `RedisListenerCoordinator.stop()` propagates its caller's cancellation
  instead of swallowing it.
- `MessageListener` no longer raises `AttributeError` for messages without
  `from_user` (anonymous admins, channel posts); the listener key's user is `None`.
- A registered listener with no pending `listen` no longer swallows every
  update of its type: `UpdateListener.resolve` used to return as resolved when
  this process held no listeners, so handlers were skipped (and, under
  coordination, the update was marked as handled for every session). It now
  calls `on_unresolved`, so `CallbackQueryListener` also cancels the message
  listener waiting on a pressed button's message when no callback listener is
  pending.

## [0.2.1] - 2026-07-26

Initial changelog; see the GitHub releases for earlier history.

[Unreleased]: https://github.com/eeeob/pyroflow/compare/v0.2.1...HEAD
[0.2.1]: https://github.com/eeeob/pyroflow/releases/tag/v0.2.1
