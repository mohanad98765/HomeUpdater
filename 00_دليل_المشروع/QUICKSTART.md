# QUICKSTART.md
## دليل البدء السريع

> هذا الملف هو "الخطوة-الأولى" عندما ترغب فعليًا في تشغيل المشروع.
>
> **ملاحظة:** المشروع لم يبدأ تطويره بعد. هذا الدليل يحضّر بيئتك ليكون كل شيء جاهزًا عندما نكتب الكود.

---

## 1. متطلبات النظام

| المتطلب | الإصدار | لماذا |
|---------|---------|-------|
| Windows | 10 / 11 | المنصة المختارة |
| RAM | 4 GB+ | كافي لتشغيل Python + DB + UI |
| مساحة التخزين | 2 GB | للأدوات والـ DB |
| اتصال بالشبكة | LAN/WiFi | لاكتشاف الأجهزة |
| صلاحيات | Administrator | لتشغيل nmap وفحص الشبكة |

---

## 2. الأدوات التي ستثبّتها (مرة واحدة)

### 2.1 Python
- اذهب لـ: https://www.python.org/downloads/
- نزّل **Python 3.11 أو أحدث**
- ⚠️ **مهم جدًا:** عند التثبيت، فعّل خيار **"Add Python to PATH"**
- بعد التثبيت، افتح PowerShell واكتب:
  ```
  python --version
  ```
  يجب أن يظهر `Python 3.11.x` أو أحدث.

### 2.2 Nmap
- اذهب لـ: https://nmap.org/download.html
- نزّل **Nmap لـ Windows (Installer)**
- ثبّته بالخيارات الافتراضية
- بعد التثبيت، افتح PowerShell جديد:
  ```
  nmap --version
  ```

### 2.3 Node.js (للواجهة)
- اذهب لـ: https://nodejs.org/
- نزّل **النسخة LTS** (الأرقام الزوجية، مثل 20.x أو 22.x)
- ثبّته بالخيارات الافتراضية
- تحقق:
  ```
  node --version
  npm --version
  ```

### 2.4 Git (اختياري لكن موصى به)
- اذهب لـ: https://git-scm.com/download/win
- ثبّت **Git for Windows**
- يفيدك في حفظ تغييرات الكود

### 2.5 محرر كود
**اختر واحدًا:**
- **VS Code** (موصى به للمبتدئين): https://code.visualstudio.com
- **Cursor** (إذا تريد AI مدمج): https://cursor.com

---

## 3. خطوات البدء (عندما يصبح الكود جاهزًا)

> ⚠️ **ملاحظة:** الكود لم يكتب بعد. الخطوات أدناه ستكون متاحة بعد إنجاز Phase 1.

```powershell
# 1. ادخل لمجلد المشروع
cd "D:\تجاربي الخاصة\تحديث كل شيء في المنزل\02_التطوير"

# 2. أنشئ Python environment
python -m venv venv
.\venv\Scripts\Activate.ps1

# 3. ثبّت المتطلبات
pip install -r backend\requirements.txt

# 4. شغّل الـ Backend
cd backend
python main.py

# 5. في نافذة Terminal جديدة، شغّل الـ Frontend
cd ..\frontend
npm install
npm run dev

# 6. افتح المتصفح
# http://localhost:5173
```

---

## 4. أول استخدام (عند الجاهزية)

1. افتح المتصفح على `http://localhost:5173`
2. ستظهر شاشة الترحيب
3. اضغط **"ابدأ الفحص الأول"**
4. انتظر 30-60 ثانية
5. ستظهر قائمة بكل الأجهزة في شبكتك
6. لكل جهاز، يقدر البرنامج أن:
   - يعرض معلوماته
   - يبحث عن تحديثات متاحة
   - يطبّق التحديث (إذا الجهاز مدعوم)

---

## 5. حل المشاكل الشائعة (Troubleshooting)

### "Python is not recognized"
- لم تفعّل **Add to PATH** عند التثبيت
- الحل: أعد تثبيت Python واختر الخيار

### "nmap requires administrator privileges"
- شغّل PowerShell كـ Administrator
- (يمين-ضغط على PowerShell → Run as administrator)

### "البرنامج لا يكتشف بعض الأجهزة"
- بعض الأجهزة تخفي نفسها (Smart TVs غالبًا)
- جرّب تشغيلها أولًا قبل الفحص
- بعض الراوترات تمنع ARP scan — تحقق من إعدادات الراوتر

### "Windows Defender يحظر الأداة"
- Defender أحيانًا يشك بأدوات فحص الشبكة
- استثناء: Settings → Defender → Add exclusion → اختر مجلد المشروع

---

## 6. مساعدة من Claude

في أي مرحلة، تقدر ترجع لـ Claude (في Cowork) وتقول:

- "افتح المشروع في `D:\تجاربي الخاصة\تحديث كل شيء في المنزل` واقرأ PROGRESS.md ثم كمّل من حيث توقفنا"
- "أنا في مهمة 1.2.1 وأحتاج مساعدة"
- "هذا الـ error: ..."

Claude يقرأ الملفات ويعرف بالضبط أين أنتم في المشروع.

---

## 7. نصائح للمستخدم العادي

1. **لا تبدأ كل شيء في يوم واحد**: قسّم العمل على جلسات قصيرة (30-60 دقيقة)
2. **اختبر كل خطوة قبل التالية**: لا تكتب 100 سطر ثم تشغّل
3. **حدّث PROGRESS.md دائمًا**: في النهاية كل جلسة، ولو سطرين
4. **اسأل Claude متى ما توقفت**: لا تضيع ساعات على مشكلة بسيطة

---

## 8. روابط مفيدة

- **Python tutorial بالعربية**: https://www.youtube.com/results?search_query=python+tutorial+arabic
- **FastAPI docs**: https://fastapi.tiangolo.com/
- **React docs**: https://react.dev/
- **Tailwind CSS**: https://tailwindcss.com/docs
- **Nmap reference**: https://nmap.org/book/

---

تذكّر: هذا مشروع طويل النفس. الهدف ليس الإنجاز السريع، بل بناء شيء **يعمل ويستمر**.
