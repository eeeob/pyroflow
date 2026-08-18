# pyroflow

[![PyPI version](https://img.shields.io/pypi/v/pyroflow)](https://pypi.org/project/pyroflow/)
[![Python versions](https://img.shields.io/pypi/pyversions/pyroflow)](https://pypi.org/project/pyroflow/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**Conversation-oriented Pyrogram extension with per-update listeners and multi-session coordination.**

pyroflow builds on top of [Pyrogram](https://github.com/pyrogram/pyrogram) / [Kurigram](https://github.com/KurimuzonAkuma/pyrogram) to replace the handler-based model with a conversation-first API — `await` a specific reply from a specific user instead of wiring up global handlers and managing state machines by hand.

```
pip install pyroflow
```

For Redis-backed coordination:

```
pip install pyroflow[redis]
```

---

## Why pyroflow?

Pyrogram fires your handler for **every** incoming update of a given type. The moment you need a back-and-forth conversation you end up writing state machines, storing `user_id → step` in a dict, and hoping two updates don't race each other.

pyroflow solves all three problems:

| Problem | pyroflow solution |
|---|---|
| Waiting for a specific reply | `UpdateListener` — `await` the next update from a user |
| Duplicate processing across multiple bot sessions | `UpdateCoordinated` — distributed lock per update |
| Replaying or inspecting previous handler steps | `UpdateHistory` — per-update-type handler record |

---

## Installation

**Minimum requirements:** Python 3.10+

```
pip install pyroflow          # core
pip install pyroflow[redis]   # + Redis coordinator support
pip install pyroflow[dev]     # + development tools (hatch, twine)
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

---

### Coordinators

A `UpdateCoordinated` acquires a **distributed lock** before processing an update. This ensures the same update is handled by exactly one session when the bot runs on multiple servers simultaneously.

```python
from functools import partial
from redis.asyncio import Redis
from pyroflow import Client, MessageCoordinated, RedisUpdateCoordinator


client = Client("my_session")
redis = Redis(db=client.name)
coordinator_factory = partial(RedisUpdateCoordinator, redis)
coordinated = MessageCoordinated(coordinator_factory)
client.register_coordinated(coordinated)

client.run()
```

**Supported backends:**

| Backend | Extra |
|---|---|
| Redis | `pip install pyroflow[redis]` |

**Lock states:**

- `HANDLED` — at least one handler *ran* for the update, whether it returned normally or raised; the lock is released and other sessions skip the update. A raising handler still counts: the update reached its owner, so replaying it elsewhere would duplicate work rather than recover.
- `None` — no handler ran at all; the lock is released so another session may retry.

To hand an update back for another session to retry, raise `UnhandledUpdate` from your handler — it stops processing on the current session and leaves the lock unclaimed.

---

### Histories

A `UpdateHistory` records which handlers ran successfully for each update. This enables features like `back` buttons that replay or inspect previous processing steps.

```python
from pyroflow import Client, CallbackQueryHistory

client = Client("my_session")
client.register_history(CallbackQueryHistory())

client.run()
```

---

They can also be removed at runtime:

```python
await client.unregister_listener(Message)
await client.unregister_coordinated(Message)
await client.unregister_history(CallbackQueryHistory)
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

---

## License

MIT
