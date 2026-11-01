# pyroflow

> هذه ترجمة عربية لـ [README.md](README.md). النص الإنجليزي هو المرجع عند أي اختلاف.

[![PyPI version](https://img.shields.io/pypi/v/pyroflow)](https://pypi.org/project/pyroflow/)
[![Python versions](https://img.shields.io/pypi/pyversions/pyroflow)](https://pypi.org/project/pyroflow/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**امتداد لـ Pyrogram قائم على المحادثة، مع listeners لكل update وتنسيق بين عدة sessions.**

تبني pyroflow فوق [Pyrogram](https://github.com/pyrogram/pyrogram) / [Kurigram](https://github.com/KurimuzonAkuma/pyrogram).

تستبدل نموذج الـ handlers بـ API يضع المحادثة أولًا: تنتظر بـ `await` ردًا محددًا من مستخدم محدد، بدل ربط handlers عامة وإدارة state machines يدويًا.

> **تُحدِّث من إصدار سابق؟** راجع [CHANGELOG.md](CHANGELOG.md) لمعرفة التغييرات الكاسرة وطريقة الانتقال.

```
pip install pyroflow
```

للتنسيق المعتمد على Redis:

```
pip install pyroflow[redis]
```

---

## لماذا pyroflow؟

يستدعي Pyrogram الـ handler عند **كل** update واردة من نوع معيّن.

بمجرد أن تحتاج محادثة ذهابًا وإيابًا، تجد نفسك تكتب state machines، وتخزّن `user_id → step` في dict، وتأمل ألا تتسابق updateان على الحالة نفسها.

تحل pyroflow المشكلات الثلاث:

| المشكلة | حل pyroflow |
|---|---|
| انتظار رد محدد | `UpdateListener`: انتظر بـ `await` الـ update التالية من مستخدم |
| معالجة مكررة عبر عدة sessions للبوت | `UpdateCoordinated`: قفل موزّع (distributed lock) لكل update |
| إعادة تشغيل خطوات الـ handlers السابقة أو فحصها | `UpdateHistory`: سجل للـ handlers لكل نوع update |

---

## التثبيت

**الحد الأدنى من المتطلبات:** Python 3.10+

```
pip install pyroflow          # core
pip install pyroflow[redis]   # + Redis coordinator support
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

---

### Coordinators

يأخذ `UpdateCoordinated` **قفلًا موزّعًا** (distributed lock) قبل معالجة الـ update.

هذا يضمن أن الـ update نفسها تُعالَج في session واحدة فقط عندما يعمل البوت على عدة خوادم في الوقت نفسه.

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

**الـ backends المدعومة:**

| Backend | Extra |
|---|---|
| Redis | `pip install pyroflow[redis]` |

**حالات القفل:**

- `HANDLED`: *شُغِّل* handler واحد على الأقل للـ update، سواء انتهى بشكل طبيعي أو رفع استثناءً. يُحرَّر القفل وتتجاهل الـ sessions الأخرى الـ update.
  - الـ handler الذي رفع استثناءً يُحسب أيضًا: الـ update وصلت إلى صاحبها، وإعادة تشغيلها في مكان آخر تكرر العمل ولا تصلح شيئًا.
- `None`: لم يُشغَّل أي handler. يُحرَّر القفل لتعيد session أخرى المحاولة.

لإعادة update كي تحاول session أخرى معالجتها، ارفع `UnhandledUpdate` من الـ handler.

هذا يوقف المعالجة في الـ session الحالية ويترك القفل دون مطالبة.

---

### Histories

يسجّل `UpdateHistory` الـ handlers التي نجح تشغيلها لكل update.

هذا يتيح ميزات مثل أزرار `back` التي تعيد تشغيل خطوات المعالجة السابقة أو تفحصها.

```python
from pyroflow import Client, CallbackQueryHistory

client = Client("my_session")
client.register_history(CallbackQueryHistory())

client.run()
```

---

ويمكن أيضًا إزالتها أثناء التشغيل:

```python
await client.unregister_listener(Message)
await client.unregister_coordinated(Message)
await client.unregister_history(CallbackQueryHistory)
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

---

## التطوير

المتطلب الوحيد هو [uv](https://docs.astral.sh/uv/).

```bash
make sync        # install the locked environment with every extra
make test        # run the test suite
make lint        # ruff check + ruff format --check
make typecheck   # ty
```

راجع [CONTRIBUTING.md](CONTRIBUTING.md) لسير العمل الكامل والقواعد.

---

## الترخيص

MIT
