# کتابچه راهنمای عملیات، پایش و واکنش به رخداد (`Operational Runbook`)

این مستند دستورالعمل‌های عملیاتی تیم فنی و پشتیبانی سامانه `Crowdfunding-Back` را برای پایش روزمره، رفع مغایرت‌های احتمالی، تعویض کلیدها و بازیابی از بحران شرح می‌دهد.

---

## ۱. نقاط پایانی پایش سلامت و متریک‌ها

| مسیر | سطح دسترسی | کاربرد عملیاتی |
|---|---|---|
| `GET /api/v1/health/live` | عمومی | بررسی زنده بودن پردازش WSGI/Passenger (`200 OK`) |
| `GET /api/v1/health/ready` | عمومی | بررسی اتصال واقعی به دیتابیس اصلی و دیتابیس کش + عدم وجود مهاجرت اعمال‌نشده |
| `GET /api/v1/health/detailed` | مدیران (`Staff`) | وضعیت تفصیلی صف Outbox، آخرین لنگر ممیزی، وضعیت تراز دفتر کل و نسخهٔ برنامه |
| `GET /metrics` | توکن `METRICS_BEARER_TOKEN` | متریک‌های استاندارد Prometheus برای شمارش درخواست‌ها، خطاها و تأخیر |

---

## ۲. فرمان‌های عملیاتی و زمان‌بندها (`manage.py`)

تمامی فرمان‌ها Idempotent هستند و اجرای مجدد آن‌ها کاملاً ایمن است:

```bash
# ۱. تخلیه و ارسال صف تراکنشی پیامک‌ها و اعلان‌ها
PYTHONPATH=src python src/manage.py process_outbox --batch-size 100

# ۲. آزادسازی سهم‌های رزرو منقضی‌شده (بیش از ۱۵ دقیقه) و پاک‌سازی چالش‌های OTP قدیمی
PYTHONPATH=src python src/manage.py reap_expired

# ۳. راستی‌آزمایی زنجیره ممیزی، امضای لنگر HMAC جدید و ثبت عکس کنترل تراز دفتر کل
PYTHONPATH=src python src/manage.py anchor_audit_chain
```

---

## ۳. سناریوهای واکنش به رخداد (Incident Playbooks)

### سناریو الف: هشدار عدم تراز دفتر کل (`ledger_balanced=False`)
1. وارد پنل مدیریت API شوید یا فرمان `python src/manage.py anchor_audit_chain` را اجرا کنید.
2. خروجی `POST /api/v1/admin/ledger/control-snapshot` را بررسی نمایید؛ این خروجی مقادیر دقیق `total_debits_rial`، `total_credits_rial`، `payable_liability_rial` و `expected_payable_rial` را نمایش می‌دهد.
3. از مسیر `GET /api/v1/admin/audit/verify` سلامت زنجیرهٔ ممیزی را استعلام کنید تا از عدم دستکاری مستقیم جداول دیتابیس خارج از برنامه اطمینان حاصل شود.
4. لیست آخرین اسناد حسابداری را در `GET /api/v1/admin/ledger/entries` و گزارش اکسل مدیریتی (`/api/v1/admin/reports/excel` — کاربرگ ۷ «دفتر کل و تسویه») بررسی نمایید.

### سناریو ب: تشخیص شکست زنجیره ممیزی (`Audit Chain Verification Failed`)
1. نقطه پایانی `GET /api/v1/admin/audit/verify` شماره ردیف دقیق (`broken_at_sequence`) و نوع مغایرت (`prev_hash_mismatch`، `entry_hash_mismatch` یا `anchor_signature_mismatch`) را برمی‌گرداند.
2. بلافاصله دسترسی‌های مستقیم دیتابیس را محدود کرده و فایل پشتیبان پیش از زمان رکورد آسیب‌دیده را جهت جرم‌شناسی (Forensics) ایزوله نمایید.

### سناریو ج: کندی یا خطای اپراتور پیامک
1. وضعیت تحویل پیامک‌ها در جدول `notifications_sms_delivery_log` و صف `core_outbox_message` قابل مشاهده است.
2. پیام‌های ناموفق با الگوریتم Exponential Backoff تا سقف تلاش مجدد زمان‌بندی می‌شوند و هیچ تراکنش پرداخت یا ثبت‌نامی به خاطر قطعی موقت پنل پیامک متوقف نمی‌گردد.
3. در صورت نیاز به سوئیچ فوری به اپراتور پشتیبان، تنها متغیرهای `SMS_API_URL`، `SMS_API_KEY` و `SMS_PATTERN_CODES_JSON` را در `.env` ویرایش کرده و `touch tmp/restart.txt` را اجرا کنید.

### سناریو د: مدیریت ترافیک ناگهانی (پویش‌های تلویزیونی / اضطراری)
- سامانه به‌طور پیش‌فرض روی مسیرهای عمومی کاتالوگ از کش نسلی `Epoch` و پاسخ `304 Not Modified` بهره می‌برد.
- میان‌افزار `LoadSheddingMiddleware` در صورت عبور درخواست‌های هم‌زمان هر پردازش از مرز `MAX_INFLIGHT_REQUESTS`، پاسخ استاندارد `503 Service Unavailable` (RFC 9457) به همراه هدر `Retry-After: 3` برمی‌گرداند تا دیتابیس MariaDB از اشباع اتصال محافظت شود.
- سیاست‌های عملیاتی (مانند فعال/غیرفعال‌سازی موقت ویژگی‌ها یا تغییر سقف سهم هر سفارش) بدون ری‌استارت سرور از طریق `POST /api/v1/admin/policies/{policy_key}` قابل تنظیم‌اند.

---

## ۴. پشتیبان‌گیری و بازیابی (Backup & Restore)

- **دیتابیس MariaDB**: توصیه می‌شود هر ۶ ساعت یک‌بار با `mariadb-dump --single-transaction --routines --triggers --hex-blob` پشتیبان رمزنگاری‌شده تهیه شده و خارج از سرور اصلی نگهداری شود.
- **تست بازیابی**: پس از بازیابی روی محیط آزمایشی، حتماً دو فرمان زیر را اجرا و خروجی سبز آن‌ها را تایید کنید:
  1. `python src/manage.py migrate --check`
  2. `python src/manage.py anchor_audit_chain` (تایید سلامت زنجیرهٔ هش ممیزی و تراز صفر دفتر کل).
