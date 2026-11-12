# pyroflow

[![PyPI version](https://img.shields.io/pypi/v/pyroflow)](https://pypi.org/project/pyroflow/)
[![Python versions](https://img.shields.io/pypi/pyversions/pyroflow)](https://pypi.org/project/pyroflow/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**محادثات لـ [Kurigram](https://github.com/KurimuzonAkuma/pyrogram) (Pyrogram): انتظر الرد بـ `await`، وشغّل تحديثات المستخدم الواحد واحداً تلو الآخر.**

> هذه ترجمة لـ [README.md](README.md). عند أي اختلاف، النص الإنجليزي هو المرجع.

```bash
pip install pyroflow
```

Python 3.10 فأعلى. `import pyroflow` يعدّل Pyrogram في مكانه: `pyroflow.Client` **هو** `pyrogram.Client`، فكودك الحالي يبقى كما هو.

تواكب pyroflow إصدارات Kurigram: الحد الأدنى `kurigram>=2.2.27` بلا حد أعلى، ومهمة CI أسبوعية تشغّل الاختبارات على أحدث إصدار من Kurigram، فأي تغيير هناك يُكتشف خلال الأسبوع.

---

## الاستماع: `ask` والـ listeners

الـ handler يسأل سؤالاً وينتظر الجواب بـ `await`، بدل آلة حالات وقاموس `user_id → step`. الـ update الذي يأخذه الانتظار لا يصل إلى الـ handlers أبداً.

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

`message.ask` يرد على الرسالة ثم ينتظر الرسالة التالية من `listen_user_id` في نفس المحادثة والـ topic. أما `ask_callback_query` فينتظر ضغطة على أزرار الرسالة التي أرسلها، وكلاهما موجود على `Client` أيضاً مع `edit_message_id` للتعديل بدل الإرسال. ويمكن الانتظار مباشرة: `client.listen_message(chat_id=..., user_id=..., timeout=120)`، أو `listener.listen(MessageKey(chat_id, user_id))`، حيث الحقل `None` يطابق أي قيمة.

> ⚠️ **العاملون لا يتجمدون.** الـ handler الذي ينتظر يمسك الـ worker الخاص به في Pyrogram. `workers_policy` يبقي worker واحداً خارج الانتظارات ليقرأ الردود، ويقرر ما يحدث حين يحاول انتظار أخذه، والافتراضي `WorkersPolicy.CANCEL_OLDEST`:
>
> | السياسة | ما يحدث |
> |---|---|
> | `WorkersPolicy.CANCEL_OLDEST` | أقدم انتظار ينتهي بـ `ListenerEvicted`، والجديد يأخذ مكانه |
> | `WorkersPolicy.REJECT` | الانتظار الجديد يرفع `ListenerWorkersBusy` |
>
> `setup_pyroflow(workers_policy=None)` يعطّلها: عندها حين تبقى `workers` أسئلة بلا جواب ولا `listen_timeout`، يتوقف البوت عن قراءة التحديثات.

كل `ask_*` يأخذ `listen_timeout`، و`listen_filters` (فلتر Pyrogram يجب أن يجتازه الجواب)، و`listen_strict` (الجواب الذي يفشل الفلتر ينهي الانتظار بـ `ListenerRejected`)، و`listen_user_id`. وأي شيء آخر يذهب إلى method الإرسال أو التعديل في Pyrogram.

**أنواع update من عندك.** الـ listener هو كلاس مفتاح وكلاس listener، و`client.listen` يعمل مع أي منها بلا كود إضافي. للانتظار على inline queries حسب المستخدم:

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

## التنسيق: `CoordinatedDispatcher`

رسالتان سريعتان من مستخدم واحد تشغّلان عادةً handler-ين معاً، والثانية قد تفوّت السؤال الذي توشك الأولى أن تطرحه. `CoordinatedDispatcher` يشغّل التحديثات التي تشترك في مفتاح، كالمحادثة مثلاً، **واحداً تلو الآخر** بترتيب قراءتها، بينما المفاتيح الأخرى تعمل بحرية. على حد علمنا، لا توفر مكتبة Pyrogram أخرى هذه الميزة.

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

دالة المفتاح ترجع مفتاحاً، أو `None` لتمرير الـ update إلى الدالة التالية. الـ handler يمسك مفتاحه حتى ينتهي، بما في ذلك أثناء انتظاره في `ask`. الـ update المنتظر في الطابور لا يأخذ worker، فالمستخدم الذي يرسل 12 رسالة لا يبطئ غيره، والـ update الذي يأتي دوره يُعرض على الانتظارات المفتوحة قبل أن تعمل الـ handlers.

> ⚠️ **ثبّته أولاً**، مباشرة بعد `Client(...)` وقبل أي handler أو `register_listener`: ما سُجّل قبله يبقى على الـ dispatcher القديم ولا يعمل أبداً، وبلا أي خطأ.
>
> ⚠️ **الانتظار بلا مهلة يجمّد مفتاحه.** المفتاح يبقى ممسوكاً أثناء الانتظار، فالـ handler الخاص بـ `/cancel` في تلك المحادثة مجرد update آخر في الطابور. مرّر `listen_timeout`.

السلوك الكامل في docstring الكلاس `CoordinatedDispatcher`. التنسيق والـ listeners يعيشان في عملية الـ client نفسها: لا شيء مشترك بين الـ sessions.

---

## ما تتضمنه المكتبة أيضاً

**`ask_until`:** يعيد السؤال حتى ترجع `parse` قيمة، مع `AskAgain` لتكرار السؤال.

```python
from pyroflow.models import AskAgain

async def parse_age(answer, kw):
    return int(answer.text) if answer.text.isdigit() else AskAgain("Digits only. Your age:")

age = await message.ask_until("Your age:", parse=parse_age, attempts=3, listen_user_id=message.from_user.id)
```

**لوحات الأزرار:** `arrange` يقسم الأزرار إلى صفوف، و`CallbackData` يحزم `callback_data` ويفكه ويفلتره.

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

**Pagination:** `NumberedPagination` و`ArrowPagination` و`SlidingPagination` تبني صفحة واحدة من العناصر مع شريط تنقل، من sequence أو من دالة جلب `(offset, limit)`.

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

**فلاتر نصية:** `pyroflow.filters` يضيف `startswith` و`endswith` و`equal` و`split_text` و`registered_command`، الذي يمرر فقط الأوامر المسجلة لهذا البوت.

```python
from pyroflow import MessageListener, filters

# A registered command ends an open question and reaches its handler.
client.register_listener(MessageListener(strict_filter=~filters.registered_command()))
```

**أوامر البوت:** `BotCommandsMixin` ينشر الأوامر المعلّمة بـ `mark_bot_commands` عند البدء.

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

**الأخطاء:** كل خطأ يرث من `PyroflowError`، وأخطاء الانتظار من `ListenerError`: `ListenerTimeout` و`ListenerCancelled` (ومنه `ListenerReplaced` و`ListenerRejected` و`ListenerEvicted`) و`ListenerAlreadyExists` و`ListenerWorkersBusy` و`ListenerAttemptsExhausted`، كلها في `pyroflow.errors`.

---

## التطوير

المتطلبان الوحيدان هما [uv](https://docs.astral.sh/uv/) و`make`.

```bash
make sync        # install the locked environment
make test        # run the test suite
make lint        # ruff check + ruff format --check
make typecheck   # ty
```

القواعد في [CONTRIBUTING.ar.md](CONTRIBUTING.ar.md). الإصدارات تُوسم بـ `v*` وينشرها الـ CI على PyPI، وملاحظات كل إصدار في [صفحة الإصدارات](https://github.com/eeeob/pyroflow/releases).

## الترخيص

MIT
