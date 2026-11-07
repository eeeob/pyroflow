# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Every breaking change lists what changed, who is affected and how to migrate.

## [Unreleased]

### Added

- `Client.listen_message` and `Client.listen_callback_query`: wait on the
  listener registered for `Message` or `CallbackQuery`, with the fields of
  its key and the wait arguments; `RuntimeError` when none is registered.
  `Client.get_listener(update_type)` returns the registered listener, or
  `None`.
- `Client` and `Message` `ask_rich`, `ask_callback_query` and
  `ask_callback_query_rich`: like `ask`, send or edit a text
  (`send_message`/`edit_message_text`, or `reply`/`edit` on `Message`) or a
  rich message (`send_rich_message`/`edit_message_text(rich_message=...)`, or
  `reply_rich`/`edit`), then wait for a press on the buttons of the message
  sent or edited, where `ask` and `ask_rich` wait for the next message. The key comes from that message:
  its chat and topics, and for a press its id. Every `ask_*` takes
  `listen_user_id`, the user to wait for; without it, any user answers.
- `pyroflow.models.MessageKey` (`chat_id`, `user_id`, `message_thread_id`,
  `direct_messages_topic_id`, `ephemeral`) and
  `pyroflow.models.CallbackQueryKey` (`chat_id`, `user_id`, `message_id`,
  `inline_message_id`, `ephemeral`), the keys of `MessageListener` and
  `CallbackQueryListener`. Every field but `ephemeral` defaults to `None`,
  which matches any value; `ephemeral` defaults to `False` and is always
  compared. A key holds the values as given: a `user_id` alone waits for
  that user in any chat, inline-mode presses included, and a private chat is
  `chat_id` set to the user's id. `exact` in a field's metadata lets a custom
  key class declare such a field; `ListenerKey.key_fields` and
  `exact_fields` read the fields once per class. `MessageKey.from_message`,
  `CallbackQueryKey.from_callback_query` and `from_sent` on both build a key
  from an update, or from a message just sent.
- Waits by topic: `message_thread_id` (a forum topic) and
  `direct_messages_topic_id` (a topic of a channel's direct messages chat) on
  `MessageListener.listen`. `ask` waits in the topic of the message
  it sent or edited.
- Presses on messages sent in inline mode: `inline_message_id` on
  `CallbackQueryListener.listen`. Such a press is keyed by its user and
  `inline_message_id`.
- `pyroflow.ListenKw`, the `TypedDict` of the wait arguments every `listen`
  takes (`context`, `filters`, `strict`, `timeout`), and `pyroflow.typings.KeyT`,
  the key type a listener is generic on.
- `pyroflow.filters.registered_command()`: passes a message whose text or
  caption is a command registered for this bot, with or without arguments,
  from `get_bot_commands()` in the given `scopes` and `language_codes`.
  `ephemeral=False` leaves
  out commands marked `is_ephemeral`, and `username_policy`, a new
  `pyroflow.enums.CommandUsernamePolicy`, sets which `@username` passes.
  `MessageListener(strict_filter=~registered_command())` lets such a command
  end a wait that passes no `listen_filters` and reach its handler.
- `Client.setup_pyroflow(workers_policy=...)` and `pyroflow.enums.WorkersPolicy`:
  what a wait inside a handler does once it would take the last worker, which
  stays out to read the replies: `REJECT` raises the new
  `ListenerWorkersBusy`, and `CANCEL_OLDEST` ends the oldest such wait with
  the new `ListenerEvicted` (a `ListenerCancelled`, through the new
  `UpdateListener.evict`) and takes its place. Without a policy, the default,
  nothing steps in; `setup_pyroflow()` removes one.
- `ListenerModel.add_done_callback`: calls a function with the model as soon
  as it is marked done, right after its future is set, and only once. A wait
  inside a handler frees its worker slot this way. A failing callback is
  logged.
- `Client.setup_pyroflow(ask_context_message=True)`: the `ask_*` methods put
  the message in `listen_context`. Off by default, so it stays as it is.
- `ephemeral=True` on `MessageListener.listen` and
  `CallbackQueryListener.listen` (the `ephemeral` field of the keys): waits on
  ephemeral updates. Ephemeral ids do not follow each other
  and can be reused, so no key holds one, an ephemeral update reaches only
  such a wait, and a regular update never does. An `ask_*` on or with an
  ephemeral message waits this way, for its `listen_user_id` when given.
- `ListenerReplaced`, a `ListenerCancelled`: a newer wait took the same key.
- `pyroflow.filters`: text-matching filters such as `split_text`.
- `BotCommandsMixin` and `mark_bot_commands`: an opt-in `Client` mixin that
  publishes the bot commands declared on registered handlers. It assumes one
  session per bot: when two overlap, such as during a rolling deploy, the one
  that stops deletes the commands the other still uses, unless it stops with
  `remove_commands=False`. A class without `Client` after it gets `TypeError`.
- `User.lang_code` and `Message.editable`.
- `py.typed`: the package ships its type hints.
- `ListenerKey.to_dict()`: the key's fields by name.
- `split_text` rules can be compiled `re.Pattern` objects; a part matches when
  the pattern fullmatches it.
- `pyroflow.utils.get_update_executor(update)`: the executor of the client an
  update is bound to, or `None`.
- `PyroflowError`, the root of every pyroflow error.
- `UpdateListener.is_closed`: whether `stop` ran since the last `start`;
  `listen` raises `ListenerCancelled` while it is.
- `filters=` and `strict=` on `listen` (`listen_filters=` and
  `listen_strict=` on the `ask_*` methods): a Pyrogram filter the awaited
  update must pass besides its key. An update whose key
  matches but that fails the filter is skipped and the listener keeps
  waiting, or, with `strict=True`, the wait ends with the new
  `ListenerRejected` (a `ListenerCancelled`).
- `UpdateListener.reject(key)`: end a wait with `ListenerRejected`.
- `UpdateListener(strict_filter=...)`: a filter for every `listen` that passes
  no `filters`; an update that fails it ends the wait with `ListenerRejected`.
- `UpdateListener(on_error_func=...)`: called with the error and the
  `ListenerModel` when a `ListenerError` ends a wait (a timeout, a
  cancellation or a strict rejection), before `listen` raises it. A failing callback is logged and never hides the error.
- `pyroflow.models.ListenerContext`, the type of a wait's `context`: a
  `SimpleNamespace` with the typed field `message`, plus
  any value the caller adds. Declared and added values are both read and set
  as attributes; subclass it to type fields of your own.
- `resolve_scope=` on every `UpdateListener` (the new
  `pyroflow.enums.ListenerScope`): `ListenerScope.FIRST` (the default) gives
  an update to the most specific matching wait only, as before;
  `ListenerScope.ALL` gives it to every matching wait.

### Changed

- **BREAKING:** `ask` asks for a message only, and
  `ask_callback_query` asks for a press, on `Client` and `Message`.
  `update_type` and `listen_message_id` are gone: the key comes from
  the message sent or edited, and a message answer is no longer matched by
  its id. `listen_user_id` stays, and without it any user answers:
  `Message.ask` no longer waits for the sender of the message it is called
  on by default. Affects `ask` calls passing `update_type` or
  `listen_message_id`, and `Message.ask` calls without `listen_user_id`.
  Migration:
  - Drop `listen_message_id` from `ask`.
  - `message.ask("Name?", listen_user_id=message.from_user.id)` to wait for
    the sender, as `message.ask("Name?")` did.
  - `client.ask_callback_query(chat_id, "Pick one:", reply_markup=keyboard)`
    instead of `client.ask(..., update_type=CallbackQuery)`, and drop
    `listen_message_id`: the press is awaited on the message sent or edited.
- **BREAKING:** `listen` takes the fields of its listener's key, each `None`
  (any value) by default: `MessageListener.listen(chat_id, user_id,
  message_thread_id, direct_messages_topic_id, ephemeral)`,
  `CallbackQueryListener.listen(chat_id, user_id, message_id,
  inline_message_id, ephemeral)`. `UpdateListener.listen(key)` takes the
  whole key instead, and raises `TypeError` for a key that is not its
  `__key_type__`. The wait arguments (`context`, `filters`, `strict`,
  `timeout`) are keyword-only. `MessageListener` no longer keys a message by
  its id. Affects code that calls `listen` with a `message_id` on a message
  wait, passes the wait arguments by position, or calls `listen` on a custom
  `UpdateListener` subclass.
  Migration: `listen(chat_id, user_id)` still works on `MessageListener` and
  `CallbackQueryListener`. Drop a third argument to `MessageListener.listen`:
  by position it is now `message_thread_id`, not a message id. Pass `meta` as
  `context=` (see below). On a custom listener, pass a key:
  `listener.listen(MyKey(chat_id))`.
- **BREAKING:** `ListenerKey` is the base of the keys and holds only
  `chat_id`, `None` by default. `MessageKey` and `CallbackQueryKey` add the
  fields of their update type, and a key equals only a key of its own class.
  `ListenerKey.sub_keys` is gone: `resolve` looks up one key for each shape
  (set of fields) of the open waits, most fields first, then by field order,
  so `(chat, user)` comes before `(chat, topic)`, which comes before `(chat)`.
  Affects code that builds or reads keys, such as
  `ListenerKey(chat_id, user_id) in listener.listeners`, or calls `sub_keys`.
  Migration: `MessageKey(chat_id, user_id)` or
  `CallbackQueryKey(chat_id, user_id, message_id)` instead of
  `ListenerKey(chat_id, user_id, message_id)`.
- **BREAKING:** `UpdateListener` is generic on its key class too, and a
  subclass sets `__key_type__`. `extract_key` and `extract_key_func` are sync
  and return a `__key_type__` or `None`; anything else raises `TypeError`.
  Affects custom listeners, annotations such as `UpdateListener[Message]`,
  and code passing an async `extract_key_func` or awaiting `extract_key`.
  Migration: `UpdateListener[Message, MessageKey]`, set
  `__key_type__ = MessageKey` (or your own `ListenerKey` subclass) on a
  custom listener, make `extract_key_func` a plain function that returns
  such a key, and call `extract_key` without `await`.
- **BREAKING:** the `ask_*` methods hand the Pyrogram arguments to Pyrogram as
  they are. `Client.ask_*` no longer ignores arguments the chosen mode does not
  take, and neither `Client` nor `Message` raises `ValueError` for a
  `reply_markup` other than `InlineKeyboardMarkup` when editing, or for send
  arguments on an edit. Affects code that relied on those. Migration: pass only
  what the mode takes; the type hints show it, and Pyrogram raises `TypeError`
  for anything else.
- **BREAKING:** the `Message.ask_*` methods call the message's own
  `reply`, `reply_rich` and `edit` instead of `Client.ask`, so Pyrogram handles
  replies in topics, business chats and ephemeral messages, and they accept
  only what those methods accept. That leaves out `reply_parameters`,
  `message_thread_id` and `direct_messages_topic_id` on a reply, and
  `schedule_date` on an edit. Affects calls on a `Message` that pass those.
  Migration: call the `Client.ask_*` method with
  those arguments.
- **BREAKING:** pyroflow needs `kurigram>=2.2.26`, the first version with
  `Message.edit(rich_message=...)`. Migration: upgrade kurigram.
- Faster dispatch: `UpdateListener.resolve` returns at once when no wait is
  open, and listener filters, `on_error_func`, handler
  callbacks and `split_text` rules that are coroutine functions are awaited
  directly (the new `pyroflow.utils.call_maybe_async`). A listener filter
  no longer captures the caller's stack on every call. An error in a
  listener filter or in `on_error_func` is now logged by the
  `pyroflow.update_listener.update_listener` logger instead of `pytrove`'s.
- **BREAKING:** `Dispatcher.handle_listen` returns whether the listener took
  the update instead of raising `StopPropagation`, and the worker calls it
  before taking its lock; `handle_update` only runs the handlers. A
  listener now resolves an update while handlers hold the worker locks.
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
  `listen_context` on the `ask_*` methods, and is a `ListenerContext`, no
  longer a value of any type or a dict; it is keyword-only, and
  `ListenerModel.meta` is `ListenerModel.context`, `None` unless one was passed.
  `ListenerModel` takes its `future` as the second field, with no default.
  With `ask_context_message` on, `ask_*` puts the sent or edited message in the
  context as `message`, on a copy, unless it holds one, so the id is
  `context.message.id` instead of
  `meta["message_id"]`. Affects code passing
  or reading `meta`, or building `ListenerModel` itself.
  Migration: `listen(chat, context=ListenerContext(step=1))` instead of
  `listen(chat, {"step": 1})`,
  `ask(..., listen_context=ListenerContext(...))` instead of
  `ask(..., meta=...)`, read `model.context.step` instead of
  `model.meta["step"]`, and build models as
  `ListenerModel(key, loop.create_future())`.
- **BREAKING:** every listen parameter of the `ask_*` methods (on `Client`
  and `Message`) starts with `listen_`: `timeout` is `listen_timeout`.
  Affects every call passing it.
  Migration: `ask(..., listen_timeout=30)` instead of
  `ask(..., timeout=30)`.
- **BREAKING:** `CallbackQueryListener` no longer cancels message waits: a
  press that no callback wait takes no longer ends the `ask` that sent the
  pressed message, and nothing in pyroflow does it instead. Affects bots
  whose buttons on an `ask` message were meant to end it.
  Migration: cancel the wait in the button's handler, by the key it waits
  on: `client.get_listener(Message).cancel(MessageKey.from_sent(query.message, user_id))`,
  with the `listen_user_id` the `ask` was given, or `None` without one.
- **BREAKING:** `Client.listeners`, `Client.message_listen` and
  `Client.callback_listen` are gone. Affects code that reads them, and their
  `KeyError` when no listener is registered.
  Migration: `client.get_listener(Message)` instead of
  `client.message_listen` or `client.listeners[Message]`; it returns `None`
  rather than raising. To wait, `client.listen_message(...)` or
  `client.listen_callback_query(...)`.
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
  longer fail their `ask_*` with `ListenerCancelled`: the listeners start
  before it.
- `BotCommandsMixin` publishes the bot commands before the dispatcher starts,
  so the first updates, such as a `registered_command` check, already see
  them. A failed publish is logged instead of failing `start` on a connected
  client.
- `BotCommandsMixin` sends one call per Telegram command list: commands
  declared with no scope and with `BotCommandScopeDefault()`, or with no
  language and `""`, used to go out in separate calls to the same list, and
  only the last to land was kept.
- `Dispatcher.stop` stops the listeners before it drains the workers, so a
  handler blocked in `ask_*` no longer holds up the shutdown until its timeout.
- `MessageListener` no longer raises `AttributeError` for messages without
  `from_user` (anonymous admins, channel posts); the listener key's user is `None`.
- A registered listener with no pending `listen` no longer swallows every
  update of its type: handlers used to be skipped while the listener held no
  waiters.

## [0.2.1] - 2026-07-26

Initial changelog; see the GitHub releases for earlier history.

[Unreleased]: https://github.com/eeeob/pyroflow/compare/v0.2.1...HEAD
[0.2.1]: https://github.com/eeeob/pyroflow/releases/tag/v0.2.1
