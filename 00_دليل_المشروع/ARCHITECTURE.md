# ARCHITECTURE.md
## المعمارية التقنية للمشروع

---

## 1. المعمارية على مستوى عالٍ (High-Level Architecture)

```
┌──────────────────────────────────────────────────────────────────┐
│                  مستخدم (المتصفح)                                 │
│              http://localhost:8080                               │
└───────────────────────────┬──────────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────────┐
│              HUB (يعمل على Windows PC أو Docker)                  │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │              Web UI (React + Tailwind)                      │  │
│  └─────────────────────────┬──────────────────────────────────┘  │
│                            │ REST API                            │
│  ┌─────────────────────────▼──────────────────────────────────┐  │
│  │              Backend (Python FastAPI)                       │  │
│  │  ┌──────────────┐ ┌──────────────┐ ┌──────────────────┐    │  │
│  │  │ Discovery    │ │ Inventory DB │ │ Update Engine    │    │  │
│  │  │ Service      │ │ (SQLite)     │ │ (Per-device)     │    │  │
│  │  └──────┬───────┘ └──────┬───────┘ └────────┬─────────┘    │  │
│  └─────────┼────────────────┼──────────────────┼──────────────┘  │
└────────────┼────────────────┼──────────────────┼─────────────────┘
             │                │                  │
             ▼                ▼                  ▼
    ┌────────────────┐ ┌────────────┐  ┌─────────────────────────┐
    │ Network Scan   │ │ External   │  │ Device Modules          │
    │ - nmap         │ │ Sources    │  │ - winget (Windows)      │
    │ - mDNS         │ │ - Vendor   │  │ - apt/dnf (Linux SSH)   │
    │ - SSDP/UPnP    │ │   APIs     │  │ - ADB (Android)         │
    │ - ARP scan     │ │ - GitHub   │  │ - OpenWRT API           │
    │                │ │   Releases │  │ - Home Assistant API    │
    │                │ │ - CVE feeds│  │ - Custom scrapers       │
    └────────────────┘ └────────────┘  └─────────────────────────┘
```

---

## 2. الـ Stack التقني المختار

### Backend
- **اللغة:** Python 3.11+
  - **لماذا؟** أكثر مكتبات شبكات وأمن متاحة، nmap-python، scapy، paramiko (SSH)، adb-shell، إلخ
- **الإطار:** FastAPI
  - **لماذا؟** سريع، توثيق تلقائي (Swagger)، Type hints، WebSockets جاهزة
- **قاعدة البيانات:** SQLite (في v1)، PostgreSQL لاحقًا
  - **لماذا؟** SQLite بدون إعداد، ملف واحد، يكفي لشبكة منزلية

### Frontend
- **الإطار:** React + Vite
- **التصميم:** Tailwind CSS + shadcn/ui
- **الحالة:** TanStack Query (للتزامن مع الـ API)
- **اللغة:** عربي (RTL) كافتراضي، إنجليزي اختياري

### Discovery & Networking
- **nmap** — الفحص الشامل
- **scapy** — ARP/mDNS/SSDP يدويًا
- **zeroconf (Python)** — اكتشاف mDNS
- **upnpclient** — اكتشاف UPnP/SSDP

### Update Modules
- **winget-cli** — لـ Windows
- **paramiko / asyncssh** — لـ SSH على Linux و OpenWRT
- **adb-shell** — للأندرويد
- **homeassistant-api** أو REST مباشر — لأجهزة المنزل الذكي
- **HTTP scrapers مخصصة** — لكل مصنّع راوتر معروف

### External Data Sources
- **NVD CVE Feed** — للثغرات الأمنية
- **GitHub Releases API** — للتحديثات المجتمعية
- **Vendor APIs** — Microsoft Update Catalog, Apple PMRSS, إلخ

---

## 3. مكوّنات النظام (Components)

### 3.1 Discovery Service
**المسؤولية:** اكتشاف كل الأجهزة في الشبكة كل X دقيقة (افتراضي: 30)

**الإخراج:** قائمة أجهزة بالبيانات التالية:
- IP address
- MAC address
- Hostname (إذا متاح)
- Vendor (من MAC OUI)
- Open ports
- mDNS service (مثل `_googlecast._tcp` للـ Chromecast)
- UPnP description

### 3.2 Identification Service
**المسؤولية:** تحويل بيانات الاكتشاف إلى "نوع جهاز معروف"

**التقنية:** Rule engine + Fingerprint database

```
mac_oui = "00:1A:11"  (Google) +
mdns = "_googlecast._tcp"
→ Device type = "Chromecast"
→ Update module = "chromecast_module"
```

### 3.3 Inventory Database
**المسؤولية:** تخزين كل الأجهزة المعروفة وحالتها التاريخية

**الجداول الرئيسية:**
- `devices` — الأجهزة
- `firmware_versions` — تاريخ الإصدارات لكل جهاز
- `updates_available` — التحديثات المتاحة حاليًا
- `update_history` — سجل التحديثات السابقة (نجاح/فشل)
- `sources` — المصادر التي جلبنا منها التحديثات

### 3.4 Update Engine
**المسؤولية:** تنفيذ التحديثات بحسب نوع الجهاز

**النمط:** Plugin Architecture
- كل نوع جهاز له `module` خاص
- كل module يطبّق واجهة موحّدة:
  ```python
  class UpdateModule:
      def detect(device) -> bool
      def get_current_version(device) -> str
      def get_available_updates(device) -> List[Update]
      def apply_update(device, update) -> Result
  ```

### 3.5 Sources Aggregator
**المسؤولية:** جلب معلومات التحديثات من كل المصادر

**المصادر:**
- **رسمية:** Microsoft, Apple, Google, Samsung, إلخ
- **CVE:** NIST NVD, CISA KEV
- **مجتمعية:** GitHub Releases, OpenWRT, XDA, LineageOS

كل تحديث مخزّن في DB مع:
- `source_name` (e.g., "Microsoft Update Catalog")
- `source_type` (official / community / unofficial)
- `trust_level` (verified / community / experimental)
- `published_at`
- `release_notes_url`

### 3.6 Web UI
**صفحات أساسية:**
1. **Dashboard** — نظرة عامة (عدد الأجهزة، تحديثات معلّقة، تنبيهات أمنية)
2. **Devices** — قائمة كل الأجهزة + تفاصيل كل واحد
3. **Updates** — التحديثات المتاحة، فلترة حسب الجهاز/المصدر
4. **History** — سجل ما تم تحديثه
5. **Settings** — إعدادات الشبكة، الجدولة، الإشعارات

---

## 4. تدفق البيانات (Data Flow)

### مثال: اكتشاف وتحديث جهاز Windows
```
1. Discovery Service scan (كل 30 دقيقة)
   → يجد IP 192.168.1.50, MAC ab:cd:ef:..., port 5985 مفتوح (WinRM)
   
2. Identification
   → MAC OUI = Intel/Microsoft + WinRM port → "Likely Windows PC"
   
3. Connect via WinRM (إذا الـ credentials محفوظة)
   → يطلب اسم الجهاز، الإصدار، البرامج المثبّتة
   
4. Backend يخزّن في DB:
   device: {hostname: "PC-MOHAND", os: "Windows 11 23H2"}
   software: [Chrome 120.0, Office 2021, ...]
   
5. Sources Aggregator
   → يستعلم Microsoft Update Catalog, winget index
   → يجد: Chrome 121.0 متاح، Windows Update KB5034441
   
6. UI يعرض في صفحة Updates:
   "PC-MOHAND: 2 updates available"
   
7. المستخدم يضغط "Update All"
   → Update Engine يستدعي winget_module.apply_update()
   → ينفذ remotely عبر WinRM: winget upgrade --all
   
8. Update History يسجل النتيجة
```

---

## 5. الأمان (Security)

هذا أهم قسم. البرنامج يصل لكل أجهزة الشبكة، فأي خرق يعني كارثة.

### مبادئ
1. **Local-only by default**: لا يتصل بأي خادم خارجي إلا للحصول على معلومات التحديثات
2. **Credentials encrypted**: كلمات السر للأجهزة (راوتر، SSH) مشفّرة بـ AES-256 بمفتاح من passphrase المستخدم
3. **Read-only by default**: لا ينفذ أي تحديث بدون موافقة صريحة (إلا إذا فعّل المستخدم Auto-mode)
4. **Audit log**: كل عملية تعديل مسجّلة بالتاريخ والمستخدم
5. **No telemetry**: لا نرسل بيانات لأي جهة خارجية

### تهديدات نتعامل معها
- **MITM** على تحميل التحديثات → نتحقق من checksum/signature
- **Credentials leak** → مشفّرة على القرص
- **Bricking devices** → نتأكد من نموذج الجهاز قبل تطبيق firmware

---

## 6. النشر (Deployment)

### Option A: Native Windows App (مستحسن للمستخدم العادي)
- ملف `.exe` واحد (PyInstaller)
- يفتح المتصفح تلقائيًا
- يُثبت كـ Service ليشتغل في الخلفية

### Option B: Docker (مستحسن للمتقدمين)
- `docker-compose.yml` يشغّل كل الخدمات
- يعمل على أي نظام (لو نقلت للسيرفر مستقبلًا)

### Option C: Raspberry Pi (لاحقًا)
- صورة جاهزة للحرق على SD
- يشتغل 24/7 بدون تأثير على الكمبيوتر الرئيسي

في v1 نركّز على **Option A**.

---

## 7. القيود التي يجب احترامها

1. **لا تستخدم credentials مكتوبة في الكود** — كل شيء عبر إعدادات
2. **لا تنفّذ تحديث firmware بدون تأكيد المستخدم وعرض warning** حتى في وضع Auto
3. **اسمح بـ rollback** عند الإمكان (احفظ نسخة من firmware القديم)
4. **سجّل كل شيء** — عند مشكلة، سنحتاج logs مفصّلة

---

## 8. ما لم نقرّره بعد (Open Questions)

- [ ] هل ندعم تحديث Bluetooth devices في v1؟
- [ ] هل نضيف dashboard mobile (Flutter / React Native)؟
- [ ] هل نكامل مع Tailscale لإدارة عن بُعد؟
- [ ] كيف نعرض ملاحظات الإصدار بالعربية (هل نترجم تلقائيًا)؟

كل هذه الأسئلة تُجاب عند الوصول للمرحلة المناسبة.
