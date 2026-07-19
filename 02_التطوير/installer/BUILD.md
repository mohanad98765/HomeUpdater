# بناء الـ Installer — HomeUpdater

دليل إنتاج ملفّ التثبيت `HomeUpdater-Setup-x.y.z.exe` من الصفر. ثلاث مراحل متسلسلة.

## المتطلّبات (مرّة واحدة)
- **Python 3.12** (البيئة الافتراضية في `backend/.venv`).
- **Node.js 20+** (لبناء الواجهة).
- **PyInstaller**: `backend\.venv\Scripts\python.exe -m pip install pyinstaller`
- **Inno Setup 6** (للمرحلة 3): <https://jrsoftware.org/isdl.php> — يوفّر `iscc.exe`.
- **(اختياري) Nmap portable** لتضمينه — راجع المرحلة 3.

---

## المرحلة 1 — بناء الواجهة (Frontend)
```powershell
cd 02_التطوير\frontend
npm ci
npm run build       # يُنتج frontend\dist
```

## المرحلة 2 — تجميع الـ Backend في exe واحد (PyInstaller)
```powershell
cd 02_التطوير\backend
.\.venv\Scripts\python.exe -m PyInstaller HomeUpdater.spec --noconfirm
```
النتيجة: `backend\dist\HomeUpdater\HomeUpdater.exe` — **تطبيق بنافذة أصلية**
(WebView2) بلا نافذة console وبلا متصفّح: نقطة الدخول `app_window.py` تُشغِّل الخادم
في خيط خلفي وتعرض الواجهة في نافذة تطبيق حقيقية. إن كان WebView2 غير مثبّت (نادر على
Win11) يفتح المتصفّح تلقائياً كبديل. المجلَّد onedir يحوي كل شيء: الواجهة المبنيّة،
migrations، والاعتماديات. (`tray.py` يبقى نقطة دخول بديلة بأيقونة شريط النظام + متصفّح.)

**تحقُّق سريع** (نقرة مزدوجة = تظهر نافذة التطبيق الأصلية):
```powershell
.\dist\HomeUpdater\HomeUpdater.exe
# تفتح نافذة "HomeUpdater — محدِّث المنزل" (WebView2)؛ /api/system/health يرجع healthy
```

> الـ exe يُشغِّل `alembic upgrade head` تلقائياً عند الإقلاع، ويَخدم الواجهة والـ API
> من خادم واحد على المنفذ 8000. نقطة الدخول `app_window.py` (نافذة أصلية)؛ `tray.py`
> بديل (tray + متصفّح)؛ و`launcher.py` بديل console للتشخيص.
> النافذة الأصلية تحتاج **WebView2 Runtime** (مثبّت افتراضياً على Windows 11).

### تشغيله كخدمة Windows (اختياري — يعمل بلا تسجيل دخول)
`service.py` يُسجِّل الـ backend كخدمة Windows (يحتاج صلاحيات مدير):
```powershell
cd 02_التطوير\backend
.\.venv\Scripts\python.exe service.py install
.\.venv\Scripts\python.exe service.py start     # stop / remove للإيقاف / الإزالة
```
الخدمة تعمل headless (بلا أيقونة tray) وتُبقي الـ hub شغّالاً بعد تسجيل الخروج.

## المرحلة 3 — بناء ملفّ التثبيت (Inno Setup)
```powershell
cd 02_التطوير\installer
iscc HomeUpdater.iss
```
النتيجة: `installer\Output\HomeUpdater-Setup-<version>.exe` — ملفّ تثبيت واحد
بنقرة مزدوجة، مع اختصارات Start Menu/Desktop و uninstaller. الإصدار يُقرأ تلقائياً
من `backend\VERSION`.

## المرحلة 4 — توقيع الكود (Code Signing)
بعد بناء الـ exe والمثبِّت، وقِّعهما رقمياً (يزيل تحذير «ناشر غير معروف» ويكشف العبث):
```powershell
cd 02_التطوير\installer
.\sign.ps1 -CreateCert -ExportCert   # أوّل مرّة: ينشئ شهادة موقَّعة ذاتياً ويوقِّع
```
**السلسلة الصحيحة:** وقِّع الـ exe → أعد بناء المثبِّت (ليحزم الـ exe الموقَّع) →
وقِّع المثبِّت. التفاصيل الكاملة، وكيفية الوثوق بالشهادة محلياً، والترقية لشهادة
حقيقية (OV/EV) لأجهزة الآخرين وSmart App Control — في [SIGNING.md](SIGNING.md).

### اكتشاف الشبكة — بلا Nmap
المسح الشبكي يعمل **بلغة Python خالصة** (جسّ TCP + قراءة جدول ARP) — لا يحتاج
`nmap` ولا `Npcap` ولا صلاحيات مدير (`settings.scan_method="auto"`). إن ثبّت
المستخدم nmap بنفسه، يُستخدم تلقائياً كتحسين. لا نُضمّن Npcap (ترخيصه يقيّد التوزيع).

---

## ملاحظات
- **الهوية البصرية جاهزة:** الأيقونة (`generate_icons.py`) وبانرات المعالج + splash
  (`generate_wizard_banners.py`) مربوطة في `HomeUpdater.iss`/`HomeUpdater.spec`.
  لإعادة توليدها من شعارك، عدّل السكربتين في `03_الموارد\logo\` وأعِد تشغيلهما
  (بانرات المعالج تحتاج `arabic-reshaper` و`python-bidi` وقت التوليد فقط).
- **بيانات المستخدم** (`%APPDATA%\HomeUpdater`: قاعدة البيانات، الإعدادات، السجلّات)
  تبقى بعد إلغاء التثبيت عمداً.
- **صلاحيات المدير**: المثبِّت والتطبيق يطلبان UAC (لازم لـ Windows Update/winget/nmap).
- **توقيع الكود** (Code Signing): ✅ مُطبَّق — الـ exe والمثبِّت موقَّعان SHA-256 +
  طابع زمني عبر `sign.ps1` (شهادة موقَّعة ذاتياً حالياً). للتوزيع لأجهزة الآخرين
  ولإرضاء Smart App Control تلزم شهادة **EV** من هيئة تصديق — انظر [SIGNING.md](SIGNING.md).
