# pyroflow

[![PyPI version](https://img.shields.io/pypi/v/pyroflow)](https://pypi.org/project/pyroflow/)
[![Python versions](https://img.shields.io/pypi/pyversions/pyroflow)](https://pypi.org/project/pyroflow/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**Conversation-oriented Pyrogram extension with per-update listeners and `ask`.**

pyroflow builds on top of [Pyrogram](https://github.com/pyrogram/pyrogram) / [Kurigram](https://github.com/KurimuzonAkuma/pyrogram) to replace the handler-based model with a conversation-first API — `await` a specific reply from a specific user instead of wiring up global handlers and managing state machines by hand.

> Arabic translation: [README.ar.md](README.ar.md). If the two differ, this English text is the reference.

> **Upgrading?** See [CHANGELOG.md](CHANGELOG.md) for breaking changes and how to migrate.

```
pip install pyroflow
```

---

## Why pyroflow?

Pyrogram fires your handler for **every** incoming update of a given type. The moment you need a back-and-forth conversation you end up writing state machines, storing `user_id → step` in a dict, and hoping two updates don't race each other.

pyroflow replaces that with a single `await`:

| Problem | pyroflow solution |
|---|---|
| Waiting for a specific reply | `UpdateListener` — `await` the next update from a user |
| Asking a question and waiting for its answer | `ask()` — send or edit a message, then `await` the reply |

---

## Installation

**Minimum requirements:** Python 3.10+

```
pip install pyroflow
```

To get the latest, unreleased changes straight from GitHub instead of the last PyPI release:

```bash
pip install git+https://github.com/eeeob/pyroflow.git --force-reinstall
```
### 🔹 Without Deps
```bash
pip install git+https://github.com/eeeob/pyroflow.git --force-reinstall --no-deps
```
---


## Quick start

```python
from pyroflow import Client, MessageListener

client = Client("my_session")
client.register_listener(MessageListener())

@client.on_message()
async def on_start(client, message):
    if message.text != "/start":
        return

    answer = await message.ask(
        text="What is your name?",
        listen_user_id=message.from_user.id,
        listen_timeout=60,
    )
    await answer.reply(f"Hello, {answer.text}!")

client.run()
```

---

## Core concepts

### Listeners

A `UpdateListener` is a typed queue bound to a Pyrogram update type. Any coroutine can `await` the next matching update from a specific user or chat. An update claimed by a listener **never reaches the normal handler pipeline**.

```python
from pyroflow import Client, MessageListener
from pyroflow.errors import ListenerTimeout

client = Client("my_session")
client.register_listener(MessageListener())

@client.on_message()
async def on_confirm(client, message):
    if message.text != "/confirm":
        return

    await message.reply("Send your confirmation code:")

    try:
        code_msg = await client.message_listen(
            chat_id=message.chat.id,
            user_id=message.from_user.id,
            timeout=120,
        )
    except ListenerTimeout:
        await message.reply("Timed out. Please try again.")
        return

    await code_msg.reply(f"Code received: {code_msg.text}")

client.run()
```

Shortcuts for the two most common listener types:

```python
client.message_listen    # UpdateListener[Message]
client.callback_listen   # UpdateListener[CallbackQuery]
```

A listener takes the next matching update its client receives after `listen` is called. When several waits match one update, such as one for the user and one for the whole chat, only the most specific gets it; pass `resolve_scope=ListenerScope.ALL` (from `pyroflow.enums`) to the listener to give it to every one. Listeners live in the client's own process: pyroflow does not coordinate between sessions, so a bot running in several processes handles each update once in every process that receives it.

### Waiting inside handlers

A handler that waits in `ask` or `listen` holds the worker running it (Pyrogram's `workers`, by default your CPU count plus four). When every worker waits, none is left to read the replies, and the bot freezes. A `WorkersPolicy` decides what happens instead, once a wait would take the last worker, which always stays out to read the replies:

```python
from pyroflow.enums import WorkersPolicy

client = Client("bot", workers=12).setup_pyroflow(workers_policy=WorkersPolicy.CANCEL_OLDEST)
```

| Policy | What happens | Fits |
|---|---|---|
| `REJECT` | The wait raises `ListenerWorkersBusy` | A deliberate cap, such as a support bot with fixed capacity |
| `CANCEL_OLDEST` | The oldest wait ends with `ListenerEvicted` (a `ListenerCancelled`), and the new one takes its place at once. Its handler may go on working, and a new wait of its goes through the same steps; with no wait to end, it raises `ListenerWorkersBusy` | Menus and questions users often leave unanswered |

By default there is no policy and no timeout, so a question nobody answers holds its worker for good: once `workers` such questions are open, the bot reads no more updates until it restarts. Set a policy, a `listen_timeout`, or both, unless `workers` is far above any number of open conversations. `setup_pyroflow()` removes a policy. Every mode keeps each handler under its worker's lock. Only waits are counted, not a handler that is simply working, and only a wait in the handler itself: one in a task the handler spawned is not counted, even if the handler awaits that task with `asyncio.gather` and so holds its worker, and neither is one in a sync handler, which runs in a thread. It is a method, not a `Client(...)` argument, so pyroflow does not have to redeclare Pyrogram's constructor.

---

### ask()

`ask()` is the high-level wrapper around listeners. It sends (or edits) a message and then suspends until a matching reply arrives — all in one `await`.

```python
# Send a new message, then wait for reply
answer = await client.ask(
    chat_id=chat_id,
    text="Choose an option:",
    reply_markup=keyboard,
    listen_user_id=user_id,
    listen_timeout=30,
)

# Edit an existing message, then wait for a callback query
callback = await client.ask(
    chat_id=chat_id,
    text="Updated — choose again:",
    message_id=sent_msg.id,
    listen_user_id=user_id,
    listen_timeout=30,
    listen_update_type=CallbackQuery,
)
```

**Parameters:**

| Parameter | Description |
|---|---|
| `chat_id` | Target chat |
| `text` | Message text |
| `message_id` | If provided, edits the message instead of sending a new one |
| `listen_user_id` | Filter the awaited update by user |
| `listen_message_id` | Filter the awaited update by message: an id, `None` (the default) for no filter, or a `ListenMessageId` (from `pyroflow.enums`): `SENT` for the message `ask` sent or edited (a press on its buttons), `NEXT` for the message right after it. In a group another member's message can take the next id |
| `listen_timeout` | Seconds to wait before raising `ListenerTimeout` |
| `listen_update_type` | Update type to wait for — determines the return type (default: `Message`) |
| `listen_context` | A `ListenerContext` of values attached to the listener |
| `listen_filters` | A Pyrogram filter the awaited update must also pass |
| `listen_strict` | `True`: an update that fails `listen_filters` ends the wait; `False`: it is skipped and the wait goes on |

**Raises:**
- `ListenerTimeout` — no reply arrived within `listen_timeout` seconds
- `ListenerCancelled` — the listener was cancelled while waiting
- `ListenerReplaced` — a newer wait took the same key (a `ListenerCancelled`)
- `ListenerRejected` — with `listen_strict=True`, an update failed `listen_filters` (a `ListenerCancelled`)
- `ListenerAlreadyExists` — with `DuplicatePolicy.REJECT` on the listener, a wait already exists on the key. The question is already sent by then.

To check before sending instead, look the key up yourself: `ListenerKey(chat_id, user_id) in client.message_listen.listeners`.

**Filters.** `listen_filters` adds a Pyrogram filter the awaited update must pass besides `listen_user_id` and `listen_message_id`. An update whose key matches but that fails the filter goes on to the handlers, and the wait goes on. With `listen_strict=True` that update ends the wait with `ListenerRejected` instead:

```python
from pyrogram import filters
from pyroflow.errors import ListenerRejected

# Wait for text; a /cancel command ends the question.
answer = await message.ask(
    "What is your name?",
    listen_filters=filters.text & ~filters.command("cancel"),
    listen_strict=True,
)

# Ask again until the answer passes the filter.
while True:
    try:
        answer = await message.ask("Send a number:", listen_filters=filters.regex(r"^\d+$"), listen_strict=True)
        break
    except ListenerRejected:
        await message.reply("That is not a number.")
```

`listen_strict` decides for the whole filter: with `filters.text & ~filters.command("cancel")` and `listen_strict=True`, a photo ends the question just like the command does. `MessageListener` logs a warning when a non-strict filter waits on a `listen_message_id`, the first case below.

To filter every wait that passes no `listen_filters`, give the listener a `strict_filter`, such as `MessageListener(strict_filter=~filters.command("cancel"))`. An update that fails it ends the wait with `ListenerRejected`.

**Registered commands.** `pyroflow.filters.registered_command()` passes a message whose text or caption is a command registered for this bot, with or without arguments. `/cmd@this_bot` passes; `/cmd@other_bot`, an unknown command and plain text do not. The commands come from `client.get_bot_commands()` for each of the filter's `scopes` (by default `registered_command.DEFAULT_SCOPES`, the four that need no chat or user) in each of its `language_codes` (by default `""`), fetched at once on first use and kept by the filter with the bot's usernames until the client starts again, so commands set meanwhile are seen after a restart. A failed fetch, as on a user account, raises its error unchanged and cancels the other fetches, and the next command fetches again. Each `registered_command()` filter fetches for itself. `registered_command(ephemeral=False)` leaves out commands marked `is_ephemeral`, and `username_policy` (a `CommandUsernamePolicy` from `pyroflow.enums`) sets which `@username` passes: `OPTIONAL` (the default) takes none or the bot's, `REQUIRED` only the bot's, `None` none or any, `ANY_REQUIRED` any but not none, and `FORBIDDEN` none.

Inverted as a `strict_filter`, it lets a registered command end a question that passes no `listen_filters` and reach its handler, while any other message answers it:

```python
from pyroflow import MessageListener, filters

client.register_listener(MessageListener(strict_filter=~filters.registered_command()))
```

A question with its own `listen_filters` skips `strict_filter`, so it adds the filter itself, and any other message that fails them, such as a photo, then ends it too:

```python
from pyrogram import filters as pyrogram_filters

name = await message.ask(
    "Your name?",
    listen_filters=pyrogram_filters.text & ~filters.registered_command(),
    listen_strict=True,
)
```

Either way the command goes on to any other wait it matches, such as one for the whole chat, and reaches its handler only if none of them takes it.

To react to every wait that fails, pass `on_error_func` to the listener. It gets the error and the `ListenerModel` (its key, `context`, filter) before `listen` raises:

```python
def report(exc, model):
    log.info("Wait for %s ended: %r", model.key, exc)

client.register_listener(MessageListener(on_error_func=report))
```

A wait's `context` is a `ListenerContext`: typed fields plus any values you add, all read and set as attributes. Subclass it to type your own fields.

```python
from pyroflow.models import ListenerContext

class OrderContext(ListenerContext):
    step: int = 0

answer = await message.ask("Your name?", listen_context=OrderContext(step=1, note="signup"))
```

With `setup_pyroflow(ask_context_message=True)`, `ask` puts the message it sent or edited in `listen_context` as `message`, on a copy, unless you set one first. Otherwise `listen_context` reaches the listener as it is. With the message, `on_error_func` can clean up the question:

```python
async def drop_question(exc, model):
    if model.context and model.context.message:
        await model.context.message.delete()
```

`MessageListenCancellingCallbackQueryListener` is a `CallbackQueryListener` that also cancels message listens: a press that no callback wait takes cancels the message wait tied to the pressed message (its `context.message`), which raises `ListenerCancelled` in `ask`. Register it instead of `CallbackQueryListener` to get this; for example, a "back" button on a question then ends the wait for its answer:

```python
from pyroflow import MessageListenCancellingCallbackQueryListener

client.register_listener(MessageListenCancellingCallbackQueryListener())
```

`cancel_policy` decides which presses cancel: `MessageListenCancelPolicy.UNRESOLVED` (the default) only those no callback wait took, `RESOLVED` only those one took, and `ALWAYS` every press. `cancel_scope` decides how many message waits tied to the pressed message (its `context.message`) one press cancels: `ListenerScope.ALL` (the default) every one, `FIRST` only the most specific. `ask` records that message in the context only with `setup_pyroflow(ask_context_message=True)`; otherwise only waits that set `context.message` themselves are tied to a message.

> ⚠️ **A wait that never ends.** Without `listen_strict`, a wait stays open until `listen_timeout`, or forever without one, when every update its key can still match fails the filter:
> - The key names a single update. With `MessageListener`, a `listen_message_id` names one incoming message: if the filter rejects it, nothing else can match.
> - The filter can never pass that update type, such as `filters.photo` while waiting for a `CallbackQuery`.
> - The user keeps sending updates the filter rejects.
>
> Give such waits a timeout (`listen_timeout` on `ask`, `timeout` on `listen` or on the listener), use `listen_strict=True` (`strict=True` on `listen`) when the first rejected update should end the wait, or end the wait yourself with `listener.cancel(key)`. Note that `listen_strict=True` ends the wait on **any** rejected update of the key, such as a photo while text is awaited.


`ask_rich()` does the same with a rich message: it sends with `send_rich_message`, or edits with `edit_message_text(rich_message=...)` when `message_id` is given. `Message.ask_rich()` mirrors `Message.ask()`. Both call the message's own `edit`, `reply` and `reply_rich`, so they accept what those accept; use `client.ask()` for arguments such as `reply_parameters`.

Ephemeral messages have ids that do not follow each other and can be reused, so listeners never match them by id. Pass `EphemeralUpdates.ANY` as `listen_message_id`, or as `message_id` of `listen()`, with a user: only that wait receives ephemeral updates, and a regular update never reaches it. So an ephemeral `ask()` gets its answer only with `listen_message_id=EphemeralUpdates.ANY`: with the default `None` it waits for the user's next regular message, and the ephemeral answer never reaches it. `SENT` and `NEXT` raise `ValueError` there. `client.ask()` with `ephemeral_message_parameters` needs `listen_user_id`; `Message.ask()` replying to an ephemeral message takes it from the sender. Two ephemeral messages to one user share a key, so tell them apart with `listen_filters`.

```python
from pyrogram.types import InputRichMessage

answer = await client.ask_rich(
    chat_id,
    InputRichMessage(html="Pick a <b>name</b>:"),
    listen_user_id=user_id,
    listen_timeout=30,
)
```

---

Listeners can also be removed at runtime:

```python
await client.unregister_listener(Message)
```

---

## Error handling

```python
from pyroflow.errors import ListenerTimeout, ListenerCancelled

try:
    reply = await client.ask(chat_id, "Your input?", listen_user_id=uid, listen_timeout=30)
except ListenerTimeout:
    await client.send_message(chat_id, "You took too long. Try again.")
except ListenerCancelled:
    await client.send_message(chat_id, "Session was cancelled.")
```

Every error derives from `PyroflowError`. `ListenerError` covers waiting and `ask` (`ListenerTimeout`, `ListenerCancelled`, `ListenerAlreadyExists`).

---

## Development

The only prerequisite is [uv](https://docs.astral.sh/uv/).

```bash
make sync        # install the locked environment
make test        # run the test suite
make lint        # ruff check + ruff format --check
make typecheck   # ty
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full workflow and rules.

---

## License

MIT
