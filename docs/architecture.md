# معماری سامانه کرادفاندینگ خیرخواهانه (`Crowdfunding-Back`)

این سند معماری فنی، مرزبندی دامنه‌ها (Bounded Contexts)، الگوهای هم‌روندی و کنترل‌های مالی سامانه بک‌اند کرادفاندینگ خیرخواهانهٔ سهم‌محور را تشریح می‌کند.

---

## ۱. نمای کلی و اصول طراحی

سامانه بر پایهٔ الگوی **Modular Monolith با مرزهای Hexagonal (Ports & Adapters)** روی **Django 6.1 + Django REST Framework + MariaDB 11.x** پیاده‌سازی شده است تا هم یکپارچگی تراکنشی اسناد مالی (ACID) در یک پایگاه‌داده واحد حفظ شود و هم بدون نیاز به زیرساخت‌های جانبی سنگین (نظیر Redis یا Celery) روی هاست‌های استاندارد **CloudLinux Passenger (سی‌پنل نایترو)** و محیط‌های کانتینری به صورت کاملاً پایدار اجرا گردد.

### گراف جهت‌دار غیرمدور وابستگی ماژول‌ها (9-App Acyclic DAG)

هیچ چرخه‌ای میان ۹ اپلیکیشن دامنه وجود ندارد و این انضباط در هر اجرای آزمون توسط گیت معماری `test_bounded_context_acyclic_dag_discipline` به‌صورت تحلیل درخت نحوی (AST) راستی‌آزمایی می‌شود:

```text
core ──► audit ──► identity ──► notifications ──► benefactors ──► campaigns ──► ledger ──► contributions ──► reporting
```

| ردیف | ماژول (`src/apps/*`) | مسئولیت محدودشده (Bounded Context) |
|---|---|---|
| ۱ | `core` | هستهٔ مشترک: شناسه‌های مرتب زمانی UUIDv7، خطاهای استاندارد RFC 9457، کش اتمیک دیتابیس (`AtomicDatabaseCache`)، کش نسلی Epoch + ETag/304، صف تراکنشی Outbox، رمزنگاری فیلدها و شاخص کور HMAC، تقویم شمسی، قفل سریال دیتابیس و سلامت/متریک‌ها |
| ۲ | `audit` | دفتر ثبت وقایع تغییرناپذیر (Append-Only) با زنجیرهٔ هش SHA-256 (`prev_hash -> entry_hash`) و لنگر امضاشدهٔ دوره‌ای HMAC (`AuditAnchor`) |
| ۳ | `identity` | احراز هویت تلفن‌محور با کد ۵ رقمی OTP (ذخیرهٔ هش نمک‌زده HMAC)، نشست دوگانه (`HttpOnly Cookie` + `SessionAwareJWT`)، چرخش Refresh Token با تشخیص سرقت/بازپخش، احراز دومرحله‌ای TOTP (RFC 6238) + کدهای بازیابی و رمزنگاری کدملی |
| ۴ | `notifications` | پورت و آداپتورهای پیامک الگومحور (ضد تزریق متن آزاد)، لاگ حاکمیت تحویل پیامک (`SmsDeliveryLog`) و صندوق اعلان‌های درون‌برنامه‌ای خیر (`UserNotification`) |
| ۵ | `benefactors` | مدیریت خیریه‌ها/موسسات نیکوکاری (`Benefactor`)، اعتبارسنجی شبا (ISO 7064 Mod-97) و قلک‌های عام خیریه (`CharityJar`) |
| ۶ | `campaigns` | حرکت‌های خیرخواهانهٔ سهم‌محور (`Campaign`)، گالری مستندات، حامیان مضاعف‌کننده (`MatchingGrant`)، گزارش‌های پیشرفت میدانی مرحله‌ای (`CampaignImpactUpdate`) و حل‌کنندهٔ پیوندک (`ShortLink`) |
| ۷ | `ledger` | دفتر کل حسابداری دوطرفهٔ ریالی (`LedgerAccount`, `JournalEntry`, `LedgerPosting`)، تسویهٔ چهارچشمی با خیریه (`DisbursementRequest` — Maker-Checker)، مغایرت‌گیری بانکی (`ReconciliationBatch`) و عکس کنترل تراز (`capture_financial_control_snapshot`) |
| ۸ | `contributions` | رزرو ۱۵ دقیقه‌ای سهام با قفل ردیفی، مشارکت سریع ۳۰ ثانیه‌ای مهمان (`ExpressContributionIntent`)، آداپتور زرین‌پال و Sandbox، رسید رسمی، نیت‌نامه و کارت هدیه معنوی (`DedicationCard`)، سفیران اجتماعی (`AmbassadorLink`)، درخت مرکل شفافیت (RFC 6962)، مشارکت خارج از درگاه و استرداد وجه |
| ۹ | `reporting` | موتور تولید گزارش اکسل مدیریتی ۸ کاربرگهٔ راست‌به‌چپ (A4 Landscape، فونت وزیرمتن، فرمول‌های زنده، نمودار میله‌ای و قالب عددی ریال/تومان) همراه با ثبت ممیزی SHA-256 خروجی‌ها |

---

## ۲. همگرایی معکوس وابستگی (Hexagonal Runtime Ports)

برای حفظ یک‌طرفه بودن گراف وابستگی بدون ایجاد import چرخه‌ای:
- **پورت پیوندک (`apps.campaigns.selectors.register_short_code_resolver`)**: ماژول `contributions` در زمان راه‌اندازی (`ContributionsConfig.ready`) حل‌کنندهٔ کدهای سفیران اجتماعی را روی پورت `campaigns` ثبت می‌کند تا مسیر واحد `/api/v1/short-links/{code}` هم کد حرکت و هم کد سفیر را پشتیبانی کند.
- **پورت مغایرت‌گیری پرداخت (`apps.ledger.services.register_verified_payment_provider`)**: ماژول `contributions` ارائه‌دهندهٔ پرداخت‌های تاییدشدهٔ درگاه را در `ledger` ثبت می‌کند تا موتور مغایرت‌گیری بانکی بدون وابستگی معکوس به مدل‌های `contributions` کار کند.

---

## ۳. کنترل هم‌روندی، یکتایی تراکنش و حسابداری دوطرفه

1. **پیشگیری قطعی از بیش‌فروشی سهام (Zero Overselling)**:
   هنگام آغاز پرداخت، سطر `Campaign` با `SELECT ... FOR UPDATE` قفل شده، ظرفیت آزاد (`total_shares - sold_shares - external_sold_shares - reserved_shares`) بررسی می‌شود و `reserved_shares` به مدت ۱۵ دقیقه افزایش می‌یابد. اگر خیر پرداخت را رها کند، فرمان زمان‌بند `reap_expired` رزرو را آزاد می‌سازد.
2. **بازگشت از درگاه کاملاً Idempotent**:
   در `verify_payment_callback`، سطر `GatewayPayment` با `SELECT ... FOR UPDATE` قفل می‌شود. فراخوانی‌های موازی یا تکراری درگاه با همان `authority` دقیقاً **یک** رسید رسمی (`CF-YYYYMM-NNNNNN`)، **یک** سند دفتر کل دوطرفه و **یک** برگ در درخت مرکل ایجاد می‌کنند.
3. **معادلهٔ تراز صفر دفتر کل (Zero-Drift Ledger Equation)**:
   تمامی مبالغ بر مبنای **ریال صحیح (`BIGINT`)** ذخیره شده و در خروجی API معادل تومانی (`rial // 10`) نیز ارائه می‌گردد. در هر لحظه تراز زیر برقرار است:
   ```text
   SUM(Debits) == SUM(Credits)
   SUM(BEN:LIAB:ONLINE_PAYABLE) == SUM(Campaign.collected_online_rial)
                                 + SUM(Campaign.matched_amount_rial)
                                 + SUM(CharityJar.total_raised_rial)
                                 - SUM(Benefactor.total_disbursed_rial)
   ```

---

## ۴. معماری کش دوطبقه و صف تراکنشی بدون نیاز به Redis

- **`AtomicDatabaseCache` روی اتصال مجزای `cache`**: جدول کش دارای متدهای `incr`/`decr` اتمیک با قفل ردیفی است و از طریق `CacheRouter` با `CONN_MAX_AGE=0` مدیریت می‌شود تا تراکنش‌های اصلی کسب‌وکار دچار نگه‌داشت اتصال نشوند.
- **نسخه‌گذاری نسلی Epoch + هدرهای `ETag` / `304 Not Modified`**: صفحات پرترافیک عمومی (فهرست حرکت‌ها، جزئیات حرکت، تابلوی شفافیت) با کلید نسلی کش می‌شوند؛ با هر پرداخت موفق یا تغییر سیاستی، عدد نسل افزایش یافته و کش بی‌درنگ باطل می‌گردد.
- **الگوی Transactional Outbox**: ارسال پیامک OTP، رسید مشارکت و اعلان‌ها در همان تراکنش دیتابیس در جدول `core_outbox_message` ثبت شده و توسط زمان‌بند `process_outbox` با قفل `FOR UPDATE SKIP LOCKED` و تلاش مجدد نمایی (Exponential Backoff) پردازش می‌شود.
