# Crowdfunding-Back — سامانه بک‌اند کرادفاندینگ خیرخواهانهٔ سهم‌محور

سرویس بک‌اند ماژولار، امن و حسابرسی‌پذیر برای پلتفرم جمع‌آوری مشارکت‌های مردمی و خیرخواهانه بر پایهٔ **سهم (Share-Based Crowdfunding)**، ساخته‌شده با **Django 6.1، Django REST Framework، پایتون ۳.۱۲ و MariaDB 11.x**.

این سامانه با الهام از بهترین الگوهای بومی حوزه‌های نیکوکاری (حرکت‌های سهم‌محور، موسسات/مددکاران تاییدشده، قلک عام و پیوندک) طراحی شده و با افزودن **دفتر کل حسابداری دوطرفه ریالی، دیوار شفافیت رمزنگاری درخت مرکل (RFC 6962)، مشارکت سریع ۳۰ ثانیه‌ای مهمان، نیت‌نامه و کارت هدیه معنوی، سفیران اجتماعی، حامیان مضاعف‌کننده، گزارش‌های پیشرفت میدانی و موتور گزارش‌گیری اکسل ۸ کاربرگهٔ فارسی**، استاندارد مهندسی و اعتمادپذیری مالی را به سطح سازمانی ارتقا می‌دهد.

---

## ویژگی‌های برجستهٔ معماری و دامنه

- **معماری ۹ ماژولی غیرمدور (9-App Acyclic Modular Monolith)**:
  جداسازی سخت‌گیرانهٔ دامنه‌های `core`، `audit`، `identity`، `notifications`، `benefactors`، `campaigns`، `ledger`، `contributions` و `reporting` همراه با گیت‌های خودکار تحلیل درخت نحوی (AST) برای جلوگیری از وابستگی معکوس و جلوگیری از دستکاری مستقیم مدل‌ها در لایهٔ View.
- **حسابداری دوطرفه ریالی بدون خطای ممیز شناور (`rial_base_dual_view`)**:
  ذخیره‌سازی تمام مبالغ بر پایهٔ عدد صحیح ریال (`BIGINT`) همگام با شاپرک/زرین‌پال و ارائهٔ هم‌زمان مقادیر ریالی و تومانی در تمام خروجی‌های API، همراه با تسویهٔ چهارچشمی (Maker-Checker) و مغایرت‌گیری بانکی.
- **کنترل هم‌روندی با قفل ردیفی MariaDB (صفر بیش‌فروشی سهام)**:
  رزرو اتمیک ۱۵ دقیقه‌ای سهام در لحظهٔ ورود به درگاه (`SELECT ... FOR UPDATE`) و آزادسازی خودکار رزروهای رهاشده توسط زمان‌بند `reap_expired`، به همراه بازگشت کاملاً Idempotent از درگاه پرداخت.
- **شفافیت رمزنگاری با درخت مرکل (RFC 6962) و زنجیره ممیزی SHA-256**:
  هر مشارکت موفق یک برگ هش‌شده در درخت مرکل حرکت ثبت می‌کند تا خیرین بدون افشای هویت یکدیگر، حضور کمک خود را در جمع کل حرکت به‌صورت ریاضی راستی‌آزمایی کنند. کلیهٔ رخدادهای مدیریتی نیز در زنجیرهٔ هش تغییرناپذیر `AuditRecord` با لنگر امضاشدهٔ `HMAC` ثبت می‌شوند.
- **احراز هویت تلفن‌محور دوگانه + Step-Up MFA برای مدیران**:
  ورود با کد ۵ رقمی OTP (ذخیرهٔ هش نمک‌زده HMAC)، پشتیبانی هم‌زمان از کوکی امن `HttpOnly` و `Bearer JWT` متصل به نشست زنده، تشخیص بازپخش Refresh Token و الزام تایید تازهٔ TOTP (RFC 6238) برای عملیات حساس مالی و حریم خصوصی.
- **آمادهٔ استقرار بومی روی هاست سی‌پنل نایترو (CloudLinux Passenger) و Docker**:
  بدون وابستگی اجباری به Redis یا Celery؛ مجهز به کش اتمیک دیتابیس (`AtomicDatabaseCache`)، کش نسلی `Epoch` + `ETag/304` و صف تراکنشی `OutboxMessage` با پورت آمادهٔ اتصال پنل پیامک الگومحور.
- **گزارش اکسل مدیریتی ۸ کاربرگهٔ راست‌به‌چپ (`openpyxl`)**:
  تولید کارپوشهٔ حرفه‌ای A4 افقی با فونت فارسی وزیرمتن، فرمول‌های زنده، نمودار میله‌ای پیشرفت حرکت‌ها، پوشاندن پیش‌فرض شماره‌های تماس خیرین و ثبت اثر انگشت `SHA-256` هر خروجی در تاریخچهٔ ممیزی.

---

## ساختار مخزن

```text
Crowdfunding-Back/
├── .github/workflows/ci.yml      # خط لوله CI (Ruff, Mypy, Bandit, pip-audit, OpenAPI, MariaDB Pytest)
├── deploy/cpanel/                # بستهٔ کامل استقرار روی سی‌پنل نایترو (Passenger WSGI + Cron + Deploy)
├── docs/
│   ├── adr/                      # تصمیم‌نامه‌های معماری (ADR-0001)
│   ├── api/v1/openapi.yaml       # قرارداد کامل و اعتبارسنجی‌شده OpenAPI 3.1.0
│   ├── architecture.md           # مستند معماری، هم‌روندی و دفتر کل دوطرفه
│   ├── security-asvs.md          # ماتریس انطباق امنیتی OWASP ASVS v5.0
│   └── runbook.md                # کتابچه عملیات، پایش و واکنش به رخداد
├── src/
│   ├── config/                   # تنظیمات محیط‌های development / test / production و مسیریابی اصلی
│   ├── apps/                     # ۹ ماژول محدودشدهٔ دامنه (Bounded Contexts)
│   └── tests/                    # مجموعه آزمون‌های یکپارچه، هم‌روندی، امنیتی و خاصیت‌محور (Hypothesis)
├── Dockerfile                    # تصویر کانتینر چندمرحله‌ای غیرریشه (Non-Root)
├── compose.yaml                  # اجرای یک‌دستوری محلی با MariaDB 11.4 + Web + Cron Worker
├── pyproject.toml                # تنظیمات قفل‌شده وابستگی‌ها، Ruff، Mypy --strict، Bandit و Pytest
└── .env.example                  # الگوی کامل متغیرهای محیطی بدون راز واقعی
```

---

## راه‌اندازی سریع در محیط توسعه

### پیش‌نیازها
- **Python 3.12+** و مدیر بستهٔ سریع **[`uv`](https://docs.astral.sh/uv/)**
- **MariaDB 10.11+ / 11.x** (یا اجرای خودکار با Docker Compose)

### روش اول: اجرا با `uv` و MariaDB محلی

```bash
# ۱. نصب وابستگی‌های قفل‌شده (شامل ابزارهای توسعه و تست)
uv sync --frozen --all-extras

# ۲. تنظیم متغیر اتصال به دیتابیس توسعه
export DATABASE_URL="mysql://crowdfunding:crowdfunding@127.0.0.1:3306/crowdfunding"
export DJANGO_SETTINGS_MODULE="config.settings.development"

# ۳. اعمال مهاجرت‌ها، ساخت جدول کش اتمیک و بارگذاری داده‌های نمونهٔ نمایشی
uv run python src/manage.py migrate
uv run python src/manage.py createcachetable --database=cache
uv run python src/manage.py seed_demo_data

# ۴. اجرای سرور توسعه
uv run python src/manage.py runserver 0.0.0.0:8000
```

پس از بالا آمدن سرور توسعه:
- مستندات تعاملی Swagger UI: `http://localhost:8000/api/v1/docs`
- مستندات ReDoc: `http://localhost:8000/api/v1/redoc`
- بررسی آمادگی سرویس: `http://localhost:8000/api/v1/health/ready`

### روش دوم: اجرای یک‌دستوری با Docker Compose

```bash
docker compose up --build -d
```

---

## گیت‌های کیفیت، امنیت و آزمون

تمامی گیت‌های زیر در خط لولهٔ CI اجرا می‌شوند و باید با خروجی صفر عبور کنند:

```bash
# ۱. قالب‌بندی و تحلیل ایستا (Ruff)
uv run ruff format --check src
uv run ruff check src

# ۲. بررسی سخت‌گیرانهٔ نوع‌ها (Mypy Strict + Django/DRF Stubs)
uv run mypy

# ۳. اسکن امنیتی کد (Bandit SAST) و آسیب‌پذیری وابستگی‌ها (pip-audit)
uv run bandit -c pyproject.toml -r src
uv run pip-audit

# ۴. اعتبارسنجی قرارداد OpenAPI 3.1 بدون هشدار
uv run python src/manage.py spectacular --api-version v1 --file docs/api/v1/openapi.yaml --validate --fail-on-warn

# ۵. اجرای کامل آزمون‌ها روی MariaDB با پوشش شاخه‌ای بالای ۸۵٪ (صفر هشدار)
uv run pytest --cov=apps --cov-branch --cov-report=term-missing --cov-fail-under=85
```

---

## مستندات تکمیلی

- [معماری فنی، گراف ماژول‌ها و کنترل هم‌روندی](docs/architecture.md)
- [تصمیم‌نامهٔ معماری و دفتر کل دوطرفه ریالی (ADR-0001)](docs/adr/0001-architecture-and-financial-ledger.md)
- [راهنمای کامل یکپارچه‌سازی API نسخهٔ ۱ و قرارداد OpenAPI 3.1](docs/api/v1/README.md)
- [ماتریس امنیت OWASP ASVS v5.0](docs/security-asvs.md)
- [راهنمای گام‌به‌گام استقرار روی هاست سی‌پنل نایترو (CloudLinux Passenger)](deploy/cpanel/README.md)
- [کتابچه عملیات، پایش و واکنش به رخداد (Runbook)](docs/runbook.md)

---

## مجوز انتشار

تمامی حقوق مادی و معنوی مطابق فایل [`LICENSE`](LICENSE) محفوظ است.
