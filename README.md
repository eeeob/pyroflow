# pyroflow

[![PyPI version](https://img.shields.io/pypi/v/pyroflow)](https://pypi.org/project/pyroflow/)
[![Python versions](https://img.shields.io/pypi/pyversions/pyroflow)](https://pypi.org/project/pyroflow/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**Conversations for [Kurigram](https://github.com/KurimuzonAkuma/pyrogram) (Pyrogram): `await` the reply, and run one key's updates, such as one chat's, one at a time.**

> Arabic translation: [README.ar.md](README.ar.md). If the two differ, this English text is the reference.

```bash
pip install pyroflow
```

`import pyroflow` patches Pyrogram in place, so your existing code keeps working. Import it before creating any `Client`.

The supported Python versions are on the badge above, and the Kurigram requirement is in [pyproject.toml](pyproject.toml). The details of every feature below are in its docstring.

---

## Listening

A handler asks a question and `await`s the answer, with no state machine. An update taken by a wait never reaches the handlers.

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

- **More ways to ask.** `ask_callback_query` waits for a button press, and both have rich versions. All of them are on `Client` too. `listen_message` and `listen_callback_query` wait without sending anything.
- **Say who and for how long.** Pass `listen_user_id` in groups, or any member can answer. Always pass `listen_timeout`.
- **Cancel a wait.** `cancel_listen` ends the wait on one key, and `cancel_listens` every wait with the fields you give, as a `/cancel` command would.
- **A wait holds a worker.** `workers_policy` decides what happens when the workers run short. See the `WorkersPolicy` docstring.
- **Your own update types.** A `ListenerKey` class and an `UpdateListener` class are enough to wait for any update. See the `UpdateListener` docstring.

---

## Coordination

Two rapid messages from one user normally run two handlers at once, and the second can miss the question the first is about to ask. `CoordinatedDispatcher` runs the updates that share a key, such as a chat, **one at a time**, while other keys run freely.

```python
from pyroflow import Client, CoordinatedDispatcher, MessageListener


def chat_key(update):
    chat = getattr(update, "chat", None)
    return None if chat is None else chat.id  # None: the update runs free


client = Client("my_session")
client.dispatcher = CoordinatedDispatcher(client, key_functions=[chat_key])  # first
client.register_listener(MessageListener())


@client.on_message()
async def on_order(client, message):
    if message.text != "/order":
        return

    answer = await message.ask(
        "What do you want?", listen_user_id=message.from_user.id, listen_timeout=60
    )
    # A second message from this chat waits its turn, unless the wait takes it as the answer.
    await answer.reply(f"Ordered {answer.text}.")
```

> ⚠️ **Install it first**, right after `Client(...)`: what was registered earlier never runs, with no error.
>
> ⚠️ **Pass `listen_timeout`.** A wait that never gets a reply, with no timeout, freezes its key.

The full behavior is in the `CoordinatedDispatcher` docstring. Listeners and coordination live in the client's own process: each client's dispatcher keeps its own lanes, and nothing is shared between clients or sessions.

---

## Also included

**Asking until valid.** `ask_until` asks again until `parse` returns a value.

```python
from pyroflow.models import AskAgain

async def parse_age(answer, kw):
    return int(answer.text) if answer.text and answer.text.isdigit() else AskAgain("Digits only. Your age:")

age = await message.ask_until(
    "Your age:",
    parse=parse_age,
    attempts=3,
    listen_user_id=message.from_user.id,
    listen_timeout=60,
)
```

**Keyboards.** `CallbackData` packs, unpacks and filters `callback_data`, and `arrange` splits buttons into rows.

```python
from pyroflow.keyboards import CallbackData, CallbackFields, arrange, parsed

class Product(CallbackFields):
    id: int = parsed(int)
    action: str

product = CallbackData("product", Product)
buttons = [product.button("Buy", id=7, action="buy")]  # callback_data: "product:7:buy"
rows = arrange(buttons, columns=2)

@client.on_callback_query(product.filter(action="buy"))
async def buy(client, query): ...
```

**Pagination.** A pagination builds one page of items with a navigation bar, from a sequence or a fetch function.

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

**Text filters.** `pyroflow.filters` adds text filters in the style of `pyrogram.filters`.

```python
from pyroflow import MessageListener, filters

# A registered command ends an open question and reaches its handler.
client.register_listener(MessageListener(strict_filter=~filters.registered_command()))
```

**Repeated presses.** `filters.too_fast` matches an update that arrived within an interval of the last one let through with its key, such as a button pressed again quickly, so `on_spam` answers it and `~` keeps the handler from running again. Make one filter per update type and use it on all of that type's handlers, not one per handler.

```python
from pyroflow import filters

# A press within 2 seconds of the same user's last press let through on that message
# is answered and skipped.
spam = filters.too_fast(2, on_spam=lambda query: query.answer("Slow down"))

@client.on_callback_query(~spam)
async def on_press(client, query): ...
```

**Bot commands.** `BotCommandsMixin` publishes the commands marked with `mark_bot_commands` when the client starts.

```python
# bot.py
from pyroflow import BotCommandsMixin, Client

class Bot(BotCommandsMixin, Client): ...

Bot("my_session", plugins=dict(root="plugins")).run()

# plugins/start.py
from pyrogram import filters
from pyrogram.types import BotCommand
from pyroflow import Client
from pyroflow.utils import mark_bot_commands

@mark_bot_commands(BotCommand("start", "Start the bot"))
@Client.on_message(filters.command("start"))  # the unbound form, not @client.on_message
async def on_start(client, message): ...
```

**Errors.** Every error is in `pyroflow.errors` and derives from `PyroflowError`.

---

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md). Release notes are on the [releases page](https://github.com/eeeob/pyroflow/releases).

## License

MIT
