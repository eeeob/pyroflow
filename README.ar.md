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

    answer = await message.ask(
        "What is your name?", listen_user_id=message.from_user.id, listen_timeout=60
    )
    await answer.reply(f"Hello, {answer.text}!")

client.run()
```

`message.ask` ترد على الرسالة، ثم تنتظر الرسالة التالية من `listen_user_id`، وهو هنا مرسلها، في نفس المحادثة والـ topic.

---

## المفاهيم الأساسية

### Listeners

الـ `UpdateListener` طابور (queue) مرتبط بنوع update من Pyrogram.

يستطيع أي coroutine أن ينتظر بـ `await` الـ update المطابقة التالية من مستخدم أو chat محدد.

الـ update التي يلتقطها listener **لا تصل أبدًا إلى مسار الـ handlers العادي**.

```python
from pyroflow import Client, MessageListener
from pyroflow.errors import ListenerTimeout
from pyroflow.models import MessageKey

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
            MessageKey(message.chat.id, message.from_user.id),
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
code_msg = await client.listen(MessageKey(chat_id, user_id), timeout=120)
code_msg = await client.listen_message(chat_id=chat_id, user_id=user_id, timeout=120)
press = await client.listen_callback_query(chat_id=chat_id, message_id=message_id)
client.get_listener(Message)   # the registered listener, or None
```

`listen` تأخذ مفتاحاً ومعاملات الانتظار، وتعرف الـ listener من `__update_type__` الخاص بالمفتاح. و`listen_message` و`listen_callback_query` تأخذان حقول المفتاح ومعاملات الانتظار، وتبنيان المفتاح بـ `__key_type__` الخاص بالـ listener، وترفعان `RuntimeError` إن لم يُسجَّل listener لنوعهما. أما `get_listener` فتُرجع `None` بدل رفع خطأ؛ واستعمل الـ listener الذي تُرجعه للبحث عن الانتظارات أو إنهائها، مثل `client.get_listener(Message).cancel(key)`.

كل listener ينتظر على مفاتيح من كلاسه الخاص، من `pyroflow.models`، و`listen` فيه تأخذ مفتاحاً منها:

- `MessageListener`: `MessageKey(chat_id, user_id, message_thread_id, direct_messages_topic_id, ephemeral)`.
- `CallbackQueryListener`: `CallbackQueryKey(chat_id, user_id, message_id, inline_message_id, ephemeral)`.

الحقل المتروك `None` يطابق أي قيمة، فـ `messages.listen(MessageKey())` تأخذ الرسالة التالية في أي مكان، و`messages.listen(MessageKey(user_id=7))` تأخذ المستخدم 7 في أي محادثة. والمفتاح يحفظ القيم كما مُرِّرت، فللانتظار في المحادثة الخاصة مع مستخدم مرِّر `chat_id`: معرّف المحادثة الخاصة هو معرّف المستخدم. و`inline_message_id` ينتظر ضغطة على رسالة أُرسلت في الـ inline mode؛ وهذه الضغطة بلا محادثة، فتصل إلى انتظار على مستخدمها، ولا تصل أبدًا إلى انتظار على محادثة.

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

### update واحد في كل مرة لكل قفل: CoordinatedDispatcher

رسالتان سريعتان من المستخدم نفسه تشغّلان عادةً handler‑ين في الوقت نفسه، فقد تفوت الثانيةَ السؤالُ الذي يوشك الأول أن يطرحه. `CoordinatedDispatcher` صنف فرعي اختياري من `Dispatcher` يشغّل الـ updates التي تشترك في قفل واحدًا بعد الآخر. ثبّته مباشرة بعد إنشاء الـ client:

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

هو كيان مستقل يبدأ فارغًا: لا يُنقل إليه شيء من الـ dispatcher الذي يحل محله. **ثبّته قبل أي handler أو listener أو استدعاء `setup_pyroflow`**، لأن ما سُجّل قبله يبقى على الـ dispatcher القديم ولا يعمل أبدًا. ولا تثبّته من `on_start` أو بعد بدء الـ client: سيستمر الـ client في قراءة الـ dispatcher القديم، بلا أي خطأ. و`Dispatcher` الخاص بـ pyroflow لا يتغير أبدًا: بدونه لا يوجد تنسيق.

- **دوال المفاتيح.** تستخرج المفتاح فقط، والـ dispatcher ينسق المفاتيح. أول دالة تعطي مفتاحًا هي المعتمدة، و`None` ينقل الـ update للدالة التالية، ومفاتيح الدوال المختلفة لا تختلط. ولقرار خاص بك أعد مفتاحًا ثابتًا لما يختاره. والـ update الذي لا تعطيه أي دالة مفتاحًا يعمل حرًا، فمنشورات القنوات بلا مستخدم، والـ inline query بلا شات. دوال المفاتيح متزامنة وتستلم الـ update المُحلَّل، والخطأ أو المفتاح غير الـ hashable يُسجَّل وينتقل الـ update للدالة التالية.
- **الترتيب.** تحلّل الـ task التي تقرأ طابور Pyrogram كل update بدوره، وتضعه خلف ما سبقه من updates مفتاحه، فيُحسب المفتاح بعد التحليل ولا يسبق update لاحق ما قبله. ولا تُنشأ task لكل update، ويصل الرد ولو كانت كل الـ workers تنتظر. والـ parser البطيء يؤخر ما بعده.
- **الحجز.** عند دور الـ update يُعرض أولًا على الانتظارات. وإن لم يأخذه أحد، تعمل handlers مع filters، فترى filters ما تركه الـ update السابق للمفتاح. ويحجز الـ handler المفتاح حتى ينتهي، حتى أثناء انتظاره في `ask`.
- **الطابور.** الـ update لمفتاح محجوز ينضم إلى طابور المفتاح ولا يأخذ worker، فالمستخدم الذي يرسل 12 رسالة لا يوقف غيره.
- **العدالة.** بعد كل update يذهب مفتاحه خلف المفاتيح الأخرى الجاهزة، فلا يبقي الإغراق المستخدمين الآخرين منتظرين.
- **الردود.** أثناء عمل الـ handler، تعرض task واحدة مشتركة بين كل المفاتيح الطابور على الانتظارات بالترتيب: كل update عند وصوله، والطابور كله من جديد كلما بدأ الـ handler انتظارًا. ما يأخذه انتظار يخرج من الطابور. وما يرفضه انتظار للـ handler يبقى في مكانه، ولا يُعرض على انتظارات ذلك الـ handler اللاحقة، وتبقى الانتظارات الأخرى تراه: فهو ليس ردًا كما في الـ dispatcher العادي، ويعمل بالـ handlers في دوره، ولا يُرفض الـ handler الذي يعيد السؤال بـ `listen_strict=True` بنفس الـ update إلى الأبد. يعمل filter الانتظار مرة واحدة لكل update مهما تكرر عرضه. والانتظار الذي يبدأ أثناء عرض update يأخذ الأقدم أولًا. ولا يلزم worker حر لذلك.
- **الانتظارات الأخرى.** الـ task التي يطلقها الـ handler تُحسب منه ما دام يعمل، فانتظاراتها انتظاراته. وحين ينتهي الـ handler يتحرك المفتاح بدون الـ task، فانتظرها بـ `await` داخل الـ handler ليبقى المفتاح محجوزًا. وأي انتظار آخر، كانتظار handler حر، أو handler لمفتاح آخر، أو task انتهى الـ handler الذي أطلقها، يصله الـ update من الطابور بنفس الطريقة، لكن الـ update الذي عُرض قبل بدء الانتظار قد لا يصله إلا في دوره. وإذا طابق update عدة انتظارات يحسم الـ listener كالعادة، بترتيب الأشكال و`resolve_scope`، ولا أولوية للـ handler الذي يحجز المفتاح.
- **بعد الـ handler.** يُنشر الـ update التالي للمفتاح: يُعرض على الانتظارات مرة أخرى، ثم تعمل handlers. ويُحرَّر المفتاح عند فراغ الطابور، ولا يترك أي حالة.
- **الإيقاف.** `stop` ينهي الانتظارات المفتوحة، ثم يعمل كل update قُرئ قبل خروج الـ workers، وتُرفض انتظاراته بـ `ListenerCancelled`.

اعرف هذه النقاط قبل تفعيله:

- **الانتظار بلا timeout يجمّد مفتاحه نهائيًا.** يبقى المفتاح محجوزًا أثناء الانتظار، فلا يعمل شيء آخر لذلك المفتاح، وhandler لأمر `/cancel` عادي هو مجرد update في الطابور: لن يعمل. مرّر `listen_timeout`. وإذا فشل أمر في `strict_filter` الخاص بالـ listener فإنه ينهي الانتظار أيضًا ويصل الأمر إلى الـ handlers بعد انتهاء الـ handler، لكن هذا يخص الانتظار بلا `listen_filters` فقط: الانتظار بـ filter خاص يحتاج `listen_strict=True` أو timeout.
- قد تنهي رسالة في الطابور انتظارًا strict لاحقًا عند عرضها عليه، لأن `strict` ينهي الانتظار عند أي update مرفوض لمفتاحه.
- يبدأ الترتيب من لحظة خروج الـ update من طابور Pyrogram، لا من لحظة إرسال Telegram له. ولا ترتيب بين updates أقفال مختلفة.
- التحليل الذي لا ينتهي يؤخر كل update خلفه، وfilter انتظار لا يعود يؤخر عرض الردود لكل المفاتيح حتى `stop`، بينما تستمر قراءة الـ updates وتشغيل الـ handlers.
- الانتظار خارج handler المفتاح (انتظار handler آخر) يرى update من طابور المفتاح عند عرضه التالي، أو عند دوره. والانتظار المفتوح من `ErrorHandler` متزامن أو `threading.Thread` عادي أو `run_in_executor` يكون خارج الحجز: فهذه لا تحمل context الـ handler.
- الطوابير بلا حد، ولا يُحذف شيء. والمفتاح الذي يتلقى أكثر مما يعالجه الـ handler يكبر فقط.
- التنسيق يعيش في هذه العملية، مثل الـ listeners: لا تنسيق بين sessions.


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
- بدونه يجيب أي مستخدم في المحادثة، وفي المحادثة الخاصة لا يجيب إلا المستخدم نفسه. ولا تخمّن pyroflow المستخدم أبدًا.
- `Message.ask_*` ترد على الرسالة، أو تعدّلها إن كانت رسالة الـ client نفسه (`editable`).

**المعاملات:**

| المعامل | الوصف |
|---|---|
| `chat_id` | في `Client` فقط: الـ chat المستهدفة |
| `text` | نص الرسالة (`rich_message` في دوال `_rich`) |
| `edit_message_id` | في `Client` فقط: إن أُعطي، تُعدَّل هذه الرسالة بدل إرسال رسالة جديدة |
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

و[`ask_until()`](#ask_until) تشغّل حلقة كهذه عنك بدالة `parse`.

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

لإنهاء سؤال من handler زر، مثل زر "رجوع" عليه، ألغِ انتظاره بمفتاحه، فترفع `ask` الخطأ `ListenerCancelled`: `client.get_listener(Message).cancel(MessageKey.from_sent(query.message, query.from_user.id))`، مع `listen_user_id` الذي أُعطي للسؤال، أو `None` إن لم يُعطَ.

> ⚠️ **انتظار لا ينتهي.** بلا `listen_strict`، يبقى الانتظار مفتوحًا حتى `listen_timeout`، أو إلى الأبد بلا `listen_timeout`، إذا رفض الفلتر كل update ما زال يمكن أن يطابق المفتاح:
> - الفلتر لا يمكن أن يقبل هذا النوع أصلًا، مثل `filters.photo` أثناء انتظار `CallbackQuery`.
> - المستخدم يرسل باستمرار ما يرفضه الفلتر.
>
> أعطِ هذا الانتظار مهلة (`listen_timeout` في `ask_*`، أو `timeout` في `listen` أو على الـ listener)، أو استعمل `listen_strict=True` (`strict=True` في `listen`) إن كان أول update مرفوض يجب أن ينهي الانتظار، أو أنهِه بنفسك بـ `listener.cancel(key)`. وانتبه: `listen_strict=True` ينهي الانتظار عند **أي** update مرفوض من نفس المفتاح، مثل صورة أثناء انتظار نص.


`ask_rich()` و`ask_callback_query_rich()` تفعلان الشيء نفسه مع rich message:

- ترسلان عبر `send_rich_message`.
- أو تعدّلان عبر `edit_message_text(rich_message=...)` إن أُعطي `edit_message_id`.

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

- حقل `ephemeral` في المفتاح ينتظر التحديثات المؤقتة، مثل `listen(MessageKey(ephemeral=True))`. هذا الانتظار وحده يستقبلها، ولا يصله تحديث عادي.
- `ask_*` على رسالة مؤقتة أو برسالة مؤقتة تنتظر بهذه الطريقة، على `listen_user_id` إن أُعطي.
- رسالتان مؤقتتان للمستخدم نفسه تشتركان في المفتاح، ففرّق بينهما بـ `listen_filters`.

---

ويمكن أيضًا إزالة الـ listeners أثناء التشغيل:

```python
await client.unregister_listener(Message)
```

---

### ask_until()

تكرر `ask_until()` استدعاء `ask()` حتى ترجع دالةٌ تمررها أنت قيمةً، ثم تعيد تلك القيمة. وتفعل `ask_rich_until()` و`ask_callback_query_until()` و`ask_callback_query_rich_until()` الشيء نفسه مع `ask_rich()` و`ask_callback_query()` و`ask_callback_query_rich()`. والأربع موجودة في `Client` وفي `Message`، فهي ثماني دوال، وتقبل كل منها ما تقبله الدالة التي تكررها، ومعه `parse` وهو إلزامي، و`attempts`.

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

تُستدعى `parse` بالشكل `parse(answer, kw)`، متزامنة أو async. و`answer` هو الـ update الذي وصل، و`kw` هو dict معاملات السؤال بأسمائها. وما تعيده `parse` يحدد ما يحدث بعدها:

| ما تعيده `parse` | ما يحدث |
|---|---|
| `AskAgain(question)` | مرفوض: يُطرح هذا السؤال بلا معاملات |
| `AskAgain(question, kw)` | مرفوض: يُطرح هذا السؤال بهذا `kw` |
| أي قيمة أخرى، و`None` منها | مقبول: تُرجَع هذه القيمة لك |

والسؤال `str`، أو `InputRichMessage` في دوال `*_rich_until`. ولإعادة السؤال نفسه أرجعه داخل `AskAgain`، ولإبقاء معاملاته مرّر `kw` التي وصلت إلى `parse`. وللحصول على الجواب نفسه استعمل `return answer`.

والجواب الذي يصل إلى `parse` قد أخذه الانتظار، فلا يصل إلى أي handler حتى لو رُفض، والأمر المرسل بدل الجواب يُعد جواباً. و`listen_filters` هو الفلتر الذي يسبق `parse`: ما لا يمر منه يمضي إلى الـ handlers ويستمر الانتظار، ولذلك فإن `~filters.command("cancel")` في المثال يترك `/cancel` يعمل. ومع `listen_strict=True`، الـ update الذي لا يمر منه يرفع `ListenerRejected` فوراً وينهي الحلقة.

والسؤال الأول وحده قد يعدّل رسالة، عبر `edit_message_id` في `Client` أو رسالة `editable` في `Message`، و`force_send` يخصه وحده. وبعد الرفض يكون كل سؤال رسالة جديدة، لأن Telegram يرفض تعديلاً لا يغيّر شيئاً. وكل إعادة ترسل `kw` الموجودة في `AskAgain` فقط، فضع فيها ما تحتاجه مثل `message_thread_id` في `Client` (أما `Message` فيرد في topic رسالته)، ويجب أن تقبلها دالة الإرسال: `link_preview_options` في دوال rich يرفع `TypeError`. وفي دوال الـ callback query ضع فيها `reply_markup`: يُرسل السؤال من جديد مع لوحته، وكل سؤال ينتظر ضغطة على أزراره هو.

ومع `attempts=None` وهو الافتراضي لا تتوقف. وإلا يُرفع `ListenerAttemptsExhausted` حين ترفض `parse` جواب آخر سؤال، ويحمل `update` فيه ذلك الجواب. أما `value` فهو عدد الأسئلة المطروحة. وقيمة `attempts` الأقل من 1 ترفع `ValueError` قبل إرسال أي شيء. و`listen_timeout` يسري على كل انتظار وحده، وأي خطأ آخر ترفعه `ask` أو `parse`، مثل `ListenerTimeout`، ينهي الحلقة فوراً.

---

## لوحات الأزرار

تبني `pyroflow.keyboards` لوحات الأزرار inline. وتقسم `arrange` قائمة مسطحة من الأزرار إلى صفوف بـ `columns` أو `layout`، وبدونهما زر في كل صف:

```python
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from pyroflow.keyboards import arrange

buttons = [InlineKeyboardButton(text, callback_data=text) for text in "abcde"]

keyboard = InlineKeyboardMarkup(arrange(buttons, columns=2))
keyboard = InlineKeyboardMarkup(arrange(buttons, layout=[1, 2]))
keyboard = InlineKeyboardMarkup(arrange(buttons, layout=[1, 2], repeat=True))
```

`columns` عرض ثابت. وبعد آخر حجم في `layout` يستمر هذا الحجم، ومع `repeat=True` يبدأ النمط من جديد. و`columns` مع `layout`، أو عرض غير موجب، يرفع `ValueError`.

و`CallbackData` تخطيط لـ `callback_data`: بادئة وحقول كلاس `CallbackFields`. نوع الحقل تلميح فقط في `pack` و`button` وفي ما تعيده `unpack`. ولقراءة الحقل بغير النص، اكتبه بـ `parsed` مع الدالة التي تحوّله، والحقل بلا دالة يبقى نصاً. تبني `pack` البيانات، وتبني `button` منها `InlineKeyboardButton`، وتعيد `unpack` الكلاس بحقوله مقروءة، وتعيد `unpack_dict` القيم نفسها في `dict`. وتُكتب خيارات `dataclass` في سطر الكلاس، مثل `class Product(CallbackFields, slots=True)`. ولتخطيط بلا كلاس، تبني `CallbackData.from_fields("product", namedtuple("Product", "id action"), slots=True)` التخطيط من `namedtuple` وخيارات `dataclass`، فتظهر الأسماء تلميحات وتبقى كل الحقول نصوصاً. وعضو `Enum` يُكتب بقيمته، و`sep` حرف واحد.

ويطابق `filter` الـ callback queries الخاصة بالتخطيط على الحقول التي تسميها، ويسمح بأي شيء آخر في البيانات. ويأخذ `filter_equal` كل الحقول كما يأخذها `pack`، ولا يمرر إلا بيانات تساوي ما يبنيه `pack`. ويأخذ `filter_rules` لكل حقل ما يأخذه `filters.split_text`: نص، أو حاوية خيارات، أو كلاس `Enum`، أو نمط مُصرَّف، أو دالة:

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

لا يوثق Telegram حداً لعدد الأزرار في الصف أو اللوحة، فلا يُفحص شيء من ذلك: اجعل اللوحات صغيرة. وحد `callback_data` هو 64 بايت. ترفع `CallbackData.pack` عند تجاوزه `ValueError`، وفي غيرها، كما في `page_data`، لا يفحصه شيء، فاجعل المعرّفات قصيرة.

### Pagination

`Pagination` هو الأساس للوحة تعرض صفحة من العناصر وشريطاً للتنقل بين الصفحات. و`NumberedPagination` و`ArrowPagination` و`SlidingPagination` أشرطته. و`build` دالة async: تعيد `Page` فيه `number` و`items` و`total_pages` و`has_next` واللوحة في `markup`. مع handler:

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

ومع `ask_callback_query`، استمر في تقليب الصفحات حتى يكون الضغط على عنصر. و`press.message` رسالة الـ client نفسه، فكل سؤال يعدّلها وينتظر الضغطة التالية على أزرارها:

```python
page = await pages.build()
press = await message.ask_callback_query("Pick a product:", reply_markup=page.markup)

while press.data.startswith("products:"):
    page = await pages.build(turn.unpack(press.data).page)
    press = await press.message.ask_callback_query("Pick a product:", reply_markup=page.markup)
```

تعيد `item` زراً من نوع `InlineKeyboardButton`، ويحدد `arrangement`، وهو `PageArrangement` من `pyroflow.models`، عدد عناصر الصفحة ويرتبها مثل `arrange`. وهذه كل الخيارات الصحيحة له، وأي تركيبة أخرى ترفع `ValueError`. وبدونه تكون الصفحة خمسة صفوف بزر واحد في كل صف:

| الخيارات | `per_page` | الصفوف |
|---|---|---|
| `lines`، `columns` | `lines * columns` | `lines` صفاً بعرض `columns` |
| `per_page`، `columns` | `per_page` | صفوف بعرض `columns`، والأخير قد يقصر |
| `layout` | مجموع `layout` | صف لكل حجم |
| `layout`، `per_page` | `per_page`، ولا يقل عن مجموع `layout` | يستمر آخر حجم |
| `layout`، `repeat`، `lines` | مجموع أول `lines` حجماً | `lines` صفاً والأحجام تتكرر |
| `layout`، `repeat`، `per_page` | `per_page` | الأحجام تتكرر |

```python
from pyroflow.models import PageArrangement

NumberedPagination(products, item=item, arrangement=PageArrangement(lines=4, columns=3))                   # 12 items in rows of 3
NumberedPagination(products, item=item, arrangement=PageArrangement(layout=[1, 2, 3]))                     # 6 items
NumberedPagination(products, item=item, arrangement=PageArrangement(lines=4, layout=[1, 2], repeat=True))  # 6 items: 1, 2, 1, 2
```

وزر الصفحة الحالية `disabled`، ولا تظهر صفحة مرتين. والصفحة الواحدة بلا شريط. وهذه الأشرطة للصفحة 6 من 12:

| الكلاس | الشريط | نصوصه |
|---|---|---|
| `NumberedPagination` | `« 1` `‹ 5` `· 6 ·` `7 ›` `12 »` | `first`، `previous`، `current`، `next`، `last` |
| `ArrowPagination` | `‹` `›` | `back`، `forward` |
| `ArrowPagination(texts=ArrowBarTexts(counter="{page}/{pages}"))` | `‹` `6/12` `›` | `back`، `counter`، `forward` |
| `SlidingPagination` | `1` `2` `3` `4` `5` `· 6 ·` `7` `8` | `page`، `current` |

يعرض `SlidingPagination` كل صفحة برقمها، و`size` هو أقصى عدد يظهر في المرة، و8 هو الافتراضي. والأرقام في مجموعات ثابتة، وعند الوصول إلى آخر رقم في مجموعة تظهر المجموعة التالية، مع بقاء الصفحة السابقة. ويوضع حجمه ونصوصه في `bar`، وهو `SlidingBar` من `pyroflow.models`.

وتوضع نصوص الشريطين الآخرين في `texts`، وهو `NumberedBarTexts` أو `ArrowBarTexts` من `pyroflow.models`. و`{page}` و`{pages}` يُملآن في أي منها. وبلا عدد معروف يظهر `{pages}` بقيمة `None`، فاستعمله مع العدد فقط. ويحمل `style`، وهو `BarStyle(nav, current)`، دوالاً يصلها كل زر في الشريط بعد إنشائه لتعدّله، ويلوّن `style` في الزر الذي تعيده `item` العنصر، ويحمل `header` صفوفاً ثابتة فوق العناصر، ويحمل `footer` صفوفاً ثابتة تحت الشريط. و`ButtonStyle.LINK` للرسائل rich فقط، ويرفضه Pyrogram على زر inline.

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

**الجلب الكسول.** يمكن أن تكون `items` دالة تُستدعى بالشكل `(offset, limit)`، متزامنة أو async، وتعيد دفعة واحدة، فكل `build` يجلب ما تحتاجه صفحته فقط. و`count` هو `ItemCount` من `pyroflow.models`، ويحمل رقماً، أو دالة بلا معاملات متزامنة أو async تُقرأ في كل `build`. ومع `strict`، وهو مفعّل افتراضياً، لا يُجلب ولا يُعرض عنصر بعده. ومع `strict=False` يحدد عدد الصفحات فقط، وتُجلب كل صفحة كاملة. ويُطبَّق على القوائم أيضاً. وبدون `count` تستعمل القائمة طولها، ويكون عدد الدالة مجهولاً.

```python
from pyroflow.models import ItemCount

async def fetch(offset, limit):
    return await db.products(offset=offset, limit=limit)

pages = NumberedPagination(fetch, item=item, count=ItemCount(db.count_products))
pages = ArrowPagination(fetch, item=item)
```

مع العدد، الصفحة خارج المدى تصير أقرب صفحة. وبدونه يجلب كل `build` عنصراً زيادة على الصفحة ليعرف هل تليها صفحة أخرى، وتكون `total_pages` هي `None`. والصفحة التي تعود فارغة، مثل التي بعد النهاية، تظهر مكانها الصفحة الأولى، ومع `first_if_empty=False` تبقى فارغة وفي شريطها طريق الرجوع. وتحتاج `NumberedPagination` و`SlidingPagination` إلى عدد الصفحات، فالدالة بلا `count` ترفع `TypeError`. أما `ArrowPagination` فتعمل في الحالتين، ويستخدم عدّادها حينها `unknown_counter`، وافتراضيه `{page}`.

**شريطك الخاص.** ورّث من `Pagination` واكتب `nav_row`، وتصلها الصفحة، وعدد الصفحات أو `None`، وهل تليها صفحة. وتبني `nav_button` زراً إلى صفحة:

```python
from pyroflow.keyboards import Pagination

class MorePagination(Pagination):
    def nav_row(self, number, total_pages, has_next):
        return [self.nav_button("More", number + 1, number, total_pages)] if has_next else []
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
