# تاریخچهٔ تغییرات (`Changelog`)

تمامی تغییرات مهم این پروژه بر پایهٔ استاندارد [Keep a Changelog](https://keepachangelog.com/fa/1.0.0/) و نسخه‌گذاری معنایی ([Semantic Versioning](https://semver.org/lang/fa/)) در این فایل مستند می‌شوند.

---

## [1.1.0] - 2026-11-14 (۱۴۰۵/۰۸/۲۳) — نسخهٔ تحویل فرانت‌اند

### افزوده‌شده (Added)
- **🎯 بستهٔ رسمی تحویل فرانتاند (`docs/frontend/`)**: پورتال بصری آفلاین `index.html` با کاوشگر ۸۳ عملیات،
  راهنمای جامع `HANDOFF.md` (جریانها، نمودارهای Mermaid، ماشین حالت پرداخت، نگاشت صفحه ← API)،
  تایپهای `api-types.d.ts` + `operations.ts`، کلاینت `api-client.ts` بدون وابستگی،
  کاتالوگ `ERRORS.md` (۳۸ کد)، ماتریس `ENDPOINTS.md`، کالکشن `postman_collection.json`،
  چکلیست پذیرش `CHECKLIST.md` و قفل `contract-fingerprint.json`.
- **کامپایلر قرارداد (`scripts/build_frontend_kit.py`)**: تولید تعیینی تمام داراییهای فرانتاند
  مستقیماً از `openapi.yaml`؛ هدف `make handoff` و گیت `make verify-handoff` در CI.
- **لایهٔ تقویت قرارداد (`apps/core/schema.py`)**: `servers`، ۲۳ `tags` توضیحدار، `externalDocs`،
  اسکیمای `Problem` (RFC 9457)، ۱۱ پاسخ خطای قابل بازاستفاده، هدرهای `X-Request-ID` /
  `Idempotency-Key` / `X-CSRFToken` / `If-None-Match`، نمونههای بدنه و سیاست `x-frontend-policy`
  (`auth` / `retry` / `paginated`) برای تمام ۸۳ عملیات.
- **اسکیمای خروجی تایپشده**: ۱۲ سریالایزر خروجی تازه برای شفافیت مرکل، رسید، نیتنامه،
  درگاه Sandbox، استرداد، دیوار همراهان و داشبورد خیر؛ **صفر پاسخ `(object)` بدون اسکیمای** باقی ماند.
- **صفحهبندی صادقانه**: پوشش `{results, meta}` + پارامترهای `cursor` / `page_size` برای
  پنج نقطهٔ پایانی مکاننمایی؛ مستندسازی فیلترهای query دهها نقطهٔ پایانی دیگر.
- **مسیر `/api/v1/redoc`** و محافظت از Swagger/ReDoc/Schema در محیط تولید پشت نشست کارکنان.
- **فیلد `app_version` در `GET /api/v1/meta`**: نسخهٔ دقیق بکاند مستقرشده برای پنل «درباره» و گزارش خطا.
- **گیت `make tscheck` (TypeScript 5.9 `strict`)**: کامپایل `api-client.ts`، `operations.ts`،
  `api-types.d.ts` و `type-tests.ts` در CI با Node 20؛ هیچ `any` پنهان و هیچ نمونهٔ نامعتبری عبور نمیکند.
- **گیتهای تازهٔ قرارداد (`src/tests/test_frontend_contract.py`)**: ۲۳ آزمون برای جلوگیری از
  درفت مستندات، ناهمسازی تایپها/کالکشن/پورتال، خطاهای اعلامنشده، پاسخهای بدون اسکیمای تایپشده،
  طرحهای امنیتی، نرخهای throttle و مسیرهای زندهٔ مستندات.
- **متغیرهای محیطی تازه**: `PUBLIC_API_BASE_URL`، `DJANGO_SESSION_COOKIE_SAMESITE`،
  `TRUSTED_PROXY_COUNT`، `PROBLEM_TYPE_URI_TEMPLATE`، `API_DOCS_ALLOW_ANONYMOUS`،
  `THROTTLE_ANON_PUBLIC` و `THROTTLE_CHECKOUT`.

### اصلاحشده (Fixed)
- **کوکی نشست عملاً `cf_session` نبود**: متغیر `AUTH_SESSION_COOKIE_NAME` تعریف شده ولی به
  `SESSION_COOKIE_NAME` متصل نبود؛ اکنون نام کوکی، طرح `cookieAuth` در OpenAPI و مستندات یکیاند.
- **مستندات منسوخ**: ۶ مسیر/متد نادرست در `docs/api/v1/README.md` و نمونهٔ خطای قدیمی در
  `docs/api/README.md` (`request_id` ← `trace_id`، نشانی `type` ← لنگر واقعی `ERRORS.md`) اصلاح شد.
- **صفحات مستندات خالی در تولید**: CSP سختگیرانه، بارگذاری CDN مجاز drf-spectacular را مسدود
  میکرد و پیشوند پنل ادمین در `docs_protected_wrapper` نادرست بود؛ هر دو اصلاح شدند.
- **پوشش صفحهبندی نادرست در قرارداد**: پنج نقطهٔ پایانی `{results, meta}` برمیگرداندند ولی
  در OpenAPI «آرایه» اعلام شده بودند (عامل خطای تولید کلاینتهای خودکار).
- **نرخهای محدودسازی بلااستفاده**: `anon_public` / `checkout` / `mfa_verify` فقط در تنظیمات تست
  تعریف شده بودند؛ اکنون `StandardIpThrottle` بهعنوان پیشفرض سراسری و `CheckoutThrottle` /
  `MfaVerifyThrottle` به نقاط حساس متصلاند.
- **نشانی `type` خطاها** به دامنهای غیرواقعی اشاره میکرد؛ اکنون لنگر پایدار و قابل استناد
  در کاتالوگ `docs/frontend/ERRORS.md` است.

- **تایپ تاریخ‌ها در `api-types.d.ts` غلط بود**: مولد، `format: date-time` را به `number` نگاشت
  می‌کرد در حالی که DRF رشتهٔ `2026-11-14T10:53:28+03:30` برمی‌گرداند؛ نتیجه در فرانت
  `new Date(number)` و نمایش ۱۹۷۰ بود. اکنون تمام ۲۷ فیلد تاریخ/زمان `string` هستند و گیت تازهٔ
  `test_typescript_types_match_runtime_json_scalars` هر درفتی را رد می‌کند.
- **گزارش اکسل با تایپ اشتباه اعلام شده بود**: `GET /admin/reports/excel` در `api-types.d.ts`
  و `ApiOperationMap` مقدار `string` داشت ولی کلاینت `blob()` برمی‌گرداند؛ اکنون `Blob` است و
  helperهای `client.download()` / `client.saveBlob()` به بسته افزوده شد.
- **توکن CSRF پس از ورود باطل می‌شد**: `establish_dual_session` نشست را `cycle_key` می‌کند و
  توکن کش‌شدهٔ فرانت با `403` رد می‌شد. اکنون `csrf_failed` کد اختصاصی دارد، `permission_denied`
  هرگز به آن آلوده نمی‌شود، و `api-client.ts` بی‌صدا توکن تازه می‌گیرد و **همان** درخواست را
  دقیقاً یک‌بار تکرار می‌کند (`resetCsrf` + `csrfRetried`، بدون حلقهٔ بی‌پایان).
- **نشت پیام‌های انگلیسی DRF به کاربر**: `detail`های «Authentication credentials were not
  provided» و «CSRF Failed: …» با پیام فارسی پایدار جایگزین شدند و متن اصلی فقط در لاگ می‌ماند.
- **قالب `today_jalali` ناهمخوان بود**: کد `YYYY-MM-DD` برمی‌گرداند ولی راهنما `YYYY/MM/DD`
  نشان می‌داد؛ مستند با رانتایم هم‌تراز شد و قاعدهٔ «ISO-8601 با انحراف منطقهٔ زمانی» (به‌جای
  فرض نادرست «UTC با Z») صریح شد.

### ارتقا یافته
- مجموعهٔ آزمونها از **۳۱ به ۶۰** و پوشش شاخهای از **۸۵٫۲۸٪ به ۸۵٫۸۲٪** افزایش یافت؛
  اسکیمای OpenAPI از **۸۲ به ۱۱۲** کامپوننت و از **۰ به ۱۱** پاسخ خطای استاندارد رسید.

---

## [1.0.0] - 2026-11-12 (۱۴۰۵/۰۸/۲۱)

### افزوده‌شده (Added)
- **معماری ماژولار ۹ لایه (Bounded Contexts)**: پیاده‌سازی کامل ماژول‌های `core`، `audit`، `identity`، `notifications`، `benefactors`، `campaigns`، `ledger`، `contributions` و `reporting` روی Django 6.1 و MariaDB 11.x با گیت‌های خودکار AST.
- **حرکت‌های خیرخواهانهٔ سهم‌محور و قلک عام**: مدل‌سازی کامل حرکت‌ها، دسته‌بندی‌ها، گالری مستندات، پیوندک (`ShortLink`)، الگوریتم رتبه‌بندی منصفانه و قلک‌های عام خیریه (`CharityJar`).
- **دفتر کل حسابداری دوطرفه ریالی (`ledger`)**: ثبت خودکار اسناد حسابداری متوازن برای هر پرداخت آنلاین، کمک مضاعف و استرداد وجه؛ تسویهٔ چهارچشمی با خیریه (Maker-Checker)؛ مغایرت‌گیری بانکی و معادلهٔ کنترل تراز صفر.
- **۸ قابلیت خلاقانهٔ دامنه + داشبورد جامع خیر**:
  1. مشارکت سریع ۳۰ ثانیه‌ای مهمان با موبایل (`ExpressContributionIntent`)
  2. نیت‌نامه و کارت هدیه معنوی با لینک اشتراک عمومی (`DedicationCard`)
  3. قلک عام خیریه برای کمک‌های خرد و مستمر (`CharityJar`)
  4. لینک اختصاصی سفیران اجتماعی با شمارش کلیک و سهام جذب‌شده (`AmbassadorLink`)
  5. حامیان مضاعف‌کنندهٔ سهام با کسر اتمیک از استخر تعهد (`MatchingGrant`)
  6. دیوار شفافیت رمزنگاری درخت مرکل منطبق بر **RFC 6962** و اثبات شمول مستقل برای هر خیر (`merkle.py`)
  7. گزارش‌های پیشرفت میدانی مرحله‌ای با اعلان خودکار به حامیان حرکت (`CampaignImpactUpdate`)
  8. ثبت ممیزی‌شدهٔ مشارکت‌های خارج از درگاه آنلاین (`ExternalContribution`)
  9. داشبورد یکپارچهٔ خیر در `/api/v1/me/dashboard`
- **امنیت، هویت دوگانه و ممیزی رمزنگاری‌شده**: ورود OTP پنج‌رقمی (هش HMAC)، نشست دوگانه کوکی `HttpOnly` + `SessionAwareJWT`، تشخیص سرقت Refresh Token، احراز دومرحله‌ای **TOTP (RFC 6238)** + کدهای بازیابی (`Step-Up MFA`)، رمزنگاری کدملی و زنجیرهٔ هش تغییرناپذیر `AuditRecord` با لنگر امضاشدهٔ `HMAC`.
- **پورت آمادهٔ اتصال پنل پیامک الگومحور (`notifications`)**: صف تراکنشی `OutboxMessage` با قفل `SKIP LOCKED` و آداپتور HTTPS بدون نیاز به تغییر کد هنگام تحویل کلید پنل پیامک.
- **موتور گزارش‌گیری اکسل ۸ کاربرگهٔ راست‌به‌چپ (`reporting`)**: کارپوشهٔ حرفه‌ای A4 افقی با فونت فارسی وزیرمتن، فرمول‌های زنده، نمودار میله‌ای، حفاظت از حریم خصوصی شماره‌ها و ثبت هش `SHA-256`.
- **زیرساخت استقرار و CI**: بستهٔ کامل استقرار سی‌پنل نایترو (CloudLinux Passenger + Cron)، فایل‌های `Dockerfile` و `compose.yaml`، قرارداد اعتبارسنجی‌شدهٔ `docs/api/v1/openapi.yaml` و خط لولهٔ کامل GitHub Actions با پوشش شاخه‌ای بالای ۸۵٪.
