# pyroflow

[![PyPI version](https://img.shields.io/pypi/v/pyroflow)](https://pypi.org/project/pyroflow/)
[![Python versions](https://img.shields.io/pypi/pyversions/pyroflow)](https://pypi.org/project/pyroflow/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**Conversations for [Kurigram](https://github.com/KurimuzonAkuma/pyrogram) (Pyrogram): `await` the reply, and run one user's updates one at a time.**

> Arabic translation: [README.ar.md](README.ar.md). If the two differ, this English text is the reference.

```bash
pip install pyroflow
```

Python 3.10+. `import pyroflow` patches Pyrogram in place: `pyroflow.Client` **is** `pyrogram.Client`, so your existing code keeps working.

pyroflow follows Kurigram's releases: the floor is `kurigram>=2.2.27` with no ceiling, and a weekly CI job runs the suite against the newest Kurigram release, so a change there is caught within the week.

---

## Listening: `ask` and listeners

A handler asks a question and `await`s the answer, instead of a state machine and a `user_id → step` dict. An update taken by a wait never reaches the handlers.

```python
from pyroflow import Client, MessageListener
from pyroflow.enums import WorkersPolicy
from pyroflow.errors import ListenerTimeout

client = Client("my_session").setup_pyroflow(workers_policy=WorkersPolicy.CANCEL_OLDEST)
client.register_listener(MessageListener())


@client.on_message()
async def on_start(client, message):
    if message.text != "/start":
        return

    try:
        answer = await message.ask(
            "What is your name?", listen_user_id=message.from_user.id, listen_timeout=60
        )
    except ListenerTimeout:
        await message.reply("Timed out.")
        return

    await answer.reply(f"Hello, {answer.text}!")


client.run()
```

`message.ask` replies, then waits for the next message from `listen_user_id` in the same chat and topic. `ask_callback_query` waits for a press on the buttons of the message it sent instead, and both are on `Client` too, with `edit_message_id` to edit instead of send. A wait can be more direct: `client.listen_message(chat_id=..., user_id=..., timeout=120)`, or `listener.listen(MessageKey(chat_id, user_id))`, where a `None` field matches any value.

> ⚠️ **Workers do not freeze.** A handler that waits holds its Pyrogram worker. `workers_policy` keeps one worker out of the waits to read the replies, and decides what happens when a wait would take it; `WorkersPolicy.CANCEL_OLDEST` is the default:
>
> | Policy | What happens |
> |---|---|
> | `WorkersPolicy.CANCEL_OLDEST` | The oldest wait ends with `ListenerEvicted`, and the new one takes its place |
> | `WorkersPolicy.REJECT` | The new wait raises `ListenerWorkersBusy` |
>
> `setup_pyroflow(workers_policy=None)` turns it off: then once `workers` questions are left unanswered with no `listen_timeout`, the bot reads no more updates.

Every `ask_*` takes `listen_timeout`, `listen_filters` (a Pyrogram filter the answer must pass), `listen_strict` (an answer that fails the filter ends the wait with `ListenerRejected`) and `listen_user_id`. Anything else goes to the Pyrogram method that sends or edits.

**Your own update types.** A listener is a key class plus a listener class, and `client.listen` works for any of them with no further code. To wait for inline queries by user:

```python
from dataclasses import dataclass

from pyrogram.types import InlineQuery
from pyroflow import UpdateListener
from pyroflow.models import ListenerKey


@dataclass(frozen=True, slots=True)
class InlineQueryKey(ListenerKey[InlineQuery]):
    __update_type__ = InlineQuery

    user_id: int | None = None

    @classmethod
    def from_update(cls, update):
        return cls(update.from_user.id)

    @classmethod
    def from_sent(cls, sent, user_id=None):
        return cls(user_id)


class InlineQueryListener(UpdateListener[InlineQuery]):
    __update_type__ = InlineQuery
    __key_type__ = InlineQueryKey


client.register_listener(InlineQueryListener())
query = await client.listen(InlineQueryKey(user_id=7), timeout=30)
```

---

## Coordination: `CoordinatedDispatcher`

Two rapid messages from one user normally run two handlers at once, and the second can miss the question the first is about to ask. `CoordinatedDispatcher` runs the updates that share a key, such as a chat, **one at a time**, in the order read, while other keys run freely. As far as we know, no other Pyrogram library offers this.

```python
from pyroflow import Client, CoordinatedDispatcher, MessageListener
from pyroflow.enums import WorkersPolicy


def chat_key(update):
    chat = getattr(update, "chat", None)
    return None if chat is None else chat.id  # None: the update runs free


client = Client("my_session")
client.dispatcher = CoordinatedDispatcher(client, key_functions=[chat_key])  # first
client.setup_pyroflow(workers_policy=WorkersPolicy.CANCEL_OLDEST)
client.register_listener(MessageListener())


@client.on_message()
async def on_order(client, message):
    if message.text != "/order":
        return

    answer = await message.ask("What do you want?", listen_timeout=60)
    # A second message from this chat waits in the key's queue until the handler ends,
    # unless the wait above takes it as the answer.
    await answer.reply(f"Ordered {answer.text}.")
```

A key function returns a key, or `None` to pass the update to the next one. The handler holds its key until it ends, including while it waits in `ask`. A queued update takes no worker, so a user who sends 12 messages does not slow other users, and an update whose turn comes is offered to the open waits before its handlers run.

> ⚠️ **Install it first**, right after `Client(...)` and before any handler or `register_listener`: what was registered earlier stays on the old dispatcher and never runs, with no error.
>
> ⚠️ **A wait with no timeout freezes its key.** The key stays held during the wait, so a `/cancel` handler of that chat is just another queued update. Pass `listen_timeout`.

The full behavior is in the `CoordinatedDispatcher` docstring. Coordination and listeners live in the client's own process: nothing is shared between sessions.

---

## Also included

**`ask_until`:** ask again until `parse` returns a value, with `AskAgain` to repeat the question.

```python
from pyroflow.models import AskAgain

async def parse_age(answer, kw):
    return int(answer.text) if answer.text.isdigit() else AskAgain("Digits only. Your age:")

age = await message.ask_until("Your age:", parse=parse_age, attempts=3, listen_user_id=message.from_user.id)
```

**Keyboards:** `arrange` splits buttons into rows, and `CallbackData` packs, unpacks and filters `callback_data`.

```python
from pyroflow.keyboards import CallbackData, CallbackFields, arrange, parsed

class Product(CallbackFields):
    id: int = parsed(int)
    action: str

product = CallbackData("product", Product)
product.button("Buy", id=7, action="buy")   # InlineKeyboardButton with "product:7:buy"
product.unpack("product:7:buy")             # Product(id=7, action="buy")

@client.on_callback_query(product.filter(action="buy"))
async def buy(client, query): ...

rows = arrange(buttons, columns=2)
```

**Pagination:** `NumberedPagination`, `ArrowPagination` and `SlidingPagination` build one page of items with a bar, from a sequence or an `(offset, limit)` fetch function.

```python
from pyroflow.keyboards import NumberedPagination

pages = NumberedPagination(
    products,
    item=lambda item: product.button(item.name, id=item.id, action="buy"),
    page_data=lambda number: f"products:{number}",
)
page = await pages.build(2)
await message.reply("Products:", reply_markup=page.markup)
```

**Text filters:** `pyroflow.filters` adds `startswith`, `endswith`, `equal`, `split_text` and `registered_command`, which passes only the commands set for this bot.

```python
from pyroflow import MessageListener, filters

# A registered command ends an open question and reaches its handler.
client.register_listener(MessageListener(strict_filter=~filters.registered_command()))
```

**Bot commands:** `BotCommandsMixin` publishes the commands marked with `mark_bot_commands` on start.

```python
from pyrogram import filters
from pyrogram.types import BotCommand
from pyroflow import BotCommandsMixin, Client
from pyroflow.utils import mark_bot_commands

class Bot(BotCommandsMixin, Client): ...

client = Bot("my_session")

@mark_bot_commands(BotCommand("start", "Start the bot"))
@client.on_message(filters.command("start"))
async def on_start(client, message): ...
```

**Errors:** every error derives from `PyroflowError`, and those of waiting from `ListenerError`: `ListenerTimeout`, `ListenerCancelled` (with `ListenerReplaced`, `ListenerRejected`, `ListenerEvicted`), `ListenerAlreadyExists`, `ListenerWorkersBusy` and `ListenerAttemptsExhausted`, all in `pyroflow.errors`.

---

## Development

The only prerequisites are [uv](https://docs.astral.sh/uv/) and `make`.

```bash
make sync        # install the locked environment
make test        # run the test suite
make lint        # ruff check + ruff format --check
make typecheck   # ty
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the rules. Releases are tagged `v*` and published to PyPI by CI; the notes of each one are on the [releases page](https://github.com/eeeob/pyroflow/releases).

## License

MIT
