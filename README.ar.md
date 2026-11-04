# pyroflow

> هذه ترجمة عربية لـ [README.md](README.md). النص الإنجليزي هو المرجع عند أي اختلاف.

[![PyPI version](https://img.shields.io/pypi/v/pyroflow)](https://pypi.org/project/pyroflow/)
[![Python versions](https://img.shields.io/pypi/pyversions/pyroflow)](https://pypi.org/project/pyroflow/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**امتداد لـ Pyrogram قائم على المحادثة، مع listeners لكل update و`ask`.**

تبني pyroflow فوق [Pyrogram](https://github.com/pyrogram/pyrogram) / [Kurigram](https://github.com/KurimuzonAkuma/pyrogram).

تستبدل نموذج الـ handlers بـ API يضع المحادثة أولًا: تنتظر بـ `await` ردًا محددًا من مستخدم محدد، بدل ربط handlers عامة وإدارة state machines يدويًا.

> **تُحدِّث من إصدار سابق؟** راجع [CHANGELOG.md](CHANGELOG.md) لمعرفة التغييرات الكاسرة وطريقة الانتقال.

```
pip install pyroflow
```

---

## لماذا pyroflow؟

يستدعي Pyrogram الـ handler عند **كل** update واردة من نوع معيّن.

بمجرد أن تحتاج محادثة ذهابًا وإيابًا، تجد نفسك تكتب state machines، وتخزّن `user_id → step` في dict، وتأمل ألا تتسابق updateان على الحالة نفسها.

تستبدل pyroflow ذلك كله بـ `await` واحد:

| المشكلة | حل pyroflow |
|---|---|
| انتظار رد محدد | `UpdateListener`: انتظر بـ `await` الـ update التالية من مستخدم |
| طرح سؤال وانتظار جوابه | `ask()`: أرسل رسالة أو عدّلها، ثم انتظر الرد بـ `await` |

---

## التثبيت

**الحد الأدنى من المتطلبات:** Python 3.10+

```
pip install pyroflow
```

لتثبيت أحدث التغييرات غير المنشورة مباشرة من GitHub بدل آخر إصدار على PyPI:

```bash
pip install git+https://github.com/eeeob/pyroflow.git --force-reinstall
```
### 🔹 بدون الاعتماديات
```bash
pip install git+https://github.com/eeeob/pyroflow.git --force-reinstall --no-deps
```
---


## بداية سريعة

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

## المفاهيم الأساسية

### Listeners

الـ `UpdateListener` طابور (queue) مرتبط بنوع update من Pyrogram.

يستطيع أي coroutine أن ينتظر بـ `await` الـ update المطابقة التالية من مستخدم أو chat محدد.

الـ update التي يلتقطها listener **لا تصل أبدًا إلى مسار الـ handlers العادي**.

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

اختصارات لأكثر نوعين شيوعًا من الـ listeners:

```python
client.message_listen    # UpdateListener[Message]
client.callback_listen   # UpdateListener[CallbackQuery]
```

الـ listener يأخذ أول update مطابق يستقبله الـ client بعد استدعاء `listen`.

الـ listeners تعيش داخل عملية الـ client نفسه، ولا تنسّق pyroflow بين الـ sessions. لذلك البوت الذي يعمل في عدة عمليات يعالج كل update مرة في كل عملية تستقبله.

---

### ask()

`ask()` غلاف عالي المستوى حول الـ listeners.

ترسل رسالة (أو تعدّلها)، ثم تتوقف حتى يصل رد مطابق، وكل ذلك في `await` واحد.

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

**المعاملات:**

| المعامل | الوصف |
|---|---|
| `chat_id` | الـ chat المستهدفة |
| `text` | نص الرسالة |
| `message_id` | إن أُعطي، تُعدَّل الرسالة بدل إرسال رسالة جديدة |
| `listen_user_id` | تصفية الـ update المنتظَرة حسب المستخدم |
| `listen_message_id` | تصفية الـ update المنتظَرة حسب الرسالة |
| `timeout` | عدد الثواني قبل رفع `ListenerTimeout` |
| `update_type` | نوع الـ update المنتظَرة، ويحدد نوع القيمة المعادة (الافتراضي: `Message`) |
| `meta` | metadata اختيارية تُرفق بالـ listener |

**الاستثناءات:**
- `ListenerTimeout`: لم يصل رد خلال `timeout` ثانية.
- `ListenerCancelled`: أُلغي الـ listener أثناء الانتظار.

`ask_rich()` تفعل الشيء نفسه مع rich message:

- ترسل عبر `send_rich_message`.
- أو تعدّل عبر `edit_message_text(rich_message=...)` إن أُعطي `message_id`.

و`Message.ask_rich()` تقابل `Message.ask()`.

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

ويمكن أيضًا إزالة الـ listeners أثناء التشغيل:

```python
await client.unregister_listener(Message)
```

---

## معالجة الأخطاء

```python
from pyroflow.errors import ListenerTimeout, ListenerCancelled

try:
    reply = await client.ask(chat_id, "Your input?", listen_user_id=uid, timeout=30)
except ListenerTimeout:
    await client.send_message(chat_id, "You took too long. Try again.")
except ListenerCancelled:
    await client.send_message(chat_id, "Session was cancelled.")
```

كل الأخطاء ترث `PyroflowError`:

- `ListenerError`: أخطاء الانتظار و`ask` (`ListenerTimeout`، `ListenerCancelled`، `ListenerAlreadyExists`).

---

## التطوير

المتطلب الوحيد هو [uv](https://docs.astral.sh/uv/).

```bash
make sync        # install the locked environment
make test        # run the test suite
make lint        # ruff check + ruff format --check
make typecheck   # ty
```

راجع [CONTRIBUTING.md](CONTRIBUTING.md) لسير العمل الكامل والقواعد.

---

## الترخيص

MIT
