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
        chat_id=message.chat.id,
        text="What is your name?",
        listen_user_id=message.from_user.id,
        timeout=60,
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

A listener takes the next matching update its client receives after `listen` is called. Listeners live in the client's own process: pyroflow does not coordinate between sessions, so a bot running in several processes handles each update once in every process that receives it.

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
    timeout=30,
)

# Edit an existing message, then wait for a callback query
callback = await client.ask(
    chat_id=chat_id,
    text="Updated — choose again:",
    message_id=sent_msg.id,
    listen_user_id=user_id,
    timeout=30,
    update_type=CallbackQuery,
)
```

**Parameters:**

| Parameter | Description |
|---|---|
| `chat_id` | Target chat |
| `text` | Message text |
| `message_id` | If provided, edits the message instead of sending a new one |
| `listen_user_id` | Filter the awaited update by user |
| `listen_message_id` | Filter the awaited update by message |
| `timeout` | Seconds to wait before raising `ListenerTimeout` |
| `update_type` | Update type to wait for — determines the return type (default: `Message`) |
| `meta` | Arbitrary metadata attached to the listener |
| `filters` | A Pyrogram filter the awaited update must also pass |
| `strict` | `True`: an update that fails `filters` ends the wait; `False`: it is skipped and the wait goes on |

**Raises:**
- `ListenerTimeout` — no reply arrived within `timeout` seconds
- `ListenerCancelled` — the listener was cancelled while waiting
- `ListenerRejected` — with `strict=True`, an update failed `filters` (a `ListenerCancelled` carrying the update)

**Filters.** `filters` adds a Pyrogram filter the awaited update must pass besides `listen_user_id` and `listen_message_id`. An update whose key matches but that fails the filter goes on to the handlers, and the wait goes on. With `strict=True` that update ends the wait with `ListenerRejected` instead, which carries the rejected update:

```python
from pyrogram import filters
from pyroflow.errors import ListenerRejected

# Wait for text; a /cancel command ends the question.
answer = await message.ask(
    "What is your name?",
    filters=filters.text & ~filters.command("cancel"),
    strict=True,
)

# Ask again until the answer passes the filter.
while True:
    try:
        answer = await message.ask("Send a number:", filters=filters.regex(r"^\d+$"), strict=True)
        break
    except ListenerRejected:
        await message.reply("That is not a number.")
```

A filter on the listener itself (`MessageListener(filters=..., strict=...)`) applies to every wait: it is joined with the call's filter by `&`, and a call that passes no `strict` takes the listener's. A strict listener filter such as `~filters.command(...)`, joined with a call's `filters.text`, makes a photo end the question too; pass `strict=False` to skip it instead, and the command then no longer ends the question.

> ⚠️ **A wait that never ends.** Without `strict`, a wait stays open until `timeout`, or forever without one, when every update its key can still match fails the filter:
> - The key names a single update. With `MessageListener`, a `listen_message_id` names one incoming message: if the filter rejects it, nothing else can match.
> - The filter can never pass that update type, such as `filters.photo` while waiting for a `CallbackQuery`.
> - The user keeps sending updates the filter rejects.
>
> Give such waits a `timeout` (on the call or on the listener), use `strict=True` when the first rejected update should end the wait, or end the wait yourself with `listener.cancel(key)`. Note that `strict=True` ends the wait on **any** rejected update of the key, such as a photo while text is awaited.


`ask_rich()` does the same with a rich message: it sends with `send_rich_message`, or edits with `edit_message_text(rich_message=...)` when `message_id` is given. `Message.ask_rich()` mirrors `Message.ask()`.

```python
from pyrogram.types import InputRichMessage

answer = await client.ask_rich(
    chat_id,
    InputRichMessage(html="Pick a <b>name</b>:"),
    listen_user_id=user_id,
    timeout=30,
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
    reply = await client.ask(chat_id, "Your input?", listen_user_id=uid, timeout=30)
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
