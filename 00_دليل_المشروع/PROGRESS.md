# PROGRESS.md
## سجل التقدم في المشروع

> **القاعدة الذهبية:** حدّث هذا الملف في نهاية كل جلسة عمل. أول شيء تقرأه عندما ترجع للمشروع.

---

## 🎯 الحالة الحالية

**التاريخ:** 2026-07-20
**المرحلة الحالية:** ✅ **مُصدَر — v1.3.2 (released)**. المشروع feature-complete: كل نطاق الخطّة الأساسي شُحن، إضافةً إلى ميزات ما بعد v1.0 (#34–#41).
**النسبة المئوية للإنجاز الكلي:** ~100% من النطاق المخطَّط (v1.0.0 + المستشار الذكي + محادثة + تقرير PDF + تطبيق بعيد + الأمان/CVE + Android لاسلكي)

**🎉 معالم محقَّقة:**
- Backend FastAPI + Frontend React كنافذة تطبيق أصلية واحدة (WebView2)، بمثبِّت موقَّع بنقرة مزدوجة
- **إصدار v1.0.0:** `build_mode="release"` — **شارة «وضع الاختبار» أُزيلت** (لم تعُد تظهر)، توقيع الكود، وواجهة بستّ لغات
- **#34** المستشار الذكي (agentic tool-use) + **#36** محادثة المستشار + **#37** تصدير تقرير أمان PDF
- **#38** توسيع «طبّق» للأجهزة البعيدة (WinRM/SSH) + ميزة الأمان (CVE) برقم/رابط CVE لكل جهاز
- **#39** إقران التصحيح اللاسلكي Android 11+ (adb الرسمية مُضمَّنة) + **#41** اكتشاف منفذ الاتصال تلقائياً (mDNS)
- 167 اختباراً ناجحاً (ruff + black نظيفان)
- logs لكل تشغيل في `02_التطوير/logs/`
- المشروع مُختبَر ويَعمل على Windows 11 build 26100 + Python 3.13 + Node 20

---

## ✅ ما تم إنجازه حتى الآن

### الجلسة #5 — 2026-07-20 (الوصول إلى v1.3.2 — مُصدَر) 🚀

بعد جلسة التصليب، شُحنت سلسلة إصدارات نقلت المشروع من «بنية وظيفية» إلى **منتج مُصدَر
feature-complete**. ملخّص المعالم (التفصيل الكامل في `CHANGELOG.md`):

- **v1.0.0 — الإصدار الأول للاستخدام:** `build_mode="release"` و**إزالة شارة «وضع الاختبار»
  نهائياً** (لم تعُد تظهر في الواجهة)، توقيع الكود (SHA-256 + طابع زمني)، **نافذة تطبيق
  أصلية (WebView2)** بدل المتصفّح، وواجهة بستّ لغات كاملة. تكاملات: Windows بعيد (WinRM)،
  لينكس/SSH، المنزل الذكي (Home Assistant)، تشفير الاعتمادات (Fernet/DPAPI)، مصادقة الـ API
  المحلي، وتحقّق هوية المضيف (SSH TOFU + WinRM TLS).
- **v1.1.0 — #34 المستشار الذكي:** مستشار agentic عبر Claude (`claude-opus-4-8`) بأدوات
  قراءة فقط يوصي بأولويات التحديث ولماذا.
- **v1.2.0 — «طبّق أهمّ ٣ تحديثات»:** المستشار صار ينفّذ عبر `set_plan` مع بوّابة أمان
  (تحقّق كل مُعرّف مقابل التحديثات المعلّقة).
- **v1.3.0 — #35** إصلاح فحص الجوّالات، **#36** محادثة المستشار (chat)، **#37** تصدير
  تقرير أمان PDF، **#38** توسيع «طبّق» للأجهزة البعيدة (WinRM/SSH).
- **v1.3.1 — #39** إقران التصحيح اللاسلكي في Android 11+ (تضمين **adb الرسمية** من Google
  في `vendor/platform-tools`)، وصفحة الأمان تعرض **رقم CVE + رابط مباشر** لكل جهاز.
- **v1.3.2 — #41** اكتشاف منفذ الاتصال تلقائياً (عبر mDNS من adb) بعد الإقران + زرّ «اكتشف
  المنفذ».
- **الاختبارات:** نمت من 48 (v1.0.0) إلى **167** اختباراً ناجحاً (ruff + black نظيفان).

### الجلسة #4 — 2026-07-19 (مراجعة شاملة + تصليب) 🛡️

مراجعة متعدِّدة المحاور (backend، frontend، عقد API، كود ميت، أمان، فجوات) ثمَّ إصلاح العيوب المؤكَّدة:

**أمان (حاجز إصدار):**
- الـ backend يعمل بصلاحيات Administrator وواجهته كانت بلا مصادقة. أُضيف middleware في `main.py`: قائمة Host بيضاء (يمنع DNS-rebinding) + إلزام ترويسة `X-HomeUpdater` على الطلبات المُغيِّرة (يمنع CSRF عبر إجبار preflight). الواجهة (`apiFetch`) تُرسلها تلقائياً.

**تصحيح عيوب مؤكَّدة:**
- تعطُّل المسح (500) عند وجود جهازين بلا MAC: العمود `mac` أصبح `nullable` (NULL بدل `""`).
- تحليل مخرجات `winget` كان يعتمد على عناوين الأعمدة الإنجليزية فيفشل على Windows العربي (يُرجع 0 → يُعلِّم الكل «مثبَّتاً»). أُعيد كتابته ليقسِّم الصفوف على مسافتين+ ويُثبِّت من اليمين — مُختبَر على عيّنات عربية/إنجليزية.
- سباق في مؤشِّرات التقدُّم (`progress.py`, `update_progress.py`): إضافة قفل حول `log`.
- خلل توازن `CoInitialize/CoUninitialize` في `windows_updates.py` (تسريب COM) + مفتاح `total` ناقص في المسار الفارغ.
- حقن أوامر ADB عبر اسم الحزمة في `open_play_store` — تحقُّق بنمط صارم.
- أقفال تزامن (409) على المسح والفحص والتثبيت لمنع الفساد المتوازي.
- الواجهة: `apiFetch` كان يقرأ `errorBody.error` والـ backend يُرجع `detail` (كل الرسائل كانت تُبتلع)؛ وتبويبا Windows/Drivers يتشاركان مفتاح كاش واحد.

**تنظيف وبنية تحتية:**
- تهيئة Git + `.gitignore` مُصحَّح (`.venv/`) + commit أساسي.
- حذف 5 وحدات ميتة (`services/network.py`, `services/classifier.py`, `models/device.py`, `modules/`, `components/DevicesTable.tsx`) + ملف `system.py` المؤقَّت.
- `requirements.txt`: فصل ACTIVE عن RESERVED (لِمراحل قادمة). إزالة `framer-motion` و`react-router-dom` من الواجهة.
- إصلاح استيراد `cn` غير المستخدَم الذي كان يُفشل `npm run build`. الواجهة الآن تجتاز typecheck نظيفة.

### الجلسة #1 — 2026-04-27 (التأسيس)

**المنجز:**
- تحديد الرؤية والنطاق ✅
- اتخاذ القرارات الأساسية:
  - منصة التشغيل: Windows PC
  - النطاق: كل فئات الأجهزة
  - وضع التحديث: تلقائي (مع حماية للـ firmware)
  - مستوى المستخدم: عادي → نحتاج GUI ودوكر/أدوات جاهزة
  - **شكل التسليم: Installer واحد (.exe) مع كل المتطلبات مضمّنة** 🆕
  - **هوية بصرية احترافية كأولوية** 🆕
- إنشاء بنية مجلدات المشروع
- كتابة الوثائق الأساسية:
  - PROJECT_GUIDE.md ✅
  - ARCHITECTURE.md ✅
  - DEVICES.md ✅
  - DECISIONS.md ✅ (12 قرارًا معتمدًا)
  - TASKS.md ✅ (مع Phase A للتصميم و Phase B للـ Installer)
  - QUICKSTART.md ✅
  - **BRAND.md ✅ (الهوية البصرية الكاملة)** 🆕
  - PROGRESS.md ✅ (هذا الملف)

**النواتج:**
- 9 ملفات وثائق في `00_دليل_المشروع/`
- مرجع كامل للرجوع له في أي وقت
- خطة تشمل: التطوير + التصميم + الـ Installer + المكوّنات التشغيلية

### الجلسة #1 (تابع) — تحديثات إضافية في نفس اليوم

**المنجز:**
- إضافة قرار جديد: **الشعار من المستخدم** (يضع الصورة في `03_الموارد/logo/`) — ADR-014
- إنشاء مجلد `03_الموارد/logo/` مع `اقرأني.md` للمستخدم
- مراجعة قرار الـ Stack بعد مدخلات المستخدم عن .NET/WPF/MSIX:
  - قرّرنا الاستمرار مع **Python + React + Inno Setup** (ADR-013)
  - مع إضافات Windows-native (Tray icon، Toast notifications، Service)
- إنشاء **WINDOWS_FUNDAMENTALS.md** — checklist شاملة لـ 24 مكوّن
- توسيع TASKS.md بـ **Phase O** (المكوّنات التشغيلية) و **Phase B** (Installer مفصّل)
- حفظ Windows fundamentals في الذاكرة الدائمة

**النواتج النهائية للجلسة #1:**
- 9 ملفات وثائق
- 14 قرار معماري معتمد
- Phases: 0 (✅) + 1, 2, 3, 4 (التطوير) + A (التصميم) + B (Installer) + O (تشغيلية)

### الجلسة #2 — 2026-04-27 (Phase 1.1: إعداد بيئة التطوير) ✅

**المنجز:**
- إنشاء بنية مجلد `02_التطوير/` بشكل كامل (backend + frontend + scripts + tests)
- **سكريبت تثبيت آلي**: `setup.bat` + `setup.ps1` يستخدمان `winget` لتثبيت Python 3.12 + Node.js LTS + Nmap + Git تلقائياً، ثم يُنشئان venv ويُثبِّتان كل المتطلبات
- **Backend جاهز** (FastAPI):
  - `requirements.txt` بكل الحِزَم المُثبَّتة الإصدارات (FastAPI, Pydantic, SQLAlchemy, python-nmap, scapy, zeroconf, paramiko, asyncssh, cryptography, loguru, pywin32, pystray, …)
  - `app/config.py` — إعدادات تستخدم `%APPDATA%\HomeUpdater\` (متوافق مع WINDOWS_FUNDAMENTALS)
  - `app/logging_setup.py` — loguru مع rotation و retention
  - `app/main.py` — تطبيق FastAPI كامل + معالج أخطاء عام بالعربية والإنجليزية + lifespan
  - `app/routers/system.py` — `/health` و `/version` و `/info`
  - `app/routers/devices.py` — placeholder لـ Phase 1.2
  - `pyproject.toml` — Black + Ruff + line-length 100
- **Frontend جاهز** (Vite + React 18 + TypeScript + Tailwind):
  - `package.json` بكل الحِزَم: TanStack Query، i18next، lucide-react، framer-motion، tailwind-merge، …
  - `vite.config.ts` — proxy `/api` → backend
  - `tailwind.config.js` — ألوان BRAND.md (primary `#0D47A1`, accent `#26A69A`) + Cairo + Inter
  - `index.html` — `lang="ar" dir="rtl"` + Google Fonts
  - `src/main.tsx` — React + QueryClient
  - `src/App.tsx` — صفحة "Hello World" تستدعي `/api/system/health` وتعرض حالة الاتصال (مع رسائل خطأ بالعربية)
  - `src/i18n.ts` — العربية الافتراضية + الإنجليزية احتياطية
  - `src/lib/utils.ts` — `cn()` و `apiFetch()` و `formatDateAr()`
  - `src/index.css` — Tailwind + RTL base + scrollbar + بطاقات/أزرار/شارات
  - `public/favicon.svg` — أيقونة مؤقَّتة (درع + سهم تحديث)
- **سكريبت تشغيل واحد**: `run.bat` يُشغِّل Backend + Frontend ويفتح المتصفح
- **دليل المستخدم**: `تعليمات_التشغيل.md` — شرح خطوة بخطوة مع حلول المشاكل الشائعة

**النواتج (Phase 1.1):**
- ~25 ملف في `02_التطوير/`
- بيئة تطوير قابلة للتشغيل بنقرة واحدة من المستخدم
- Backend ↔ Frontend متَّصلان عبر `/api` proxy
- جاهز فعلياً لكتابة أوَّل وحدة اكتشاف للأجهزة (Phase 1.2)

---

## 🟡 ما يجري الآن

المشروع **مُصدَر عند v1.3.2 (feature-complete)** — لا عمل تطوير كبير جارٍ، والحالة الآن
**صيانة وتحسينات تدريجية**. اكتملت منذ جلسة التصليب: الاختبارات (167) + Alembic + CI،
وبقية Phase 2 (لينكس/SSH، Home Assistant، الإشعارات، WinRM بعيد)، وكل ميزات ما بعد v1.0
(#34–#41). راجع سجل الجلسة #5 أعلاه و`CHANGELOG.md`.

---

## ⏭️ ما هو التالي (مرتَّب بالأولوية)

> ملاحظة: كل أولويات جلسة التصليب أدناه **شُحنت فعلاً** في إصدارات v1.0.0–v1.3.2 —
> تُركت مشطوبة كسجلّ لا كـ«تالٍ».

**أولويات جلسة التصليب (2026-07-19) — كلّها ✅ أُنجزت:**
1. ~~**اختبارات**~~ ✅ حزمة pytest نمت إلى **167** اختباراً (winget، الأمان، الأقفال، adb، الحلقة الوكيلة…).
2. ~~**Alembic migrations**~~ ✅ بنية كاملة + `init_db()` يُشغِّل `upgrade head` عند الإقلاع.
3. ~~**بقية Phase 2**~~ ✅ لينكس/SSH، Home Assistant، الإشعارات، CVE/NVD، وWinRM بعيد.
4. ~~**خدمة الملفات الساكنة للإنتاج**~~ ✅ الـ backend يَخدم `frontend/dist` (خادم واحد للإنتاج).
5. ~~**مصادقة اختيارية**~~ ✅ #29 — رمز جلسة عشوائي لكل تشغيل عبر ترويسة `X-HomeUpdater-Token`.

**الأعمال المتبقّية (اختيارية / بعد الإصدار):**
- شهادة **EV** حقيقية للتوزيع لأجهزة الآخرين وإرضاء Smart App Control (انظر SIGNING.md).
- تدقيق نهائي لقاعدة OUL/OUI مقابل سجلّ IEEE (متابَع).
- تحسينات UX تدريجية وردود فعل المستخدمين.

**للتشغيل:** `run.bat` (auto-elevate + Backend :8000 + Frontend :5173) — أو المثبِّت الموقَّع.
> ⚠️ بعد تغيير مخطَّط `mac`: احذف قاعدة البيانات التجريبية مرَّة واحدة —
> `Remove-Item "$env:APPDATA\HomeUpdater\data\homeupdater.db"`

---

## ❓ نقاط مفتوحة تحتاج قرارًا

هذه أسئلة تحتاج جواب قبل التقدم في مراحل لاحقة:

1. **هل ترغب أن أكتب لك الكود في الجلسات القادمة، أم تفضّل أن تتعلم Python أولًا؟**
   - الخيار الأول: أنا أكتب، أنت تختبر وتقرر — تجربة أسرع
   - الخيار الثاني: أنا أعلّمك خطوة بخطوة — تستفيد على المدى البعيد

2. **هل تريد رفع المشروع على GitHub؟** (مجاني، ويسمح بالاحتفاظ بنسخة في السحابة)

3. **هل عندك راوتر OpenWRT أو راوتر مزوّد؟** (يحدد أولوية المهام)

---

## 📊 إحصائيات المراحل

| Phase | الحالة | التقدم |
|-------|--------|--------|
| Phase 0 - التهيئة | ✅ مكتمل | 100% |
| Phase 1.1 - بيئة التطوير | ✅ مكتمل | 100% |
| Phase 1.2 - اكتشاف الشبكة | ✅ مكتمل | 100% |
| Phase 1.3 - قاعدة البيانات | ✅ مكتمل | 100% |
| Phase 1.4 - تحديثات Windows | ✅ مكتمل | 100% |
| Phase 1.5 - البرامج (winget) + التعريفات | ✅ مكتمل | 100% |
| Phase 2 - Android عبر ADB | ✅ مكتمل | 100% |
| مراجعة + تصليب (Hardening) | ✅ مكتمل | 100% |
| Phase 2 - بقية التوسع (لينكس/SSH + HA + إشعارات + WinRM بعيد) | ✅ مكتمل | 100% |
| اختبارات + Alembic + CI | ✅ مكتمل | 100% (167 اختباراً + Alembic + GitHub Actions) |
| Phase 3 - الإثراء (المستشار الذكي + الأمان/CVE + تقارير PDF) | ✅ مكتمل | 100% |
| Phase 4 - النضج (Installer + توقيع الكود + إصدار v1.3.2) | ✅ مكتمل | 100% |

---

## 📝 سجل الجلسات (Session Log)

### الجلسة #1 — 2026-04-27
- **المدة:** ~30 دقيقة (مع Claude في Cowork)
- **الأشخاص:** مهند + Claude
- **المحاور:**
  - مناقشة الفكرة وتحديد جدواها
  - اتخاذ القرارات التأسيسية
  - بناء كامل لوثائق "الدليل"
- **النتيجة:** Phase 0 مكتملة، جاهزون لـ Phase 1

### الجلسة #2 — 2026-04-27
- **المدة:** ~45 دقيقة
- **الأشخاص:** مهند + Claude
- **المحاور:**
  - بناء بنية `02_التطوير/` كاملة
  - كتابة `setup.bat` + `setup.ps1` للتثبيت الآلي عبر winget
  - إعداد Backend FastAPI Hello World
  - إعداد Frontend Vite+React+Tailwind Hello World
  - كتابة `run.bat` و `تعليمات_التشغيل.md`
- **النتيجة:** Phase 1.1 مكتملة، جاهزون لـ Phase 1.2

### الجلسة #2 — Hotfix #1 🔧
- **المشكلة:** عند تشغيل `setup.bat` ظهرت أخطاء PowerShell `Unexpected token` بسبب أنَّ PS 5.1 لا يقرأ UTF-8 بدون BOM فتلفت النصوص العربية في `setup.ps1`.
- **الحل:** أُعيدت كتابة `setup.ps1` بالإنجليزية ASCII فقط.
- **تحسينات إضافية:**
  - 🛡️ **Auto-elevate**: `setup.bat` و `run.bat` يطلبان UAC تلقائياً.
  - 🧪 **TEST MODE**: شارة صفراء في الواجهة + `build_mode: "test"` في config.py.
  - حُفظت القاعدتان في `feedback_admin_and_test_mode.md`.

### الجلسة #3 — Phase 2 — Android via ADB (2026-05-08) 📱

**Backend (مُنجَز):**
- `services/android.py` — ADB over TCP/IP:
  - إدارة RSA keys في `%APPDATA%\HomeUpdater\adb_keys\` (توليد تلقائي أوَّل مرَّة).
  - `probe(host, port)` — يَتَّصل + يَقرأ ro.product.* عبر getprop.
  - `list_apps()` — يَستخدم `pm list packages -f -3` + `dumpsys package <pkg>` للإصدارات.
  - `open_play_store()` — يُشغِّل intent لِفتح صفحة Play Store على الهاتف.
- `models/orm.py` — `AndroidDeviceORM` جديد (host, port, serial, brand/model, android_version, custom_name, is_online).
- `routers/android.py` — endpoints كاملة:
  - `GET/POST/DELETE /api/android/devices`
  - `POST /devices/{id}/refresh`
  - `PATCH /devices/{id}` (custom_name)
  - `GET /devices/{id}/apps`
  - `POST /devices/{id}/apps/{pkg}/open`
- تسجيل الـ router في main.py.

**Frontend (مُنجَز):**
- `pages/AndroidPage.tsx` كاملة:
  - قائمة الأجهزة بشكل بطاقات (device cards) مع رقم Android + الرقم التسلسلي + آخر تحديث أمني.
  - Dialog "إضافة هاتف" مع IP + Port + تعليمات USB debugging.
  - كل بطاقة فيها: عرض التطبيقات، تحديث الحالة، إعادة تسمية، إزالة.
  - عرض تطبيقات الهاتف في جدول مع package name + version + زر "افتح في Play Store".
- Tab جديد "Android" في الرأس.
- ترجمات عربية + إنجليزية.

**المتطلَّبات على الهاتف:**
- Developer Options مُفعَّلة.
- USB debugging + Wireless debugging (Android 11+) مُفعَّل.
- على الاتصال الأوَّل، Windows PC تَظهر له نافذة "Allow USB debugging?" → المستخدم يَقبل.

**قيد التطوير:**
- ADB لا يَدعم "check updates" مباشرة (Play Store مقفلة). البديل الحالي: زر "افتح في Play Store" يَقفز مباشرة لصفحة التطبيق على الهاتف حيث يَضغط المستخدم تحديث.

---

### الجلسة #2 — Phase 1.5 — تحديثات البرامج + Drivers + OUI (2026-04-28) 📦

**Backend (مُنجَز):**
- `services/software_updates.py` — تكامل **winget** عبر subprocess:
  - `list_software_updates()` — يُشغِّل `winget upgrade --include-unknown` ويُحلِّل جدول الإخراج إلى قائمة packages.
  - `install_software_update(package_id)` — يُشغِّل `winget upgrade <id> --silent`.
  - `install_many(packages)` — يُثبِّت عدَّة packages بالتسلسل مع تَتبُّع التقدُّم.
- `services/windows_updates.py` — تَوسيع لدعم **Drivers**:
  - `check_for_updates(kind="Software" | "Driver")` — يَستخدم `Type='{kind}'` في WUA query.
  - install function يَبحث بدون filter Type ليَجد كلا النوعين.
- `services/mac_vendor.py` — قاعدة بيانات OUI مُختارة (~250 prefix) تُغطي:
  - Apple, Samsung, Xiaomi, Huawei, TP-Link, ASUS, Netgear, D-Link, Cisco, Linksys.
  - Intel, Microsoft, Dell, HP, Lenovo, Acer, MSI.
  - LG, Sony, Vizio, TCL, Hisense (Smart TVs), Roku, Chromecast, Fire TV.
  - Espressif, Philips Hue, Tuya, Raspberry Pi (IoT).
  - `enrich_vendor(mac, current)` — يُكمل vendor الفارغ الذي تَركه nmap.
- `models/orm.py`:
  - `SoftwarePackageORM` — جدول جديد لتحديثات البرامج.
  - `WindowsUpdateORM.kind` — حقل جديد ("windows" | "driver") للتمييز.
- `routers/updates.py` — endpoints جديدة:
  - `GET /api/updates/drivers` + `POST /drivers/check` + `POST /drivers/install`
  - `GET /api/updates/software` + `POST /software/check` + `POST /software/install`

**Frontend (مُنجَز):**
- `pages/SoftwareUpdatesView.tsx` — مكوِّن خاص بـ winget مع جدول وأعمدة (الاسم، الإصدار الحالي، المتوفِّر، المصدر).
- `pages/UpdatesPage.tsx` — أُعيد تنظيمه بـ **3 تابات**:
  - 🪟 تحديثات Windows
  - 📦 البرامج (winget)
  - 🔧 تعريفات الأجهزة
- مكوِّن `WUAUpdatesView` مُعمَّم لـ Windows + Drivers (نفس الـ UI، فقط الـ endpoint يَتغيَّر بـ prop).
- ترجمات `updateTabs.*` و `software.*` و `drivers.*` بالعربية والإنجليزية.

**اعتماديات:** لا حِزَم جديدة — winget موجود في PATH من setup.bat.

---

### الجلسة #2 — Phase 1.4 — تحديثات Windows الحقيقية (2026-04-28) 🪟

**أوَّل وحدة تحديث حقيقية في المشروع!** الآن البرنامج يَكتشف ويُثبِّت تحديثات Windows فعلياً.

**Backend (مُنجَز):**
- `services/update_progress.py` — singleton tracker مع phases (`checking`/`downloading`/`installing`/`rebooting`/`done`/`error`).
- `services/windows_updates.py` — تكامل Windows Update Agent (WUA) عبر COM:
  - `check_for_updates()` — استعلام `Microsoft.Update.Session` بـ "IsInstalled=0 and IsHidden=0 and Type='Software'"، يُرجع تفاصيل (KB, severity, size, reboot).
  - `install_updates(update_ids)` — يَقبل EULA → يُنزِّل (CreateUpdateDownloader) → يُثبِّت (CreateUpdateInstaller) → يُرجع نتائج لكل تحديث + هل reboot مطلوب.
  - يَستخدم `pythoncom.CoInitialize()` ويَعمل في thread executor لئلَّا يَحجب الـ event loop.
- `models/orm.py` — إضافة `WindowsUpdateORM` (cache لكل التحديثات + install state).
- `routers/updates.py` — endpoints جديدة:
  - `GET /api/updates/windows` — قائمة من DB (pending + installed_recent + إجمالي حجم)
  - `POST /api/updates/windows/check` — يُشغِّل البحث ويُحدِّث الـ DB
  - `POST /api/updates/windows/install` — يُثبِّت محدَّد أو الكل
  - `GET /api/updates/windows/status` — live progress للـ UI
- `main.py` — تَسجيل router جديد بـ prefix `/api/updates`.

**Frontend (مُنجَز):**
- `pages/UpdatesPage.tsx` — صفحة كاملة:
  - 3 بطاقات إحصائيات (عدد المعلَّق، الحجم الإجمالي، يحتاج reboot).
  - زر **فحص التحديثات** + زر **تثبيت** (محدَّد أو الكل).
  - جدول مع checkboxes لاختيار تحديثات معيَّنة.
  - Activity Log حيٌّ مع شريط تقدُّم (progress bar) أثناء check/install.
  - تأكيد قبل التثبيت (`window.confirm` بترجمة).
  - شارات severity ملوَّنة (Critical=أحمر، Important=برتقالي، Moderate=أزرق).
  - حالة "نظامك مُحدَّث ✓" عند عدم وجود تحديثات.
  - رسالة "إعادة تشغيل مطلوبة" واضحة بعد التثبيت.
- `App.tsx` — tab جديد "تحديثات" (Download icon) + page state موسَّع.
- `i18n.ts` — قسم `updates.*` كامل بالعربية والإنجليزية (53 مفتاح).

**اعتماديات:**
- `pywin32==308` (مُثبَّت سابقاً) — يُوفِّر `win32com.client` + `pythoncom`.

**المتطلَّبات للتشغيل:** صلاحيات Administrator (موجودة عبر run.bat auto-elevate).

**خطَّة Phase 1.5 (لاحقاً):** تحديثات البرامج المُثبَّتة عبر `winget upgrade` (Chrome, VS Code, Discord, ...).

---

### الجلسة #2 — Phase 1.3 — قاعدة بيانات + UX polish (2026-04-28) 💾

**الإصلاح الجوهري لـ Phase 1.2:** نَجح الفحص بعد تغيير nmap من `-PR` (ARP فقط) إلى `-sn -T4` (ICMP+TCP+ARP) — الآن يَعبر الـ routers ويَجد البوابة عبر شبكات /16 المُقسَّمة.

**Phase 1.3 — Backend (مُنجَز):**
- `db.py` — SQLAlchemy 2.0 async engine + `SessionLocal` + `init_db()` يُنشئ الجداول عند البدء.
- `models/orm.py` — `DeviceORM` ORM model مع id, mac, ip, hostname, vendor, device_type, **custom_name**, **notes**, first_seen, last_seen, is_online + `to_dict()` يَحوي `display_name` (custom > host > vendor > ip).
- `routers/devices.py` أُعيد كتابته بالكامل ليَستخدم DB:
  - `GET /api/devices` — استعلام من DB
  - `GET /api/devices/stats` — جديد، counts (total/online/offline + by_type)
  - `GET /api/devices/{id}` — تفاصيل جهاز
  - `PATCH /api/devices/{id}` — تحديث custom_name + notes
  - `POST /api/devices/scan` — upsert بدلاً من in-memory
- التخزين دائم في `%APPDATA%\HomeUpdater\data\homeupdater.db` — الأجهزة تَبقى بعد إعادة التشغيل.
- `main.py` لـ lifespan الآن يَستدعي `init_db()` لإنشاء الجداول.

**Phase 1.3 — Frontend (مُنجَز):**
- `components/StatsCards.tsx` — 4 بطاقات أعلى الصفحة: إجمالي / متصل / راوترات / هواتف، ملوَّنة بألوان مختلفة، أيقونات لـ lucide-react.
- `components/DeviceDetailPanel.tsx` — لوحة جانبية منزلقة (drawer):
  - حقل **اسم مُخصَّص** قابل للتعديل
  - حقل **ملاحظات** (textarea)
  - أقسام **Identity** (IP/MAC/Host/Vendor/Type/Status/ID) و **Timing** (first_seen/last_seen مُنسَّقة بالعربية).
  - زر "حفظ" يَستدعي `PATCH /api/devices/{id}` ويُظهر "تَمَّ الحفظ ✓" لـ 2 ثانية.
  - يُغلق بـ Escape أو نقرة على الخلفية.
- `pages/DevicesPage.tsx` — كل صفٍّ في الجدول الآن قابل للنقر → يَفتح اللوحة. الاسم المُخصَّص يَظهر فوق الـ hostname إذا مُحدَّد.
- ترجمات `stats.*` و `detail.*` لكل من العربية والإنجليزية (لغات أخرى تَرجع للإنجليزية افتراضياً).

**الفائدة العملية:**
- إعادة التشغيل ➜ الأجهزة لا تُفقَد.
- إعادة المسح ➜ يُحدِّث `last_seen` ولا يَفقد `custom_name`/`notes`.
- المستخدم يستطيع تَسمية أجهزته (مثلاً: `راوتر غرفة المعيشة`، `هاتف أحمد`).
- بطاقات الإحصائيات تُحدَّث تلقائياً كل 30 ثانية.

---

### الجلسة #2 — Phase 1.2 — تحسينات بطلب المستخدم (2026-04-28) 🎛️

**تجربة المستخدم على شبكته الفعلية كَشَفت ثغرات:**
- شبكته كانت `10.38.0.0/16` (65k IP) — Nmap لا يكتشف أجهزة لأنَّ ARP broadcast لا يَخرج من broadcast domain.
- المستخدم لا يَرى ما يَحدث أثناء المسح (يَظنُّ البرنامج معطَّل).

**معالجات هذه الجلسة:**
1. **اكتشاف Default Gateway** عبر `route PRINT 0.0.0.0` على Windows → بطاقة "معلومات الشبكة" تَعرض IP المحلِّي + Gateway + Netmask + Adapter.
2. **حقل تعديل نطاق المسح** (CIDR override) في الواجهة — مع validation وإظهار حجم العناوين المتوقَّعة.
3. **Activity Log حيٌّ داخل الصفحة:**
   - `services/progress.py` — `ProgressTracker` singleton يَتتبَّع الـ phases (`detecting`/`scanning`/`resolving`/`classifying`/`done`).
   - `discovery.py` يُحدِّث الـ tracker مع كل جهاز يُكتشَف.
   - `GET /api/devices/scan/status` — endpoint جديد للـ live state.
   - `DevicesPage` يَستفسر عنه كل ثانية (`refetchInterval: 1000`) أثناء المسح ويَعرض السجلَّ الزمني المباشر.
4. **عدَّاد ثوانٍ** + عدَّاد أجهزة + رسائل بحالة كل phase ملوَّنة.
5. **سلوك المسح الافتراضي**: يَتبع الـ netmask الكامل كما يَعرضه Windows (تَفضيل المستخدم — "هذي الطريقة الصحيحة"). تَحذير إذا الشبكة كبيرة (>1024 عنوان) مع اقتراح للنطاق الأصغر `/24` كزرٍّ سريع.

**ما تبقَّى لاحقاً:**
- AI لتصنيف الأجهزة المجهولة (Phase 3).
- استبدال in-memory storage بـ SQLite (Phase 1.3).

---

### الجلسة #2 — Phase 1.2 — اكتشاف أجهزة الشبكة 🔍

**Backend (مُنجَز):**
- `services/network_utils.py` — اكتشاف الـ subnet المحلِّي تلقائياً عبر `psutil.net_if_addrs()` + socket trick، `normalize_mac()`، تصنيف الأجهزة (router/phone/computer/smart_tv/iot/unknown).
- `services/discovery.py` — فحص ARP عبر `python-nmap` بأرغومنت `-sn -PR -T4` (ARP ping بدون port scan)، يعمل في thread executor لئلَّا يحجب الـ event loop. Reverse-DNS lookup للأجهزة بعد الفحص.
- `models/device.py` — Pydantic models: `Device` و `ScanResponse`.
- `routers/devices.py` — endpoints حقيقية: `GET /api/devices` (قائمة), `GET /api/devices/info` (subnet + interfaces), `POST /api/devices/scan` (تشغيل المسح). تخزين in-memory مفتاحه MAC.

**Frontend (مُنجَز):**
- `pages/DevicesPage.tsx` — صفحة كاملة: زر "Scan now"، loading state، جدول بأعمدة (نوع، اسم، IP، MAC، صانع، حالة)، summary بعد المسح (total/new/duration)، empty state، error state.
- `components/DeviceTypeIcon.tsx` — أيقونات ملوَّنة لكل نوع جهاز.
- `App.tsx` أُعيد بناؤه ليكون "App shell" مع tabs navigation بين Dashboard و Devices. زر "ابدأ فحص الشبكة" في Dashboard ينتقل إلى صفحة Devices تلقائياً.

**ما يتطلَّبه التشغيل:**
- صلاحيات Administrator (موجودة عبر auto-elevate في run.bat) — Nmap ARP scan يحتاجها على Windows.
- Nmap في PATH (موجود من setup).

**الترجمات (في الـ i18n.ts):** قسم `devices` و `status.online/offline` مُترجَم لكل اللغات الست.

**خطَّة Phase 1.3 (لاحقاً):** استبدال التخزين in-memory بـ SQLite (الـ schema جاهز في الـ ARCHITECTURE)، إضافة Alembic migrations، حقول custom_name للجهاز.

---

### الجلسة #2 — تحسينات UX 🎨 (نظام ثيمات + لغات متعددة)
بطلب المستخدم بعد اكتمال Phase 1.1، أُضيفت مكوِّنات Polish:
- **نظام ثيمات متعدد (8 ثيمات)** عبر CSS variables:
  - `system` (تَبع نظام التشغيل تلقائياً عبر `prefers-color-scheme`)
  - `light` / `dark` (الافتراضيان)
  - `ocean` (سماوي/فيروزي فاتح)
  - `forest` (أخضر طبيعي)
  - `sunset` (برتقالي دافئ)
  - `royal` (بنفسجي داكن)
  - `midnight` (أسود مزرق عميق)
  - الثيم المختار يُحفَظ في localStorage تحت مفتاح `homeupdater.theme`
  - Tailwind config أُعيد تشكيله ليَستخدم semantic colors (`bg`, `surface`, `fg`, `primary`, ...) بدلاً من ألوان مُثبَّتة → كل ثيم يُغيِّر `--color-*` وتنعكس عبر التطبيق فوراً.
- **نظام لغات متعدد (6 لغات)**:
  - `ar` العربية (الافتراضية, RTL)
  - `en` English
  - `fr` Français
  - `es` Español
  - `tr` Türkçe
  - `ur` اردو (RTL)
  - الـ `<html lang>` و `dir` يُحدَّثان تلقائياً عند تغيير اللغة.
  - الاختيار محفوظ في localStorage تحت `homeupdater.language`.
- **مكوِّنات جديدة:**
  - `src/lib/theme.tsx` — Provider + Hook + Theme registry
  - `src/lib/language.tsx` — Provider + Hook + Language registry (مع RTL detection)
  - `src/components/ThemeToggle.tsx` — قائمة منسدلة مع أيقونات وألوان معاينة
  - `src/components/LanguageToggle.tsx` — قائمة منسدلة مع أعلام
- الـ `App.tsx` أُعيد تشكيله ليستخدم الـ semantic Tailwind classes بدلاً من `slate-*` و `dark:*`.

### الجلسة #2 — Hotfix #5 🔧 (مسارات API + SyntaxWarning)
- **التشغيل الأوَّل ناجح بصرياً:** الـ Frontend عَرض الواجهة العربية + شارة TEST MODE، لكنَّه أَظهر "🔴 غير متصل".
- **السبب:** الـ Backend استلم الطلبات لكن أعاد 404. الـ Router مُسجَّل بـ prefix `/api` فقط، بينما الـ Frontend يَطلب `/api/system/health`.
- **الحلول:**
  1. تغيير prefix في `main.py`: `/api` → `/api/system` و `/api/devices`.
  2. تعديل routes داخل `devices.py` لتَتطابق مع الـ prefix الجديد.
  3. تحويل docstrings في `config.py` و `logging_setup.py` إلى raw strings (`r"""..."""`) لإسكات تحذيرات `SyntaxWarning: invalid escape sequence '\H'` (مسارات Windows).
- **النتيجة النهائية:** 🎉 Phase 1.1 مُكتمَلة ومُختبَرة على نظام المستخدم. الواجهة تَعرض "🟢 متصل" + كل بيانات الإصدار.

### الجلسة #2 — Hotfix #4 🔧 (netifaces غير متوافق مع Python 3.13)
- **التقدُّم الإيجابي:** كل الأدوات تَمَّ تثبيتها بنجاح:
  - Python 3.13.7 (موجود مسبقاً)
  - Node.js 20.18.1 (تنزيل + تثبيت silent عبر msiexec)
  - Nmap 7.99 (موجود مسبقاً)
  - Git 2.54.0 (موجود مسبقاً)
  - venv أُنشئ بنجاح
- **المشكلة:** فشل `pip install -r requirements.txt` على حِزمة `netifaces==0.11.0` لأنَّها مُهملة، لا توجد لها prebuilt wheels لـ Python 3.11+، فحاول pip بناءها من المصدر مما تطلَّب Visual C++ Build Tools (5GB+، تجربة سيِّئة للمستخدم).
- **الحل:** استبدال `netifaces` بـ `psutil==6.1.0`:
  - `psutil` مُحدَّثة باستمرار، لها wheels لكل إصدارات Python.
  - تُوفِّر نفس المعلومات (`psutil.net_if_addrs()`) + إحصائيات النظام كبونص.
  - في Phase 1.2، اكتشاف الـ default gateway سيتمُّ عبر socket trick (`socket.connect("8.8.8.8")` ثم `getsockname`).

### الجلسة #2 — Hotfix #3 🔧 (winget غير متوفِّر)
- **المشكلة:** بعد إصلاح الترميز، كشف log الـ setup أنَّ `winget` غير مُثبَّت على نظام المستخدم (Windows 11 build 26100)، فتوقَّف السكربت قبل تثبيت أيِّ شيء.
- **الحل:** اعتماد التنزيل المباشر (Direct Download) كآلية رئيسية:
  - Python 3.12.8 من `python.org`
  - Node.js 20.18.1 LTS من `nodejs.org`
  - Nmap 7.95 من `nmap.org`
  - Git 2.47.1 من `github.com/git-for-windows`
  - Cache في `%TEMP%\HomeUpdater-Installers\` لتجنُّب إعادة التنزيل عند المحاولة الثانية.
  - تجربة `winget` مزالة بالكامل من `setup.ps1` لأنَّها غير موثوقة.
- **توثيق القرار:** ADR-015 في `DECISIONS.md`.

### الجلسة #2 — Hotfix #2 🔧
- **المشكلة:** بعد إصلاح الـ PS1، أنتج `setup.bat` نفسه عشرات الأخطاء `'xxx' is not recognized` لأنَّ `cmd.exe` يقرأ ملفات `.bat` بترميز OEM المحلي (CP1256 على Windows العربي) وليس UTF-8 — فتلفت العربية داخل `echo` وفقدت كلمة `echo` نفسها في بعض الأسطر، فتُفسَّر النصوص بعدها كأوامر مستقلة.
- **الحل:**
  1. أُعيدت كتابة `setup.bat` و `run.bat` بـ ASCII فقط (لا عربية، لا Unicode، لا emoji).
  2. تجزئة منطق التشغيل إلى سكربتات PowerShell معاونة في `scripts/start_backend.ps1` و `scripts/start_frontend.ps1` — لتجنُّب nested quotes في cmd مع المسارات العربية.
  3. تحديث `feedback_ps1_encoding.md` ليشمل `.bat` أيضاً.
- **بطلب المستخدم — نظام Logging شامل:**
  - 📜 كل تشغيل `setup` يُحفَظ في `logs/setup_<timestamp>.log` عبر `Start-Transcript`.
  - 📜 كل تشغيل `run` يُحفَظ في `logs/run_*.log` و `backend_*.log` و `frontend_*.log` عبر `Tee-Object`.
  - نسخة "latest" من كل نوع لقراءة سريعة.
  - حُفظت مواقع الـ logs في الذاكرة الدائمة (`reference_homeupdater_logs.md`).

### الجلسة #3 — (قادمة)
- ابدأ من PROGRESS.md → اقرأ "ما هو التالي" (Phase 1.2 — اكتشاف الأجهزة)

---

## 🔗 روابط سريعة

- المرجع الرئيسي: [PROJECT_GUIDE.md](./PROJECT_GUIDE.md)
- المعمارية: [ARCHITECTURE.md](./ARCHITECTURE.md)
- الأجهزة: [DEVICES.md](./DEVICES.md)
- القرارات: [DECISIONS.md](./DECISIONS.md)
- الهوية البصرية: [BRAND.md](./BRAND.md)
- **أساسيات Windows (مرجع إلزامي):** [WINDOWS_FUNDAMENTALS.md](./WINDOWS_FUNDAMENTALS.md)
- المهام: [TASKS.md](./TASKS.md)
- البدء السريع: [QUICKSTART.md](./QUICKSTART.md)
