# DEVICES.md
## كتالوج الأجهزة المدعومة

> هذا الملف يصف **كل فئة جهاز** نتعامل معها: كيف نكتشفها، كيف نحدّثها، ومصادر التحديث، وحدودها.

---

## مفتاح الرموز
- ✅ مدعوم بالكامل (تلقائي)
- ⚠️ مدعوم جزئيًا (تنبيه أو نصف تلقائي)
- ❌ غير ممكن (قيد من المصنّع)
- 🟡 قيد التخطيط

---

## 1. أجهزة الكمبيوتر

### 1.1 Windows (10/11)
| البند | التفصيل |
|-------|---------|
| الاكتشاف | ARP scan + nmap (port 5985 WinRM, 445 SMB) |
| التعرّف | MAC OUI + SMB OS detection + hostname |
| التحديث (الجهاز المحلي / الـ hub) | ✅ تلقائي عبر `winget upgrade --all` (للبرامج) + Windows Update (للنظام) + التعريفات |
| التحديث (أجهزة Windows أخرى عن بُعد) | ✅ عبر WinRM (المرحلة 1.6): صفحة «Windows بعيد» تُشغّل winget على الهدف |
| المصادر الرسمية | Microsoft Update Catalog, winget index |
| المصادر غير الرسمية | Chocolatey, Scoop |
| المتطلبات (المحلي) | صلاحيات Admin على الـ hub |
| المتطلبات (عن بُعد) | تفعيل WinRM على الهدف + بيانات اعتماد مسؤول |
| الحدود | أدوات Windows Update/winget تنفَّذ محلياً على كل جهاز؛ التحديث عن بُعد يحتاج WinRM لأن لا API سحابياً مركزياً. بعض البرامج لا تدعم winget |

> **لماذا التحديث المحلي فقط الآن؟** `Windows Update` و`winget` أدوات تعمل على
> الجهاز نفسه، فتحديث الـ hub مباشر. تحديث أجهزة Windows أخرى يتطلّب قناة تنفيذ
> عن بُعد — الخيار العملي هو **WinRM** (PowerShell Remoting)، وهو ما تغطّيه
> المرحلة 1.6 أدناه. (أجهزة لينكس/الأندرويد/أجهزة HA تُحدَّث عن بُعد فعلاً عبر
> SSH/ADB/REST — الفجوة محصورة في أجهزة Windows البعيدة.)

#### المرحلة 1.6 — تحديث Windows عن بُعد (WinRM) — ✅ مُنفَّذة
- **الاعتماد:** `pywinrm` (HTTP 5985 / HTTPS 5986)، transport افتراضي `ntlm`
  (يعمل بحساب مسؤول محلي ويُشفّر الحمولة حتى على HTTP، بلا `AllowUnencrypted`).
- **جدول `winrm_hosts`:** host, username, password (لا تُعاد؛ TODO تشفير عند التخزين)،
  use_https, transport، اسم مخصّص + نتائج الفحص (نظام/إصدار/hostname/winget).
  Migration `60df94c429f7`.
- **الخدمة `services/winrm_hosts.py`:** `probe()` و`check_updates()` و`apply_updates()`
  عبر `winget upgrade` (يُعاد استخدام مُحلِّل winget المقاوم للعربية). كل نداء WinRM
  مُغلَّف بـ `asyncio.to_thread` فلا يُعطِّل حلقة الأحداث.
- **endpoints:** `/api/winrm/hosts` CRUD + `/check` + `/upgrade` (كلمة المرور لا تُعرَض).
- **صفحة «Windows بعيد»:** إضافة جهاز + فحص + ترقية بنقرة، مع تعليمات `Enable-PSRemoting`.
- **الأمان:** بيانات الاعتماد لا تُسجَّل ولا تُعاد؛ HTTPS مدعوم؛ 14 اختبار وحدة.
- **الحدود:** يجب تفعيل WinRM على الهدف (`Enable-PSRemoting -Force`) وحساب مسؤول،
  وأن يكون winget قابلاً للوصول من جلسة WinRM.

### 1.2 Linux (Ubuntu/Debian/Fedora)
| البند | التفصيل |
|-------|---------|
| الاكتشاف | ARP + port 22 (SSH) |
| التعرّف | SSH banner + `/etc/os-release` |
| التحديث | ✅ تلقائي عبر SSH: `apt update && apt upgrade` أو `dnf upgrade` |
| المصادر الرسمية | Ubuntu archive, Debian, Fedora repos |
| المصادر غير الرسمية | Snap, Flatpak, AppImage |
| المتطلبات | SSH key authentication (لا يستخدم passwords) |
| الحدود | يحتاج sudo، بعض الحزم تحتاج تدخل يدوي |

### 1.3 macOS
| البند | التفصيل |
|-------|---------|
| الاكتشاف | mDNS (`_apple-mobdev._tcp`) + ARP |
| التعرّف | mDNS + Bonjour |
| التحديث | ⚠️ شبه تلقائي عبر `softwareupdate` و `brew upgrade` (يحتاج تفعيل SSH على الجهاز) |
| المصادر الرسمية | Apple Software Update |
| المصادر غير الرسمية | Homebrew, MacPorts |
| الحدود | معظم تحديثات macOS الكبرى تتطلب إعادة تشغيل وتأكيد المستخدم |

---

## 2. الجوالات والأجهزة اللوحية

### 2.1 Android
| البند | التفصيل |
|-------|---------|
| الاكتشاف | mDNS + ARP + DHCP fingerprint |
| التعرّف | mDNS hostname + UA من DHCP |
| التحديث | ⚠️ متعدد المستويات |
|  | - **التطبيقات:** عبر ADB إذا مفعّل (`pm list packages` + tracker لـ updates) |
|  | - **النظام:** ❌ تنبيه فقط (OTA من المصنّع) |
| المصادر الرسمية | Google Play, Galaxy Store, Mi Store |
| المصادر غير الرسمية | F-Droid, APKMirror, XDA |
| المتطلبات | تفعيل USB Debugging أو Wireless ADB |
| الحدود | لا يقدر يحدّث النظام بدون root |

### 2.2 iOS / iPadOS
| البند | التفصيل |
|-------|---------|
| الاكتشاف | mDNS + Bonjour |
| التعرّف | mDNS device-info |
| التحديث | ❌ مستحيل تلقائيًا |
| المصادر الرسمية | Apple فقط |
| ما نقدر نسويه | عرض الإصدار الحالي + نقول للمستخدم "حدّث يدويًا" |
| الحدود | Apple مغلق بالكامل، لا API محلي |

---

## 3. الراوترات والمودمات

### 3.1 OpenWRT / DD-WRT (راوترات Custom)
| البند | التفصيل |
|-------|---------|
| الاكتشاف | nmap + port 22 (SSH) أو 80/443 (LuCI) |
| التعرّف | LuCI banner أو SSH + `cat /etc/openwrt_release` |
| التحديث | ✅ تلقائي عبر SSH: `opkg update && opkg upgrade` (للحزم) + sysupgrade (للفريم وير) |
| المصادر الرسمية | OpenWRT package index |
| المتطلبات | SSH key |
| الحدود | sysupgrade يحتاج تأكيد لأنه قد يخرّب الجهاز إذا فشل |

### 3.2 pfSense / OPNsense
| البند | التفصيل |
|-------|---------|
| الاكتشاف | nmap + port 443 |
| التعرّف | LuCI/web UI fingerprint |
| التحديث | ✅ تلقائي عبر REST API |
| المصادر الرسمية | pfSense/OPNsense official |

### 3.3 راوترات منزلية تجارية (TP-Link, ASUS, D-Link)
| البند | التفصيل |
|-------|---------|
| الاكتشاف | nmap + UPnP description |
| التعرّف | UPnP modelName + web UI fingerprint |
| التحديث | ⚠️ HTTP scraper مخصص لكل علامة تجارية |
| المصادر الرسمية | موقع الشركة (TP-Link.com/download, إلخ) |
| الحدود | كل موديل قد يحتاج logic مختلف، صيانة عالية |

### 3.4 راوترات المزوّدين (STC, Mobily, Du)
| البند | التفصيل |
|-------|---------|
| الاكتشاف | كأي راوتر |
| التعرّف | غالبًا مقفّل |
| التحديث | ❌ مغلق من المزوّد |
| ما نقدر نسويه | تنبيه: "راوترك من STC، التحديثات تأتي تلقائيًا من STC" |

---

## 4. التلفزيونات الذكية

### 4.1 Android TV / Google TV
| البند | التفصيل |
|-------|---------|
| الاكتشاف | mDNS (`_androidtvremote._tcp`) |
| التعرّف | mDNS + Cast Receiver |
| التحديث | ⚠️ عبر ADB (مثل Android العادي) |
| المتطلبات | تفعيل ADB على التلفزيون |

### 4.2 Samsung Tizen
| البند | التفصيل |
|-------|---------|
| الاكتشاف | mDNS + UPnP |
| التعرّف | UPnP modelName="Samsung TV" |
| التحديث | ❌ مغلق |
| ما نقدر نسويه | تنبيه + رابط لصفحة التحديث في موقع سامسونج |

### 4.3 LG webOS
| البند | التفصيل |
|-------|---------|
| الاكتشاف | SSDP |
| التعرّف | SSDP service type |
| التحديث | ❌ مغلق |
| ما نقدر نسويه | نفس Tizen |

### 4.4 Apple TV
| البند | التفصيل |
|-------|---------|
| التحديث | ❌ مستحيل (مغلق من Apple) |

---

## 5. أجهزة المنزل الذكي (IoT)

### 5.1 Philips Hue
| البند | التفصيل |
|-------|---------|
| الاكتشاف | mDNS + UPnP + Hue Bridge SSDP |
| التحديث | ✅ عبر Hue Bridge API |

### 5.2 Smart Plugs / Switches (TP-Link Kasa, Tuya)
| البند | التفصيل |
|-------|---------|
| الاكتشاف | mDNS + manufacturer-specific |
| التحديث | ⚠️ عبر تطبيق المصنّع (نطلق التطبيق ونعرض تنبيه) |
| ملاحظة | بعضها يدعم Tasmota (firmware مفتوح) → ✅ |

### 5.3 Home Assistant Hub
| البند | التفصيل |
|-------|---------|
| إذا موجود | ✅ تكامل عبر REST API لجلب كل الأجهزة المسجّلة فيه |
| ملاحظة | Home Assistant بنفسه قاعدة بيانات IoT جاهزة، نستخدمه |

### 5.4 Chromecast / Google Nest
| البند | التفصيل |
|-------|---------|
| الاكتشاف | mDNS (`_googlecast._tcp`) |
| التحديث | ⚠️ تلقائي من Google + قراءة الإصدار |

---

## 6. الكاميرات والطابعات

### 6.1 كاميرات IP (Hikvision, Dahua, Reolink)
| البند | التفصيل |
|-------|---------|
| الاكتشاف | nmap + port 80/554 (RTSP) |
| التحديث | ⚠️ HTTP scraper لكل علامة |
| ملاحظة | Hikvision/Dahua لديهم API رسمي |

### 6.2 طابعات (HP, Canon, Epson)
| البند | التفصيل |
|-------|---------|
| الاكتشاف | mDNS (`_ipp._tcp`) + IPP |
| التحديث | ⚠️ HP لديها API، الباقي scraper |

---

## 7. أولوية الدعم في v1

نبدأ بهذه الفئات بهذا الترتيب:
1. **Windows PC** (الأسهل، فيه winget)
2. **Linux PC** (SSH واضح)
3. **OpenWRT routers** (الأكثر تأثيرًا أمنيًا)
4. **Android via ADB** (للأجهزة المخصصة فقط)
5. **Home Assistant integration** (لجمع كل IoT دفعة واحدة)

---

## 8. ملاحظات للتطوير المستقبلي

- **Plugin Architecture** يسمح لأي شخص يضيف دعم لجهاز جديد بكتابة Python module بسيط
- نحتاج **Fingerprint Database** نبنيها تدريجيًا
- نقدر نستفيد من قاعدة بيانات [Wireshark Manuf](https://gitlab.com/wireshark/wireshark/-/blob/master/manuf) لـ MAC OUI mapping
