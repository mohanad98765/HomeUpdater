# نشر HomeUpdater في بيئة مؤسّسية (Enterprise deployment)

هذا الدليل يشرح كيف تُوزَّع الحزمة على عدّة أجهزة بلا تدخّل يدويّ — عبر **Microsoft Intune**
أو **سياسة المجموعة (GPO)** أو أي أداة توزيع تُشغّل ملفًّا تنفيذيًّا.

> كل القيم أدناه مُتحقَّق منها فعليًّا على تثبيتٍ حقيقيّ، لا مُقدَّرة.

---

## 1. المثبّت وخصائصه

| الخاصية | القيمة | لماذا تهمّ |
|---|---|---|
| نوع التثبيت | **لكل الجهاز (per-machine)** — `PrivilegesRequired=admin` + `{autopf}` | يُثبَّت مرّة واحدة لكل الأجهزة، لا لكل مستخدم |
| مسار التثبيت | `C:\Program Files\HomeUpdater\` | |
| المعرّف الثابت (AppId) | `{8F3A1C7E-2B4D-4E6A-9C1F-5D7E8A9B0C1D}` | **لا يتغيّر بين الإصدارات** — فالترقية تحلّ محلّ القديم بنظافة |
| التشغيل بعد التثبيت | مُعطَّل في الوضع الصامت (`skipifsilent`) | لا تفتح واجهة على شاشة المستخدم أثناء النشر |
| البنية | x64 | |

## 2. أوامر التثبيت الصامت

**تثبيت (أو ترقية) صامت كامل:**

```
HomeUpdater-Setup-1.5.10.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP- /LOG="%ProgramData%\HomeUpdater-install.log"
```

**اختيار المهام الاختيارية صراحةً** (أيقونة سطح المكتب / التشغيل عند الدخول):

```
HomeUpdater-Setup-1.5.10.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /MERGETASKS="!desktopicon,!startuptask"
```

- `!desktopicon` = **بلا** أيقونة سطح مكتب · `desktopicon` = بها.
- `!startuptask` = **بلا** تشغيل تلقائيّ عند الدخول (يُنصح به في النشر المؤسّسيّ).

**إزالة صامتة:**

```
"C:\Program Files\HomeUpdater\unins000.exe" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART
```

> **ترقية على جهاز يعمل عليه التطبيق:** السكربت يضبط `CloseApplications=no`، فالملفّات المفتوحة
> قد تفرض إعادة تشغيل. في النشر الجماعي أَنْهِ العملية أولًا:
> `taskkill /F /T /IM HomeUpdater.exe` ثم شغّل المثبّت.

## 3. النشر عبر Microsoft Intune (تطبيق Win32)

1. **حزّم** المثبّت بأداة مايكروسوفت `IntuneWinAppUtil.exe` (Microsoft Win32 Content Prep Tool)
   لتحصل على `HomeUpdater-Setup-<الإصدار>.intunewin`.
2. **أمر التثبيت:**
   ```
   HomeUpdater-Setup-1.5.10.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /MERGETASKS="!desktopicon,!startuptask"
   ```
3. **أمر الإزالة:**
   ```
   "C:\Program Files\HomeUpdater\unins000.exe" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART
   ```
4. **سياق التثبيت:** System (الجهاز) · **سلوك إعادة التشغيل:** لا يلزم (No specific action).
5. **قاعدة الكشف (Detection rule)** — **مُتحقَّق منها على جهاز مُثبَّت فعلًا**، من نوع **Registry**:

   | الحقل | القيمة |
   |---|---|
   | المسار | `HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{8F3A1C7E-2B4D-4E6A-9C1F-5D7E8A9B0C1D}_is1` |
   | القيمة | `DisplayVersion` |
   | نوع المقارنة | Version · **greater than or equal to** · `1.5.10` |
   | العرض (Registry view) | **64‑bit** — ⚠️ المفتاح **غير موجود** في `WOW6432Node`، فلا تُفعّل «تطبيق على 32‑بت» |

   *(بديل أبسط: كشف بوجود الملف `C:\Program Files\HomeUpdater\HomeUpdater.exe`.)*

## 4. النشر عبر سياسة المجموعة (GPO) أو أداة توزيع أخرى

Inno Setup لا يُنتج MSI، فلا تُستخدم «Software Installation» في GPO. الطريقة الصحيحة:
**سكربت بدء تشغيل للجهاز (Computer Startup Script)** يُشغِّل المثبّت من مشاركة شبكية،
مع حراسة تمنع إعادة التثبيت في كل إقلاع:

```powershell
# Startup script (سياق الجهاز). يُثبِّت مرّة واحدة، ويُرقّي فقط عند صدور إصدار أحدث.
$target  = '1.5.10'
$setup   = '\\srv\share\HomeUpdater-Setup-1.5.10.exe'
$key     = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{8F3A1C7E-2B4D-4E6A-9C1F-5D7E8A9B0C1D}_is1'
$current = (Get-ItemProperty $key -ErrorAction SilentlyContinue).DisplayVersion
if (-not $current -or [version]$current -lt [version]$target) {
    taskkill /F /T /IM HomeUpdater.exe 2>$null | Out-Null      # حرّر الملفّات المفتوحة
    Start-Process $setup -Wait -ArgumentList `
        '/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/MERGETASKS=!desktopicon,!startuptask'
}
```

## 5. التوقيع وثقة ويندوز (مهمّ قبل أي نشر واسع)

الإصدارات الحالية موقَّعة بشهادة **ذاتية التوقيع** — أي أن **SmartScreen يحذّر**، وسياسات
**WDAC/AppLocker** قد **تحجب الملفّ قبل أن يراه أي مستخدم**. لذلك:

- خطّ الإصدار في CI **مُهيَّأ مسبقًا** لشهادة معتمدة: ضع سرّي المستودع
  `SIGNING_PFX_BASE64` و`SIGNING_PFX_PASSWORD` فيتحوّل التوقيع تلقائيًّا إلى `trusted`
  (`.github/workflows/release.yml`). ولا يحتاج ذلك أي تغيير في الكود.
- محليًّا: `installer\sign.ps1 -Thumbprint <بصمة>` أو `-PfxPath <ملف>`.
- **الفرق العمليّ:** شهادة **OV** تُزيل التحذير تدريجيًّا ببناء السمعة؛ شهادة **EV** تُزيله
  من أول تنزيل. الذاتية تحذّر دائمًا.
- ⚠️ **الشهادة الذاتيّة تُولَّد من جديد في كل بناء، فبصمتها تتغيّر مع كل إصدار.** مثال
  محقَّق: v1.10.1 بصمتها `E395B408…` وv1.10.2 بصمتها `E329712D…`. النتيجة العمليّة:
  **لا تُدرِج الشهادة نفسها في قائمة سماح** (WDAC/AppLocker/Smart App Control) لأن
  الإصدار التالي سيُحجَب؛ ولا تُبنى أي سمعة SmartScreen لأن كل بناء «ناشر جديد».
  الحلّ هو سرّ `SIGNING_PFX_BASE64` بشهادة **ثابتة** (ولو ذاتيّة للتجارب الداخليّة،
  والأفضل OV/EV للنشر) — قبل ذلك، السماح الوحيد الممكن هو بالهاش لكل إصدار.

## 6. ما يحتاجه الجهاز الهدف

- Windows 10/11 x64 (أو Windows Server حديث).
- **WebView2 Runtime** (مثبَّت أصلًا على أغلب أنظمة ويندوز 11).
- صلاحية مسؤول للتثبيت.
- **لا** يلزم فتح أي منفذ وارد: واجهة التطبيق محليّة على `127.0.0.1` فقط.

---

## ملاحظة صريحة على الحدود الحالية

إدارة الأجهزة **الأخرى** عن بُعد تعتمد اليوم على **WinRM ببيانات مسؤول مخزَّنة**، وهي
**تفشل على الأجهزة المضمّة لدومين والمُقسّاة بأساس أمنيّ** (سياسة «منع الوصول إلى هذا
الجهاز من الشبكة» للحسابات المحلّية) — وهذا حدٌّ معماريّ لا عيب قابل للإصلاح بإعداد.
الحلّ المخطَّط هو **وكيل خفيف** يعمل كـ`LOCAL SYSTEM` باتصال صادر فقط، فينفّذ محليًّا
بلا «تسجيل دخول شبكيّ» وبلا كلمات مرور مخزَّنة. حتى ذلك الحين: هذا الدليل يغطّي **نشر
التطبيق نفسه** على عدّة أجهزة، وهو مسار مدعوم بالكامل.
