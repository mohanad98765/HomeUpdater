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
- **حزمة اختبارات pytest (47 اختباراً)** تحت `backend/tests/` تغطّي: مُحلِّل winget
  (عربي/إنجليزي)، middleware الأمان (Host/CSRF)، upsert المسح مع MAC فارغ، حقن ADB،
  قفل مؤشِّرات التقدُّم، أقفال التزامن، واختبارات smoke للـ endpoints. جميعها تجتاز
  على الإصدارات المثبَّتة في `requirements.txt`.

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
