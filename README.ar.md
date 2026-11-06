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
        text="What is your name?",
        listen_user_id=message.from_user.id,
        listen_timeout=60,
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

إن طابق update واحد عدة انتظارات، مثل انتظار للمستخدم وآخر للمحادثة كلها، يأخذه الأكثر تحديدًا فقط. مرّر `resolve_scope=ListenerScope.ALL` (من `pyroflow.enums`) إلى الـ listener ليأخذه كل انتظار مطابق.

الـ listeners تعيش داخل عملية الـ client نفسه، ولا تنسّق pyroflow بين الـ sessions. لذلك البوت الذي يعمل في عدة عمليات يعالج كل update مرة في كل عملية تستقبله.

### الانتظار داخل الـ handlers

الـ handler الذي ينتظر في `ask` أو `listen` يحجز الـ worker الذي يشغّله (الـ `workers` في Pyrogram، وعددها افتراضيًا عدد أنوية المعالج زائد أربعة). فإذا انتظرت كل الـ workers، لا يبقى من يقرأ الردود، فيتجمّد البوت. يحدد `WorkersPolicy` ما يحدث بدل ذلك، عندما يأخذ انتظار جديد آخر worker، وهو يبقى دائمًا لقراءة الردود:

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
    listen_timeout=30,
)

# Edit an existing message, then wait for a callback query
callback = await client.ask(
    chat_id=chat_id,
    text="Updated — choose again:",
    message_id=sent_msg.id,
    listen_user_id=user_id,
    listen_timeout=30,
    listen_update_type=CallbackQuery,
)
```

**المعاملات:**

| المعامل | الوصف |
|---|---|
| `chat_id` | الـ chat المستهدفة |
| `text` | نص الرسالة |
| `message_id` | إن أُعطي، تُعدَّل الرسالة بدل إرسال رسالة جديدة |
| `listen_user_id` | تصفية الـ update المنتظَرة حسب المستخدم |
| `listen_message_id` | تصفية الـ update المنتظَرة حسب الرسالة: رقم، أو `None` (الافتراضي) بلا تصفية، أو `ListenMessageId` (من `pyroflow.enums`): `SENT` للرسالة التي أرسلها `ask` أو عدّلها (ضغطة على أزرارها)، و`NEXT` للرسالة التي بعدها مباشرة. في المجموعات قد تأخذ رسالة عضو آخر الرقم التالي |
| `listen_timeout` | عدد الثواني قبل رفع `ListenerTimeout` |
| `listen_update_type` | نوع الـ update المنتظَرة، ويحدد نوع القيمة المعادة (الافتراضي: `Message`) |
| `listen_context` | `ListenerContext` بقيم تُرفق بالـ listener |
| `listen_filters` | filter من Pyrogram يجب أن يجتازه الـ update المنتظَر أيضًا |
| `listen_strict` | `True`: الـ update الذي يرفضه `listen_filters` ينهي الانتظار؛ `False`: يُتخطى ويستمر الانتظار |

**الاستثناءات:**
- `ListenerTimeout`: لم يصل رد خلال `listen_timeout` ثانية.
- `ListenerCancelled`: أُلغي الـ listener أثناء الانتظار.
- `ListenerReplaced`: أخذ انتظار أحدث المفتاح نفسه (وهو `ListenerCancelled`).
- `ListenerRejected`: مع `listen_strict=True`، رفض `listen_filters` update (وهو `ListenerCancelled`).
- `ListenerAlreadyExists`: مع `DuplicatePolicy.REJECT` على الـ listener، يوجد انتظار على المفتاح نفسه. يكون السؤال قد أُرسل.

وللفحص قبل الإرسال، ابحث عن المفتاح بنفسك: `ListenerKey(chat_id, user_id) in client.message_listen.listeners`.

**الفلاتر.** `listen_filters` يضيف filter من Pyrogram يجب أن يجتازه الـ update المنتظَر، إضافة إلى `listen_user_id` و`listen_message_id`.

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

`listen_strict` يقرر للفلتر كله: مع `filters.text & ~filters.command("cancel")` و`listen_strict=True`، تنهي الصورة السؤال كما ينهيه الأمر. ويسجّل `MessageListener` تحذيرًا في الـ log حين ينتظر فلتر غير صارم على `listen_message_id`، وهي الحالة الأولى أدناه.

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

مع `setup_pyroflow(ask_context_message=True)` يضع `ask` الرسالة التي أرسلها أو عدّلها في `listen_context` باسم `message`، على نسخة منه، إلا إذا ضبطتها أنت مسبقًا. وبدونه يصل `listen_context` إلى الـ listener كما هو. بالرسالة تستطيع `on_error_func` تنظيف السؤال:

```python
async def drop_question(exc, model):
    if model.context and model.context.message:
        await model.context.message.delete()
```

`MessageListenCancellingCallbackQueryListener` هو `CallbackQueryListener` يلغي أيضًا انتظار الرسائل: الضغطة التي لا يأخذها أي انتظار callback تلغي انتظار الرسائل المرتبط بالرسالة المضغوطة (`context.message` فيه)، فيرفع `ask` الخطأ `ListenerCancelled`. سجّله بدل `CallbackQueryListener` لتحصل على ذلك. مثلًا، زر "رجوع" على رسالة سؤال ينهي عندها انتظار جوابه:

```python
from pyroflow import MessageListenCancellingCallbackQueryListener

client.register_listener(MessageListenCancellingCallbackQueryListener())
```

`cancel_policy` يحدد أي ضغطة تلغي:

- `MessageListenCancelPolicy.UNRESOLVED` (الافتراضي): الضغطة التي لم يأخذها انتظار callback فقط.
- `RESOLVED`: الضغطة التي أخذها انتظار callback فقط.
- `ALWAYS`: كل ضغطة.

و`cancel_scope` يحدد كم انتظار رسائل مرتبط بالرسالة المضغوطة (`context.message` فيه) تلغيه الضغطة:

- `ListenerScope.ALL` (الافتراضي): كل انتظار مرتبط.
- `FIRST`: الأكثر تحديدًا فقط، أي الأول بترتيب `sub_keys`.

و`ask` يسجّل تلك الرسالة في السياق مع `setup_pyroflow(ask_context_message=True)` فقط. وبدونه لا يرتبط برسالة إلا انتظار وضع `context.message` بنفسه.

> ⚠️ **انتظار لا ينتهي.** بلا `listen_strict`، يبقى الانتظار مفتوحًا حتى `listen_timeout`، أو إلى الأبد بلا `listen_timeout`، إذا رفض الفلتر كل update ما زال يمكن أن يطابق المفتاح:
> - المفتاح يسمّي update واحدًا. في `MessageListener` يسمّي `listen_message_id` رسالة واردة واحدة، فإن رفضها الفلتر لا يطابق شيء بعدها.
> - الفلتر لا يمكن أن يقبل هذا النوع أصلًا، مثل `filters.photo` أثناء انتظار `CallbackQuery`.
> - المستخدم يرسل باستمرار ما يرفضه الفلتر.
>
> أعطِ هذا الانتظار مهلة (`listen_timeout` في `ask`، أو `timeout` في `listen` أو على الـ listener)، أو استعمل `listen_strict=True` (`strict=True` في `listen`) إن كان أول update مرفوض يجب أن ينهي الانتظار، أو أنهِه بنفسك بـ `listener.cancel(key)`. وانتبه: `listen_strict=True` ينهي الانتظار عند **أي** update مرفوض من نفس المفتاح، مثل صورة أثناء انتظار نص.


`ask_rich()` تفعل الشيء نفسه مع rich message:

- ترسل عبر `send_rich_message`.
- أو تعدّل عبر `edit_message_text(rich_message=...)` إن أُعطي `message_id`.

و`Message.ask_rich()` تقابل `Message.ask()`. وكلتاهما تستدعي `edit` و`reply` و`reply_rich` من الرسالة نفسها، فتقبلان ما تقبله هذه الدوال. ولمعاملات مثل `reply_parameters` استعمل `client.ask()`.

معرّفات الرسائل المؤقتة لا تتسلسل وقد يُعاد استعمالها، فلا يطابقها الاستماع بالرقم. مرّر `EphemeralUpdates.ANY` في `listen_message_id`، أو في `message_id` عند `listen()`، مع مستخدم: فهذا الانتظار وحده يستقبل التحديثات المؤقتة، ولا يصله تحديث عادي. لذلك لا يستلم `ask()` المؤقت رده إلا مع `listen_message_id=EphemeralUpdates.ANY`: فبالافتراضي `None` ينتظر رسالة عادية من المستخدم، ولا يصله الرد المؤقت. وترفع `SENT` و`NEXT` الخطأ `ValueError` هناك. ويشترط `client.ask()` مع `ephemeral_message_parameters` تمرير `listen_user_id`، أما `Message.ask()` عند الرد على رسالة مؤقتة فيأخذه من مرسلها. ورسالتان مؤقتتان للمستخدم نفسه تشتركان في المفتاح، ففرّق بينهما بـ `listen_filters`.

```python
from pyrogram.types import InputRichMessage

answer = await client.ask_rich(
    chat_id,
    InputRichMessage(html="Pick a <b>name</b>:"),
    listen_user_id=user_id,
    listen_timeout=30,
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
    reply = await client.ask(chat_id, "Your input?", listen_user_id=uid, listen_timeout=30)
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
