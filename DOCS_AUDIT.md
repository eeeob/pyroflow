# تقرير تدقيق التوثيق — 2026-11-12

فُحص: 38 ملف كود في `pyroflow/`، و66 ملفاً في `tests/`، و30 ملف توثيق وإعداد (README وCONTRIBUTING بلغتيهما، `CLAUDE.md`، `.claude/docs` والقرارات والقواعد، `pyproject.toml`، `Makefile`، الـ workflows)، و10 روابط.

الفحص الآلي:

| الفحص | النتيجة |
|---|---|
| `ruff --select DOC,D417` على `pyroflow` | 50 تنبيهاً، حُكم على كل منها أدناه |
| `pydoclint` | غير مثبت (تثبيته يسرّع الفحص البنيوي) |
| doctests | 55 نجحت |
| الروابط | 10 من 10 تعمل (200) |
| أمثلة README | كل كتل Python تُترجم وكل الـ imports تعمل، ومثالا `InlineQueryListener` و`CoordinatedDispatcher` نُفّذا فعلاً |

## ✅ حالة الإصلاح — 2026-11-12

أُصلح التوثيق والتعليقات والـ docstrings فقط، دون أي تغيير في سلوك الكود. بعد الإصلاح: `make lint` و`make typecheck` نجحا، و55 doctest نجحت، و1659 اختباراً نجحت مع 2 متخطاة. الـ 48 تنبيهاً الباقية من `ruff DOC` كلها من الأنواع المحكوم عليها أدناه بأنها لا تحتاج تغييراً.

| الحالة | البنود |
|---|---|
| ✅ أُصلح | D1–D31، C1 (تحذير في docstrings الطرق rich)، C5، S1، S2، S4، T1، T2، T3، Q1–Q16، Q18، Q21–Q24، Q26، Q27، Q30، A4 (السبب مكتوب من الكود نفسه) |
| ⏸️ يحتاج تغيير كود، فهو مهمة منفصلة | C3، C4، T4، Q20، Q25، Q28، Q29 |
| ⏸️ يحتاج قرارك | C2 (أُصلح منه فقط الادعاء الخاطئ عن تعليقات الإصدارات)، A1–A3، A5–A7 |
| ⏭️ لم يُغيَّر بعد التحقق | S3 (افتراض لم يُتحقق منه)، T5 (`pytrove.enums.TimeUnit` موجود، فالمثال صحيح)، T6 (دقيق الآن)، Q17 (التعليقان ليسا متعارضين: وسائط التعديل العادية يقبلها `send_message`، والـ rich لا يقبلها `send_rich_message`)، Q19 (التعليقان يقولان شيئين مختلفين) |
| ✳️ تصحيح للتقرير | T3: العنوان "with the rest of the library" ليس فارغاً، فتحته اختبارات، فبقي. |

---

**حكم تنبيهات ruff:** كل تنبيهات `docstring-extraneous-exception` غير حقيقية. الاستثناءات المذكورة يرفعها callee (`require_listener`، `UpdateListener.listen`، `pack`، `_check_update_type`...) وتصل فعلاً إلى المستدعي. تنبيهات `missing-returns` على `classproperty` والدوال الداخلية من سطر واحد لا تحتاج تغييراً. التنبيهات الحقيقية مغطاة في D4 وD9 أدناه.

---

## 🔴 توثيق خاطئ والكود هو الصحيح (يُصلح التوثيق)

### الكود العام

- [D1] `pyroflow/client/client.py:601-603` — يقول عن `ask_callback_query`: "from any user, so narrow it with `listen_filters`" — الكود (`client.py:642`، `models/listener_key.py:286`): `from_sent(sent, listen_user_id)` يضع المستخدم في المفتاح — الإصلاح: "from `listen_user_id`, or from any user without it".
- [D2] `pyroflow/client/client.py:314-315` — "`mode`: The second argument of `ask`" — الكود (`:351`): `ask(*target, question, mode)`، فهو الثالث مع `Client` (بعد `chat_id`) — الإصلاح: "The positional argument after `question`".
- [D3] `pyroflow/models/ask_again.py:23-24` — "`kw`: The arguments of the next question; empty sends it with none" — الكود (`client.py:351, 360`): `kw` يحل محل السابقة فقط، ومعاملات `listen_*` تبقى — الإصلاح: "The keyword arguments of the next question, in place of the previous ones; the `listen_*` arguments stay."
- [D4] `pyroflow/client/client.py:129-145, 175-180, 220-225` — `Raises` في `listen` و`listen_message` و`listen_callback_query` يغفل `ListenerWorkersBusy`، و`listen` يغفل `TypeError` — الكود: `update_listener.py:539-540` و`:487-492` — الإصلاح: إضافة البندين.
- [D5] `pyroflow/client/client.py:428` و`pyroflow/types/message.py:127` — `listen_timeout` و`listen_filters` لا يذكران الرجوع إلى إعدادات الـ listener، و"or forever without one" (`client.py:606`، `message.py:301`) غير دقيقة — الكود (`update_listener.py:521-522, 567-568`): `None` يأخذ `timeout` و`strict_filter` الخاصين بالـ listener — الإصلاح: "`None` falls back to the listener's `timeout` / `strict_filter`".
- [D6] `pyroflow/client/client.py:272-274` — `Returns` في `context_with_message` تغفل حالة `context is None` — الكود (`:279-280`): يرجع `ListenerContext(message=sent)` جديداً — الإصلاح: إضافة الحالة.
- [D7] `pyroflow/update_listener/update_listener.py:81-87` — "Errors raised before a wait starts, `ListenerAlreadyExists` and `ListenerWorkersBusy`, are not reported" — الكود (`:509-510`): `ListenerCancelled` لـ listener مغلق يُرفع قبل الـ `try` أيضاً ولا يصل `on_error_func` — الإصلاح: إضافته إلى القائمة.
- [D8] `pyroflow/update_listener/update_listener.py:406-408` — "The listener is registered before this coroutine first yields" — الكود (`:506-507`): تحت `CoordinatedDispatcher` يسبق التسجيلَ `await hold.wait_offer_lock(...)` — الإصلاح: "…; under a `CoordinatedDispatcher` it may first wait for an offer under way."
- [D9] `pyroflow/update_listener/update_listener.py:633-634` — `resolve` يذكر `TypeError` لنوع update خاطئ فقط — الكود (`:642`، `:735-740`): يُرفع أيضاً حين يرجع `extract_key_func` غير `__key_type__` — الإصلاح: كما في docstring `extract_key` (`:720-723`).
- [D10] `pyroflow/dispatcher/coordinated_dispatcher/coordinated_dispatcher.py:123-124` — "a client that has started keeps reading the dispatcher it started with" — kurigram (`.venv/.../pyrogram/client.py:973-1014`): يقرأ `self.dispatcher.enqueue` مع كل update، والـ dispatcher غير المبدوء يُسقط ما يصله (`pyrogram/dispatcher.py:430-431`) — الإصلاح: "Replace it only before `start`: on a started client the new dispatcher is never started, so it drops every update, and the old workers are never stopped."
- [D11] `pyroflow/__init__.py:1` — "the `ask_*` methods and listeners" — الكود (`:12-15`) يصدّر أيضاً الـ dispatcher والفلاتر ولوحات الأزرار — الإصلاح: "…the `ask_*` methods, listeners, the `CoordinatedDispatcher`, text filters and inline keyboards."
- [D12] `pyroflow/models/__init__.py:1` — لا يذكر `ask_again` و`pagination_options` المصدَّرين (`:3, 7`) — الإصلاح: "…its context and its model, `AskAgain` of the `ask_*_until` methods, and the page and options of a `Pagination`."
- [D13] `pyroflow/utils/__init__.py:1` — "and ask error dispatch" — الكود: لا شيء كهذا في `helpers.__all__` (`helpers.py:162-166`) — الإصلاح: "…update binding and `call_maybe_async`."
- [D14] `pyroflow/keyboards/layout.py:31-33` — `Raises` لا تذكر `layout` الفارغ — الكود (`:43-47`): `not layout` يرفع `ValueError` — الإصلاح: "…, `layout` is empty, or a width is not positive".

### ملفات التوثيق والإعداد

- [D15] `README.md:135` و`README.ar.md:135` — "before any handler, `register_listener` or `setup_pyroflow`: what was registered earlier stays on the old dispatcher" — الكود (`client.py:91-92`): `setup_pyroflow` يضبط قيماً على الـ client لا على الـ dispatcher — الإصلاح: حذف `setup_pyroflow` من الجملة.
- [D16] `README.md:221` و`README.ar.md:221` — "The only prerequisite is uv"، والقسم نفسه يستعمل `make` — `CONTRIBUTING.md:18`: "`uv` and `make` are the only prerequisites" — الإصلاح: "`uv` and `make`".
- [D17] `CLAUDE.md:12`، `.claude/docs/overview.md:24`، `.claude/docs/commands.md:31`، `.claude/rules/tests.md:24` — "1637 اختباراً" — الفعلي: `1661 tests collected` — الإصلاح: 1661 (وانظر Q11).
- [D18] `.claude/docs/commands.md:39` و`.claude/docs/conventions.md:26` — "`.venv` على 3.13" — الفعلي: 3.12.10، و`CLAUDE.md:37` يقول 3.12 — الإصلاح: 3.12.
- [D19] `CONTRIBUTING.md:23, 77` و`CONTRIBUTING.ar.md:23, 77` — "with every extra" — الفعلي: لا `optional-dependencies` في `pyproject.toml`، و`make sync` هو `uv sync` — الإصلاح: حذف العبارة.
- [D20] `CONTRIBUTING.md:84` و`CONTRIBUTING.ar.md:84` — "the test recipes on every supported Python" — الفعلي (`tests.yml:27, 54, 109, 122`): matrix لـ `test` و`test-minimal` فقط — الإصلاح: "`make test` and `make test-minimal` on every supported Python; `test-floor` and `test-ceil` on the floor and the ceiling".
- [D21] `Makefile:50` — "no docstring has an example yet" — الفعلي: 55 doctest — الإصلاح: "kept so the recipe passes if every example is removed".
- [D22] `Makefile:41` — "Skipped until the directory exists" — الفعلي: `tests/typing/` موجود — الإصلاح: "Skipped if the directory is absent".
- [D23] `.github/workflows/tests.yml:7` — "Every job installs from uv.lock" — الفعلي: `test-minimal` و`test-floor` و`test-ceil` تبني من `pyproject.toml` (`Makefile:10-11`) — الإصلاح: "The `test`, `lint` and `typecheck` jobs install from uv.lock…".
- [D24] `.claude/docs/decisions/0002-kurigram-fork-as-runtime-dependency.md:21` — "ويذكر `README.md` Kurigram بلا إصدار" — الفعلي: `README.md:17` يذكر `kurigram>=2.2.27` — الإصلاح: حذف العبارة.
- [D25] `.claude/docs/architecture.md:47` و`.claude/docs/glossary.md:9` — "`_shape_order` يرتبها" — الكود (`update_listener.py:186-212`): `_shapes` و`_shape_order` attributes، والترتيب في `_order_shapes`، والشكل من `_shape_of` — الإصلاح: "`_shape_of` يحسب الشكل، و`_order_shapes` يرتب `_shapes` في `_shape_order`".

### تعليقات الاختبارات

- [D26] `tests/conftest.py:3-6` — قائمة الكلاسات المعدّلة تغفل `User` (`pyroflow/types/user.py:16`) — الإصلاح: إضافته.
- [D27] `tests/test_filters.py:3-6` — "rather than by reaching into the module's private helpers" — الملف يستدعي `_normalize_rule` (`:253`) و`_COMMAND_RE` (`:440`) و`_BotCommands` (`:604`) — الإصلاح: قصر الجملة على فلاتر النص.
- [D28] `tests/dispatcher/coordinated_dispatcher/test_coordinated_dispatcher.py:2223` — "as `_read_updates` does" — الوضع في الـ lane يقع في `_parse_and_place` (`coordinated_dispatcher.py:395`) — الإصلاح: "as `_parse_and_place` does".
- [D29] نفس الملف `:2414, 2421` — "whose reader can run alone" و"Have the reader place `update`" — الـ workers هي التي تحلل وتضع — الإصلاح: "Parse and place `update` as a worker would".
- [D30] نفس الملف `:2013` — "the holds `offers` has" — لا attribute بهذا الاسم؛ الطابور `offer_pass_requests` (`coordinated_dispatcher.py:189`) — الإصلاح: "the holds in `offer_pass_requests`".
- [D31] `tests/dispatcher/coordinated_dispatcher/test_models.py:1` — "the data the sequencer moves around" — لا sequencer في الحزمة — الإصلاح: "the data `CoordinatedDispatcher` moves around".

---

## 🟠 تعارض غير محسوم (قد يكون الكود هو الخطأ)

- [C1] `pyroflow/client/client.py:797` (و`ask_rich_until`/`ask_callback_query_rich_until` بالإحالة) — التوثيق ينصح بإعادة نفس `kw` في `AskAgain`. لكن `kw` السؤال الأول في الطرق rich قد يحمل `link_preview_options` (`_internal/client_ask_params.py:125-135`). إعادة السؤال ترسله إلى `send_rich_message` أو `reply_rich`، ولا يقبله أي منهما في kurigram 2.2.27، فيُرفع `TypeError`. والتعليقان فوق الـ overloads (`client.py:755, 868`) يعلّلان القرار بطريقتين متعاكستين. الـ README القديم كان يحذّر من هذا، وحذفته إعادة الكتابة. الحل إما تحذير في الـ docstring، أو تضييق النوع في الكود.
- [C2] `pyroflow/_internal/client_ask_params.py:1-8` — "with every argument any supported kurigram accepts". لكن `AskEditKw` و`AskRichEditKw` يغفلان `business_connection_id`، و`AskSendKw` و`AskRichSendKw` يغفلان `repeat_period`، وكلاهما موجود في kurigram 2.2.27. هل هو نقص، أم استثناء مقصود يجب ذكره كما ذُكر `schedule_date`؟
- [C3] `pyroflow/dispatcher/dispatcher.py:75, 95-97` — "registration is refused while it is [running]". لكن `is_started` لا يصبح `True` إلا بعد عودة `oldstart`، الذي يشغّل handlers الفجوات (`recover_gaps`). handler يعمل في تلك النافذة يستطيع `register_listener`، فلا يُرفض الـ listener ولا يبدأ.
- [C4] `tests/utils/test_bot_commands.py:60-62` — الـ `skip` يحرس `BusinessMessageHandler`. لكن `pyroflow/utils/bot_commands.py:23` يستورده بلا حراسة، فلن يُطلق الـ skip أبداً. الحل إما حذف الحراسة، أو حراسة الحزمة نفسها.
- [C5] `CLAUDE.md:67` يطلب الاختبارات كاملة قبل إنهاء أي مهمة. بينما القرار `0006-scoped-checks-after-each-change.md:26, 39-44` و`.claude/rules/tests.md:8` تقصرها على الفحص المحدود. والقرار نفسه (`:62`) يدّعي أنه عدّل هذا السطر، ولم يتغير.

---

## 🟡 مصادر وروابط

- [S1] `pyproject.toml:2` — "hatchling 1.27 is the first release with PEP 639 support" — سجل hatchling: الدعم بدأ في 1.26.0، و1.27.0 أول إصدار يجعل core metadata 2.4 افتراضياً. الحد صحيح والصياغة لا — الإصلاح: "the first to emit core metadata 2.4 (PEP 639) by default".
- [S2] `pyroflow/keyboards/__init__.py:3-4` — "Telegram documents no limit on buttons…" صحيح، لكن kurigram يعرّف `REPLY_MARKUP_TOO_LONG` (`errors/exceptions/bad_request_400.py:3567`) — اقتراح: "though Telegram rejects an oversized markup with `REPLY_MARKUP_TOO_LONG`".
- [S3] `pyroflow/client/client.py:446` و`pyroflow/types/message.py:150` — "What `ask_*` accepts always gets a message back" افتراض. `send_message` في kurigram مُعلن `-> Message | None` (`send_message.py:89`). لم يُتحقق متى يرجع `None` فعلاً.
- [S4] `pyroflow/client/bot_commands_mixin.py:39-47` — "after connecting (so `plugins` handlers are included)" — النتيجة صحيحة، لكن الـ plugins تُحمَّل **قبل** الاتصال (`pyrogram/methods/utilities/start.py:85, 87`)، فالتعليل غير دقيق.
- الروابط العشرة كلها تعمل، والروابط الداخلية كلها تصل إلى ملفات موجودة.

---

## ⚠️ أمان في التوثيق

لا شيء. كل القيم في الأمثلة والاختبارات وهمية (`api_id=1, api_hash="x"`). البريد الوحيد في `pyproject.toml` هو بريد المؤلف.

---

## ⚪ ملاحظات قديمة

- [T1] `tests/test_compat_static.py:62, 72` — "regression guard for C1" و"see audit finding C1" تشيران إلى تدقيق قديم لا أثر له في المستودع — الإصلاح: كتابة السبب نصاً ("`StrEnum` is 3.11+").
- [T2] `tests/test_compat_static.py:8` — "while the suite itself runs on 3.14" — المحلي 3.12 والـ CI من 3.10 إلى 3.14 — الإصلاح: "on a newer interpreter".
- [T3] `tests/dispatcher/coordinated_dispatcher/test_coordinated_dispatcher.py:226, 229, 855, 858, 1026` — عناوين أقسام فارغة بلا اختبارات تحتها، ومنها "extract_key" الذي لا يوجد في الحزمة — الإصلاح: حذفها.
- [T4] `tests/client/test_client.py:17, 78-79` — `_cmd` واستيراد `BotCommand` غير مستعملين.
- [T5] `.claude/docs/conventions.md:15` — مثال `from pytrove.enums import TimeUnit` لا يستعمله أي module.
- [T6] `.claude/docs/gotchas.md:8-9` — يصف إصدارات مثبتة على هذا الجهاز (kurigram 2.2.26، pyroflow 0.2.1). صحيح الآن لكنه سيتقادم.
- القراران `0003` و`0005` يشيران إلى ملفات محذوفة، لكنهما معلّمان superseded، فهما تاريخيان ولا يحتاجان تغييراً.

---

## 🔵 تحسين الجودة

### README (كُتب اليوم)
- [Q1] `README.md:11` و`README.ar.md:11` — code fence بلا لغة ← "```bash".
- [Q2] `README.md:189` و`README.ar.md:189` — قائمة الفلاتر تغفل `split_text` (في `pyroflow.filters.__all__`) ← إضافته.
- [Q3] `README.md:215` و`README.ar.md:215` — قائمة الأخطاء تغفل `ListenerError` (الأب المشترك) و`ListenerAlreadyExists` ← إضافتهما.

### توضيح ودقة الصياغة
- [Q4] `pyroflow/update_listener/update_listener.py:77-80` — كلمة `None` بمعنيين في جملتين متجاورتين ← "a returned `None` skips the update; passing `None` uses `from_update` of `__key_type__`".
- [Q5] `pyroflow/update_listener/update_listener.py:437-438` و`pyroflow/enums.py:52` — سمِّ `ListenerReplaced` صراحة بدل "cancel"/"a newer listener replaces it".
- [Q6] `pyroflow/models/listener_model.py:69` — "The slot the listener is registered under"، و"slot" تعني في مكان آخر مقعد الـ worker ← "The key the listener is registered under".
- [Q7] `pyroflow/models/listener_model.py:85` — "mostly those that failed `filters`" ← "those that failed `filters`, and what earlier waits of the same coordinated handler declined".
- [Q8] `pyroflow/models/listener_key.py:146-148` — `Returns` يذكر الرسائل المعدّلة ويغفل `edit_hidden` المستبعدة في `:161-162` ← إضافتها.
- [Q9] `pyroflow/update_listener/update_listener.py:503-505` — "once the handler ended there is nothing to wait for" توحي بأن الانتظار لا يبدأ ← "no offer to wait for; the wait goes on as a plain one".
- [Q10] `pyroflow/dispatcher/coordinated_dispatcher/coordinated_dispatcher.py:330` — "Nothing below suspends" فوق `await` يعلّق ← "After this await nothing suspends, …"؛ و`:465` "outside any lock" بينما كل offer يمسك `offer_lock` ← "in a task of their own"؛ و`:139-140` "no worker is needed for a reply" ← "to offer a reply".
- [Q11] عدد الاختبارات منسوخ في 4 ملفات وانحرف (D17)، والقاعدة 6.6 في CONTRIBUTING تمنع ذلك ← إبقاؤه في `.claude/docs/commands.md` وحده والإحالة إليه.
- [Q12] `pyroflow/dispatcher/coordinated_dispatcher/models.py:48-49, 56-58, 63-64, 148-149` — أوصاف `offered_at_generation` و`last_wait_generation` و`handler_task` لا تطابق ما يخزّنه الكود (`coordinated_dispatcher.py:309, 333, 499`) ← "The hold's `last_wait_generation` when it was last offered; `-1` if never."، و"`None` while no handler runs."
- [Q13] `pyroflow/keyboards/pagination.py:39-44` — `items` و`count` الـ sync تعمل في thread (`call_maybe_async`)، وهذا غير مذكور ← "sync (run in a thread) or async".
- [Q14] `pyroflow/utils/helpers.py:131-132` — "as Pyrogram's `Handler.check` does" تناقض السطر التالي؛ `Handler.check` يفحص `filters.__call__` ← حذف المقارنة.
- [Q15] `pyroflow/utils/bot_commands.py:1` — "Internal bot command helpers" بينما `mark_bot_commands` عامة ← "Bot command helpers: the public `mark_bot_commands` decorator and the internal entry expansion."

### اختصار وتكرار
- [Q16] `pyroflow/dispatcher/coordinated_dispatcher/coordinated_dispatcher.py:355-364` — Warning في method خاصة يكرر Warning الكلاس (`:144-153`) ← "See the class warning on `workers_policy`."
- [Q17] `pyroflow/client/client.py:755, 962` و`:868, 1058` و`pyroflow/types/message.py:553, 730` — تعليقا overload بتعليلين متعاكسين لنفس القرار ← تعليق واحد موحد بعد حسم C1.
- [Q18] `pyroflow/client/client.py:824, 1014` و`message.py:513, 690` — `**kw` بلا "for the first question"، بينما نظائرها rich تذكرها والسلوك واحد ← توحيد الصياغة.
- [Q19] `tests/test_filters.py:110-111` — تعليقان بنفس المعنى ← إبقاء الأول.
- [Q20] `tests/models/test_listener_key.py:278-283` — `CALLBACK_MARKUP` مكرر من `tests/conftest.py:27` ← استيراده.

### اتساق وضجيج
- [Q21] `pyroflow/client/client.py:48` — "per-update-type systems" ← "one listener per update type".
- [Q22] `pyroflow/client/bot_commands_mixin.py:188-202` — `stop` بلا `Returns` ← "Returns: The stopped client, as `pyrogram.Client.stop` returns it."
- [Q23] `pyroflow/dispatcher/dispatcher.py:29` — `log` بلا docstring تحته خلافاً للقاعدة 6.4 ← "Logger for listener and handler errors."
- [Q24] `pyroflow/dispatcher/dispatcher.py:104-105` — "blocked in `ask_*` method" ← "blocked in an `ask_*` method".
- [Q25] `pyroflow/keyboards/pagination.py:15, 29` — `ItemCount` مستورد مرتين ← حذف `:29`.
- [Q26] `pyroflow/dispatcher/coordinated_dispatcher/coordinated_dispatcher.py:139, 196, 264, 353` — "offer pass task" و"the offer task" و"the offers" لمهمة واحدة ← توحيدها على "offer pass task".
- [Q27] `pyroflow/dispatcher/coordinated_dispatcher/coordinated_dispatcher.py:477` — `_HANDLER_HOLD.set(None)` بلا التعليق الموجود عند نظيره `:291` ← نسخه.
- [Q28] `tests/test_enums.py:38` و`tests/keyboards/test_pagination.py:267` — اسما اختبارين يستعملان أسماء محذوفة (`workers_busy_mode`، `ikb`) ← `test_workers_policy_values` و`test_build_arranges_the_items_like_arrange`.
- [Q29] `tests/dispatcher/coordinated_dispatcher/test_coordinated_dispatcher.py:2234` — فرع `if lane is None:` ميت لأن `lane` أُنشئت قبله مباشرة.
- [Q30] `.claude/skills/sync-kurigram/SKILL.md:108` — code fence بلا لغة ← "```text".

---

## ❓ أسئلة لك

- [A1] `pyroflow/client/client.py:351` — `listen_kw | kw` تجعل أي `listen_*` داخل `kw` (ومنها `AskAgain.kw`) يطغى على المعاملات الممررة. هل هذا مقصود، كتغيير `listen_timeout` بين محاولة وأخرى؟ لا اختبار ولا docstring يذكره.
- [A2] لماذا استُثني `repeat_period` و`business_connection_id` من `Ask*Kw` (انظر C2)؟
- [A3] `pyroflow/client/client.py:183, 228` — `listen_message` و`listen_callback_query` يبنيان المفتاح بحقول `MessageKey` و`CallbackQueryKey` فقط. إن سجّل المستخدم listener بمفتاح فرعي بحقول إضافية فتُتجاهل بصمت. هل هذا مقصود؟
- [A4] `tests/dispatcher/coordinated_dispatcher/test_coordinated_dispatcher.py:978` — "as in gotcha 12" يحيل إلى `.claude/` الخارج عن git. هل يُستبدل بجملة السبب نفسها؟
- [A5] القاعدة 1.5 في CONTRIBUTING و`.claude/rules/library.md:14` تذكر `_internal.py` لكل قسم، ولا يوجد أي ملف بهذا الاسم، والاسم يلتبس مع الحزمة `pyroflow/_internal/`. هل تبقى القاعدة كما هي، أم تصبح "a private module in the section's package"؟
- [A6] `CLAUDE.md:68` يحيل إلى `/project-bootstrap:update-docs` و`/project-bootstrap:record-decision`، وهما غير ظاهرتين في هذه الجلسة. هل ما زالتا موجودتين؟
- [A7] `pyroflow/dispatcher/coordinated_dispatcher/coordinated_dispatcher.py:66` — "a slow parse holds back little": هل المقصود "at most `workers` reads"؟

---

## لم يُتحقق منه

- سلوك خوادم Telegram نفسها: `MESSAGE_NOT_MODIFIED`، وتكرار ids الرسائل ephemeral، وحدود الأزرار.
- `pyproject.toml:49` "Every name used is in pytrove 1.1.0" (الإصدار 1.1.0 غير مثبت).
- `Ask*Kw` مقابل كل إصدارات kurigram المدعومة، فالمفحوص 2.2.27 وحده.
- `ty check` بلا مسار يعرض "مئات التنبيهات" (`CLAUDE.md:16`)، لم يُشغَّل.
- نسخ `.claude/worktrees/` القديمة، لم تُفحص.
