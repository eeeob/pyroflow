# pyroflow

> هذه ترجمة عربية لـ [README.md](README.md). النص الإنجليزي هو المرجع عند أي اختلاف.

[![PyPI version](https://img.shields.io/pypi/v/pyroflow)](https://pypi.org/project/pyroflow/)
[![Python versions](https://img.shields.io/pypi/pyversions/pyroflow)](https://pypi.org/project/pyroflow/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**امتداد لـ Pyrogram قائم على المحادثة، مع listeners لكل update ودوال `ask_*`.**

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
| طرح سؤال وانتظار جوابه | `ask()` / `ask_callback_query()`: أرسل رسالة أو عدّلها، ثم انتظر الرد أو الضغطة بـ `await` |

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

    answer = await message.ask("What is your name?", listen_timeout=60)
    await answer.reply(f"Hello, {answer.text}!")

client.run()
```

`message.ask` ترد على الرسالة، ثم تنتظر الرسالة التالية من مرسلها في نفس المحادثة والـ topic.

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
messages = MessageListener()
client.register_listener(messages)

@client.on_message()
async def on_confirm(client, message):
    if message.text != "/confirm":
        return

    await message.reply("Send your confirmation code:")

    try:
        code_msg = await messages.listen(
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

ويستطيع الـ client أن ينتظر أيضًا، على الـ listener المسجَّل لنوع الـ update:

```python
code_msg = await client.listen_message(chat_id=chat_id, user_id=user_id, timeout=120)
press = await client.listen_callback_query(chat_id=chat_id, message_id=message_id)
client.get_listener(Message)   # the registered listener, or None
```

`listen_message` و`listen_callback_query` تأخذان حقول مفتاحهما ومعاملات الانتظار، وترفعان `RuntimeError` إن لم يُسجَّل listener لنوعهما. أما `get_listener` فتُرجع `None` بدل رفع خطأ؛ واستعمل الـ listener الذي تُرجعه للبحث عن الانتظارات أو إنهائها، مثل `client.get_listener(Message).cancel(key)`.

كل listener ينتظر على مفاتيح من كلاسه الخاص، من `pyroflow.models`، و`listen` فيه تأخذ الحقول نفسها:

- `MessageListener`: `MessageKey(chat_id, user_id, message_thread_id, direct_messages_topic_id, ephemeral)`.
- `CallbackQueryListener`: `CallbackQueryKey(chat_id, user_id, message_id, inline_message_id, ephemeral)`.

الحقل المتروك `None` يطابق أي قيمة، فـ `messages.listen()` تأخذ الرسالة التالية في أي مكان، و`messages.listen(user_id=7)` تأخذ المستخدم 7 في أي محادثة. والمفتاح يحفظ القيم كما مُرِّرت، فللانتظار في المحادثة الخاصة مع مستخدم مرِّر `chat_id`: معرّف المحادثة الخاصة هو معرّف المستخدم. و`inline_message_id` ينتظر ضغطة على رسالة أُرسلت في الـ inline mode؛ وهذه الضغطة بلا محادثة، فتصل إلى انتظار على مستخدمها، ولا تصل أبدًا إلى انتظار على محادثة.

**الـ topics.** `message_thread_id` ينتظر في topic واحد من منتدى، أو في topic من محادثة خاصة للبوت. و`direct_messages_topic_id` ينتظر في topic واحد من محادثة الرسائل المباشرة لقناة. و`ask` تنتظر في topic الرسالة التي أرسلتها أو عدّلتها. ويترك Kurigram الحقل `message_thread_id` فارغًا في topic الـ General، فالسؤال المطروح هناك ينتظر على المحادثة كلها.

الـ listener يأخذ أول update مطابق يستقبله الـ client بعد استدعاء `listen`.

إن طابق update واحد عدة انتظارات، مثل انتظار للمستخدم وآخر للمحادثة كلها، يأخذه الأكثر تحديدًا فقط: صاحب أكثر الحقول المضبوطة، ثم حسب ترتيب الحقول، فـ `(chat, user)` قبل `(chat, topic)`. مرّر `resolve_scope=ListenerScope.ALL` (من `pyroflow.enums`) إلى الـ listener ليأخذه كل انتظار مطابق.

الـ listeners تعيش داخل عملية الـ client نفسه، ولا تنسّق pyroflow بين الـ sessions. لذلك البوت الذي يعمل في عدة عمليات يعالج كل update مرة في كل عملية تستقبله.

### الانتظار داخل الـ handlers

الـ handler الذي ينتظر في إحدى دوال `ask_*` أو في `listen` يحجز الـ worker الذي يشغّله (الـ `workers` في Pyrogram، وعددها افتراضيًا عدد أنوية المعالج زائد أربعة). فإذا انتظرت كل الـ workers، لا يبقى من يقرأ الردود، فيتجمّد البوت. يحدد `WorkersPolicy` ما يحدث بدل ذلك، عندما يأخذ انتظار جديد آخر worker، وهو يبقى دائمًا لقراءة الردود:

```python
from pyroflow.enums import WorkersPolicy

client = Client("bot", workers=12).setup_pyroflow(workers_policy=WorkersPolicy.CANCEL_OLDEST)
```

| السياسة | ماذا يحدث | يناسب |
|---|---|---|
| `REJECT` | يرفع الانتظار `ListenerWorkersBusy` | سقف مقصود، مثل بوت دعم بطاقة ثابتة |
| `CANCEL_OLDEST` | ينتهي أقدم انتظار بـ `ListenerEvicted` (وهو `ListenerCancelled`)، ويدخل الجديد مكانه فورًا. وقد يكمل الـ handler القديم عمله، وأي انتظار جديد منه يمر بالخطوات نفسها. وإن لم يوجد انتظار يُنهى، يرفع `ListenerWorkersBusy` | قوائم وأسئلة يتركها المستخدمون كثيرًا دون رد |

افتراضيًا لا سياسة ولا مهلة، فالسؤال الذي لا يُجاب يمسك الـ worker للأبد: وحين تُفتح `workers` أسئلة كهذه يتوقف البوت عن قراءة الـ updates حتى إعادة التشغيل. فاضبط سياسة أو `listen_timeout` أو كليهما، إلا إذا كانت `workers` أكبر بكثير من أي عدد محادثات مفتوحة. و`setup_pyroflow()` يلغي السياسة. كل الأوضاع تُبقي كل handler تحت قفل الـ worker الخاص به. والعدّ للانتظارات فقط، لا للـ handler الذي يعمل، وللانتظار في الـ handler نفسه فقط: فالانتظار في task أنشأها الـ handler لا يُحسب، حتى لو انتظرها بـ `asyncio.gather` فبقي حاجزًا للـ worker، ولا الانتظار في handler غير async، لأنه يعمل في thread. وهي method وليست معاملًا في `Client(...)`، حتى لا تعيد pyroflow كتابة توقيع الـ constructor الخاص بـ Pyrogram.

---

### ask() وask_callback_query()

دوال `ask_*` أغلفة عالية المستوى حول الـ listeners.

ترسل رسالة (أو تعدّلها)، ثم تتوقف حتى يصل الجواب، وكل ذلك في `await` واحد:

- `ask` تنتظر الرسالة التالية.
- `ask_callback_query` تنتظر ضغطة على أزرار الرسالة التي أرسلتها أو عدّلتها.

الدوال موجودة على `Client` وعلى `Message`، وكلها تأخذ المفتاح من الرسالة المرسلة أو المعدّلة: محادثتها والـ topic، ورقمها في حالة الضغطة.

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

- كل `ask_*` تأخذ `listen_user_id`، المستخدم المطلوب انتظاره.
- بدونه يكون الانتظار على المستخدم الذي تسمّيه الرسالة المرسلة أو المعدّلة: مستقبل الرسالة المؤقتة (`ephemeral_message_parameters`)، أو مرسل الرسالة التي ترد عليها (`reply_parameters`) إلا إن كانت رسالة الـ client نفسه. وإن لم يوجد أيهما فعلى أي مستخدم في المحادثة، وفي المحادثة الخاصة لا يجيب إلا المستخدم نفسه.
- `Message.ask_*` ترد على الرسالة، أو تعدّلها إن كانت رسالة الـ client نفسه (`editable`). وبدون `listen_user_id` تنتظر مرسلها أولًا.

**المعاملات:**

| المعامل | الوصف |
|---|---|
| `chat_id` | في `Client` فقط: الـ chat المستهدفة |
| `text` | نص الرسالة (`rich_message` في دوال `_rich`) |
| `message_id` | في `Client` فقط: إن أُعطي، تُعدَّل الرسالة بدل إرسال رسالة جديدة |
| `force_send` | في `Message` فقط: يرسل ردًا جديدًا حتى لو كانت الرسالة `editable` |
| `listen_timeout` | عدد الثواني قبل رفع `ListenerTimeout` |
| `listen_context` | `ListenerContext` بقيم تُرفق بالـ listener |
| `listen_filters` | filter من Pyrogram يجب أن يجتازه الـ update المنتظَر أيضًا |
| `listen_strict` | `True`: الـ update الذي يرفضه `listen_filters` ينهي الانتظار؛ `False`: يُتخطى ويستمر الانتظار |

أي keyword argument آخر يذهب إلى دالة Pyrogram التي ترسل أو تعدّل، مثل `reply_markup`.

**الاستثناءات:**
- `ListenerTimeout`: لم يصل رد خلال `listen_timeout` ثانية.
- `ListenerCancelled`: أُلغي الـ listener أثناء الانتظار.
- `ListenerReplaced`: أخذ انتظار أحدث المفتاح نفسه (وهو `ListenerCancelled`).
- `ListenerRejected`: مع `listen_strict=True`، رفض `listen_filters` update (وهو `ListenerCancelled`).
- `ListenerAlreadyExists`: مع `DuplicatePolicy.REJECT` على الـ listener، يوجد انتظار على المفتاح نفسه. يكون السؤال قد أُرسل.

وللفحص قبل الإرسال، ابحث عن المفتاح بنفسك كما يبنيه الانتظار: `MessageKey(chat_id, user_id) in client.get_listener(Message).listeners` لـ `message.ask` في محادثة بلا topics، مع `None` مكان `user_id` إن كانت الرسالة رسالة الـ client نفسه (`editable`). أما `client.ask` فتنتظر بلا `user_id`.

**الفلاتر.** `listen_filters` يضيف filter من Pyrogram يجب أن يجتازه الـ update المنتظَر، إضافة إلى مفتاحه.

- الـ update الذي يطابق المفتاح ويرفضه الفلتر يذهب إلى الـ handlers، ويستمر الانتظار.
- مع `listen_strict=True` ينهي ذلك الـ update الانتظار بـ `ListenerRejected`.

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

`listen_strict` يقرر للفلتر كله: مع `filters.text & ~filters.command("cancel")` و`listen_strict=True`، تنهي الصورة السؤال كما ينهيه الأمر.

ولفلترة كل انتظار لا يمرر `listen_filters`، أعطِ الـ listener قيمة `strict_filter`، مثل `MessageListener(strict_filter=~filters.command("cancel"))`. والـ update الذي يفشل فيه ينهي الانتظار بـ `ListenerRejected`.

**الأوامر المسجلة.** يمرر `pyroflow.filters.registered_command()` الرسالة التي نصها أو `caption` فيها أمر مسجل لهذا الـ bot، بوسائط أو بدونها. فالأمر `/cmd@this_bot` يمر، أما `/cmd@other_bot` والأمر المجهول والنص العادي فلا. وتأتي الأوامر من `client.get_bot_commands()` لكل نطاق في `scopes` (الافتراضي `registered_command.DEFAULT_SCOPES`، أي النطاقات الأربعة التي لا تحتاج شاتاً ولا مستخدماً) بكل لغة في `language_codes` (الافتراضي `""`)، تُجلب معاً عند أول استعمال ويحتفظ بها الفلتر مع usernames الـ bot حتى يُشغَّل الـ client من جديد، فتظهر الأوامر المضافة بعد إعادة التشغيل. والجلب الفاشل، كما في حساب مستخدم، يرفع خطأه كما هو ويلغي بقية الطلبات، ويُعاد الجلب مع الأمر التالي. وكل فلتر `registered_command()` يجلب لنفسه. و`registered_command(ephemeral=False)` يستثني الأوامر المعلّمة بـ `is_ephemeral`، و`username_policy` (قيمة `CommandUsernamePolicy` من `pyroflow.enums`) يحدد أي `@username` يمر: `OPTIONAL` (الافتراضي) بلا username أو username الـ bot، و`REQUIRED` username الـ bot فقط، و`None` بلا username أو أي username، و`ANY_REQUIRED` أي username لا بدونه، و`FORBIDDEN` بلا username فقط.

ومعكوسًا في `strict_filter`، يتيح للأمر المسجل إنهاء السؤال الذي لا يمرر `listen_filters` والوصول إلى الـ handler الخاص به، وأي رسالة أخرى تجيب عن السؤال:

```python
from pyroflow import MessageListener, filters

client.register_listener(MessageListener(strict_filter=~filters.registered_command()))
```

أما السؤال الذي يمرر `listen_filters` فلا يطبَّق عليه `strict_filter`، فيضيف الفلتر بنفسه، وعندها تنهيه أيضًا أي رسالة أخرى تفشل فيها الفلاتر، مثل صورة:

```python
from pyrogram import filters as pyrogram_filters

name = await message.ask(
    "Your name?",
    listen_filters=pyrogram_filters.text & ~filters.registered_command(),
    listen_strict=True,
)
```

وفي الحالتين يُعرض الأمر على أي انتظار آخر يطابقه، مثل انتظار للمحادثة كلها، ولا يصل إلى الـ handler إلا إن لم يأخذه أي منها.

للتصرف عند كل انتظار يفشل، مرّر `on_error_func` إلى الـ listener. يستقبل الخطأ والـ `ListenerModel` (مفتاحه و`context` وفلتره) قبل أن يرفع `listen` الخطأ:

```python
def report(exc, model):
    log.info("Wait for %s ended: %r", model.key, exc)

client.register_listener(MessageListener(on_error_func=report))
```

`context` الانتظار من نوع `ListenerContext`:

- فيه حقول لها أنواع، وأي قيم تضيفها أنت.
- الكل يُقرأ ويُضبط بالنقطة (attribute).
- لإعطاء حقولك أنواعًا، أنشئ كلاسًا فرعيًا منه.

```python
from pyroflow.models import ListenerContext

class OrderContext(ListenerContext):
    step: int = 0

answer = await message.ask("Your name?", listen_context=OrderContext(step=1, note="signup"))
```

مع `setup_pyroflow(ask_context_message=True)` تضع دوال `ask_*` الرسالة التي أرسلها أو عدّلها في `listen_context` باسم `message`، على نسخة منه، إلا إذا ضبطتها أنت مسبقًا. وبدونه يصل `listen_context` إلى الـ listener كما هو. بالرسالة تستطيع `on_error_func` تنظيف السؤال:

```python
async def drop_question(exc, model):
    if model.context and model.context.message:
        await model.context.message.delete()
```

لإنهاء سؤال من handler زر، مثل زر "رجوع" عليه، ألغِ انتظاره بمفتاحه، فترفع `ask` الخطأ `ListenerCancelled`: `client.get_listener(Message).cancel(MessageKey.from_sent(query.message, query.from_user.id))` بعد `message.ask` على رسالة المستخدم، أو مع `None` مكان المستخدم بعد `client.ask`، أو بعد `message.ask` على رسالة الـ client نفسه (`editable`)، مثل `query.message`.

> ⚠️ **انتظار لا ينتهي.** بلا `listen_strict`، يبقى الانتظار مفتوحًا حتى `listen_timeout`، أو إلى الأبد بلا `listen_timeout`، إذا رفض الفلتر كل update ما زال يمكن أن يطابق المفتاح:
> - الفلتر لا يمكن أن يقبل هذا النوع أصلًا، مثل `filters.photo` أثناء انتظار `CallbackQuery`.
> - المستخدم يرسل باستمرار ما يرفضه الفلتر.
>
> أعطِ هذا الانتظار مهلة (`listen_timeout` في `ask_*`، أو `timeout` في `listen` أو على الـ listener)، أو استعمل `listen_strict=True` (`strict=True` في `listen`) إن كان أول update مرفوض يجب أن ينهي الانتظار، أو أنهِه بنفسك بـ `listener.cancel(key)`. وانتبه: `listen_strict=True` ينهي الانتظار عند **أي** update مرفوض من نفس المفتاح، مثل صورة أثناء انتظار نص.


`ask_rich()` و`ask_callback_query_rich()` تفعلان الشيء نفسه مع rich message:

- ترسلان عبر `send_rich_message`.
- أو تعدّلان عبر `edit_message_text(rich_message=...)` إن أُعطي `message_id`.

ودوال `Message` تستدعي `edit` و`reply` و`reply_rich` من الرسالة نفسها، فتقبل ما تقبله هذه الدوال. ولمعاملات مثل `reply_parameters` استعمل دوال `Client`.

```python
from pyrogram.types import InputRichMessage

answer = await client.ask_rich(
    chat_id,
    InputRichMessage(html="Pick a <b>name</b>:"),
    listen_timeout=30,
)
```

معرّفات الرسائل المؤقتة لا تتسلسل وقد يُعاد استعمالها، فلا يحمل أي مفتاح رقمها:

- `ephemeral=True` في `listen` ينتظر التحديثات المؤقتة. هذا الانتظار وحده يستقبلها، ولا يصله تحديث عادي.
- `Message.ask_*` على رسالة مؤقتة تنتظر مرسلها بهذه الطريقة.
- `Client.ask_*` لا تعرف مستخدمًا، فترفع `ValueError` مع `ephemeral_message_parameters` قبل الإرسال.
- رسالتان مؤقتتان للمستخدم نفسه تشتركان في المفتاح، ففرّق بينهما بـ `listen_filters`.

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
    reply = await client.ask(chat_id, "Your input?", listen_timeout=30)
except ListenerTimeout:
    await client.send_message(chat_id, "You took too long. Try again.")
except ListenerCancelled:
    await client.send_message(chat_id, "Session was cancelled.")
```

كل الأخطاء ترث `PyroflowError`:

- `ListenerError`: أخطاء الانتظار ودوال `ask_*` (`ListenerTimeout`، `ListenerCancelled`، `ListenerAlreadyExists`).

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
