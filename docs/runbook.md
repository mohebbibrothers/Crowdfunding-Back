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

# ۴. داوری پرداخت‌های رهاشده — «آیا وجهی پس از انقضای رزرو نزد درگاه گیر کرده است؟»
PYTHONPATH=src python src/manage.py reconcile_abandoned_payments --batch-size 200

# ۴ب. همان فرمان، فقط پیش‌نمایش (هیچ نوشتنی در دیتابیس انجام نمی‌شود)
PYTHONPATH=src python src/manage.py reconcile_abandoned_payments --dry-run

# ۵. ارسال تعهدهای بازپرداخت به درگاه
PYTHONPATH=src python src/manage.py dispatch_pending_refunds --batch-size 100
```

### لایهٔ حقیقت وجه (Money Truth Layer) — چرا صورت‌حساب اجباری است

تا وقتی فقط از درگاه می‌پرسیم «این تراکنش موفق بود؟»، جواب همیشه «بله» است
چون همان تراکنشی را می‌پرسیم که درباره‌اش قضاوت می‌کنیم. **این تأیید خودگواه
است.** صورت‌حساب تسویه، تنها منبعی است که خودش را تأیید نمی‌کند: یا تراکنش
در آن هست یا نیست.

بدون ورود منظم صورت‌حساب، این سه حالت **هرگز** کشف نمی‌شوند:

| حالت | معنا | کشف با verify()؟ |
| --- | --- | --- |
| درگاه پول گرفت، ما ثبت نکردیم | حامی پول داد، ما نگفتیم ممنونیم | ❌ |
| ما ثبت کردیم، درگاه پول را برنگرداند | بدهی دفتری بدون پشتوانه | ❌ |
| پول در حساب ما، مالکش معلوم نیست | پول بی‌مالک | ❌ |

**روند هفتگی اجباری (حداقل):**
1. از پنل زرین‌پال/بانک، فایل تسویهٔ هفته را Export کنید.
2. `POST /api/v1/admin/settlements` — سند را وارد کنید (با `declared_total_rial` اگر فایل جمع دارد).
3. `POST /api/v1/admin/settlements/{id}/reconcile` با `dry_run=true` — ببینید چه چیزی کشف می‌شود.
4. اگر آمار معقول بود، همان را با `dry_run=false` اجرا کنید.
5. `POST /api/v1/admin/settlements/{id}/remediate` — خوددرمانی مجاز را اجرا کنید.
6. `GET /api/v1/admin/money-truth` — مطمئن شوید `conflict == 0` و
   `unresolved_findings` صفر شد.
7. بقیهٔ مغایرت‌ها (پول بی‌مالک، اختلاف مبلغ، پرداخت غایب در فایل) را **دستی**
   از پنل ادمین بررسی کنید — این‌ها عمداً خودکار حل نمی‌شوند.

> **هشدار:** اگر `statement_age_hours` از آستانهٔ `truth.max_statement_age_hours`
> (پیش‌فرض ۴۸ ساعت) بگذرد، پنل سلامت مالی هشدار `critical` می‌دهد. این هشدار
> را نادیده نگیرید: یعنی «چشم مستقل کور شده و هیچ‌کس نمی‌داند پول درست است یا نه».

### زمان‌بندی اجباری در Cron (بدون این‌ها حلقهٔ وجه ناقص است)

| وظیفه | تناوب | چرا این تناوب |
| --- | --- | --- |
| `process_outbox` | هر دقیقه | تأخیر پیامک/اعلان باید زیر یک دقیقه بماند. |
| `reap_expired` | هر ۲ دقیقه | آزادسازی سریع سهم‌های رزرو تا ظرفیت حرکت قفل نماند. |
| `reconcile_abandoned_payments` | **هر ۱۰ دقیقه** | وجهی که پس از انقضا نزد درگاه مانده، تا داوری نشود «معلّق» است: نه درآمد، نه بازپرداخت. هر ۱۰ دقیقه = حداکثر ۱۰ دقیقه تأخیر در بستن پرونده، به‌علاوهٔ دورهٔ تنفس `recovery.grace_minutes`. |
| `dispatch_pending_refunds` | **هر ۱۰ دقیقه** | تعهد بازپرداخت نباید بیش از ۱۰ دقیقه در صف بماند؛ هر دقیقه انتظار = ریسک شکایت حامی. |
| `run_pledge_cycle` | **روزی یک‌بار، ۱۰ صبح** | چرخهٔ تعهد مستمر چهار گام دارد و گام یادآوری فقط در پنجرهٔ ۹ تا ۲۱ تهران کار می‌کند. اجرای نیمه‌شب یعنی قسط ساخته می‌شود ولی پیامک ساعت ۹ می‌رود — تأخیر ۹ ساعته میان «قسط شما سررسید شد» و «همین حالا». |
| `anchor_audit_chain` | ساعتی | لنگر HMAC زنجیرهٔ ممیزی. |

اسکریپت آماده: `deploy/cpanel/cron_jobs.sh` (با `flock` برای جلوگیری از اجرای همزمان).

```cron
* * * * *   /home/CPANEL_USER/Crowdfunding-Back/deploy/cpanel/cron_jobs.sh outbox   >> /home/CPANEL_USER/logs/cf-cron.log 2>&1
*/2 * * * * /home/CPANEL_USER/Crowdfunding-Back/deploy/cpanel/cron_jobs.sh reap     >> /home/CPANEL_USER/logs/cf-cron.log 2>&1
*/10 * * * * /home/CPANEL_USER/Crowdfunding-Back/deploy/cpanel/cron_jobs.sh recovery >> /home/CPANEL_USER/logs/cf-cron.log 2>&1
*/10 * * * * /home/CPANEL_USER/Crowdfunding-Back/deploy/cpanel/cron_jobs.sh refunds  >> /home/CPANEL_USER/logs/cf-cron.log 2>&1
0 10 * * *  /home/CPANEL_USER/Crowdfunding-Back/deploy/cpanel/cron_jobs.sh pledges  >> /home/CPANEL_USER/logs/cf-cron.log 2>&1
0 * * * *   /home/CPANEL_USER/Crowdfunding-Back/deploy/cpanel/cron_jobs.sh anchor   >> /home/CPANEL_USER/logs/cf-cron.log 2>&1
```

### سیاست‌های قابل تنظیم بدون دیپلوی (پنل مدیر → Policy Rules)

| کلید | پیش‌فرض | اثر |
| --- | --- | --- |
| `recovery.grace_minutes` | `30` | فرصت درگاه برای نهایی‌کردن وضعیت پیش از داوری. |
| `recovery.max_attempts` | `5` | سقف تلاش خودکار؛ پس از آن پرونده به `MANUAL_REVIEW` می‌رود. |
| `recovery.auto_refund_enabled` | `True` | خاموش‌کردن کامل ارسال خودکار بازپرداخت. |
| `recovery.auto_refund_max_rial` | `50_000_000` | **سقف ریالی ارسال خودکار.** بالاتر از این، تعهد به `MANUAL` می‌رود و باید دستی تأیید شود. `0` = بدون سقف. |
| `truth.max_statement_age_hours` | `48` | بیشینهٔ فاصله از آخرین صورت‌حساب؛ پس از آن «چشم مستقل کور» است و هشدار `critical` می‌آید. |
| `truth.auto_heal_enabled` | `True` | آیا پرداخت اثبات‌نشده‌ای که صورت‌حساب تأییدش می‌کند، خودکار درمان شود. |
| `truth.auto_heal_max_rial` | `20_000_000` | سقف ریالی خوددرمانی خودکار. بالاتر ⇒ بررسی انسانی. |
| `truth.unresolved_impact_alert_rial` | `5_000_000` | آستانهٔ اثر ریالی مغایرت‌های حل‌نشده برای هشدار. |

> **هشدار عملیاتی:** هرگز `auto_refund_max_rial` را روی `0` نگذارید بدون این‌که
> هشدار `pending_refunds` در `/api/v1/admin/financial-health` را پایش کنید. بدون
> سقف، یک باگ در منطق داوری می‌تواند کل موجودی حساب درگاه را خودکار خارج کند.

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

---

## تعهد کمک مستمر (Recurring Pledges) — v1.4.0

### چرا این‌گونه طراحی شده است

درگاه‌های ایرانی **توکن کارت** نمی‌دهند؛ هیچ راهی نیست که سرور شما هر ماه
بدون حضور خیر از حساب او پول بردارد. هر محصولی که «کمک ماهانهٔ خودکار»
وعده بدهد و به کارت خیر دسترسی نداشته باشد، در بهترین حالت اشتباه است.

این ماژول صادق است: **تعهد** می‌سازد، **یادآوری** می‌کند، و پرداخت را از
همان درگاه معمولی می‌گذراند. هیچ موتور پرداخت موازی، هیچ ذخیرهٔ کارت، هیچ
ادعای کسر خودکار.

### چرخهٔ روزانه — چهار گام مستقل

```
run_pledge_cycle
  ├─ ۱. resume_paused_pledges      تعهدهایی که دورهٔ توقفشان تمام شده
  ├─ ۲. materialize_due_installments  قسط جدید برای سررسیدهای رسیده
  ├─ ۳. dispatch_pledge_reminders     پیامک، فقط ۹ تا ۲۱ تهران، حداکثر ۲ بار
  └─ ۴. expire_stale_installments     اقساط معوق + انقضای تعهد پس از ۳ شکست
```

**چرا گام ۲ و ۳ جدا هستند؟** اگر یک تراکنش بودند، خطای اپراتور پیامک
تولید قسط را هم برمی‌گرداند. جدا بودن یعنی حتی با پیامک خراب، خیر در پنلش
قسطِ قابل‌پرداخت می‌بیند.

### اجرای دستی

```bash
# کل چرخه
PYTHONPATH=src python src/manage.py run_pledge_cycle

# فقط تولید قسط، بدون هیچ پیامکی (برای عیب‌یابی یا اجرای اضطراری)
PYTHONPATH=src python src/manage.py run_pledge_cycle --skip-reminders

# فقط یک گام
PYTHONPATH=src python src/manage.py run_pledge_cycle --only expire --json
```

### شش حالت شکست و نشانهٔ هرکدام

| نشانه | معنا | اقدام |
|---|---|---|
| `installments_created = 0` ولی تعهد فعال با سررسید گذشته زیاد است | `pledge.engine_enabled` خاموش است یا کرون اجرا نمی‌شود | سیاست را چک کن، لاگ cron را ببین |
| `reminders.sent = 0` و `window_open = false` | چرخه بیرون پنجرهٔ ۹–۲۱ اجرا شده | خط cron را به ساعت ۱۰ منتقل کن |
| `reminders.skipped_cap` بالا | همه به سقف یادآوری رسیده‌اند | طبیعی است؛ اگر زیاد بود، `max_reminders_per_installment` را بازبینی کن |
| `pledges_expired` جهش کرد | شکست زنجیره‌ای پیامک یا درگاه | `OutboxMessage` با `event_type=sms.pledge_reminder` و وضعیت FAILED را ببین |
| `errors > 0` در materialize | یک تعهد دادهٔ معیوب دارد | شناسه در لاگ؛ بقیهٔ دسته سالم پیش رفته‌اند |
| قسط PAID است ولی `total_paid_rial` نه | نشانهٔ تسویهٔ نیمه‌کاره | `settle_installment_payment` را دوباره اجرا کن (idempotent است) |

### پنل‌های مدیریتی

* پنل جنگو ← بخش **مشارکت‌ها** ← *تعهدهای کمک مستمر* — فهرست تعهدها،
  فقط‌خواندنی برای مبلغ و تاریخ. **تغییر مبلغ تعهد از پنل ادمین ممنوع است**: تعهد، توافق خیر
  است و باید از مسیر خودش تغییر کند.
* پنل جنگو ← بخش **مشارکت‌ها** ← *اقساط تعهد* — فقط‌خواندنی. هر تغییر دستی
  روی قسط یعنی جعل سند مالی.

### آمار برای مدیریت

`GET /api/v1/admin/pledges/stats` — مهم‌ترین عدد `monthly_recurring_revenue_rial`
(MRR) است: تعهدهای سه‌ماهه به معادل ماهانه تبدیل می‌شوند تا با ماهانه‌ها
جمع‌شدنی باشند. بدون این نرمال‌سازی، MRR تا سه برابر اشتباه می‌شود.
