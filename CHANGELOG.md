# سجل التغييرات (CHANGELOG)

جميع التغييرات المهمّة في مشروع **HomeUpdater / محدِّث المنزل** تُوثَّق هنا.

التنسيق مبنيّ على [Keep a Changelog](https://keepachangelog.com/ar/1.1.0/)،
والمشروع يتبع [الإصدار الدلالي (SemVer)](https://semver.org/lang/ar/).

## [غير مُصدَر] — Unreleased

### الأمان (Security)
- إضافة middleware حماية في `backend/app/main.py`: قائمة Host بيضاء (`allowed_hosts`)
  تمنع هجمات DNS-rebinding، وإلزام ترويسة `X-HomeUpdater` على الطلبات المُغيِّرة
  (POST/PUT/PATCH/DELETE) لمنع CSRF عبر إجبار CORS preflight. الواجهة تُرسل الترويسة تلقائياً.
- إضافة تحقُّق صارم من اسم حزمة Android قبل تمريره لأمر `am start` (يمنع حقن أوامر ADB).

### التصحيحات (Fixed)
- **تعطُّل المسح**: العمود `devices.mac` أصبح `nullable` (NULL بدل `""`)، فلم يعُد جهازان
  بلا MAC يُسقطان المسح بخطأ UNIQUE (شائع بلا صلاحيات مدير). *(يتطلَّب حذف قاعدة البيانات التجريبية مرَّة واحدة.)*
- **تحليل winget على Windows العربي**: أُعيد كتابة `_parse_winget_table` ليقسِّم الصفوف
  على مسافتين+ ويُثبِّت الأعمدة من اليمين بدل الاعتماد على عناوين إنجليزية — فلم يعُد الفحص
  يُرجع صفراً ثمَّ يُعلِّم كل البرامج «مثبَّتة» خطأً.
- **سباق مؤشِّرات التقدُّم**: إضافة قفل حول سجلّ الأحداث في `progress.py` و`update_progress.py`
  لمنع أخطاء 500 المتقطِّعة أثناء استطلاع الواجهة.
- **تسريب COM**: موازنة `CoInitialize`/`CoUninitialize` في `windows_updates.py`.
- **KeyError كامن**: إضافة مفتاح `total` في مسار التثبيت الفارغ.
- **رسائل الأخطاء**: `apiFetch` يقرأ الآن `detail` (شكل HTTPException) إضافةً إلى `error`.
- **تصادم كاش**: تبويبا تحديثات Windows والتعريفات لم يعودا يتشاركان مفتاح كاش واحد.
- **بناء الإنتاج**: إزالة استيراد `cn` غير المستخدَم الذي كان يُفشل `npm run build`.

### أُضيف (Added)
- أقفال تزامن (HTTP 409) على المسح والفحص والتثبيت لمنع العمليات المتوازية المتضاربة.
- تهيئة مستودع Git مع `.gitignore` جذر شامل.
- **حزمة اختبارات pytest (48 اختباراً)** تحت `backend/tests/` تغطّي: مُحلِّل winget
  (عربي/إنجليزي)، middleware الأمان (Host/CSRF)، upsert المسح مع MAC فارغ، حقن ADB،
  قفل مؤشِّرات التقدُّم، أقفال التزامن، اختبارات smoke، وتشغيل migration. جميعها تجتاز
  على الإصدارات المثبَّتة في `requirements.txt`.
- **Alembic migrations**: بنية كاملة + migration أساسي، و`init_db()` يُشغِّل
  `upgrade head` عند الإقلاع (مع تبنّي قاعدة بيانات قديمة عبر `stamp` بلا انهيار).
- **CI عبر GitHub Actions**: فحص backend (ruff + black + pytest على windows) وبناء
  frontend (tsc + vite على ubuntu). *(يعمل بعد ربط المستودع بـ GitHub ودفعه.)*
- **Phase B — الـ Installer (بداية)**:
  - خدمة الملفّات الساكنة: الـ backend يَخدم الواجهة المبنيّة من "/" (خادم واحد للإنتاج).
  - `launcher.py` + `HomeUpdater.spec`: تجميع PyInstaller ينتج `HomeUpdater.exe` واحداً
    يُقلع ويُهاجر ويَخدم الواجهة والـ API (مُختبَر فعلياً).
  - `installer/HomeUpdater.iss` + `BUILD.md`: سكربت Inno Setup ودليل بناء ثلاثي المراحل.
  - **المثبِّت النهائي مُنتَج ✅**: صُرِّف عبر Inno Setup 6.7 →
    `HomeUpdater-Setup-0.1.0.exe` (~29MB) — ملفّ تثبيت واحد بنقرة مزدوجة يحوي
    الواجهة والـ backend والـ migrations، بالأيقونة وبانرات المعالج.
  - **tray + خدمة (B.6)**: `tray.py` (أيقونة شريط النظام + قائمة، الـ exe صار تطبيق
    tray بلا نافذة console) و`service.py` (خدمة Windows عبر pywin32 للتشغيل headless).
  - **إشعارات Windows (B.6.3)**: toast عبر أيقونة الـ tray عند توفّر تحديثات
    (Windows / تعريفات / برامج)، بلا اعتمادية جديدة، + endpoint `‎/api/system/notify-test`.
- **Phase A — الهوية البصرية (أيقونة)**: علامة افتراضية (منزل + سهم تحديث على خلفية
  زرقاء متدرّجة) عبر `03_الموارد/logo/generate_icons.py`، بكل المقاسات + `.ico`،
  مربوطة بالـ favicon والـ tray وأيقونة الـ exe وأيقونة المثبِّت. قابلة لإعادة التوليد
  من شعار المستخدم لاحقاً.
- **Phase A — بانرات المعالج + splash**: `generate_wizard_banners.py` يُنتج بانرات
  Inno (كبير 164×314 + صغير 55×58، بنسختَي DPI) مع نصّ عربي مُشكَّل صحيحاً، وصورة
  splash 800×800؛ البانرات مربوطة في `HomeUpdater.iss`.

### تغيير (Changed)
- **اكتشاف الشبكة بلغة Python خالصة** (`discovery_python.py`): جسّ TCP + قراءة جدول
  ARP بدل nmap — لا يحتاج nmap/Npcap ولا صلاحيات مدير (يتفادى قيود ترخيص Npcap عند
  التوزيع). nmap يبقى اختيارياً (`scan_method="auto"`). مُختبَر حيّاً: 23 جهازاً في ~5 ثوانٍ.
  إصلاح تعطّل عند MAC مكرَّر في نفس الجولة (جهازان بنفس MAC عبر ARP) — دمجهما بدل الانهيار.
- تنسيق كامل للـ backend بـ black + ruff، وإعداد `pyproject` لتجاهل نمط FastAPI
  (`B008`) واستثناء `alembic/` المُولَّد. إزالة 8 مفاتيح OUI مكرَّرة في
  `mac_vendor.py` كانت تُلبِّس المُصنِّعين (بانتظار تدقيق نهائي مقابل سجلّ IEEE).

### أُزيل / نُظِّف (Removed)
- 5 وحدات ميتة: `services/network.py`, `services/classifier.py`, `models/device.py`,
  حزمة `modules/`, ومكوِّن `components/DevicesTable.tsx`، وملف `system.py` المؤقَّت.
- اعتماديتا واجهة غير مستخدَمتين: `framer-motion`, `react-router-dom`.
- إعادة تنظيم `requirements.txt` إلى ACTIVE مقابل RESERVED (لمراحل قادمة).

## [0.1.0] — 2026-05-08

- Phase 0–1 كاملة: بيئة التطوير، اكتشاف الشبكة (nmap)، قاعدة SQLite، تحديثات Windows،
  تحديثات البرامج (winget) + التعريفات، وإثراء بيانات المُصنِّعين (OUI).
- Phase 2: إدارة هواتف Android عبر ADB over TCP/IP.
- Backend FastAPI + Frontend React/Vite مع ثيمات متعدِّدة وتعدُّد لغات (RTL).
