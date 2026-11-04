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
- `PyroflowError`, the root of every pyroflow error.
- `Client.ask_rich` and `Message.ask_rich`: `ask` for rich messages, sent with
  `send_rich_message` or edited with `edit_message_text(rich_message=...)`.
- `UpdateListener.is_closed`: whether `stop` ran since the last `start`;
  `listen` raises `ListenerCancelled` while it is.
- `filters=` and `strict=` on `listen`, `ask` and `ask_rich`: a Pyrogram
  filter the awaited update must pass besides its key. An update whose key
  matches but that fails the filter is skipped and the listener keeps
  waiting, or, with `strict=True`, the wait ends with the new
  `ListenerRejected` (a `ListenerCancelled` that carries the rejected
  update). `MessageListener` logs a warning for a non-strict filter on a key
  with a `message_id`, which names one message and can leave the wait open.
- `UpdateListener.reject(key, update)`: end a wait with `ListenerRejected`.
- `UpdateListener(on_error_func=...)` and `UpdateListener.on_error`: called
  with the error and the `ListenerModel` when a `ListenerError` ends a wait
  (a timeout, a cancellation or a strict rejection), before `listen` raises
  it. A failing callback is logged and never hides the error.
- `pyroflow.typings.MetaT` (`dict[Hashable, Any]`), the type of `meta`, and
  `pyroflow.constants.ASK_MESSAGE_ID_META_KEY`.
- `pyroflow.utils.subsets_largest_first(items)`: every subset of `items`,
  from all of them down to none.

### Changed

- **BREAKING:** `UpdateListener.resolve` returns whether a listener took the
  update, instead of returning `None` or raising `UnresolvedUpdate`.
  Affects code calling or overriding `resolve`.
  Migration: check the returned `bool`; an `on_unresolved` override becomes a
  `resolve` override that acts when the result is `False`.
- **BREAKING:** `UpdateListener.cancel(key, *, is_duplicate=False)` is a plain
  method, no longer a coroutine, and returns whether a listener was
  cancelled. Affects code that awaits it or passes `cancel_coordinator`.
  Migration: call `listener.cancel(key)` without `await`.
- **BREAKING:** `UpdateListener.is_listenable` and `is_listenable_func` are
  gone: `extract_key` (and `extract_key_func`) returns `None` for an update
  that should not be listened to. Affects custom listeners and code passing
  these arguments.
  Migration: return `None` from `extract_key_func` where `is_listenable_func`
  returned `False`.
- **BREAKING:** `meta` is a dict (`MetaT`) and keyword-only in `listen`;
  `ListenerModel` takes its `future` as the second field, with no default.
  `ask` copies `meta` and adds the sent or edited message's id under
  `ASK_MESSAGE_ID_META_KEY` (`"message_id"`, as before) unless `meta` already
  has it; a non-dict `meta` is no longer accepted. A button pressed on that
  message cancels the ask when no callback listener takes the press; the ask
  is found from the presser and the pressed message, so an ask aimed at
  another user is left alone. Affects code passing a non-dict `meta`,
  passing `meta` positionally to `listen`, or building `ListenerModel`
  itself.
  Migration: pass `meta` as a dict by keyword (`listen(chat, meta={...})`),
  and build models as `ListenerModel(key, loop.create_future())`.
- **BREAKING:** `ListenerKey.to_tuple` is a method. Affects code reading
  `key.to_tuple` as a property.
  Migration: call `key.to_tuple()`.
- **BREAKING:** the error hierarchy. `PyroflowError` is the root;
  `ListenerError` keeps `ListenerCancelled`, `ListenerTimeout` and
  `ListenerAlreadyExists`. Every message changed, e.g.
  "Listener for {value} timed out" instead of
  "UpdateListener {value} timed out". Affects code that matches message text.
  Migration: match on the class (or catch `PyroflowError` for everything),
  not the message.
- `split_text` never matches `bytes` callback data, even without a
  `separator` (it used to pass the bytes to a single callable rule).
- pyroflow now depends on `pytrove>=2.0` and `kurigram>=2.2.24` only. It no
  longer depends on `cachetools`, `sortedcontainers` or `typing_extensions`.
- `pyroflow.typings` now also holds `UpdateType`.
- Every module defines `__all__`; `pyroflow.typings`, `pyroflow.errors`,
  `pyroflow.models`, `pyroflow.enums` and `pyroflow.constants` are the entry
  points for each kind of name.
- Contributors: development runs through `uv` and the `Makefile`, with `ruff`
  and `ty` enforced; see `CONTRIBUTING.md`.

### Removed

- **BREAKING:** multi-session coordination. pyroflow now works within one
  client: each client matches the updates it receives against its own
  listeners, and nothing is locked, deduplicated or shared between sessions.
  Gone are:
  - the packages `pyroflow.update_coordinated` (`UpdateCoordinated`,
    `MessageCoordinated`, `CallbackQueryCoordinated`),
    `pyroflow.update_coordinator` (`UpdateCoordinator`,
    `MemoryUpdateCoordinator`, `RedisUpdateCoordinator`) and
    `pyroflow.listener_coordinator` (`ListenerCoordinator`,
    `MemoryListenerCoordinator`, `RedisListenerCoordinator`);
  - `Client`/`Dispatcher.register_coordinated` and `unregister_coordinated`,
    and `Dispatcher.coordinateds`;
  - `UpdateListener(coordinator_factory=...)`, `on_unresolved` and `_cancel`,
    and `ListenerModel.coordinator_id`;
  - `UnresolvedUpdate` and `UnhandledUpdate`;
  - the `redis` extra.

  Affects code that registers a coordinated, passes `coordinator_factory`, or
  runs one bot in several processes that rely on sharing work.
  Migration: drop `register_coordinated(...)` and `coordinator_factory=`; a
  listener needs only `client.register_listener(MessageListener())`. Running
  the same bot in several processes now handles each update once per
  process, and pyroflow offers no replacement for that. Redis keys pyroflow
  wrote (`update|...`, `listen|...`) are no longer read and can be deleted.
- **BREAKING:** handler histories are gone: `UpdateHistory`, `MessageHistory`,
  `CallbackQueryHistory`, `UpdateHistoryStore`, `MemoryUpdateHistoryStore`,
  `UpdateRecord`, `UpdateHistoryKeyT`, `Client`/`Dispatcher.register_history`
  and `unregister_history`, and `Dispatcher.histories`, with the packages
  `pyroflow.update_history` and `pyroflow.update_history_store`. Nothing in
  pyroflow read the records, they lived in one process only, and a handler
  cannot be stored and rebuilt with its filters. Affects code that registered
  a history or read its records.
  Migration: carry the step a button leads back to in its `callback_data`
  (such as `back:menu`), which survives restarts, or keep a conversation's
  state in one `ask()` flow.
- **BREAKING:** the general-purpose helpers in `pyroflow.utils` are gone,
  together with the modules `pyroflow.utils.async_tools`,
  `pyroflow.utils.iter_tools`, `pyroflow.utils.validate_tools` and
  `pyroflow.utils.enums`. Affects code that imported helpers such as
  `safe_await`, `maybe_awaitable`, `to_thread` or `gather_helper` from
  `pyroflow.utils`.
  Migration: import them from `pytrove` directly, e.g. `from pytrove import safe_await`.
- **BREAKING:** `pyroflow.utils.typings` is gone, and `pyroflow.utils` no
  longer exposes `typings`. Affects code that imported from it or from the
  `pyroflow.utils` submodules (`classes`, `misc_tools`, ...).
  Migration:
  - `UpdateType` -> `pyroflow.typings`.
  - `MaybeCoroutineCallable`, `MaybeAwaitable`, `NestedContainer`,
    `NotContainer`, `Number` -> `pytrove.typings`; `JsonValueT` ->
    `pytrove.typings.JsonValue`.
  - Helpers (`patch_cls`, `UpdateBound`, ...) -> import them from
    `pyroflow.utils` directly; its submodule paths are not public.
  - The lock types (`AsyncioLock`, `LockKeyT`, the coordinator key aliases)
    are gone with coordination.
- **BREAKING:** the `UpdateLockState` enum, gone with coordination.
  Migration: drop the import; nothing replaces it.
- **BREAKING** (contributors and packagers): the `dev` and `test` extras.
  Tooling now lives in dependency groups.
  Migration: run `uv sync` (or `make sync`) instead of `pip install pyroflow[dev]`.
- `pyroflow/__meta__.py`.
  Migration: use `pyroflow.__version__`.

### Fixed

- `Dispatcher.stop` stops the listeners before it drains the workers, so a
  handler blocked in `ask` no longer holds up the shutdown until its timeout.
- `MessageListener` no longer raises `AttributeError` for messages without
  `from_user` (anonymous admins, channel posts); the listener key's user is `None`.
- A registered listener with no pending `listen` no longer swallows every
  update of its type: handlers used to be skipped while the listener held no
  waiters. `CallbackQueryListener` also cancels the ask on a pressed button's
  message when no callback listener is pending.

## [0.2.1] - 2026-07-26

Initial changelog; see the GitHub releases for earlier history.

[Unreleased]: https://github.com/eeeob/pyroflow/compare/v0.2.1...HEAD
[0.2.1]: https://github.com/eeeob/pyroflow/releases/tag/v0.2.1
