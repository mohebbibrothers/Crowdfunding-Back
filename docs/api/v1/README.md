# راهنمای جامع API نسخهٔ ۱ (`/api/v1`) — یکپارچه‌سازی فرانت‌اند و موبایل

قرارداد ماشینی کامل این نسخه در فایل [`openapi.yaml`](./openapi.yaml) (استاندارد **OpenAPI 3.1.0** با صفر هشدار اعتبارسنجی) قرار دارد. در محیط توسعه نیز رابط تعاملی Swagger UI در `/api/v1/docs` و ReDoc در `/api/v1/redoc` در دسترس است.

---

## ۱. قرادادهای سراسری پروتکل

### الف) واحد پولی دوگانه (`rial_base_dual_view`)
- تمامی ورودی‌های مبلغ بر مبنای **ریال صحیح (`int` مضرب ۱۰)** دریافت می‌شوند (برای حرکت‌های سهم‌محور فقط `shares_count` ارسال می‌شود و سرور مبلغ را از قیمت سهم محاسبه می‌کند).
- در تمامی پاسخ‌های API، هر مبلغ به‌صورت جفت فیلد `*_rial` و `*_toman` بازگردانده می‌شود تا رابط کاربری بدون خطای محاسباتی، معادل تومانی را نمایش دهد.

### ب) کلید یکتایی درخواست (`Idempotency-Key`)
- برای نقاط پایانی حساس به تکرار نظیر `POST /api/v1/contributions/checkout` و `POST /api/v1/contributions/express/initiate`، ارسال هدر `Idempotency-Key: <UUID>` پشتیبانی می‌شود.
- ارسال مجدد همان کلید با همان بدنه، پاسخ کش‌شدهٔ قبلی را برمی‌گرداند؛ ارسال همان کلید با بدنهٔ متفاوت با خطای `409 Conflict` مسدود می‌شود.

### ج) احراز هویت دوگانه (`Cookie` + `Bearer JWT`)
1. **فرانت‌اند وب هم‌دامنه / زیردامنه**: ابتدا `GET /api/v1/auth/csrf` را فراخوانی کنید؛ پس از تایید OTP، کوکی امن `HttpOnly` (`cf_session`) روی مرورگر ست می‌شود.
2. **اپلیکیشن موبایل / کلاینت‌های SPA مستقل**: از `access_token` و `refresh_token` برگشتی در هدر `Authorization: Bearer <access_token>` استفاده کنید. در هر چرخش توکن (`POST /api/v1/auth/token/refresh`)، توکن قبلی باطل شده و استفادهٔ مجدد از توکن قدیمی تمام نشست را به دلیل احتمال سرقت مسدود می‌کند.

### د) احراز دومرحله‌ای ارتقایافته (`Step-Up MFA`) برای مدیران
عملیات حساس مدیریتی (تغییر سیاست‌ها، ثبت مشارکت خارجی، تایید تسویه با خیریه، استرداد وجه، رویت شماره موبایل کامل خیر و خروجی اکسل شامل اطلاعات هویتی) نیازمند نشست دارای تایید تازهٔ TOTP هستند. در صورت دریافت پاسخ `403` با `"code": "mfa_required"`، کلاینت باید کد ۶ رقمی TOTP را به `POST /api/v1/auth/mfa/verify` ارسال و سپس درخواست را تکرار کند.

---

## ۲. خلاصهٔ نقاط پایانی اصلی به تفکیک دامنه

### سلامت و سیاست‌ها (`core`)
- `GET /api/v1/health/live` و `GET /api/v1/health/ready` — سلامت زنده بودن و آمادگی دیتابیس
- `GET /api/v1/health/detailed` — سلامت تفصیلی ویژه مدیران
- `GET /api/v1/admin/policies` و `POST /api/v1/admin/policies/{policy_key}` — مشاهده و ویرایش زندهٔ سیاست‌های عملیاتی و پرچم ویژگی‌ها

### هویت، نشست‌ها و MFA (`identity` & `notifications`)
- `POST /api/v1/auth/otp/request` و `POST /api/v1/auth/otp/verify` — ورود/ثبت‌نام خیرین با کد ۵ رقمی موبایل
- `POST /api/v1/auth/staff/password-login` — ورود اولیه کارکنان
- `POST /api/v1/auth/token/refresh`، `POST /api/v1/auth/logout`، `POST /api/v1/auth/logout-others` — مدیریت چرخه توکن و خروج
- `POST /api/v1/auth/mfa/totp/setup`، `POST /api/v1/auth/mfa/totp/confirm`، `POST /api/v1/auth/mfa/verify`، `GET /api/v1/auth/mfa/status` — مدیریت کامل TOTP و کدهای بازیابی
- `GET/PATCH /api/v1/me`، `GET /api/v1/me/sessions`، `POST /api/v1/me/sessions/{session_id}/revoke` — پروفایل و نشست‌های فعال کاربر
- `GET /api/v1/me/notifications`، `POST /api/v1/me/notifications/{id}/read`، `POST /api/v1/me/notifications/read-all` — صندوق اعلان‌ها
- `GET /api/v1/admin/users`، `POST /api/v1/admin/users/{id}/reveal-phone`، `POST /api/v1/admin/users/{id}/role` — مدیریت کاربران و رویت ممیزی‌شده شماره

### خیریه‌ها، قلک‌ها و حرکت‌های سهم‌محور (`benefactors` & `campaigns`)
- `GET /api/v1/benefactors` و `GET /api/v1/benefactors/{slug}` — فهرست و صفحهٔ اختصاصی خیریه‌ها (مددکاران)
- `GET /api/v1/jars` و `GET /api/v1/jars/{identifier}` — قلک‌های عام خیریه برای مبالغ دلخواه
- `GET /api/v1/campaign-categories`، `GET /api/v1/campaigns`، `GET /api/v1/campaigns/{identifier}` — کاتالوگ حرکت‌ها (با پشتیبانی از `ETag` / `If-None-Match` و مرتب‌سازی هوشمند)
- `GET /api/v1/short-links/{short_code}` — حل‌کنندهٔ یکپارچه پیوندک حرکت و لینک سفیران اجتماعی
- `POST /api/v1/admin/campaigns/{id}/matching-grants` — ثبت حامی مضاعف‌کننده (ضریب هم‌افزایی سهام)
- `POST /api/v1/admin/campaigns/{id}/impact-updates` — انتشار گزارش پیشرفت میدانی مرحله‌ای (همراه با اعلان خودکار به خیرین آن حرکت)

### مشارکت‌ها، قابلیت‌های خلاقانه و شفافیت مرکل (`contributions`)
- `POST /api/v1/contributions/checkout` — آغاز مشارکت در حرکت سهم‌محور یا قلک عام (رزرو اتمیک ۱۵ دقیقه‌ای سهام)
- `POST /api/v1/contributions/express/initiate` و `POST /api/v1/contributions/express/confirm-otp` — مشارکت سریع ۳۰ ثانیه‌ای مهمان بدون نیاز به ثبت‌نام قبلی
- `GET/POST /api/v1/payments/callback` و `POST /api/v1/payments/sandbox/{authority}/complete` — بازگشت از درگاه بانکی و شبیه‌ساز توسعه
- `GET /api/v1/receipts/verify/{verification_token}` — استعلام عمومی اصالت رسید رسمی مشارکت
- `GET /api/v1/dedications/{public_token}` — مشاهده عمومی کارت هدیه معنوی و نیت‌نامه خیر
- `GET/POST /api/v1/me/ambassador-links` — ساخت لینک سفیر اجتماعی و مشاهده آمار سهام جذب‌شده
- `GET /api/v1/me/dashboard` — داشبورد جامع کاربری خیر (مجموع تاثیر، حرکت‌های حمایت‌شده، رسیدها، نیت‌نامه‌ها و اثر سفیر)
- `GET /api/v1/campaigns/{identifier}/transparency`، `GET /api/v1/me/contributions/{id}/merkle-proof` و `POST /api/v1/transparency/verify-proof` — دیوار شفافیت رمزنگاری و راستی‌آزمایی اثبات شمول درخت مرکل

### دفتر کل دوطرفه، ممیزی و گزارش اکسل ۸ کاربرگه (`ledger`, `audit`, `reporting`)
- `GET /api/v1/admin/ledger/accounts`، `GET /api/v1/admin/ledger/entries`، `POST /api/v1/admin/ledger/control-snapshot`
- `GET/POST /api/v1/admin/disbursements` و `POST /api/v1/admin/disbursements/{id}/approve` — تسویهٔ چهارچشمی با خیریه
- `GET/POST /api/v1/admin/reconciliations` — مغایرت‌گیری فایل تسویه درگاه بانکی با دفتر کل
- `POST /api/v1/admin/campaigns/{id}/external-contributions` و `POST /api/v1/admin/payments/{id}/refund` — ثبت کمک خارج از درگاه و استرداد وجه
- `GET /api/v1/admin/audit/logs` و `GET /api/v1/admin/audit/verify` — مشاهده و راستی‌آزمایی زنجیرهٔ هش ممیزی
- `GET /api/v1/admin/reports/excel` و `GET /api/v1/admin/reports/exports-history` — دانلود کارپوشه اکسل ۸ کاربرگهٔ راست‌به‌چپ با ثبت هش SHA-256
