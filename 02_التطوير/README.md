# 02_التطوير — مجلد الكود الفعلي

> هنا يعيش الكود الذي نطوّره. الوثائق المرجعية في `00_دليل_المشروع/`.

## كيف تبدأ

### المرة الأولى فقط (إعداد البيئة):
1. انقر نقرًا مزدوجًا على **`setup.bat`** (Run as Administrator)
2. انتظر حتى ينتهي السكريبت من تثبيت كل المتطلبات (Python, Node, Nmap, Git)
3. اقرأ الرسائل في الشاشة للتأكد من نجاح كل خطوة

### كل مرة بعد ذلك:
- انقر نقرًا مزدوجًا على **`run.bat`**
- المتصفح يفتح تلقائيًا على `http://localhost:5173`

## بنية المجلدات

```
02_التطوير/
├── setup.bat            ← إعداد البيئة (المرة الأولى فقط)
├── setup.ps1            ← السكريبت الفعلي (لا تشغّله مباشرة)
├── run.bat              ← تشغيل المشروع كل مرة
├── stop.bat             ← إيقاف الـ servers
│
├── backend/             ← كود Python (FastAPI)
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py      ← نقطة الدخول
│   │   ├── config.py    ← الإعدادات
│   │   ├── logging_setup.py
│   │   ├── routers/     ← API endpoints
│   │   ├── services/    ← Business logic
│   │   ├── models/      ← Database models
│   │   └── modules/     ← Update modules (Plugin architecture)
│   ├── requirements.txt
│   ├── pyproject.toml
│   └── VERSION
│
├── frontend/            ← React + Vite + Tailwind
│   ├── src/
│   │   ├── App.tsx
│   │   ├── main.tsx
│   │   ├── components/
│   │   ├── pages/
│   │   └── lib/
│   ├── public/
│   ├── package.json
│   ├── tailwind.config.js
│   └── vite.config.ts
│
├── scripts/             ← سكريبتات PowerShell مساعدة (تُستدعى من run.bat)
│   ├── start_backend.ps1   ← يُشغِّل FastAPI ويحفظ log
│   └── start_frontend.ps1  ← يُشغِّل Vite ويحفظ log
│
├── logs/                ← (يُنشأ تلقائيًا) ملفات السجل لكل تشغيل
│   ├── setup_*.log        ← مخرجات setup الكاملة
│   ├── run_*.log          ← خطوات المُشغِّل
│   ├── backend_*.log      ← مخرجات FastAPI الحيَّة
│   └── frontend_*.log     ← مخرجات Vite الحيَّة
├── data/                ← (يُنشأ تلقائيًا) قاعدة البيانات
│
├── .gitignore
└── README.md            ← هذا الملف
```

## معلومات تقنية

- **Backend Port:** `http://localhost:8000`
- **Frontend Port:** `http://localhost:5173`
- **API Docs:** `http://localhost:8000/docs` (Swagger تلقائي)

## استكشاف الأخطاء

إذا واجهت مشاكل، اقرأ `تعليمات_التشغيل.md` في هذا المجلد.
