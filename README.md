# pyroflow

[![PyPI version](https://img.shields.io/pypi/v/pyroflow)](https://pypi.org/project/pyroflow/)
[![Python versions](https://img.shields.io/pypi/pyversions/pyroflow)](https://pypi.org/project/pyroflow/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**Conversation-oriented Pyrogram extension with per-update listeners and `ask_*`.**

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
| Asking a question and waiting for its answer | `ask()` / `ask_callback_query()` — send or edit a message, then `await` the reply or the press |

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

    answer = await message.ask("What is your name?", listen_timeout=60)
    await answer.reply(f"Hello, {answer.text}!")

client.run()
```

`message.ask` replies to the message, then waits for the next message from its sender in the same chat and topic.

---

## Core concepts

### Listeners

A `UpdateListener` is a typed queue bound to a Pyrogram update type. Any coroutine can `await` the next matching update from a specific user or chat. An update claimed by a listener **never reaches the normal handler pipeline**.

```python
from pyroflow import Client, MessageListener
from pyroflow.errors import ListenerTimeout

client = Client("my_session")
messages = MessageListener()
client.register_listener(messages)

@client.on_message()
async def on_confirm(client, message):
    if message.text != "/confirm":
        return

    await message.reply("Send your confirmation code:")

    try:
        code_msg = await messages.listen(
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

The client can wait too, on the listener registered for the update type:

```python
code_msg = await client.listen_message(chat_id=chat_id, user_id=user_id, timeout=120)
press = await client.listen_callback_query(chat_id=chat_id, message_id=message_id)
client.get_listener(Message)   # the registered listener, or None
```

`listen_message` and `listen_callback_query` take the fields of their key and the wait arguments, and raise `RuntimeError` when no listener is registered for their type. `get_listener` returns `None` instead of raising; use the listener it returns to look up or end waits, such as `client.get_listener(Message).cancel(key)`.

Each listener waits on keys of its own class, from `pyroflow.models`, and its `listen` takes the same fields:

- `MessageListener`: `MessageKey(chat_id, user_id, message_thread_id, direct_messages_topic_id, ephemeral)`.
- `CallbackQueryListener`: `CallbackQueryKey(chat_id, user_id, message_id, inline_message_id, ephemeral)`.

A field left `None` matches any value, so `messages.listen()` takes the next message anywhere, and `messages.listen(user_id=7)` takes user 7 in any chat. A key holds the values as given, so to wait in a user's private chat pass `chat_id`: a private chat has the user's id. `inline_message_id` waits for a press on a message sent in inline mode; such a press has no chat, so it reaches a wait on its user, never a wait on a chat.

**Topics.** `message_thread_id` waits in one forum topic, or in a topic of a bot's private chat. `direct_messages_topic_id` waits in one topic of a channel's direct messages chat. `ask` waits in the topic of the message it sent or edited. Kurigram leaves `message_thread_id` empty in a forum's General topic, so a question asked there waits on the whole chat.

A listener takes the next matching update its client receives after `listen` is called. When several waits match one update, such as one for the user and one for the whole chat, only the most specific gets it: the one with the most fields set, then by field order, so `(chat, user)` comes before `(chat, topic)`. Pass `resolve_scope=ListenerScope.ALL` (from `pyroflow.enums`) to the listener to give it to every one. Listeners live in the client's own process: pyroflow does not coordinate between sessions, so a bot running in several processes handles each update once in every process that receives it.

### Waiting inside handlers

A handler that waits in an `ask_*` method or `listen` holds the worker running it (Pyrogram's `workers`, by default your CPU count plus four). When every worker waits, none is left to read the replies, and the bot freezes. A `WorkersPolicy` decides what happens instead, once a wait would take the last worker, which always stays out to read the replies:

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

### ask() and ask_callback_query()

The `ask_*` methods are the high-level wrappers around listeners. They send (or edit) a message and then suspend until the answer arrives — all in one `await`. `ask` waits for the next message, and `ask_callback_query` for a press on the buttons of the message it sent or edited. Both are on `Client` and on `Message`, and both take the key from the message sent or edited: its chat and topic, and for a press its id.

```python
from pyrogram import filters

# Send a new message, then wait for the user's next message in the chat
answer = await client.ask(
    chat_id,
    "What is your name?",
    listen_filters=filters.user(user_id),
    listen_timeout=30,
)

# Edit an existing message, then wait for a press on its buttons
callback = await client.ask_callback_query(
    chat_id,
    "Updated — choose again:",
    sent_msg.id,
    reply_markup=keyboard,
    listen_timeout=30,
)
```

Every `ask_*` takes `listen_user_id`, the user to wait for. Without it, the wait is on the user the message sent or edited names: the receiver of an ephemeral message (`ephemeral_message_parameters`), or the sender of the message it replies to (`reply_parameters`), unless that message is the client's own; with neither, on anyone in the chat, and in a private chat the user is the only one who can answer. `Message.ask_*` replies to the message, or edits it when it is the client's own (`editable`), and without `listen_user_id` waits for its sender first.

**Parameters:**

| Parameter | Description |
|---|---|
| `chat_id` | `Client` only: target chat |
| `text` | Message text (`rich_message` in the `_rich` methods) |
| `message_id` | `Client` only: if provided, edits the message instead of sending a new one |
| `force_send` | `Message` only: reply with a new message even when this one is `editable` |
| `listen_timeout` | Seconds to wait before raising `ListenerTimeout` |
| `listen_context` | A `ListenerContext` of values attached to the listener |
| `listen_filters` | A Pyrogram filter the awaited update must also pass |
| `listen_strict` | `True`: an update that fails `listen_filters` ends the wait; `False`: it is skipped and the wait goes on |

Any other keyword argument goes to the Pyrogram method that sends or edits, such as `reply_markup`.

**Raises:**
- `ListenerTimeout` — no reply arrived within `listen_timeout` seconds
- `ListenerCancelled` — the listener was cancelled while waiting
- `ListenerReplaced` — a newer wait took the same key (a `ListenerCancelled`)
- `ListenerRejected` — with `listen_strict=True`, an update failed `listen_filters` (a `ListenerCancelled`)
- `ListenerAlreadyExists` — with `DuplicatePolicy.REJECT` on the listener, a wait already exists on the key. The question is already sent by then.

To check before sending instead, look the key up yourself, as the wait builds it: `MessageKey(chat_id, user_id) in client.get_listener(Message).listeners` for `message.ask` in a chat without topics, with `None` as `user_id` when the message is the client's own (`editable`). `client.ask` waits with no `user_id`.

**Filters.** `listen_filters` adds a Pyrogram filter the awaited update must pass besides its key. An update whose key matches but that fails the filter goes on to the handlers, and the wait goes on. With `listen_strict=True` that update ends the wait with `ListenerRejected` instead:

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

`listen_strict` decides for the whole filter: with `filters.text & ~filters.command("cancel")` and `listen_strict=True`, a photo ends the question just like the command does.

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

With `setup_pyroflow(ask_context_message=True)`, the `ask_*` methods put the message it sent or edited in `listen_context` as `message`, on a copy, unless you set one first. Otherwise `listen_context` reaches the listener as it is. With the message, `on_error_func` can clean up the question:

```python
async def drop_question(exc, model):
    if model.context and model.context.message:
        await model.context.message.delete()
```

To end a question from a button's handler, such as a "back" button on it, cancel its wait by its key, which raises `ListenerCancelled` in `ask`: `client.get_listener(Message).cancel(MessageKey.from_sent(query.message, query.from_user.id))` after `message.ask` on the user's message, or with `None` as the user after `client.ask`, or after `message.ask` on the client's own (`editable`) message, such as `query.message`.

> ⚠️ **A wait that never ends.** Without `listen_strict`, a wait stays open until `listen_timeout`, or forever without one, when every update its key can still match fails the filter:
> - The filter can never pass that update type, such as `filters.photo` while waiting for a `CallbackQuery`.
> - The user keeps sending updates the filter rejects.
>
> Give such waits a timeout (`listen_timeout` on `ask_*`, `timeout` on `listen` or on the listener), use `listen_strict=True` (`strict=True` on `listen`) when the first rejected update should end the wait, or end the wait yourself with `listener.cancel(key)`. Note that `listen_strict=True` ends the wait on **any** rejected update of the key, such as a photo while text is awaited.


`ask_rich()` and `ask_callback_query_rich()` do the same with a rich message: they send with `send_rich_message`, or edit with `edit_message_text(rich_message=...)` when `message_id` is given. The `Message` methods call the message's own `edit`, `reply` and `reply_rich`, so they accept what those accept; use the `Client` methods for arguments such as `reply_parameters`.

```python
from pyrogram.types import InputRichMessage

answer = await client.ask_rich(
    chat_id,
    InputRichMessage(html="Pick a <b>name</b>:"),
    listen_timeout=30,
)
```

Ephemeral messages have ids that do not follow each other and can be reused, so no key holds one. `ephemeral=True` on `listen` waits on ephemeral updates. Only such a wait receives them, and a regular update never reaches it. `Message.ask_*` on an ephemeral message waits this way for its sender. `Client.ask_*` knows no user, so it raises `ValueError` for `ephemeral_message_parameters` before sending. Two ephemeral messages to one user share a key, so tell them apart with `listen_filters`.

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
    reply = await client.ask(chat_id, "Your input?", listen_timeout=30)
except ListenerTimeout:
    await client.send_message(chat_id, "You took too long. Try again.")
except ListenerCancelled:
    await client.send_message(chat_id, "Session was cancelled.")
```

Every error derives from `PyroflowError`. `ListenerError` covers waiting and the `ask_*` methods (`ListenerTimeout`, `ListenerCancelled`, `ListenerAlreadyExists`).

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
