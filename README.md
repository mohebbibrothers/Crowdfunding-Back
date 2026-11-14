# Crowdfunding-Back — سامانه بک‌اند کرادفاندینگ خیرخواهانهٔ سهم‌محور

[![CI — Quality, Security, Contract & MariaDB Suite](https://github.com/mohebbibrothers/Crowdfunding-Back/actions/workflows/ci.yml/badge.svg)](https://github.com/mohebbibrothers/Crowdfunding-Back/actions/workflows/ci.yml)
![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![Django 6.1](https://img.shields.io/badge/Django-6.1-092E20?logo=django&logoColor=white)
![MariaDB 11](https://img.shields.io/badge/MariaDB-11.x-003545?logo=mariadb&logoColor=white)
![OpenAPI 3.1.0](https://img.shields.io/badge/OpenAPI-3.1.0-6BA539?logo=openapiinitiative&logoColor=white)
![Mypy Strict](https://img.shields.io/badge/mypy-strict-blue)
![Branch Coverage 85.84%](https://img.shields.io/badge/branch%20coverage-85.84%25-brightgreen)
![Frontend Handoff Kit](https://img.shields.io/badge/Frontend%20Kit-v1.1.0-6C5CE7?logo=typescript&logoColor=white)
![Release](https://img.shields.io/badge/release-v1.1.0-2ECC71?logo=github)

سرویس بک‌اند ماژولار، امن و حسابرسی‌پذیر برای پلتفرم جمع‌آوری مشارکت‌های مردمی و خیرخواهانه بر پایهٔ **سهم (Share-Based Crowdfunding)**، مهندسی‌شده با **Django 6.1، Django REST Framework، پایتون ۳.۱۲ و MariaDB 11.x**.

این سامانه با بهره‌گیری از الگوهای اصیل حوزهٔ نیکوکاری ایران (**حرکت‌های سهم‌محور، موسسات/مددکاران تاییدشده، قلک عام و پیوندک**) و ترکیب آن‌ها با **دفتر کل حسابداری دوطرفه ریالی، دیوار شفافیت رمزنگاری درخت مرکل (RFC 6962)، مشارکت سریع ۳۰ ثانیه‌ای مهمان، نیت‌نامه و کارت هدیه معنوی، سفیران اجتماعی، حامیان مضاعف‌کننده، گزارش‌های پیشرفت میدانی و موتور گزارش‌گیری اکسل ۸ کاربرگهٔ فارسی**، یک زیرساخت مالی قابل ممیزی در تراز سازمانی فراهم می‌سازد.


---

## 📦 بستهٔ رسمی تحویل به فرانتاند (Frontend Handoff Kit) — نسخهٔ ۱٫۱٫۰

> **👋 تیم فرانت‌اند از اینجا شروع کنید:** [`START-HERE.md`](START-HERE.md) — راهنمای ورود ۵ دقیقه‌ای
> **همین حالا تحویل بدهید:** [`docs/frontend/index.html`](docs/frontend/index.html) (پورتال بصری آفلاین)
> · [`docs/frontend/HANDOFF.md`](docs/frontend/HANDOFF.md) (راهنمای جامع)
> · [`docs/frontend/README.md`](docs/frontend/README.md) (نقشهٔ بسته)

قرارداد دیگر «یک فایل YAML تنها» نیست؛ یک **خط تولید قراردادمحور** است که تمام داراییهای فرانتاند را
بهصورت خودکار و تعیینی از همان `openapi.yaml` میسازد و CI همگامی آنها را قفل میکند:

| دارایی | خروجی | دارایی | خروجی |
| --- | --- | --- | --- |
| قرارداد | **۷۲ مسیر · ۸۳ عملیات · ۱۱۲ اسکیما** | خطاها | **۳۸ کد RFC 9457** + اقدام UX |
| تایپها | `api-types.d.ts` + `operations.ts` | کالکشن | `postman_collection.json` (۲۳ پوشه) |
| کلاینت | `api-client.ts` (CSRF/JWT/refresh/ETag/retry) | ماتریس | `ENDPOINTS.md` + کاوشگر تعاملی |
| پذیرش | `CHECKLIST.md` (Definition of Done) | قفل CI | `contract-fingerprint.json` (SHA-256) |

**چهار اصل تحویل:** ① هیچ پاسخ موفقی بدون اسکیمای تایپشده نیست ② تمام ۸۳ عملیات خطاهای
استاندارد و هدر ردیابی دارند ③ پنج لیست مکاننمایی دقیقاً همان پوشش `{results, meta}` را اعلام میکنند
④ نام کوکی، CSRF، Idempotency، ETag و سرورها همگی از تنظیمات زنده خوانده میشوند — نه حدس.

```bash
make handoff          # بازتولید کل بسته از قرارداد
make verify-handoff   # گیت همگامی (هر درفتی را قرمز میکند)
```

---

## نمای گرافیکی معماری و جریان تراکنش مالی

### ۱. گراف غیرمدور ۹ ماژول دامنه (9-App Acyclic Bounded Contexts)

```mermaid
flowchart TB
    CORE["1. core<br/>UUIDv7 · RFC 9457 · Atomic DB Cache · Outbox · Crypto · Jalali"]
    AUDIT["2. audit<br/>Append-Only SHA-256 Hash Chain · HMAC AuditAnchor"]
    IDENT["3. identity<br/>Phone OTP · Dual Session (Cookie + JWT) · RFC 6238 TOTP MFA"]
    NOTIF["4. notifications<br/>Pattern SMS Port · SmsDeliveryLog · UserNotification Inbox"]
    BENEF["5. benefactors<br/>Verified Charities (IBAN Mod-97) · CharityJar (قلک عام)"]
    CAMP["6. campaigns<br/>Share Campaigns · MatchingGrant · ImpactUpdate · ShortLink Port"]
    LEDG["7. ledger<br/>Rial Double-Entry Journal · Maker-Checker Disbursement · Reconciliation"]
    CONTRIB["8. contributions<br/>15m Share Hold · Express 30s · Zarinpal · Dedication · Ambassador · Merkle"]
    REPORT["9. reporting<br/>8-Sheet RTL Persian Excel Engine (A4 Landscape + SHA-256 Audit)"]

    CORE --> AUDIT --> IDENT --> NOTIF --> BENEF --> CAMP --> LEDG --> CONTRIB --> REPORT
    CONTRIB -. "Hexagonal Runtime Port<br/>(register_short_code_resolver)" .-> CAMP
    CONTRIB -. "Hexagonal Runtime Port<br/>(register_verified_payment_provider)" .-> LEDG
```

### ۲. چرخهٔ اتمیک رزرو سهام، پرداخت، دفتر کل دوطرفه و شفافیت مرکل

```mermaid
sequenceDiagram
    autonumber
    actor Donor as خیر / نیکوکار
    participant API as Crowdfunding-Back
    participant DB as MariaDB (FOR UPDATE)
    participant GW as درگاه پرداخت (زرین‌پال / Sandbox)
    participant Ledger as دفتر کل دوطرفه + درخت مرکل

    Donor->>API: درخواست مشارکت (تعداد سهم یا مبلغ قلک + Idempotency-Key)
    API->>DB: قفل ردیفی حرکت و رزرو اتمیک سهام به مدت ۱۵ دقیقه
    API-->>Donor: بازگشت شناسه Authority و لینک هدایت به درگاه
    Donor->>GW: پرداخت آنلاین شاپرکی (ریال)
    GW->>API: بازگشت از درگاه (/api/v1/payments/callback)
    API->>DB: قفل ردیفی GatewayPayment (تضمین Idempotency در برابر تکرار)
    API->>GW: استعلام تایید قطعی تراکنش (Verify)
    API->>Ledger: صدور سند متوازن بدهکار/بستانکار + کسر استخر حامی مضاعف + ثبت برگ درخت مرکل
    API->>DB: صدور رسید رسمی (CF-YYYYMM-NNNNNN) + صف کردن پیامک رسید در Outbox
    API-->>Donor: نمایش رسید رسمی، گواهی نیت‌نامه و اثبات شمول مرکل (Merkle Proof)
```

---

## قابلیت‌های کلیدی مهندسی و خلاقانه

| محور | شرح قابلیت پیاده‌سازی‌شده |
|---|---|
| **معماری غیرمدور با گیت AST** | جداسازی سخت‌گیرانهٔ ۹ دامنه؛ ممنوعیت وابستگی معکوس و ممنوعیت دستکاری مستقیم مدل‌ها در لایهٔ View که در هر اجرای تست به‌طور خودکار بررسی می‌شود. |
| **دفتر کل دوطرفه ریالی (`rial_base_dual_view`)** | ذخیرهٔ تمامی مبالغ با عدد صحیح ریال (`BIGINT` بدون هیچ‌گونه `float`) همگام با شاپرک، همراه با نمایش هم‌زمان ریال و تومان در API، تسویهٔ چهارچشمی (Maker-Checker) و مغایرت‌گیری بانکی. |
| **صفر بیش‌فروشی سهام زیر بار هم‌روند** | قفل ردیفی `SELECT ... FOR UPDATE` روی ظرفیت سهام حرکت هنگام آغاز پرداخت و آزادسازی خودکار رزروهای منقضی‌شدهٔ ۱۵ دقیقه‌ای توسط زمان‌بند `reap_expired`. |
| **مشارکت سریع ۳۰ ثانیه‌ای مهمان** | امکان انتخاب سهام و تایید موبایل در یک مرحله بدون نیاز به ثبت‌نام قبلی یا خروج از صفحهٔ حرکت (`ExpressContributionIntent`). |
| **دیوار شفافیت رمزنگاری (RFC 6962 Merkle)** | ثبت هش ناشناس هر مشارکت در درخت مرکل حرکت و ارائهٔ مسیر اثبات ریاضی (`merkle-proof`) به هر خیر برای راستی‌آزمایی مستقل جمع کل. |
| **نیت‌نامه، سفیران اجتماعی و حامی مضاعف** | صدور کارت هدیهٔ معنوی قابل اشتراک (`DedicationCard`)، لینک اختصاصی سفیران با رهگیری سهام جذب‌شده (`AmbassadorLink`) و ضریب هم‌افزایی حامیان مضاعف (`MatchingGrant`). |
| **امنیت دفاع در عمق و Step-Up MFA** | کد ۵ رقمی OTP با هش نمک‌زده HMAC، نشست دوگانه (`HttpOnly Cookie` + `SessionAwareJWT`)، تشخیص بازپخش Refresh Token، تایید دومرحله‌ای **TOTP (RFC 6238)** برای عملیات حساس مدیریتی و زنجیرهٔ ممیزی `SHA-256`. |
| **گزارش اکسل مدیریتی ۸ کاربرگهٔ راست‌به‌چپ** | تولید کارپوشهٔ `openpyxl` در قطع A4 افقی با فونت وزیرمتن، فرمول‌های زنده، نمودار میله‌ای، پوشاندن پیش‌فرض شماره‌های تماس خیرین و ثبت اثر انگشت `SHA-256`. |
| **سازگار با سی‌پنل نایترو و Docker** | اجرای بومی روی **CloudLinux Passenger + Cron** بدون وابستگی اجباری به Redis/Celery به لطف `AtomicDatabaseCache`، کش نسلی `Epoch + ETag/304` و صف تراکنشی `OutboxMessage`. |

---

## ساختار مخزن

```text
Crowdfunding-Back/
├── .github/workflows/ci.yml      # خط لوله CI روی گیت‌هاب (Ruff, Mypy, Bandit, pip-audit, OpenAPI, MariaDB)
├── deploy/cpanel/                # بسته کامل استقرار سی‌پنل نایترو (passenger_wsgi.py + Cron + Deploy)
├── docs/
│   ├── adr/                      # تصمیم‌نامه‌های معماری (ADR-0001)
│   ├── api/v1/openapi.yaml       # قرارداد کامل و اعتبارسنجی‌شده OpenAPI 3.1.0
│   ├── api/v1/README.md          # قراردادهای سراسری و نقشهٔ کامل نقاط پایانی
│   ├── frontend/                 # 🎯 بستهٔ تحویل فرانتاند (پورتال، تایپها، کلاینت، خطاها، Postman، چکلیست)
│   ├── architecture.md           # مستند معماری، هم‌روندی و معادلات تراز دفتر کل
│   ├── security-asvs.md          # ماتریس انطباق امنیتی OWASP ASVS v5.0
│   └── runbook.md                # کتابچه عملیات، پایش و واکنش به رخداد
├── scripts/
│   └── build_frontend_kit.py     # کامپایلر قرارداد → داراییهای تایپشدهٔ فرانتاند
├── src/
│   ├── config/                   # تنظیمات محیط‌های development / test / production و مسیریابی اصلی
│   ├── apps/                     # ۹ ماژول محدودشدهٔ دامنه (Bounded Contexts)
│   └── tests/                    # ۶۱ آزمون یکپارچه، قراردادی، همروندی، امنیتی و خاصیتمحور
├── Dockerfile                    # تصویر کانتینر چندمرحله‌ای غیرریشه (Non-Root)
├── compose.yaml                  # اجرای یک‌دستوری محلی با MariaDB 11.4 + Web + Cron Worker
├── Makefile                      # میانبرهای سریع توسعه، کنترل کیفیت و اجرای آزمون‌ها
├── SECURITY.md                   # سیاست امنیت و گزارش محرمانه آسیب‌پذیری
├── CONTRIBUTING.md               # راهنمای مشارکت و قواعد معماری
├── CHANGELOG.md                  # تاریخچه نسخه‌ها
└── .env.example                  # الگوی کامل متغیرهای محیطی بدون راز واقعی
```

---

## راه‌اندازی سریع در محیط توسعه

### روش اول: اجرا با `uv` (یا `Makefile`) و MariaDB محلی

```bash
# ۱. نصب وابستگی‌های قفل‌شده
make install

# ۲. تنظیم اتصال دیتابیس توسعه، اعمال مهاجرت‌ها و بارگذاری داده‌های نمایشی
export DATABASE_URL="mysql://crowdfunding:crowdfunding@127.0.0.1:3306/crowdfunding"
make migrate
make seed

# ۳. اجرای سرور توسعه روی پورت ۸۰۰۰
make run
```

پس از راه‌اندازی:
- مستندات تعاملی **Swagger UI**: `http://localhost:8000/api/v1/docs`
- مستندات **ReDoc**: `http://localhost:8000/api/v1/redoc`
- بررسی آمادگی سرویس: `http://localhost:8000/api/v1/health/ready`

### روش دوم: اجرای یک‌دستوری با Docker Compose

```bash
docker compose up --build -d
```

---

## گیت‌های کیفیت، امنیت و آزمون

تمامی گیت‌های زیر در خط لولهٔ GitHub Actions روی کانتینر واقعی **MariaDB 11.4** اجرا می‌شوند:

```bash
make check           # Ruff + Mypy (--strict) + Bandit + pip-audit + OpenAPI 3.1 + همگامی بستهٔ فرانتاند
make handoff         # بازتولید تایپها، کالکشن Postman، ماتریس، خطاها و پورتال از قرارداد
make tscheck         # بررسی تایپهای TypeScript بستهٔ فرانتاند (strict)
make test            # اجرای کامل ۶۱ آزمون Pytest روی MariaDB با شرط پوشش شاخهای >= ۸۵٪

# گیتهای تازهٔ نسخهٔ ۱٫۱٫۰: درفت مستندات، تایپشدهبودن تمام پاسخها، پوشش صفحهبندی،
# کاتالوگ خطاها، طرحهای امنیتی و مسیرهای زندهٔ Swagger/ReDoc.
```

---

## مستندات مهندسی و عملیاتی

- [معماری فنی، گراف ماژول‌ها و کنترل هم‌روندی](docs/architecture.md)
- [تصمیم‌نامهٔ معماری و دفتر کل دوطرفه ریالی (ADR-0001)](docs/adr/0001-architecture-and-financial-ledger.md)
- 🎯 [پورتال بصری بستهٔ تحویل فرانتاند](docs/frontend/index.html) · [راهنمای جامع یکپارچهسازی](docs/frontend/HANDOFF.md)
- 🎯 [تایپهای TypeScript](docs/frontend/api-types.d.ts) · [کلاینت HTTP](docs/frontend/api-client.ts) · [کاتالوگ خطاها](docs/frontend/ERRORS.md) · [چکلیست پذیرش](docs/frontend/CHECKLIST.md)
- [راهنمای کامل یکپارچه‌سازی API نسخهٔ ۱ و قرارداد OpenAPI 3.1](docs/api/v1/README.md)
- [ماتریس امنیت OWASP ASVS v5.0](docs/security-asvs.md) و [سیاست امنیت](SECURITY.md)
- [راهنمای گام‌به‌گام استقرار روی هاست سی‌پنل نایترو (CloudLinux Passenger)](deploy/cpanel/README.md)
- [کتابچه عملیات، پایش و واکنش به رخداد (Runbook)](docs/runbook.md)
- [راهنمای مشارکت در توسعه](CONTRIBUTING.md) و [تاریخچه تغییرات](CHANGELOG.md)

---

## مجوز انتشار

تمامی حقوق مادی و معنوی مطابق فایل [`LICENSE`](LICENSE) محفوظ است.
