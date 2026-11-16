# pyroflow

[![PyPI version](https://img.shields.io/pypi/v/pyroflow)](https://pypi.org/project/pyroflow/)
[![Python versions](https://img.shields.io/pypi/pyversions/pyroflow)](https://pypi.org/project/pyroflow/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**محادثات لـ [Kurigram](https://github.com/kurigram-org/kurigram) (Pyrogram): انتظر الرد بـ `await`، وشغّل تحديثات المفتاح الواحد، كالمحادثة الواحدة، واحداً تلو الآخر.**

> هذه ترجمة لـ [README.md](README.md). عند أي اختلاف، النص الإنجليزي هو المرجع.

```bash
pip install pyroflow
```

`import pyroflow` يعدّل Pyrogram في مكانه، فكودك الحالي يبقى كما هو. استورده قبل إنشاء أي `Client`.

إصدارات Python المدعومة في الشارة أعلاه، ومتطلب Kurigram في [pyproject.toml](pyproject.toml). وتفاصيل كل ميزة أدناه في الـ docstring الخاص بها.

---

## الاستماع

الـ handler يسأل سؤالاً وينتظر الجواب بـ `await`، بلا آلة حالات. والـ update الذي يأخذه الانتظار لا يصل إلى الـ handlers أبداً.

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

- **طرق أخرى للسؤال.** `ask_callback_query` ينتظر ضغطة زر، ولكليهما نسخة rich. وكلها موجودة على `Client` أيضاً. أما `listen_message` و`listen_callback_query` فينتظران دون إرسال شيء.
- **حدّد مَن يجيب وكم تنتظر.** مرّر `listen_user_id` في المجموعات، وإلا أجاب أي عضو. ومرّر `listen_timeout` دائماً.
- **ألغِ انتظاراً.** `cancel_listen` ينهي الانتظار على مفتاح واحد، و`cancel_listens` كل انتظار يحمل الحقول التي تعطيها، كما يفعل أمر `/cancel`.
- **الانتظار يحجز worker.** `workers_policy` يقرر ما يحدث حين تقلّ الـ workers. راجع docstring الـ `WorkersPolicy`.
- **أنواع update من عندك.** كلاس `ListenerKey` وكلاس `UpdateListener` يكفيان لانتظار أي update. راجع docstring الـ `UpdateListener`.

---

## التنسيق

رسالتان سريعتان من مستخدم واحد تشغّلان عادةً handler-ين معاً، والثانية قد تفوّت السؤال الذي توشك الأولى أن تطرحه. `CoordinatedDispatcher` يشغّل التحديثات التي تشترك في مفتاح، كالمحادثة مثلاً، **واحداً تلو الآخر**، بينما المفاتيح الأخرى تعمل بحرية.

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

> ⚠️ **ثبّته أولاً**، مباشرة بعد `Client(...)`: ما سُجّل قبله لا يعمل أبداً، وبلا أي خطأ.
>
> ⚠️ **مرّر `listen_timeout`.** الانتظار الذي لا يأتيه رد، بلا مهلة، يجمّد مفتاحه.

السلوك الكامل في docstring الـ `CoordinatedDispatcher`. الـ listeners والتنسيق يعيشان في عملية الـ client نفسها: الـ dispatcher في كل client يحفظ الـ lanes الخاصة به، ولا شيء مشترك بين الـ clients أو الـ sessions.

---

## ما تتضمنه المكتبة أيضاً

**السؤال حتى يصح الجواب.** `ask_until` يعيد السؤال حتى ترجع `parse` قيمة.

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

**لوحات الأزرار.** `CallbackData` يحزم `callback_data` ويفكه ويفلتره، و`arrange` يقسم الأزرار إلى صفوف.

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

**الـ Pagination.** الـ pagination يبني صفحة واحدة من العناصر مع شريط تنقل، من sequence أو من دالة جلب.

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

**فلاتر نصية.** `pyroflow.filters` يضيف فلاتر نصية بأسلوب `pyrogram.filters`.

```python
from pyroflow import MessageListener, filters

# A registered command ends an open question and reaches its handler.
client.register_listener(MessageListener(strict_filter=~filters.registered_command()))
```

**الضغط المتكرر.** `filters.too_fast` يطابق الـ update الذي وصل خلال مدة من آخر update مُرِّر بمفتاحه، كزر مضغوط مرة أخرى بسرعة، فيجيب عنه `on_spam`، و`~` يمنع الـ handler من العمل مرة أخرى. أنشئ فلتراً واحداً لكل نوع update واستعمله على كل handlers ذلك النوع، لا فلتراً لكل handler.

```python
from pyroflow import filters

# A press within 2 seconds of the same user's last press let through on that message
# is answered and skipped.
spam = filters.too_fast(2, on_spam=lambda query: query.answer("Slow down"))

@client.on_callback_query(~spam)
async def on_press(client, query): ...
```

**أوامر البوت.** `BotCommandsMixin` ينشر الأوامر المعلّمة بـ `mark_bot_commands` عند بدء الـ client.

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

**الأخطاء.** كل الأخطاء في `pyroflow.errors` وترث من `PyroflowError`.

---

## التطوير

راجع [CONTRIBUTING.ar.md](CONTRIBUTING.ar.md). وملاحظات الإصدارات في [صفحة الإصدارات](https://github.com/eeeob/pyroflow/releases).

## الترخيص

MIT
