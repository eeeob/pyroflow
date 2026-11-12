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

    answer = await message.ask(
        "What is your name?", listen_user_id=message.from_user.id, listen_timeout=60
    )
    await answer.reply(f"Hello, {answer.text}!")

client.run()
```

`message.ask` replies to the message, then waits for the next message from `listen_user_id`, here its sender, in the same chat and topic.

---

## Core concepts

### Listeners

A `UpdateListener` is a typed queue bound to a Pyrogram update type. Any coroutine can `await` the next matching update from a specific user or chat. An update claimed by a listener **never reaches the normal handler pipeline**.

```python
from pyroflow import Client, MessageListener
from pyroflow.errors import ListenerTimeout
from pyroflow.models import MessageKey

client = Client("my_session")
messages = MessageListener()
client.register_listener(messages)  # bound to this client; another client refuses it

@client.on_message()
async def on_confirm(client, message):
    if message.text != "/confirm":
        return

    await message.reply("Send your confirmation code:")

    try:
        code_msg = await messages.listen(
            MessageKey(message.chat.id, message.from_user.id),
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
code_msg = await client.listen(MessageKey(chat_id, user_id), timeout=120)
code_msg = await client.listen_message(chat_id=chat_id, user_id=user_id, timeout=120)
press = await client.listen_callback_query(chat_id=chat_id, message_id=message_id)
client.get_listener(Message)   # the registered listener, or None
```

`listen` takes a key and the wait arguments, and finds the listener from the key's `__update_type__`. `listen_message` and `listen_callback_query` take the fields of the key and the wait arguments, make the key with the listener's `__key_type__`, and raise `RuntimeError` when no listener is registered for their type. `get_listener` returns `None` instead of raising; use the listener it returns to look up or end waits, such as `client.get_listener(Message).cancel(key)`.

Each listener waits on keys of its own class, from `pyroflow.models`, and its `listen` takes one:

- `MessageListener`: `MessageKey(chat_id, user_id, message_thread_id, direct_messages_topic_id, ephemeral)`.
- `CallbackQueryListener`: `CallbackQueryKey(chat_id, user_id, message_id, inline_message_id, ephemeral)`.

A field left `None` matches any value, so `messages.listen(MessageKey())` takes the next message anywhere, and `messages.listen(MessageKey(user_id=7))` takes user 7 in any chat. A key holds the values as given, so to wait in a user's private chat pass `chat_id`: a private chat has the user's id. `inline_message_id` waits for a press on a message sent in inline mode; such a press has no chat, so it reaches a wait on its user, never a wait on a chat.

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

### One update at a time per lock: CoordinatedDispatcher

Two rapid messages from one user normally run two handlers at once, and the second can miss the question the first is about to ask. `CoordinatedDispatcher`, an opt-in `Dispatcher` subclass, runs the updates that share a lock one at a time. Install it right after creating the client:

```python
from pyroflow import Client, CoordinatedDispatcher

client = Client("bot")


def chat_key(update):
    chat = getattr(update, "chat", None)
    return None if chat is None else chat.id  # None: the update runs free


key_functions = [chat_key]                    # one lock per chat
key_functions = [lambda update: update.text]  # your own key

# Your own decision is a constant key: everything it picks shares one lock.
key_functions = [lambda update: "payments" if is_payment(update) else None]
# Chats 1 and 2 share one lock, and every other chat has its own.
key_functions = [lambda update: "vip" if chat_key(update) in (1, 2) else None, chat_key]

client.dispatcher = CoordinatedDispatcher(client, key_functions=key_functions)
```

It stands alone and starts empty: nothing is carried over from the dispatcher it replaces. **Install it before any handler, listener or `setup_pyroflow` call**, as what was registered earlier stays on the old dispatcher and never runs, and do not install it from `on_start` or once the client has started: the client would keep reading the old dispatcher, and no error is raised. Pyroflow's own `Dispatcher` is never changed: without it, nothing is coordinated.

- **Key functions.** They only extract a key, and the dispatcher coordinates the keys. The first function to give a key decides, `None` passes the update to the next, and keys of different functions never mix. For a decision of your own, return a constant key for what it picks. An update no function gives a key runs free, so channel posts have no user, and an inline query has no chat. Key functions are sync and get the parsed update; an error or an unhashable key is logged and the update goes to the next function.
- **Order.** The task that reads Pyrogram's queue parses each update in turn and places it behind the earlier updates of its key, so the keys are computed after parsing and no update overtakes an earlier one. No task is created per update, and a reply still arrives while every worker waits. A slow parser holds back the updates behind it.
- **The hold.** An update whose turn comes is offered to the waits first. If none takes it, its handlers run, filters included, so filters see what the previous update of the key left behind. The handler holds the key until it ends, including while it waits in `ask`.
- **The queue.** An update of a held key joins the key's queue and takes no worker, so a user who sends 12 messages does not stop other users.
- **Fairness.** After each update its key goes behind the other keys that are ready, so a flood does not keep other users waiting.
- **Replies.** While the handler runs, one task shared by all the keys offers the queue to the waits in order: each update as it arrives, and the whole queue again each time the handler starts a wait. What a wait takes leaves the queue. What a wait of the handler declines keeps its place, and goes to no later wait of that handler, though other waits still get it: as with the plain dispatcher, it is not a reply and runs its handlers in its turn, and a handler that asks again with `listen_strict=True` is not refused the same update forever. A wait's filter runs once per update, however often the update is offered. A wait that starts while an update is on offer gets the older ones first. No free worker is needed for this.
- **Other waits.** A task the handler spawns counts as the handler while the handler runs, so its waits are the handler's. Once the handler ends, the key moves on without the task, so `await` the task in the handler to keep the key held. Any other wait, such as one in a free handler, in a handler of another key, or in a task whose handler ended, gets queued updates the same way, but an update offered before the wait started may reach it only in its turn. When several waits match an update, the listener decides as usual, by shape order and `resolve_scope`: the handler holding the key has no priority.
- **After the handler.** The next update of the key is posted: it is offered to the waits once more, then runs its handlers. The key is freed when the queue empties, and leaves no state.
- **Stopping.** `stop` ends the open waits, then every update already read still runs before the workers exit, with its own waits refused with `ListenerCancelled`.

Know these before you turn it on:

- **A wait with no timeout freezes its key for good.** The key stays held during the wait, so nothing else of that key runs, and a plain `/cancel` handler is just another queued update: it never runs. Pass `listen_timeout`. A listener's `strict_filter` that a command fails also ends the wait, and the command reaches the handlers once the handler ends, but it only covers a wait with no `listen_filters`: a wait with its own filter needs `listen_strict=True` or a timeout.
- A queued message can end a later strict wait when it is offered to it, as `strict` ends a wait on any rejected update of its key.
- Order holds from the moment an update leaves Pyrogram's queue, not from when Telegram sent it. Updates of different locks have no order between them.
- A parse that never ends delays every update behind it, and a wait filter that never returns delays the offers of every key until `stop`. Reading updates and running handlers go on.
- A wait outside the key's handler (another handler's) sees a queued update of the key when the update is next offered, or when its turn comes. A wait opened from a sync `ErrorHandler`, a plain `threading.Thread` or `run_in_executor` is outside the hold: they do not carry the handler's context.
- The queues have no limit, and nothing is dropped. A key that gets more than its handler can process only grows.
- The coordination lives in this process, like the listeners: it does not coordinate between sessions.


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

Every `ask_*` takes `listen_user_id`, the user to wait for. Without it, anyone in the chat answers; in a private chat the user is the only one who can. pyroflow never guesses the user. `Message.ask_*` replies to the message, or edits it when it is the client's own (`editable`).

**Parameters:**

| Parameter | Description |
|---|---|
| `chat_id` | `Client` only: target chat |
| `text` | Message text (`rich_message` in the `_rich` methods) |
| `edit_message_id` | `Client` only: if provided, edits this message instead of sending a new one |
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

[`ask_until()`](#ask_until) runs such a loop for you, with a `parse` function.

`listen_strict` decides for the whole filter: with `filters.text & ~filters.command("cancel")` and `listen_strict=True`, a photo ends the question just like the command does.

To filter every wait that passes no `listen_filters`, give the listener a `strict_filter`, such as `MessageListener(strict_filter=~filters.command("cancel"))`. An update that fails it ends the wait with `ListenerRejected`.

A slow filter holds up the updates behind it. `filters_timeout` bounds it: `MessageListener(filters_timeout=2)` declines an update whose filter runs over 2 seconds, as if it failed, and logs it. A sync filter's thread still runs to the end. The first fetch of `registered_command()` goes on in the background, so only the update that ran over is declined.

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

To end a question from a button's handler, such as a "back" button on it, cancel its wait by its key, which raises `ListenerCancelled` in `ask`: `client.get_listener(Message).cancel(MessageKey.from_sent(query.message, query.from_user.id))`, with the `listen_user_id` the `ask` was given, or `None` without one.

> ⚠️ **A wait that never ends.** Without `listen_strict`, a wait stays open until `listen_timeout`, or forever without one, when every update its key can still match fails the filter:
> - The filter can never pass that update type, such as `filters.photo` while waiting for a `CallbackQuery`.
> - The user keeps sending updates the filter rejects.
>
> Give such waits a timeout (`listen_timeout` on `ask_*`, `timeout` on `listen` or on the listener), use `listen_strict=True` (`strict=True` on `listen`) when the first rejected update should end the wait, or end the wait yourself with `listener.cancel(key)`. Note that `listen_strict=True` ends the wait on **any** rejected update of the key, such as a photo while text is awaited.


`ask_rich()` and `ask_callback_query_rich()` do the same with a rich message: they send with `send_rich_message`, or edit with `edit_message_text(rich_message=...)` when `edit_message_id` is given. The `Message` methods call the message's own `edit`, `reply` and `reply_rich`, so they accept what those accept; use the `Client` methods for arguments such as `reply_parameters`.

```python
from pyrogram.types import InputRichMessage

answer = await client.ask_rich(
    chat_id,
    InputRichMessage(html="Pick a <b>name</b>:"),
    listen_timeout=30,
)
```

Ephemeral messages have ids that do not follow each other and can be reused, so no key holds one. The `ephemeral` field of a key waits on ephemeral updates, as in `listen(MessageKey(ephemeral=True))`. Only such a wait receives them, and a regular update never reaches it. An `ask_*` on or with an ephemeral message waits this way, for its `listen_user_id` when given. Two ephemeral messages to one user share a key, so tell them apart with `listen_filters`.

---

Listeners can also be removed at runtime:

```python
await client.unregister_listener(Message)
```

---

### ask_until()

`ask_until()` repeats `ask()` until a function you pass returns a value, and returns that value. `ask_rich_until()`, `ask_callback_query_until()` and `ask_callback_query_rich_until()` do the same for `ask_rich()`, `ask_callback_query()` and `ask_callback_query_rich()`. All four are on `Client` and on `Message`, eight methods in all, and each takes what the method it repeats takes, plus `parse`, which is required, and `attempts`.

```python
from pyrogram import filters
from pyrogram.enums import ParseMode
from pyroflow.errors import ListenerAttemptsExhausted
from pyroflow.models import AskAgain

async def parse_username(answer, kw):
    if not answer.text.isascii():
        return AskAgain("Latin letters only. Try again:")

    if await is_taken(answer.text):
        return AskAgain("<b>That name is taken.</b> Try another:", {"parse_mode": ParseMode.HTML})

    return answer.text

try:
    username = await message.ask_until(
        "Pick a username:",
        parse=parse_username,
        attempts=3,
        listen_filters=filters.text & ~filters.command("cancel"),
        listen_user_id=message.from_user.id,
    )
except ListenerAttemptsExhausted as exc:
    await message.reply(f"Giving up after {exc.update.text!r}.")
```

`parse` is called as `parse(answer, kw)`, sync or async. `answer` is the update that arrived, and `kw` is the dict of the question's keyword arguments. What `parse` returns decides what happens next:

| `parse` returns | What happens |
|---|---|
| `AskAgain(question)` | Rejected: this question is asked with no arguments |
| `AskAgain(question, kw)` | Rejected: this question is asked with this `kw` |
| Anything else, `None` included | Accepted: this value is returned to you |

A question is a `str`, or an `InputRichMessage` in the `*_rich_until` methods. To repeat a question, return it in `AskAgain`, and to keep its arguments, pass on the `kw` that `parse` got. To get the answer itself, `return answer`.

An answer that reaches `parse` was taken by the wait, so it reaches no handler even when rejected, and a command sent instead of an answer counts as one. `listen_filters` is the filter in front of `parse`: what fails it goes on to the handlers and the wait goes on, so `~filters.command("cancel")` above lets `/cancel` run. With `listen_strict=True`, an update that fails it raises `ListenerRejected` at once and ends the loop.

Only the first question may edit a message, through `edit_message_id` on `Client` or an `editable` message on `Message`, and `force_send` applies to it alone. After a rejection each question is a new message, since Telegram refuses an edit that changes nothing. A retry sends only the `kw` in `AskAgain`, so put what it needs there, such as `message_thread_id` on `Client` (`Message` replies in its own topic), and it must hold what the send takes: `link_preview_options` in the rich methods raises `TypeError`. In the callback query methods, put `reply_markup` in it: the question goes out again with its keyboard, and each one waits for a press on its own buttons.

With `attempts=None`, the default, it never gives up. Otherwise `ListenerAttemptsExhausted` is raised when `parse` rejects the answer to the last question, and its `update` holds that answer. Its `value` is the number of questions asked. `attempts` below 1 raises `ValueError` before anything is sent. `listen_timeout` applies to each wait on its own, and anything else `ask` or `parse` raises, such as `ListenerTimeout`, ends the loop at once.

---

## Keyboards

`pyroflow.keyboards` builds inline keyboards. `arrange` splits a flat list of buttons into rows by `columns` or `layout`, one button per row without either:

```python
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from pyroflow.keyboards import arrange

buttons = [InlineKeyboardButton(text, callback_data=text) for text in "abcde"]

keyboard = InlineKeyboardMarkup(arrange(buttons, columns=2))
keyboard = InlineKeyboardMarkup(arrange(buttons, layout=[1, 2]))
keyboard = InlineKeyboardMarkup(arrange(buttons, layout=[1, 2], repeat=True))
```

`columns` is a fixed width. After the last size of `layout` its size goes on, and with `repeat=True` the layout starts over. `columns` with `layout`, or a width that is not positive, raises `ValueError`.

`CallbackData` is a layout for `callback_data`: a prefix and the fields of a `CallbackFields` class. The type of a field is only a hint on `pack`, on `button` and on what `unpack` returns. To read a field as anything but text, write it with `parsed` and the function that converts it; a field without one stays text. `pack` builds the data, `button` builds an `InlineKeyboardButton` with it, and `unpack` returns the class with its fields read. `unpack_dict` returns the same values as a `dict`. The options of `dataclass` go on the class line, as in `class Product(CallbackFields, slots=True)`. For a layout without a class, `CallbackData.from_fields("product", namedtuple("Product", "id action"), slots=True)` builds one from a `namedtuple` and the options of `dataclass`: the names show as hints, and every field is text. An `Enum` member goes in by its value, and `sep` is one character.

`filter` matches the callback queries of the layout on the fields you name and allows anything else in the data. `filter_equal` takes every field, as `pack` does, and passes only data equal to what `pack` builds. `filter_rules` takes for each field what `filters.split_text` takes: a text, a container of options, an `Enum` class, a compiled pattern or a function:

```python
from pyroflow.keyboards import CallbackData, CallbackFields, parsed

class Product(CallbackFields):
    id: int = parsed(int)
    action: str

product = CallbackData("product", Product)

product.pack(id=7, action="buy")           # "product:7:buy"
product.button("Buy", id=7, action="buy")  # an InlineKeyboardButton
product.unpack("product:7:buy")            # Product(id=7, action="buy")

@app.on_callback_query(product.filter(action="buy"))
async def buy(client, query):
    ...

@app.on_callback_query(product.filter_rules(id=str.isdigit, action=["buy", "sell"]))
async def act(client, query):
    ...
```

Telegram documents no limit on buttons per row or per keyboard, so none is checked: keep keyboards small. `callback_data` is limited to 64 bytes. `CallbackData.pack` raises `ValueError` beyond that, and elsewhere, as in `page_data`, nothing checks it, so keep ids short.

### Pagination

`Pagination` is the base for a keyboard of one page of items with a bar to move between pages. `NumberedPagination`, `ArrowPagination` and `SlidingPagination` are its bars. `build` is async: it returns a `Page` with `number`, `items`, `total_pages`, `has_next` and the keyboard in `markup`. With a handler:

```python
from pyrogram import filters
from pyroflow.keyboards import CallbackData, CallbackFields, NumberedPagination, parsed

class ProductId(CallbackFields):
    id: int = parsed(int)

class Turn(CallbackFields):
    page: int = parsed(int)

product = CallbackData("product", ProductId)
turn = CallbackData("products", Turn)

pages = NumberedPagination(
    products,
    item=lambda item: product.button(item.name, id=item.id),
    page_data=lambda number: turn.pack(page=number),
)

@app.on_message(filters.command("products"))
async def show(client, message):
    page = await pages.build()
    await message.reply("Products:", reply_markup=page.markup)

@app.on_callback_query(turn.filter())
async def turn_page(client, query):
    page = await pages.build(turn.unpack(query.data).page)
    await query.message.edit_reply_markup(page.markup)
```

With `ask_callback_query`, keep turning pages until the press is on an item. `press.message` is the client's own message, so each question edits it and waits for the next press on its buttons:

```python
page = await pages.build()
press = await message.ask_callback_query("Pick a product:", reply_markup=page.markup)

while press.data.startswith("products:"):
    page = await pages.build(turn.unpack(press.data).page)
    press = await press.message.ask_callback_query("Pick a product:", reply_markup=page.markup)
```

`item` returns an `InlineKeyboardButton`. `arrangement`, a `PageArrangement` from `pyroflow.models`, says how many items a page holds and arranges them like `arrange`. These are all its valid sets, and any other mix raises `ValueError`. Without it, a page is five rows of one button each:

| Options | `per_page` | Rows |
|---|---|---|
| `lines`, `columns` | `lines * columns` | `lines` rows of `columns` |
| `per_page`, `columns` | `per_page` | rows of `columns`, the last may be shorter |
| `layout` | the sum of `layout` | one row per size |
| `layout`, `per_page` | `per_page`, at least the sum of `layout` | the last size goes on |
| `layout`, `repeat`, `lines` | the sum of the first `lines` sizes | `lines` rows, the sizes cycling |
| `layout`, `repeat`, `per_page` | `per_page` | the sizes cycling |

```python
from pyroflow.models import PageArrangement

NumberedPagination(products, item=item, arrangement=PageArrangement(lines=4, columns=3))                   # 12 items in rows of 3
NumberedPagination(products, item=item, arrangement=PageArrangement(layout=[1, 2, 3]))                     # 6 items
NumberedPagination(products, item=item, arrangement=PageArrangement(lines=4, layout=[1, 2], repeat=True))  # 6 items: 1, 2, 1, 2
```

The current page's button is `disabled`, and no page shows twice. A single page has no bar. The bars, here on page 6 of 12:

| Class | Bar | Its texts |
|---|---|---|
| `NumberedPagination` | `« 1` `‹ 5` `· 6 ·` `7 ›` `12 »` | `first`, `previous`, `current`, `next`, `last` |
| `ArrowPagination` | `‹` `›` | `back`, `forward` |
| `ArrowPagination(texts=ArrowBarTexts(counter="{page}/{pages}"))` | `‹` `6/12` `›` | `back`, `counter`, `forward` |
| `SlidingPagination` | `1` `2` `3` `4` `5` `· 6 ·` `7` `8` | `page`, `current` |

`SlidingPagination` shows every page by number, at most `size` at a time, 8 by default. The numbers come in fixed groups, and reaching the last one of a group brings the next group, keeping the page before it. Its size and texts go in `bar`, a `SlidingBar` from `pyroflow.models`.

The texts of the other two go in `texts`: a `NumberedBarTexts` or an `ArrowBarTexts` from `pyroflow.models`. `{page}` and `{pages}` are filled in any of them. Without a known count `{pages}` shows `None`, so use it only with a count. `style`, a `BarStyle(nav, current)`, holds functions that get each button of the bar once it is built, to change it, `style` on the button that `item` returns colors an item, `header` holds fixed rows above the items, and `footer` holds fixed rows under the bar. `ButtonStyle.LINK` is for rich messages only, and Pyrogram refuses it on an inline button.

```python
from pyrogram.enums import ButtonStyle
from pyrogram.types import InlineKeyboardButton
from pyroflow.keyboards import ArrowPagination
from pyroflow.models import ArrowBarTexts, BarStyle

def primary(button):
    button.style = ButtonStyle.PRIMARY

def success(button):
    button.style = ButtonStyle.SUCCESS

pages = ArrowPagination(
    products,
    item=lambda item: InlineKeyboardButton(
        item.name,
        callback_data=f"product:{item.id}",
        style=ButtonStyle.DANGER if item.sold_out else ButtonStyle.SUCCESS,
    ),
    page_data=lambda number: f"products:{number}",
    texts=ArrowBarTexts(back="Back", forward="Next", counter="{page}/{pages}"),
    style=BarStyle(nav=primary, current=success),
    footer=[[InlineKeyboardButton("Close", callback_data="close")]],
)
```

**Fetching lazily.** `items` can be a function called as `(offset, limit)`, sync or async, that returns one batch, so each `build` fetches only what its page needs. `count` is an `ItemCount` from `pyroflow.models`, which holds a number, or a sync or async function of no arguments read on every `build`. With `strict`, on by default, no item past it is fetched or shown. With `strict=False` it only sets how many pages there are, and each page is fetched whole. It applies to a sequence too. Without `count`, a sequence uses its length and the count of a function is unknown.

```python
from pyroflow.models import ItemCount

async def fetch(offset, limit):
    return await db.products(offset=offset, limit=limit)

pages = NumberedPagination(fetch, item=item, count=ItemCount(db.count_products))
pages = ArrowPagination(fetch, item=item)
```

With a count, a page out of range becomes the nearest one. Without one, each `build` fetches one item more than a page to tell whether another page follows, and `total_pages` is `None`. A page that comes back empty, such as one past the end, shows the first page instead, and with `first_if_empty=False` it stays empty, with the way back on its bar. `NumberedPagination` and `SlidingPagination` need the number of pages, so a function without `count` raises `TypeError`. `ArrowPagination` works either way, and its counter then uses `unknown_counter`, `{page}` by default.

**Your own bar.** Subclass `Pagination` and write `nav_row`, which gets the page, the number of pages or `None`, and whether a page follows. `nav_button` builds a button to a page:

```python
from pyroflow.keyboards import Pagination

class MorePagination(Pagination):
    def nav_row(self, number, total_pages, has_next):
        return [self.nav_button("More", number + 1, number, total_pages)] if has_next else []
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
