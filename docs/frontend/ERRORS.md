# کاتالوگ رسمی خطاهای API (RFC 9457) — ویژهٔ فرانتاند

> هر پاسخ خطا `Content-Type: application/problem+json` دارد و فیلد `type` آن دقیقاً به یکی از لنگرهای زیر اشاره میکند. مبنای branching در رابط کاربری، **`code`** است؛ هرگز روی `detail` یا `status` بهتنهایی شرط نگذارید.

## شکل کلی پاسخ خطا

```json
{
  "type": "https://github.com/mohebbibrothers/Crowdfunding-Back/blob/main/docs/frontend/ERRORS.md#error-mfa_required",
  "title": "تأیید دومرحلهای الزامی است",
  "status": 403,
  "detail": "برای دسترسی به پنل عملیاتی، ابتدا کد تأیید دومرحلهای را وارد کنید.",
  "code": "mfa_required",
  "instance": "/api/v1/contributions/checkout",
  "trace_id": "019384ab-...",
  "errors": { "shares_count": ["باید بزرگتر از صفر باشد."] }
}
```

## فهرست کدها

| کد (`code`) | HTTP | عنوان | اقدام پیشنهادی در رابط |
| --- | --- | --- | --- |
| [`malformed_request`](#error-malformed_request) | `400` | درخواست بدشکل | بدنه را دوباره بساز؛ از ارسال رشتهٔ خام یا Content-Type اشتباه پرهیز کن. |
| [`authentication_required`](#error-authentication_required) | `401` | احراز هویت ناموفق | ابتدا refresh توکن را امتحان کن؛ در صورت شکست، کاربر را به جریان OTP هدایت کن. |
| [`permission_denied`](#error-permission_denied) | `403` | عدم مجوز دسترسی | دکمه/مسیر را پنهان کن و پیام عمومی نمایش بده؛ جزئیات نقش را افشا نکن. |
| [`mfa_required`](#error-mfa_required) | `403` | تأیید دومرحله‌ای الزامی است | مودال کد ۶ رقمی TOTP را باز کن و سپس درخواست را دقیقاً یکبار تکرار کن. |
| [`step_up_required`](#error-step_up_required) | `403` | نیازمند تأیید مجدد امنیتی | کد TOTP تازه بگیر، سپس همان درخواست را با همان Idempotency-Key بازارسال کن. |
| [`not_found`](#error-not_found) | `404` | یافت نشد | صفحهٔ ۴۰۴ عمومی نشان بده؛ پیام «وجود ندارد» را به «عدم دسترسی» تعبیر نکن. |
| [`invalid_cursor`](#error-invalid_cursor) | `404` | مکان‌نمای نامعتبر | کش صفحات را پاک کن و از صفحهٔ نخست بدون cursor شروع کن. |
| [`conflict`](#error-conflict) | `409` | تصادم با وضعیت فعلی | وضعیت را دوباره واکشی کن و رابط را با آخرین state همگام کن. |
| [`idempotency_conflict`](#error-idempotency_conflict) | `409` | تعارض کلید هم‌توانی | کلید تازهٔ UUIDv4 بساز؛ هرگز کلید قدیمی را با بدنهٔ متفاوت بازارسال نکن. |
| [`idempotency_in_progress`](#error-idempotency_in_progress) | `409` | درخواست همزمان در حال پردازش | ۲ تا ۵ ثانیه صبر کن و همان کلید را بازارسال کن (بدون ساخت رکورد تازه). |
| [`resource_expired`](#error-resource_expired) | `410` | منقضی‌شده | رزرو/کد را از نو آغاز کن و شمارشگر معکوس رابط را ریست کن. |
| [`validation_error`](#error-validation_error) | `422` | خطای اعتبارسنجی ورودی | errors[field] را مستقیماً زیر هر فیلد نمایش بده و فوکوس را به اولین خطا ببر. |
| [`feature_disabled`](#error-feature_disabled) | `409` | قابلیت غیرفعال است | بلوک رابط را پنهان کن؛ پیش از رندر، features متادیتا را بررسی کن. |
| [`rate_limited`](#error-rate_limited) | `429` | عبور از سقف مجاز درخواست | طبق هدر Retry-After یا فیلد retry_after صبر کن و سپس تلاش مجدد کن. |
| [`service_overloaded`](#error-service_overloaded) | `503` | سامانه موقتاً پرمشغله است | نمایش وضعیت «در حال تلاش دوباره» و retry نمایی با هدر Retry-After. |
| [`method_not_allowed`](#error-method_not_allowed) | `405` | متد غیرمجاز | متد را با جدول نقاط پایانی تطبیق بده (اشکال قراردادی است، نه خطای کاربر). |
| [`internal_error`](#error-internal_error) | `500` | خطای داخلی سامانه | فقط trace_id را به کاربر نشان بده تا بتواند به پشتیبانی ارجاع دهد. |
| [`invalid_phone`](#error-invalid_phone) | `422` | شماره موبایل نامعتبر | پیام inline زیر فیلد موبایل؛ قالب 09xxxxxxxxx را پیشنهاد بده. |
| [`invalid_otp_code`](#error-invalid_otp_code) | `422` | کد تأیید نادرست | ورودی را پاک کن و شمارندهٔ تلاشهای باقیمانده را نمایش بده. |
| [`otp_expired`](#error-otp_expired) | `410` | کد تأیید منقضی شد | دکمهٔ «ارسال مجدد کد» را فعال کن. |
| [`otp_attempts_exceeded`](#error-otp_attempts_exceeded) | `429` | سقف تلاشهای کد یکبارمصرف پر شد | چالش را از نو آغاز کن و پیام محدودیت زمانی نشان بده. |
| [`otp_window_exceeded`](#error-otp_window_exceeded) | `429` | درخواست کد بیش از حد | شمارشگر معکوس تا زمان ارسال مجدد نمایش بده. |
| [`invalid_mfa_code`](#error-invalid_mfa_code) | `422` | کد دومرحله‌ای نادرست | کد را پاک کن؛ تعداد تلاشهای باقیمانده را نمایش بده. |
| [`mfa_locked`](#error-mfa_locked) | `429` | عامل دوم موقتاً قفل شد | زمان رفع قفل را نمایش بده و از کد بازیابی استفاده کن. |
| [`mfa_not_enrolled`](#error-mfa_not_enrolled) | `409` | عامل دوم راهاندازی نشده | کاربر را به جریان setup/confirm هدایت کن. |
| [`mfa_already_enrolled`](#error-mfa_already_enrolled) | `409` | عامل دوم پیشتر فعال شده | به صفحهٔ وضعیت MFA هدایت کن. |
| [`mfa_setup_missing`](#error-mfa_setup_missing) | `409` | نشست راهاندازی TOTP یافت نشد | فرایند setup را از نو آغاز کن. |
| [`invalid_sheba`](#error-invalid_sheba) | `422` | شبا نامعتبر | زیر فیلد شبا خطا بده؛ قالب IR و ۲۴ رقم پس از آن را یادآوری کن. |
| [`invalid_national_code`](#error-invalid_national_code) | `422` | کد ملی نامعتبر | خطای inline زیر فیلد کد ملی. |
| [`duplicate_national_code`](#error-duplicate_national_code) | `409` | کد ملی تکراری | امکان بازیابی حساب را پیشنهاد بده. |
| [`reason_required`](#error-reason_required) | `422` | ثبت دلیل الزامی است | فیلد دلیل را اجباری کن و حداقل طول را رعایت کن. |
| [`unknown_policy_key`](#error-unknown_policy_key) | `404` | کلید سیاست ناشناخته | فهرست سیاستها را از /api/v1/admin/policies واکشی کن. |
| [`cannot_revoke_current_session`](#error-cannot_revoke_current_session) | `409` | ابطال نشست جاری ممکن نیست | کاربر را به خروج عادی هدایت کن. |
| [`user_inactive`](#error-user_inactive) | `401` | حساب غیرفعال | پیام پشتیبانی عمومی نمایش بده و توکنها را پاک کن. |
| [`sms_budget_exhausted`](#error-sms_budget_exhausted) | `503` | بودجهٔ پیامک به پایان رسید | پیام «موقتاً در دسترس نیست» و تلاش مجدد بعدی. |
| [`domain_error`](#error-domain_error) | `400` | خطای دامنه | detail را به کاربر نمایش بده و وضعیت را دوباره واکشی کن. |
| [`csrf_failed`](#error-csrf_failed) | `403` | اعتبار توکن CSRF از دست رفت | با GET /auth/csrf توکن تازه بگیر و همان درخواست را یک‌بار تکرار کن؛ کلاینت این کار را خودکار انجام می‌دهد. |
| [`session_rotated`](#error-session_rotated) | `409` | نشست هم‌زمان در دستگاه دیگری به‌روز شد | صفحه را تازه‌سازی کن و در صورت ادامهٔ خطا، کاربر را به ورود مجدد هدایت کن. |

## جزئیات هر کد

### <a id="error-malformed_request"></a>`malformed_request` — درخواست بدشکل (`400`)

- **شرح سرور:** ساختار JSON یا بدنهٔ ارسالی قابل خواندن نیست.
- **اقدام فرانتاند:** بدنه را دوباره بساز؛ از ارسال رشتهٔ خام یا Content-Type اشتباه پرهیز کن.
- **نشانی `type`:** `.../ERRORS.md#error-malformed_request`

### <a id="error-authentication_required"></a>`authentication_required` — احراز هویت ناموفق (`401`)

- **شرح سرور:** نشست باطل شده، توکن منقضی شده یا کاربر وارد نشده است.
- **اقدام فرانتاند:** ابتدا refresh توکن را امتحان کن؛ در صورت شکست، کاربر را به جریان OTP هدایت کن.
- **نشانی `type`:** `.../ERRORS.md#error-authentication_required`

### <a id="error-permission_denied"></a>`permission_denied` — عدم مجوز دسترسی (`403`)

- **شرح سرور:** نقش کاربر اجازهٔ انجام این عملیات را ندارد.
- **اقدام فرانتاند:** دکمه/مسیر را پنهان کن و پیام عمومی نمایش بده؛ جزئیات نقش را افشا نکن.
- **نشانی `type`:** `.../ERRORS.md#error-permission_denied`

### <a id="error-mfa_required"></a>`mfa_required` — تأیید دومرحله‌ای الزامی است (`403`)

- **شرح سرور:** نشست کارمند هنوز عامل دوم را نگذرانده است.
- **اقدام فرانتاند:** مودال کد ۶ رقمی TOTP را باز کن و سپس درخواست را دقیقاً یکبار تکرار کن.
- **نشانی `type`:** `.../ERRORS.md#error-mfa_required`

### <a id="error-step_up_required"></a>`step_up_required` — نیازمند تأیید مجدد امنیتی (`403`)

- **شرح سرور:** عملیات حساس نیازمند TOTP تازه (در پنجرهٔ ۱۰ دقیقه) است.
- **اقدام فرانتاند:** کد TOTP تازه بگیر، سپس همان درخواست را با همان Idempotency-Key بازارسال کن.
- **نشانی `type`:** `.../ERRORS.md#error-step_up_required`

### <a id="error-not_found"></a>`not_found` — یافت نشد (`404`)

- **شرح سرور:** منبع ناموجود است یا متعلق به کاربر جاری نیست (ضد افشای شناسه).
- **اقدام فرانتاند:** صفحهٔ ۴۰۴ عمومی نشان بده؛ پیام «وجود ندارد» را به «عدم دسترسی» تعبیر نکن.
- **نشانی `type`:** `.../ERRORS.md#error-not_found`

### <a id="error-invalid_cursor"></a>`invalid_cursor` — مکان‌نمای نامعتبر (`404`)

- **شرح سرور:** نشانی cursor صفحه دستکاری شده یا منقضی شده است.
- **اقدام فرانتاند:** کش صفحات را پاک کن و از صفحهٔ نخست بدون cursor شروع کن.
- **نشانی `type`:** `.../ERRORS.md#error-invalid_cursor`

### <a id="error-conflict"></a>`conflict` — تصادم با وضعیت فعلی (`409`)

- **شرح سرور:** وضعیت موجودیت اجازهٔ انجام عملیات را نمی‌دهد.
- **اقدام فرانتاند:** وضعیت را دوباره واکشی کن و رابط را با آخرین state همگام کن.
- **نشانی `type`:** `.../ERRORS.md#error-conflict`

### <a id="error-idempotency_conflict"></a>`idempotency_conflict` — تعارض کلید هم‌توانی (`409`)

- **شرح سرور:** همان Idempotency-Key پیشتر با بدنه یا کاربر متفاوتی ثبت شده است.
- **اقدام فرانتاند:** کلید تازهٔ UUIDv4 بساز؛ هرگز کلید قدیمی را با بدنهٔ متفاوت بازارسال نکن.
- **نشانی `type`:** `.../ERRORS.md#error-idempotency_conflict`

### <a id="error-idempotency_in_progress"></a>`idempotency_in_progress` — درخواست همزمان در حال پردازش (`409`)

- **شرح سرور:** درخواست دیگری با همان کلید هنوز در حال اجراست.
- **اقدام فرانتاند:** ۲ تا ۵ ثانیه صبر کن و همان کلید را بازارسال کن (بدون ساخت رکورد تازه).
- **نشانی `type`:** `.../ERRORS.md#error-idempotency_in_progress`

### <a id="error-resource_expired"></a>`resource_expired` — منقضی‌شده (`410`)

- **شرح سرور:** مهلت رزرو سهم، لینک یا کد یکبارمصرف به پایان رسیده است.
- **اقدام فرانتاند:** رزرو/کد را از نو آغاز کن و شمارشگر معکوس رابط را ریست کن.
- **نشانی `type`:** `.../ERRORS.md#error-resource_expired`

### <a id="error-validation_error"></a>`validation_error` — خطای اعتبارسنجی ورودی (`422`)

- **شرح سرور:** تمام خطاهای فیلدها بهصورت تجمیعی در کلید errors بازگشتهاند.
- **اقدام فرانتاند:** errors[field] را مستقیماً زیر هر فیلد نمایش بده و فوکوس را به اولین خطا ببر.
- **نشانی `type`:** `.../ERRORS.md#error-validation_error`

### <a id="error-feature_disabled"></a>`feature_disabled` — قابلیت غیرفعال است (`409`)

- **شرح سرور:** پرچم ویژگی مربوطه در /api/v1/meta خاموش است.
- **اقدام فرانتاند:** بلوک رابط را پنهان کن؛ پیش از رندر، features متادیتا را بررسی کن.
- **نشانی `type`:** `.../ERRORS.md#error-feature_disabled`

### <a id="error-rate_limited"></a>`rate_limited` — عبور از سقف مجاز درخواست (`429`)

- **شرح سرور:** نرخ درخواستها بیش از حد مجاز است.
- **اقدام فرانتاند:** طبق هدر Retry-After یا فیلد retry_after صبر کن و سپس تلاش مجدد کن.
- **نشانی `type`:** `.../ERRORS.md#error-rate_limited`

### <a id="error-service_overloaded"></a>`service_overloaded` — سامانه موقتاً پرمشغله است (`503`)

- **شرح سرور:** سد ظرفیت همزمانی فعال شده است.
- **اقدام فرانتاند:** نمایش وضعیت «در حال تلاش دوباره» و retry نمایی با هدر Retry-After.
- **نشانی `type`:** `.../ERRORS.md#error-service_overloaded`

### <a id="error-method_not_allowed"></a>`method_not_allowed` — متد غیرمجاز (`405`)

- **شرح سرور:** متد HTTP ارسالی برای این مسیر پشتیبانی نمیشود.
- **اقدام فرانتاند:** متد را با جدول نقاط پایانی تطبیق بده (اشکال قراردادی است، نه خطای کاربر).
- **نشانی `type`:** `.../ERRORS.md#error-method_not_allowed`

### <a id="error-internal_error"></a>`internal_error` — خطای داخلی سامانه (`500`)

- **شرح سرور:** خطای غیرمنتظره رخ داده است.
- **اقدام فرانتاند:** فقط trace_id را به کاربر نشان بده تا بتواند به پشتیبانی ارجاع دهد.
- **نشانی `type`:** `.../ERRORS.md#error-internal_error`

### <a id="error-invalid_phone"></a>`invalid_phone` — شماره موبایل نامعتبر (`422`)

- **شرح سرور:** شماره موبایل با الگوی ایرانی همخوانی ندارد.
- **اقدام فرانتاند:** پیام inline زیر فیلد موبایل؛ قالب 09xxxxxxxxx را پیشنهاد بده.
- **نشانی `type`:** `.../ERRORS.md#error-invalid_phone`

### <a id="error-invalid_otp_code"></a>`invalid_otp_code` — کد تأیید نادرست (`422`)

- **شرح سرور:** کد ۵ رقمی واردشده با چالش فعال مطابقت ندارد.
- **اقدام فرانتاند:** ورودی را پاک کن و شمارندهٔ تلاشهای باقیمانده را نمایش بده.
- **نشانی `type`:** `.../ERRORS.md#error-invalid_otp_code`

### <a id="error-otp_expired"></a>`otp_expired` — کد تأیید منقضی شد (`410`)

- **شرح سرور:** مهلت استفاده از کد یکبارمصرف سپری شده است.
- **اقدام فرانتاند:** دکمهٔ «ارسال مجدد کد» را فعال کن.
- **نشانی `type`:** `.../ERRORS.md#error-otp_expired`

### <a id="error-otp_attempts_exceeded"></a>`otp_attempts_exceeded` — سقف تلاشهای کد یکبارمصرف پر شد (`429`)

- **شرح سرور:** سقف تلاشهای مجاز برای این چالش پر شده است.
- **اقدام فرانتاند:** چالش را از نو آغاز کن و پیام محدودیت زمانی نشان بده.
- **نشانی `type`:** `.../ERRORS.md#error-otp_attempts_exceeded`

### <a id="error-otp_window_exceeded"></a>`otp_window_exceeded` — درخواست کد بیش از حد (`429`)

- **شرح سرور:** تعداد درخواستهای ارسال کد در پنجرهٔ زمانی بیش از حد است.
- **اقدام فرانتاند:** شمارشگر معکوس تا زمان ارسال مجدد نمایش بده.
- **نشانی `type`:** `.../ERRORS.md#error-otp_window_exceeded`

### <a id="error-invalid_mfa_code"></a>`invalid_mfa_code` — کد دومرحله‌ای نادرست (`422`)

- **شرح سرور:** کد TOTP یا کد بازیابی معتبر نیست.
- **اقدام فرانتاند:** کد را پاک کن؛ تعداد تلاشهای باقیمانده را نمایش بده.
- **نشانی `type`:** `.../ERRORS.md#error-invalid_mfa_code`

### <a id="error-mfa_locked"></a>`mfa_locked` — عامل دوم موقتاً قفل شد (`429`)

- **شرح سرور:** تلاشهای ناموفق متوالی باعث قفل موقت TOTP شده است.
- **اقدام فرانتاند:** زمان رفع قفل را نمایش بده و از کد بازیابی استفاده کن.
- **نشانی `type`:** `.../ERRORS.md#error-mfa_locked`

### <a id="error-mfa_not_enrolled"></a>`mfa_not_enrolled` — عامل دوم راهاندازی نشده (`409`)

- **شرح سرور:** کارمند هنوز دستگاه TOTP فعالی ندارد.
- **اقدام فرانتاند:** کاربر را به جریان setup/confirm هدایت کن.
- **نشانی `type`:** `.../ERRORS.md#error-mfa_not_enrolled`

### <a id="error-mfa_already_enrolled"></a>`mfa_already_enrolled` — عامل دوم پیشتر فعال شده (`409`)

- **شرح سرور:** دستگاه TOTP دیگری روی حساب فعال است.
- **اقدام فرانتاند:** به صفحهٔ وضعیت MFA هدایت کن.
- **نشانی `type`:** `.../ERRORS.md#error-mfa_already_enrolled`

### <a id="error-mfa_setup_missing"></a>`mfa_setup_missing` — نشست راهاندازی TOTP یافت نشد (`409`)

- **شرح سرور:** چالش setup منقضی یا مصرف شده است.
- **اقدام فرانتاند:** فرایند setup را از نو آغاز کن.
- **نشانی `type`:** `.../ERRORS.md#error-mfa_setup_missing`

### <a id="error-invalid_sheba"></a>`invalid_sheba` — شبا نامعتبر (`422`)

- **شرح سرور:** رقم کنترل شماره شبا با الگوریتم ISO 13616 ناسازگار است.
- **اقدام فرانتاند:** زیر فیلد شبا خطا بده؛ قالب IR و ۲۴ رقم پس از آن را یادآوری کن.
- **نشانی `type`:** `.../ERRORS.md#error-invalid_sheba`

### <a id="error-invalid_national_code"></a>`invalid_national_code` — کد ملی نامعتبر (`422`)

- **شرح سرور:** رقم کنترل کد ملی نادرست است.
- **اقدام فرانتاند:** خطای inline زیر فیلد کد ملی.
- **نشانی `type`:** `.../ERRORS.md#error-invalid_national_code`

### <a id="error-duplicate_national_code"></a>`duplicate_national_code` — کد ملی تکراری (`409`)

- **شرح سرور:** این کد ملی پیشتر ثبت شده است.
- **اقدام فرانتاند:** امکان بازیابی حساب را پیشنهاد بده.
- **نشانی `type`:** `.../ERRORS.md#error-duplicate_national_code`

### <a id="error-reason_required"></a>`reason_required` — ثبت دلیل الزامی است (`422`)

- **شرح سرور:** عملیات حساس بدون دلیل ممیزیشونده پذیرفته نمیشود.
- **اقدام فرانتاند:** فیلد دلیل را اجباری کن و حداقل طول را رعایت کن.
- **نشانی `type`:** `.../ERRORS.md#error-reason_required`

### <a id="error-unknown_policy_key"></a>`unknown_policy_key` — کلید سیاست ناشناخته (`404`)

- **شرح سرور:** کلید سیاست در رجیستری زمان اجرا تعریف نشده است.
- **اقدام فرانتاند:** فهرست سیاستها را از /api/v1/admin/policies واکشی کن.
- **نشانی `type`:** `.../ERRORS.md#error-unknown_policy_key`

### <a id="error-cannot_revoke_current_session"></a>`cannot_revoke_current_session` — ابطال نشست جاری ممکن نیست (`409`)

- **شرح سرور:** برای خروج از نشست فعلی باید از /auth/logout استفاده شود.
- **اقدام فرانتاند:** کاربر را به خروج عادی هدایت کن.
- **نشانی `type`:** `.../ERRORS.md#error-cannot_revoke_current_session`

### <a id="error-user_inactive"></a>`user_inactive` — حساب غیرفعال (`401`)

- **شرح سرور:** حساب کاربر توسط تیم عملیات غیرفعال شده است.
- **اقدام فرانتاند:** پیام پشتیبانی عمومی نمایش بده و توکنها را پاک کن.
- **نشانی `type`:** `.../ERRORS.md#error-user_inactive`

### <a id="error-sms_budget_exhausted"></a>`sms_budget_exhausted` — بودجهٔ پیامک به پایان رسید (`503`)

- **شرح سرور:** سقف ارسال پیامک یا اعتبار پنل تکمیل شده است.
- **اقدام فرانتاند:** پیام «موقتاً در دسترس نیست» و تلاش مجدد بعدی.
- **نشانی `type`:** `.../ERRORS.md#error-sms_budget_exhausted`

### <a id="error-domain_error"></a>`domain_error` — خطای دامنه (`400`)

- **شرح سرور:** قاعدهای از قواعد کسبوکار نقض شده است.
- **اقدام فرانتاند:** detail را به کاربر نمایش بده و وضعیت را دوباره واکشی کن.
- **نشانی `type`:** `.../ERRORS.md#error-domain_error`

### <a id="error-csrf_failed"></a>`csrf_failed` — اعتبار توکن CSRF از دست رفت (`403`)

- **شرح سرور:** توکن CSRF ارسالی با کوکی جاری هم‌خوان نیست (معمولاً پس از چرخش توکن در ورود).
- **اقدام فرانتاند:** با GET /auth/csrf توکن تازه بگیر و همان درخواست را یک‌بار تکرار کن؛ کلاینت این کار را خودکار انجام می‌دهد.
- **نشانی `type`:** `.../ERRORS.md#error-csrf_failed`

### <a id="error-session_rotated"></a>`session_rotated` — نشست هم‌زمان در دستگاه دیگری به‌روز شد (`409`)

- **شرح سرور:** نشست این دستگاه با چرخش توکن در جای دیگری هم‌خوان نیست.
- **اقدام فرانتاند:** صفحه را تازه‌سازی کن و در صورت ادامهٔ خطا، کاربر را به ورود مجدد هدایت کن.
- **نشانی `type`:** `.../ERRORS.md#error-session_rotated`

## قواعد سراسری مدیریت خطا

1. همیشه `trace_id` (معادل هدر `X-Request-ID`) را در پیام پشتیبانی نمایش دهید.
2. برای `429` و `503` تنها پس از `Retry-After` / `retry_after` و با backoff نمایی تلاش مجدد کنید.
3. `422` را با نگاشت `errors[field]` مستقیماً پایین همان فیلدها نشان دهید.
4. `403` با `code=mfa_required` یا `step_up_required` یعنی بازکردن مودال TOTP و سپس **بازارسال همان درخواست با همان `Idempotency-Key`**.
5. `401` یعنی یکبار `POST /api/v1/auth/token/refresh`؛ در صورت شکست، پاکسازی کامل توکنها و هدایت به جریان OTP (هرگز حلقهٔ بیپایان refresh نسازید).
