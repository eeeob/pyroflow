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

**Raises:**
- `ListenerTimeout` — no reply arrived within `timeout` seconds
- `ListenerCancelled` — the listener was cancelled while waiting

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
