# WINDOWS_FUNDAMENTALS.md
## أساسيات بناء برامج Windows الاحترافية — Reference & Checklist

> هذا الملف يوثّق المعرفة المرجعية الكاملة لبناء أي برنامج Windows على مستوى احترافي.
> **يُراجَع قبل اتخاذ أي قرار معماري وقبل بدء كل Phase.**

---

## القسم 1: تقنيات تطبيقات Windows (Tech Stacks)

عند بناء برنامج لـ Windows، عندنا 3 مسارات رئيسية:

### المسار أ) تطبيقات .NET (الأكثر شيوعًا وسهولة)

| التقنية | الوصف | متى تختارها |
|---------|-------|-------------|
| **C# + WinForms** | سريع لبناء أدوات داخلية وواجهات بسيطة | أدوات داخلية، prototypes سريعة |
| **C# + WPF** | واجهات أجمل/أقوى (Binding/MVVM) | تطبيقات سطح مكتب احترافية |
| **.NET + WinUI 3** | حديث، شكل عصري، تكامل أفضل | تطبيقات Windows 10/11 حديثة |

**✅ مناسب لو تبغى:** سرعة تطوير + سهولة نشر + مجتمع كبير + قبول مؤسسي.

### المسار ب) تطبيقات Native (أداء أعلى)

| التقنية | الوصف |
|---------|-------|
| **C++ (Win32 / MFC)** | أداء عالي وتحكم كامل بالنظام |

**✅ مناسب لو تبغى:** أداء شديد، تعامل عميق مع النظام، drivers، أدوات أمن.

### المسار ج) تطبيقات متعددة المنصات (تنزل على ويندوز)

| التقنية | الوصف | الإيجابيات | السلبيات |
|---------|-------|-----------|----------|
| **Electron (JS/TS)** | ويب داخل ويندوز | سهولة، تطوير سريع | يستهلك موارد كثيرة |
| **Qt (C++/Python)** | قوي، احترافي | واجهات قوية | منحنى تعلّم |
| **.NET MAUI** | متعدد المنصات | كود واحد لمنصات متعددة | لسه مو الأفضل لسطح المكتب |
| **Tauri (Rust)** | بديل خفيف لـ Electron | حجم صغير، أداء جيد | منحنى تعلّم |

---

## القسم 2: مفهوم "التثبيت" على Windows

التثبيت ليس مجرّد "نسخ ملفات". أي installer احترافي يقوم بـ:

1. **نسخ ملفات البرنامج** لمجلد مناسب (`Program Files` أو `AppData`)
2. **إنشاء اختصارات** (Start Menu / Desktop)
3. **تسجيل Uninstaller** في `Add or remove programs`
4. **إضافة إعدادات/تبعيات** (Runtime، Drivers، VC++ Redistributable...)
5. **اختياريًا:**
   - تسجيل خدمة Windows Service
   - إنشاء Scheduled Task
   - تسجيل بروتوكول URL (`myapp://`)
   - File Associations (ربط امتداد بالبرنامج)

---

## القسم 3: خيارات التغليف (Installer / Packaging)

عندنا 3 خيارات منتشرة:

### 3.1 MSIX (الحديث، مفضل من Microsoft)
- **الميزات:** أمان أعلى، عزل (Sandbox-ish)، إلغاء تثبيت نظيف، تحديثات أسهل
- **يناسب:** تطبيقات حديثة بدون تعديلات عميقة بالنظام
- **أداة البناء:** Visual Studio أو MSIX Packaging Tool

### 3.2 MSI (التقليدي، المؤسسي)
- **الميزات:** مشهور في الشركات، قوي مع Group Policy و SCCM
- **يناسب:** بيئات شركات، إدارة أصول، نشر عبر AD
- **أداة البناء:** WiX Toolset، Advanced Installer

### 3.3 Installers مخصصة
| الأداة | الوصف | متى تستخدمها |
|--------|-------|---------------|
| **Inno Setup** | مجاني، سهل، Pascal-based scripts | أبسط بداية للمشاريع الصغيرة-المتوسطة |
| **NSIS** | مجاني، أكثر مرونة، scripts معقدة | لو تحتاج تخصيصًا فنيًا عاليًا |
| **WiX** | مجاني، يولّد MSI، احترافي | للمشاريع الكبيرة المؤسسية |

> **بداية المبتدئ الموصى بها:** `Inno Setup` أو `MSIX` (حسب نوع التطبيق).

---

## القسم 4: Checklist الشاملة لمكوّنات أي برنامج احترافي

نقسّمها لـ 3 طبقات:

### الطبقة (أ) - مكوّنات المنتج الأساسية

- [ ] **1. واجهة المستخدم (UI)**
  - شاشات واضحة، رسائل خطأ مفهومة، حالات تحميل (Loading States)
  - Empty states، error states، success feedback
  - Keyboard shortcuts، tooltips
  
- [ ] **2. منطق العمل (Business Logic)**
  - قواعد النظام: حسابات، صلاحيات، عمليات
  - فصل واضح عن الـ UI (Separation of Concerns)
  
- [ ] **3. طبقة البيانات (Data Layer)**
  - تخزين محلي: SQLite / ملفات JSON / Registry (بحدود)
  - أو اتصال بخادم/API
  - استراتيجية backup/restore
  
- [ ] **4. طبقة التكامل (Integration)**
  - ملفات، طابعة، USB/Serial، شبكة، Active Directory، إلخ
  - APIs خارجية إذا موجودة

### الطبقة (ب) - مكوّنات تشغيلية (الفرق بين "مشروع" و "منتج")

- [ ] **5. الإعدادات (Configuration)**
  - مكان حفظ الإعدادات:
    - `%APPDATA%` للمستخدم الواحد
    - `%PROGRAMDATA%` لكل المستخدمين
  - ملف config قابل للتعديل بدون إعادة بناء (JSON/YAML/INI)

- [ ] **6. التسجيل (Logging)**
  - ملف Log واضح + مستويات (Debug/Info/Warning/Error/Critical)
  - Rotation (تدوير الملفات لمنع نموها بلا حد)
  - مهم جدًا للدعم الفني واستكشاف الأخطاء

- [ ] **7. معالجة الأخطاء (Error Handling)**
  - رسائل موجهة للمستخدم (User-friendly، بالعربية)
  - تفاصيل تقنية تذهب للـ Log
  - Crash reporting (اختياري)

- [ ] **8. التحديثات (Updates)**
  - Auto-update أو على الأقل آلية تحقق من إصدار جديد
  - تصميم البرنامج بحيث لا "يتكسر" مع التحديث
  - Migration للـ DB schema بين الإصدارات

- [ ] **9. الأمان (Security)**
  - تشفير البيانات الحساسة (AES-256)
  - عدم تخزين كلمات مرور كنص صريح
  - أقل صلاحيات ممكنة (Principle of Least Privilege)
  - فهم UAC: متى Run as Admin ضروري ومتى لا

- [ ] **10. الأداء والاستقرار**
  - Startup سريع قدر الإمكان
  - عدم تجميد الواجهة (UI thread freezing) — استخدم async/background threads
  - Memory leaks check
  - Resource cleanup

- [ ] **11. التوافق (Compatibility)**
  - Windows 10/11؟ 64-bit فقط؟
  - الاعتماديات المطلوبة (.NET Runtime / VC++ Redistributable / Python embedded)
  - اختبار على Windows جديد + قديم

- [ ] **12. إمكانية الوصول (Accessibility)**
  - دعم كيبورد كامل (Tab navigation)
  - تباين الألوان WCAG AA على الأقل
  - حجم خط قابل للتغيير
  - Screen reader compatibility (NVDA/JAWS)
  - مهم خصوصًا في البرامج المؤسسية

- [ ] **13. التعريب/اللغات (Localization)**
  - فصل النصوص عن الكود (Resource files)
  - دعم RTL للعربية كاملًا (ليس مجرّد align right)
  - تنسيق التواريخ والأرقام حسب اللغة

- [ ] **14. التوثيق (Docs)**
  - README للمطورين
  - دليل مستخدم مختصر داخل البرنامج (in-app help)
  - أو PDF dev/user guide

### الطبقة (ج) - مكوّنات الـ Installer نفسه

- [ ] **15. Installer UI**
  - شاشة ترحيب
  - اختيار مسار التثبيت
  - قبول رخصة الاستخدام (EULA)
  - اختيار مكونات (مثل: إضافة اختصار سطح المكتب)
  - Progress bar للتثبيت
  - شاشة نهاية + خيار التشغيل

- [ ] **16. نسخ الملفات + إنشاء مجلدات**
  - `Program Files\HomeUpdater\` للتطبيق
  - `AppData\HomeUpdater\` للبيانات
  - `ProgramData\HomeUpdater\` للإعدادات المشتركة

- [ ] **17. Shortcuts**
  - Start Menu (دائمًا)
  - Desktop (اختياري، يسأل المستخدم)
  - Quick Launch (اختياري)

- [ ] **18. Uninstaller**
  - مسجّل في `Add or remove programs`
  - يشيل الملفات الأساسية بشكل نظيف
  - يسأل عن بيانات المستخدم: حذف أو إبقاء؟

- [ ] **19. Dependencies**
  - تثبيت .NET Runtime إن لم يكن موجودًا
  - تثبيت VC++ Redistributable إن لزم
  - أو على الأقل: رسالة واضحة عن المتطلب المفقود
  - **في حالتنا (Python):** نضمّن Python embedded داخل المجلد (لا يتطلب تثبيت Python على النظام)

- [ ] **20. Permissions / UAC**
  - هل البرنامج يحتاج Admin؟ ولماذا؟
  - حاول تتفادى الـ Admin إن أمكن
  - إذا لازم، اشرح للمستخدم قبل طلب الترقية

- [ ] **21. Code Signing (توقيع رقمي)**
  - **مهم جدًا** عشان لا يطلع تحذير "Unknown Publisher"
  - يقلل مشاكل SmartScreen و Defender
  - يحتاج شهادة من Comodo / DigiCert / Sectigo (~$200-500/سنة)
  - بدائل: Self-signed للاختبار الداخلي فقط

- [ ] **22. Versioning**
  - رقم إصدار واضح بصيغة SemVer: `1.4.2`
  - قواعد الترقية (Upgrade) والتراجع (Downgrade)
  - DB migrations عند تغيير الـ schema

- [ ] **23. Repair / Modify (ميزة MSI غالبًا)**
  - إصلاح التثبيت إذا تخرّبت ملفات
  - تعديل المكونات المثبّتة (إضافة/إزالة)

- [ ] **24. Clean Uninstall**
  - حذف الملفات بالكامل
  - السؤال عن بيانات المستخدم
  - تنظيف Registry entries
  - إزالة Windows Service إذا كانت مثبّتة

---

## القسم 5: خارطة الطريق العملية (للبدء بسرعة بدون تعقيد)

```
1. اختر التقنية (مثلًا: Python+React مع Inno Setup، أو C# WPF)
   ↓
2. بنية مشروع مرتبة (UI / Core / Data / Installer)
   ↓
3. فعّل Logging من البداية ✅
   ↓
4. جهّز إعدادات محفوظة في AppData ✅
   ↓
5. أنشئ Installer بسيطًا (Inno Setup أو MSIX)
   ↓
6. وقّع البرنامج (حتى لو شهادة اختبار داخلي)
   ↓
7. جرّب سيناريوهات:
   - تثبيت جديد على VM نظيف
   - ترقية من إصدار قديم
   - إلغاء تثبيت
   - تشغيل بدون صلاحيات Admin
   - جهاز بدون Runtime (تأكد من التعامل)
```

---

## القسم 6: الأخطاء الشائعة (تجنّبها من البداية)

| الخطأ | لماذا خطأ | الحل |
|------|-----------|------|
| **تخزين ملفات في Program Files والكتابة عليها أثناء التشغيل** | يحتاج Admin، يصطدم مع UAC | اكتب في `AppData` |
| **عدم وجود Logging** | الأعطال "غامضة"، لا يمكن التشخيص | فعّل Logging من اليوم الأول |
| **عدم التفكير في التحديثات من البداية** | إصدار v2 يكسر v1 | صمّم migration من البداية |
| **الاعتماد على .NET Runtime موجود** | يفشل على أجهزة نظيفة | افحص أو ضمّن |
| **Installer لا يسوّي Uninstall نظيف** | تتراكم ملفات وإعدادات | اختبر uninstall قبل النشر |
| **عدم توقيع البرنامج** | تحذيرات SmartScreen المزعجة | وقّع، حتى self-signed للاختبار |
| **الواجهة تتجمّد عند العمليات الطويلة** | تجربة سيئة، يبدو معطلًا | استخدم async/Task/threads |
| **رسائل خطأ تقنية للمستخدم** | يحتار ويزعجك بالأسئلة | رسائل ودودة + Log technical |

---

## القسم 7: تطبيق هذه الـ Checklist على مشروعنا

سنستخدم هذا الجدول في PROGRESS.md ونحدّثه كلما أكملنا عنصرًا:

### مكوّنات المنتج
| العنصر | الحالة | ملاحظات |
|--------|--------|---------|
| 1. UI | 🔲 | ينتظر اختيار stack نهائي |
| 2. Business Logic | 🔲 | discovery + identification + update engine |
| 3. Data Layer | ⏸️ | معتمد SQLite (ADR-002) |
| 4. Integration | 🔲 | nmap + ADB + SSH + APIs |

### مكوّنات تشغيلية
| العنصر | الحالة | ملاحظات |
|--------|--------|---------|
| 5. Configuration | 🔲 | في `AppData/HomeUpdater/config.json` |
| 6. Logging | 🔲 | Python logging + rotation |
| 7. Error Handling | 🔲 | user-friendly + log details |
| 8. Updates | 🔲 | self-update mechanism |
| 9. Security | ⏸️ | معتمد AES-256 (ADR-007) |
| 10. Performance | 🔲 | async I/O، background scans |
| 11. Compatibility | ⏸️ | Win 10/11 64-bit |
| 12. Accessibility | 🔲 | Tab nav + WCAG AA |
| 13. Localization | ⏸️ | عربي + إنجليزي (ADR-010) |
| 14. Documentation | 🟡 | جزئي (دليل المشروع موجود) |

### مكوّنات الـ Installer
| العنصر | الحالة | ملاحظات |
|--------|--------|---------|
| 15. Installer UI | 🔲 | Inno Setup مع شاشات مخصصة بألوان BRAND |
| 16. File copy | 🔲 | `Program Files` + `AppData` + `ProgramData` |
| 17. Shortcuts | 🔲 | Start Menu + Desktop optional |
| 18. Uninstaller | 🔲 | clean + يسأل عن البيانات |
| 19. Dependencies | 🔲 | Python embedded + Nmap bundled |
| 20. Permissions/UAC | 🔲 | تشغيل عادي + رفع للـ network scan فقط |
| 21. Code Signing | 🔲 | لاحقًا، نبدأ self-signed |
| 22. Versioning | 🔲 | SemVer من البداية |
| 23. Repair/Modify | 🔲 | اختياري للـ v1 |
| 24. Clean Uninstall | 🔲 | اختبار VM نظيف |

---

## القسم 8: قواعد ذهبية للمشروع (مستخلصة من كل ما سبق)

1. **Logging من اليوم الأول** — قبل أي feature
2. **Settings في AppData، لا Program Files** — تجنّب UAC issues
3. **اختبر Uninstall كل أسبوع** — لتجنّب تراكم mess
4. **SemVer من البداية** — ولو v0.0.1
5. **رسائل الخطأ بالعربية للمستخدم، بالإنجليزية للـ Log**
6. **لا UI freezing** — كل I/O async
7. **سؤال "هل يعمل بدون Admin؟"** قبل كل feature
8. **اختبار VM نظيف قبل كل release**

---

## مراجع خارجية موصى بها

- [Microsoft App Packaging](https://learn.microsoft.com/en-us/windows/msix/)
- [Inno Setup Docs](https://jrsoftware.org/ishelp/)
- [WiX Toolset](https://wixtoolset.org/)
- [SemVer](https://semver.org/lang/ar/)
- [WCAG 2.1 Accessibility](https://www.w3.org/WAI/standards-guidelines/wcag/)
