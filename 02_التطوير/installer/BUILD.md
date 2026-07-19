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
النتيجة: `backend\dist\HomeUpdater\HomeUpdater.exe` — **تطبيق tray** (بلا نافذة
console) يُشغِّل الخادم في الخلفية ويَعرض أيقونة في شريط النظام، بقائمة نقر-يمين
(افتح HomeUpdater / التوثيق / خروج). المجلَّد onedir يحوي كل شيء: الواجهة المبنيّة،
migrations، والاعتماديات.

**تحقُّق سريع** (يشغّل الخادم بلا فتح متصفّح):
```powershell
$env:HOMEUPDATER_NO_BROWSER=1
.\dist\HomeUpdater\HomeUpdater.exe
# أيقونة tray تَظهر؛ افتح http://127.0.0.1:8000 — الواجهة تعمل و /api/system/health يرجع healthy
```

> الـ exe يُشغِّل `alembic upgrade head` تلقائياً عند الإقلاع، ويَخدم الواجهة والـ API
> من خادم واحد على المنفذ 8000. نقطة الدخول `tray.py`؛ و`launcher.py` بديل console للتشخيص.

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

### تضمين Nmap (اكتشاف الشبكة)
اكتشاف الأجهزة يحتاج `nmap`. لتضمينه في المثبِّت:
1. نزّل Nmap portable وضع ملفّاته في `installer\vendor\nmap\`.
2. أزِل التعليق عن سطر `Source: "vendor\nmap\*"` في `HomeUpdater.iss`.
3. التزم برخصة Nmap (GPL) — أرفِق ملفّ الترخيص.
بدون ذلك، يعمل كل شيء عدا المسح الشبكي (يظهر خطأ واضح للمستخدم).

---

## ملاحظات
- **الأيقونة والهوية البصرية** (شاشات المُثبِّت، أيقونة الـ exe): تُضاف في Phase A —
  المواضع مُعلَّمة بـ `TODO` في `HomeUpdater.iss` و`HomeUpdater.spec`.
- **بيانات المستخدم** (`%APPDATA%\HomeUpdater`: قاعدة البيانات، الإعدادات، السجلّات)
  تبقى بعد إلغاء التثبيت عمداً.
- **صلاحيات المدير**: المثبِّت والتطبيق يطلبان UAC (لازم لـ Windows Update/winget/nmap).
- **توقيع الكود** (Code Signing): غير مُطبَّق بعد (Phase B.7) — سيَظهر تحذير SmartScreen
  حتى تُوقَّع النسخة النهائية.
