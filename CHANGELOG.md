# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Every breaking change lists what changed, who is affected and how to migrate.

## [Unreleased]

### Added

- `Client.setup_pyroflow(workers_policy=WorkersPolicy(...))`, `pyroflow.models.WorkersPolicy`
  and `pyroflow.enums.WorkersBusyMode`: what a wait inside a handler does
  once it would leave fewer than `free_workers` workers free (`1` by
  default), after up to `busy_timeout` seconds (`5` by default): `REJECT`
  raises the new `ListenerWorkersBusy`, and `CANCEL_OLDEST` ends the oldest
  such wait with the new `ListenerEvicted` (a `ListenerCancelled`, through
  the new `UpdateListener.evict`), then waits up to `evict_timeout` seconds
  (`5` by default) for a worker to free, since the evicted handler may go on
  working, or raises the new `ListenerEvictionTimeout` (a
  `ListenerWorkersBusy`). Without a policy, the default, nothing steps in;
  `setup_pyroflow()` removes one.
- `Client.setup_pyroflow(ask_context_message=True)`: `ask` and `ask_rich` put
  the message in `listen_context`. Off by default, so it stays as it is.
- `pyroflow.enums.EphemeralUpdates.ANY`: waits on ephemeral updates, in `listen` and in
  `listen_message_id` of `ask`. It needs a user. Ephemeral ids do not follow
  each other and can be reused, so no key holds one, an ephemeral update reaches
  only such a wait, and a regular update never does. After an ephemeral `ask`,
  `SENT` is `EphemeralUpdates.ANY` and `NEXT` waits for that user's next regular message.
- `ListenerReplaced`, a `ListenerCancelled`: a newer wait took the same key.
- `pyroflow.filters`: text-matching filters such as `split_text`.
- `BotCommandsMixin` and `mark_bot_commands`: an opt-in `Client` mixin that
  publishes the bot commands declared on registered handlers. It assumes one
  session per bot: when two overlap, such as during a rolling deploy, the one
  that stops deletes the commands the other still uses, unless it stops with
  `remove_commands=False`.
- `pyroflow.enums.ListenMessageId` as `listen_message_id` on `ask` and
  `ask_rich`: `SENT` waits on the message `ask` sent or edited, such as a
  press on its buttons; `NEXT` waits for the message right after it.
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
- `filters=` and `strict=` on `listen` (`listen_filters=` and
  `listen_strict=` on `ask` and `ask_rich`): a Pyrogram filter the awaited
  update must pass besides its key. An update whose key
  matches but that fails the filter is skipped and the listener keeps
  waiting, or, with `strict=True`, the wait ends with the new
  `ListenerRejected` (a `ListenerCancelled`). `MessageListener`'s default `on_listen_func` logs a warning for a
  non-strict filter on a key with a `message_id`, which names one message and
  can leave the wait open.
- `UpdateListener.reject(key)`: end a wait with `ListenerRejected`.
- `UpdateListener(on_listen_func=...)`: called inline with one dict of the
  arguments of every `listen` call by name, before the wait is registered;
  an error it raises stops the wait from starting.
- `UpdateListener(on_error_func=...)`: called with the error and the
  `ListenerModel` when a `ListenerError` ends a wait (a timeout, a
  cancellation or a strict rejection), before `listen` raises it. A failing callback is logged and never hides the error.
- `pyroflow.models.ListenerContext`, the type of a wait's `context`: a
  `SimpleNamespace` with the typed fields `message_id` and `message`, plus
  any value the caller adds. Declared and added values are both read and set
  as attributes; subclass it to type fields of your own.
- `MessageListenCancellingCallbackQueryListener`: a `CallbackQueryListener`
  whose presses that no callback wait takes cancel the message listen tied
  to the pressed message (see the Changed entry below): every wait whose
  `context.message` is that message, which `ask` sets with
  `ask_context_message` on. Its `cancel_policy=` (the new
  `pyroflow.enums.MessageListenCancelPolicy`) sets which presses cancel:
  `ALWAYS`, `UNRESOLVED` (the default) or `RESOLVED`; its `cancel_scope=`
  (the new `pyroflow.enums.ListenerScope`) how many tied waits:
  `ALL` (the default) or `FIRST`, the most specific.
- `resolve_scope=` on every `UpdateListener`: `ListenerScope.FIRST` (the
  default) gives an update to the most specific matching wait only, as
  before; `ListenerScope.ALL` gives it to every matching wait.

### Changed

- **BREAKING:** `ask` and `ask_rich` hand the Pyrogram arguments to Pyrogram as
  they are. `Client.ask` no longer ignores arguments the chosen mode does not
  take, and neither `Client` nor `Message` raises `ValueError` for a
  `reply_markup` other than `InlineKeyboardMarkup` when editing, or for send
  arguments on an edit. Affects code that relied on those. Migration: pass only
  what the mode takes; the type hints show it, and Pyrogram raises `TypeError`
  for anything else.
- **BREAKING:** `Message.ask` and `Message.ask_rich` call the message's own
  `reply`, `reply_rich` and `edit` instead of `Client.ask`, so Pyrogram handles
  replies in topics, business chats and ephemeral messages, and they accept
  only what those methods accept. That leaves out `reply_parameters`,
  `message_thread_id` and `direct_messages_topic_id` on a reply, and
  `schedule_date` on an edit. Migration: call `client.ask` with those arguments.
- **BREAKING:** pyroflow needs `kurigram>=2.2.26`, the first version with
  `Message.edit(rich_message=...)`. Migration: upgrade kurigram.
- Faster dispatch: `UpdateListener.resolve` returns at once when no wait is
  open, and listener filters, `extract_key_func`, `on_error_func`, handler
  callbacks and `split_text` rules that are coroutine functions are awaited
  directly (the new `pyroflow.utils.call_maybe_async`). A listener filter
  no longer captures the caller's stack on every call. An error in a
  listener filter or in `on_error_func` is now logged by the
  `pyroflow.update_listener.update_listener` logger instead of `pytrove`'s.
- **BREAKING:** `Dispatcher.handle_listen` returns whether the listener took
  the update instead of raising `StopPropagation`, and the worker calls it
  before taking its lock; `handle_update` only runs the handlers. A
  listener now resolves an update while handlers hold the worker locks.
- **BREAKING:** `listen_message_id` on `ask` and `ask_rich` (on `Client` and
  `Message`) defaults to `ListenMessageId.AUTO` instead of `None`: a
  `Message` wait now takes only the message right after the question
  (`NEXT`), a `CallbackQuery` wait only a press on the question's buttons
  (`SENT`), and other waits keep no message filter. In a group another
  member's message can take the next id; there, and for the old behavior,
  pass `listen_message_id=None`.
- **BREAKING:** `UpdateListener.resolve` returns whether a listener took the
  update, instead of returning `None` or raising `UnresolvedUpdate`.
  Affects code calling or overriding `resolve`.
  Migration: check the returned `bool`; an `on_unresolved` override becomes a
  `resolve` override that acts when the result is `False`.
- **BREAKING:** `UpdateListener.cancel(key)` is a plain
  method, no longer a coroutine, and returns whether a listener was
  cancelled. Affects code that awaits it or passes `cancel_coordinator`.
  Migration: call `listener.cancel(key)` without `await`.
- **BREAKING:** `UpdateListener.is_listenable` and `is_listenable_func` are
  gone: `extract_key` (and `extract_key_func`) returns `None` for an update
  that should not be listened to. Affects custom listeners and code passing
  these arguments.
  Migration: return `None` from `extract_key_func` where `is_listenable_func`
  returned `False`.
- **BREAKING:** `meta` is renamed `context` on `listen` and
  `listen_context` on `ask` and `ask_rich`, and is a `ListenerContext`, no
  longer a value of any type or a dict; it is keyword-only, and
  `ListenerModel.meta` is `ListenerModel.context`, `None` unless one was passed.
  `ListenerModel` takes its `future` as the second field, with no default.
  With `ask_context_message` on, `ask` puts the sent or edited message in the
  context as `message`, on a copy, unless it holds one, so the id is
  `context.message.id` instead of
  `meta["message_id"]`. Affects code passing
  or reading `meta`, or building `ListenerModel` itself.
  Migration: `listen(chat, context=ListenerContext(step=1))` instead of
  `listen(chat, {"step": 1})`, `ask(..., listen_context=ListenerContext(...))`
  instead of `ask(..., meta=...)`, read `model.context.step` instead of
  `model.meta["step"]`, and build models as
  `ListenerModel(key, loop.create_future())`.
- **BREAKING:** every listen parameter of `ask` and `ask_rich` (on `Client`
  and `Message`) starts with `listen_`: `timeout` is `listen_timeout` and
  `update_type` is `listen_update_type`. Affects every call passing them.
  Migration: `ask(..., listen_timeout=30, listen_update_type=CallbackQuery)`
  instead of `ask(..., timeout=30, update_type=CallbackQuery)`.
- **BREAKING:** `CallbackQueryListener` no longer cancels message waits. A
  press that no callback wait takes cancels the message listen tied to the
  pressed message (the `ask` that sent it) only with the new
  `MessageListenCancellingCallbackQueryListener`; the wait is found from the
  presser and the pressed message, so a wait aimed at another user is left
  alone. Affects bots whose buttons on an `ask` message were meant to end it.
  Migration: register
  `MessageListenCancellingCallbackQueryListener()` instead of
  `CallbackQueryListener()`.
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
- pyroflow now depends on `pytrove>=2.0` and `kurigram` only. It no
  longer depends on `cachetools`, `sortedcontainers` or `typing_extensions`.
- `pyroflow.typings` now also holds `UpdateType`.
- Every module defines `__all__`; `pyroflow.typings`, `pyroflow.errors`,
  `pyroflow.models` and `pyroflow.enums` are the entry points for each kind
  of name.
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

- After a `stop`, the updates the original `start` dispatches first no
  longer fail their `ask` with `ListenerCancelled`: the listeners start
  before it.
- A failed bot command publish in `BotCommandsMixin.start` is logged instead
  of failing `start` on a connected client.
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
