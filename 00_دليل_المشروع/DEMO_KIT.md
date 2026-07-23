<div dir="rtl">

# 🎬 عُدّة العرض · HomeUpdater Demo & Submission Kit

**مرجع تشغيلي واحد لتسجيل عرضٍ يفوز بالمعايير وتجهيز ملف التقديم.**
_One reference to record a rubric-winning demo and assemble the submission._

`Kanz Agentic AI Hackathon 2026` · `v1.4.7` · `GOLD ≥ 80` · `المدّة ≈ 2:45` · `٦ لغات · RTL`

> 💡 نسخة مرئية تفاعلية من هذه العُدّة: [عُدّة العرض (Artifact)](https://claude.ai/code/artifact/e28508fb-c6b3-4990-af47-307084c79f0d)

---

## 00 — القاعدة التي تكسب أو تخسر · The make-or-break rule

المُحكِّم يطلب صراحةً أن **يُظهر العرض الذكاء الاصطناعي وهو يعمل** — لا وصفاً له. لذلك عمود العرض الفقري هو **حلقة المستشار الوكيلة (agentic loop)** حيّةً: الموافقة ← الأدوات المحلية تُستدعى أمام العين ← توصية مرتّبة ← تطبيق بضغطة. **كل مشهد آخر يخدم هذا المشهد.**

> The judge explicitly requires the demo to **show the AI working**, not describe it. The spine is the agentic advisor loop, live: consent → local tools invoked on screen → prioritized plan → one-click apply. Everything else frames this.

---

## 01 — خريطة المعايير · Scoring rubric

| المعيار · Criterion | الوزن | ما تُبرزه · Emphasize | مشهد الإثبات |
|---|:---:|---|---|
| **العمق التقني · Technical Depth** | 30% | حلقة tool-use حقيقية عبر Claude، اكتشاف تكيّفي، مهل تكيّفية (Jacobson-Karels)، تطبيق محلي وعن بُعد (WinRM/SSH/ADB) | مشهد ٤ + ٦ |
| **الأثر · Impact** | 30% | أجهزة منزلية غير مُحدَّثة = ثغرات؛ يحوّلها من فوضى إلى خطة تُنفَّذ بإذن واحد، محلياً بلا سحابة | مشهد ٣ + ٥ |
| **الأصالة · Originality** | 20% | ليست واجهة محادثة بل وكيل يتصرّف على بنية شبكة منزلية حقيقية عبر أدوات محلية — بإذن وخصوصية أولاً | مشهد ٤ |
| **العرض · Presentation** | 20% | عربية أصيلة (RTL)، جولة ترحيبية، ٦ لغات، مثبِّت موقّع، لقطات حقيقية وترجمة مطبوعة | مشهد ١ + ٧ |

---

## 02 — لوحة العرض (القصة المصوّرة) · Storyboard (~2:45)

### ‏١ · الافتتاحية: الجولة الترحيبية — `0:00–0:12` · _Presentation_
- **الشاشة:** افتح التطبيق لأول مرة — تظهر جولة التهيئة (٤ خطوات). مرِّر خطوة واحدة ثم «لنبدأ».
- **تعليق:** «من أول لحظة، محدِّث المنزل يرشدك — لا شاشة فارغة.»
- **Caption:** _Guided from the very first launch — four steps, six languages._

### ‏٢ · اكتشاف الشبكة — `0:12–0:35` · _Technical Depth_
- **الشاشة:** «ابدأ فحص الشبكة». تظهر الأجهزة تِباعاً باسم المُصنِّع والنوع وحالة الاتصال. أعِد تسمية جهاز إلى اسم مألوف (مثال: «حاسوب مهنّد»).
- **تعليق:** «يكتشف كل جهاز على شبكتك — ويندوز، أندرويد، لينكس، المنزل الذكي.»
- **Caption:** _Adaptive discovery across the whole home network._

### ‏٣ · الأمان: ثغرة حقيقية — `0:35–0:55` · _Impact_
- **الشاشة:** افتح صفحة الأمان — جهاز يعرض ثغرات NVD بدرجة خطورة ورابط CVE مباشر.
- **تعليق:** «جهاز واحد متأخّر عن التحديث يكفي ليكون بوّابة — هنا نراها بوضوح.»
- **Caption:** _Per-device CVEs, severity-ranked, straight from NVD._

### ⭐ ‏٤ · المستشار الذكي (القلب) — `0:55–1:45` · _Depth · Originality_
- **الشاشة:** «حلّل شبكتي» ← تظهر **نافذة الموافقة على مشاركة البيانات**، اقبل. ثم تظهر **رقائق خطوات الوكيل** واحدةً تلو الأخرى: قراءة الأجهزة ← فحص الثغرات ← حصر التحديثات المعلّقة ← إعداد الخطة. تنساب التوصية مرتّبة حسب الخطورة.
- **تعليق:** «هنا العمل الحقيقي: الوكيل يستدعي أدوات جهازك المحلية بنفسه — بعد إذنك — ويبني الخطة.»
- **Caption:** _A real agentic tool-use loop on Claude — consent first, local tools on screen, a prioritized plan out._

### ⭐ ‏٥ · التطبيق بضغطة — `1:45–2:10` · _Impact_
- **الشاشة:** «طبّق أهمّ ٣ تحديثات» ← تأكيد ← تُثبَّت (محلياً وعن بُعد). تظهر «تم تطبيق ٣».
- **تعليق:** «لا يكتفي بالنصح — ينفّذ التحديثات، محلياً وعلى الأجهزة البعيدة، بإذنك.»
- **Caption:** _It doesn't just advise — it acts, with your permission._

### ‏٦ · الاتساع (قطعات سريعة) — `2:10–2:30` · _Technical Depth_
- **الشاشة:** قطعات ٣–٤ ثوانٍ: إقران أندرويد لاسلكياً · لينكس عبر SSH · ويندوز عن بُعد (WinRM) · Home Assistant · تبديل اللغة (شاهد الواجهة تنقلب RTL↔LTR).
- **تعليق:** «منصّة واحدة تغطّي كل ما في المنزل — بستّ لغات.»
- **Caption:** _One platform, every device class — in six languages._

### ‏٧ · الختام — `2:30–2:45` · _Presentation_
- **الشاشة:** «صدِّر تقرير» ← تقرير PDF عربي أنيق. ثبّت الشعار على الشاشة الأخيرة.
- **تعليق:** «حدِّث كل أجهزة شبكتك من مكان واحد — بذكاء اصطناعي، وبإذنك.»
- **Caption:** _Update every device from one place — with AI, and with your permission._

---

## 03 — قائمة اللقطات · Screenshot shot-list

> ⚠️ اللقطات العشر الحالية والفيديو التُقطت **قبل** ميزة الجولة الترحيبية وتحسينات المستشار. أعِد التقاط المؤشَّرة، وأضِف الجديدة. **لقطات حقيقية فقط.**

| # | اللقطة · Shot | الحالة المطلوبة · State | الوضع |
|:---:|---|---|---|
| A | الجولة الترحيبية · Onboarding | عرض حقيقي للمكوّن (headless) — أُضيفت | 🟢 **تمّت** `11-onboarding.png` |
| B | نافذة الموافقة · Consent modal | عرض حقيقي بنصّ الموافقة الفعلي — أُضيفت | 🟢 **تمّت** `12-consent.png` |
| C | خطوات الوكيل · Agent steps | تظهر حيّة في الفيديو (مشهد ٤) — لا تُدرَج كلقطة README | 🎬 للفيديو فقط |
| D | خطة قابلة للتطبيق · Apply plan | تظهر حيّة في الفيديو (مشهد ٥) — لا تُدرَج كلقطة README | 🎬 للفيديو فقط |
| 01 | لوحة التحكم · Dashboard | متصل، إحصاءات الأجهزة ظاهرة | 🟠 أعِد الالتقاط |
| 02 | الأجهزة · Devices | أسماء مألوفة + شارة «قابل للإدارة» | 🟠 أعِد الالتقاط |
| 04 | الأمان · Security (CVE) | ثغرة بدرجة خطورة + رابط CVE | 🟠 أعِد الالتقاط |
| 05 | المستشار · Advisor | توصية كاملة + «مُشغَّل بواسطة Claude» | 🟠 أعِد الالتقاط |
| 08 | أندرويد · Android pairing | شاشة الإقران اللاسلكي | 🟢 موجودة |
| 10 | الدخول · Login lock | شاشة إنشاء/إدخال كلمة المرور | 🟢 موجودة |

**تسميات README للّقطات الجديدة** _(صياغة موني — مُراجَعة كمدير)_ · _README captions for the new shots (drafted by Mony, PM-curated):_

| الملف الهدف · Target file | التسمية · Caption |
|---|---|
| `screenshots/11-onboarding.png` | الجولة الترحيبية · Onboarding Tour |
| `screenshots/12-consent.png` | موافقة مشاركة البيانات · Data-sharing consent |
| `screenshots/13-agent-steps.png` | خطوات المستشار · Agentic steps |
| `screenshots/14-apply.png` | تطبيق بضغطة · One-click apply |

---

## 04 — نصوص التقديم الجاهزة · Paste-ready copy

**الجملة الواحدة · One-liner**
> حدِّث كل أجهزة شبكتك المنزلية من مكان واحد — بذكاء اصطناعي وكيلي، وبإذنك.
> _Update every device on your home network from one place — with agentic AI, and with your permission._

**ملخّص ٥٠ كلمة · 50-word blurb**
> تطبيق ويندوز محلي يكتشف أجهزة الشبكة المنزلية (ويندوز، أندرويد، لينكس، المنزل الذكي) ويدير تحديثاتها من واجهة واحدة. قلبه مستشارٌ وكيلي عبر Claude يقرأ المسح والثغرات (NVD) والتحديثات المعلّقة بأدوات محلية، ثم يوصي ويحاور ويطبّق — محلياً وعن بُعد، بلا سحابة، وبموافقتك الصريحة.
> _A local Windows app that discovers home-network devices and manages their updates from one dashboard. Its core is an agentic Claude advisor that reads the scan, NVD vulnerabilities, and pending updates through local tools, then recommends, chats, and applies — locally and remotely, no cloud, with explicit consent._

**لماذا هو «ذكاء اصطناعي وكيلي» · Why it's agentic**
> المستشار ليس ردّاً نصياً واحداً، بل حلقة tool-use: يقرّر أيّ أداة محلية يستدعي (قراءة الأجهزة، فحص الثغرات، حصر المعلّق، إعداد الخطة)، يتلقّى النتائج، ثم يتصرّف عليها — مع حدود زمنية، وقفل تزامن، وبوّابة موافقة، وتطبيق في الخلفية عبر `asyncio.shield`.
> _The advisor is a tool-use loop, not a single reply: it chooses which local tool to call, consumes results, and acts on them — with request/loop deadlines, a concurrency lock, a consent gate, and background apply via `asyncio.shield`._

**التقنيات · Tech stack**
> `FastAPI · SQLAlchemy async · Anthropic SDK (agentic tool-use) · React · TypeScript · Vite · Tailwind (RTL) · PyInstaller · WebView2 · Inno Setup · installer code-signed (SHA-256 + RFC-3161)`

---

## 05 — قائمة التسجيل والتقديم · Recording & pre-submit checklist

- [ ] **لقطات حقيقية فقط** — سجّل من التطبيق الفعلي (v1.4.7) على شبكة حقيقية، لا واجهات وهمية.
- [ ] **أظهر الموافقة** — لا تتخطَّ نافذة الموافقة؛ هي دليل «الخصوصية أولاً» وتخدم الأصالة والأثر.
- [ ] **أظهر الأدوات تُستدعى** — اترك رقائق خطوات الوكيل تظهر واحدة تلو الأخرى، لا تقصّها في المونتاج.
- [ ] **بيانات قابلة للعرض** — أعِد تسمية الأجهزة لأسماء مألوفة قبل التسجيل؛ تجنّب أي معلومات حسّاسة على الشاشة.
- [ ] **ترجمة مطبوعة** — اطبع التعليقات الإنجليزية على الفيديو (accessibility + محكّم غير عربي).
- [ ] **الجودة والمدّة** — 1080p على الأقل، ثبات الإطار، وابقَ ضمن ≈ 2:45.
- [ ] **حدِّث README قبل التقديم** — استبدل اللقطات المُعاد التقاطها وأضِف لقطة الجولة الترحيبية.

---

<sub>عُدّة داخلية لإعداد العرض · فريق محدِّث المنزل · HomeUpdater v1.4.7</sub>

</div>
