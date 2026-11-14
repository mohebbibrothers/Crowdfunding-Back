# ✅ چکلیست پذیرش تحویل فرانتاند (Definition of Done)

> این چکلیست سند رسمی «آمادهٔ استقرار» است. تیک نخوردن هر ردیف یعنی هنوز ریسک
> ناهماهنگی با بکاند وجود دارد. نسخهٔ قرارداد: `v1.1.0` · اثر انگشت:
> [`contract-fingerprint.json`](./contract-fingerprint.json)

## الف) قرارداد و تایپها

- [ ] `docs/api/v1/openapi.yaml` خوانده شد و `servers[0].url` با `VITE_API_BASE_URL` یکی است.
- [ ] `api-types.d.ts` و `operations.ts` مستقیماً کپی شدند و **دستکاری نشدند**.
- [ ] `make handoff` روی مخزن بکاند اجرا شد و خروجی `git status` تمیز است (یعنی درفتی وجود ندارد).
- [ ] `make tscheck` با `strict: true` عبور کرد و `type-tests.ts` هیچ خطای تایپی نداد.
- [ ] هیچ نقطهٔ پایانی بهصورت دستی hardcoded نشده؛ همه از `OPERATIONS[operationId]` میآیند.
- [ ] `ApiOperationMap` در حداقل ۳ فراخوانی واقعی استفاده شده و خطای تایپی وجود ندارد.

## ب) بوت، پیکربندی و بومیسازی

- [ ] `GET /api/v1/meta` در بوت اپ فراخوانی میشود و `supported_versions` شامل `v1` است.
- [ ] `app_version` متادیتا (نسخهٔ استقراری بکاند) در پنل «درباره»/گزارش خطا ثبت میشود.
- [ ] پرچمهای `features` مبنای نمایش/پنهانسازی بلوکهای رابط هستند (مثلاً نیتنامه، مرکل، قلک عام، حامی مضاعف).
- [ ] `share_hold_ttl_minutes` از متادیتا خوانده میشود، نه hardcoded عدد ۱۵.
- [ ] تمام مبالغ نمایشی از فیلد `*_toman` و با `Intl.NumberFormat("fa-IR")` رندر میشوند.
- [ ] تمام تاریخهای نمایشی از فیلد `*_jalali`اند؛ تبدیل سمت کلاینت انجام نمیشود.
- [ ] رابط `dir="rtl"`، فونت فارسی و ارقام `tabular-nums` در جداول مالی تنظیم شده است.

## ج) احراز هویت و نشست

- [ ] حالت `cookie`: `GET /auth/csrf` در بوت و `X-CSRFToken` روی تمام متدهای نوشتنی ارسال میشود.
- [ ] حالت `cookie`: `credentials: "include"` تنظیم شده و نام کوکی `cf_session` توسط JS خوانده **نمیشود**.
- [ ] حالت `bearer`: توکنها در حافظهٔ امن نگهداری میشوند و در `localStorage` ذخیره **نمیشوند**.
- [ ] چرخش توکن دقیقاً یکبار و بهصورت Single-Flight انجام میشود (چند `401` همزمان ⇒ یک refresh).
- [ ] تشخیص سرقت refresh ⇒ پاکسازی کامل توکنها و هدایت به `/login` بدون حلقهٔ بیپایان.
- [ ] صفحهٔ «دستگاههای من» با `GET /me/sessions` و `POST /me/sessions/{id}/revoke` کار میکند.
- [ ] پنل ادمین: جریان `password-login → mfa/status → totp/setup → totp/confirm → mfa/verify` تست شد.
- [ ] `403` با `step_up_required` ⇒ مودال TOTP تازه ⇒ **همان** درخواست با **همان** `Idempotency-Key`.

## د) خطاها و تابآوری

- [ ] تمام خطاها به `ApiClientError` تبدیل میشوند و branching روی `code` است، نه `detail`.
- [ ] `422`: پیامهای `errors[field]` دقیقاً زیر همان فیلدها نمایش داده میشوند.
- [ ] `429`/`503`: `Retry-After` رعایت و backoff نمایی اعمال میشود.
- [ ] `500`: فقط `trace_id` به کاربر نمایش داده میشود؛ هیچ جزئیات فنی/ stack traces افشا نمیشود.
- [ ] `404 invalid_cursor`: کش لیست پاک و صفحهبندی از نو آغاز میشود.
- [ ] `Idempotency-Key` تازه برای هر عملیات مالی؛ یک کلید هرگز با دو بدنهٔ متفاوت ارسال نمیشود.
- [ ] هدر `X-Request-ID` پاسخ در گزارش خطای کاربر به پشتیبانی ذخیره میشود.

## ه) دادهها و لیستها

- [ ] پنج لیست مکاننمایی (`me/contributions`, `me/notifications`, `admin/audit/logs`,
      `admin/users`, `admin/auth/risk-signals`) بهصورت `{results, meta}` رندر میشوند.
- [ ] `meta.next` عیناً (بدون ساخت دستی `cursor`/`offset`) استفاده میشود.
- [ ] `meta.total` فقط در لیستهای شخصی انتظار میرود؛ جداول ادمین `total` ندارند.
- [ ] `ETag`/`If-None-Match` و پاسخ `304` در فهرست حرکتها/خیریهها تست شد.
- [ ] فیلترهای مستندشده (`category`, `status`, `order`, `q`, `unread`, …) با همان نام ارسال میشوند.
- [ ] دیوار همراهان، مقدار «خیر گمنام» را بدون تلاش برای شناسایی نمایش میدهد.
- [ ] صفحهٔ نیتنامهٔ عمومی هیچ عدد ریالی/تومانی نشان نمیدهد.

## و) جریان پرداخت (مهمترین تست انتهابهانتها)

- [ ] `POST /contributions/checkout` با `gateway_name: "sandbox"` ⇒ پاسخ ۲۰۱ با `gateway_redirect_url`.
- [ ] شمارشگر معکوس رزرو ۱۵ دقیقهای نمایش داده میشود و در انقضا پیام `resource_expired` هندل میشود.
- [ ] `GET /payments/sandbox/{authority}` رندر شبیهساز درگاه را تغذیه میکند.
- [ ] `GET|POST /payments/callback` **تنها** مبنای نمایش «پرداخت موفق» است (نه `Status=OK` درگاه).
- [ ] صفحهٔ نتیجه با refresh مرورگر مشارکت تکراری نمیسازد (idempotent).
- [ ] `receipt_number` و `verification_code` به صفحهٔ رسید منتقل و `GET /receipts/verify/{code}` تست شد.
- [ ] در صورت وجود `dedication_token`، `GET /dedications/{token}` کارت هدیهٔ معنوی را نشان میدهد.
- [ ] جریان مهمان ۳۰ ثانیهای (`express/start → express/confirm`) بهصورت کامل تست شد.
- [ ] `GET /campaigns/{slug}/transparency` و `POST /transparency/verify-proof` با `valid: true` تست شد.

## ز) امنیت و استقرار

- [ ] `CORS_ALLOWED_ORIGINS` دقیقاً دامنهٔ فرانتاند است (نه `*`) و `CORS_ALLOW_CREDENTIALS` روشن.
- [ ] روی دامنهٔ متفاوت: `DJANGO_SESSION_COOKIE_SAMESITE=None` + `SESSION_COOKIE_SECURE=true` + HTTPS.
- [ ] هیچ شماره تلفن کامل خیری در لیستهای عمومی نمایش داده نمیشود (`masked_phone` / «خیر گمنام»).
- [ ] CSP فرانتاند، `X-Frame-Options` و جلوگیری از بارگذاری اسکریپت ناشناس بررسی شدند.
- [ ] لاگهای کلاینت حاوی توکن، کد OTP، شماره موبایل یا `Idempotency-Key` نیستند.
- [ ] `GET /health/ready` در مانیتورینگ/ readiness فرانتاند (در صورت SSR) استفاده میشود.
- [ ] `SECURITY.md` و [`ERRORS.md`](./ERRORS.md) در اختیار تیم پشتیبانی قرار گرفتند.

## ح) هماهنگی تیمی

- [ ] تیم فرانتاند [`HANDOFF.md`](./HANDOFF.md) را خوانده و [`index.html`](./index.html) را دیده است.
- [ ] [`postman_collection.json`](./postman_collection.json) در Postman/Bruno import و متغیرها تنظیم شدند.
- [ ] مالک قرارداد مشخص است؛ هر تغییر بکاند ⇒ `make handoff` ⇒ بررسی diff ⇒ اطلاع به فرانتاند.
- [ ] نسخهٔ `v1.1.0` در CHANGELOG ثبت و تگ/Release مربوطه منتشر شد.

---

**امضای تحویل:** پس از تیک خوردن تمام موارد، این فایل در PR فرانتاند پیوست شود. 🎉
