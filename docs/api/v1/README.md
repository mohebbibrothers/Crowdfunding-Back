# قرارداد رسمی API نسخهٔ ۱ (`/api/v1`) — ویژهٔ فرانتاند و موبایل

> **منبع حقیقت ماشینی:** [`openapi.yaml`](./openapi.yaml) — استاندارد **OpenAPI 3.1.0**،
> **۷۲ مسیر / ۸۳ عملیات / ۱۱۲ اسکیما**، اعتبارسنجیشده با صفر هشدار و قفلشده توسط CI.
> **راهنمای یکپارچهسازی (پیشنهادی برای شروع):** [`../../frontend/HANDOFF.md`](../../frontend/HANDOFF.md)
> **مستندات تعاملی:** Swagger UI در `/api/v1/docs` · ReDoc در `/api/v1/redoc` · Schema در `/api/v1/schema`

⚠️ جدولهای زیر **مستقیماً از `openapi.yaml` تولید شدهاند**؛ تستهای مخزن هرگونه مسیر غیرواقعی
در مستندات را رد میکنند. بنابراین آنچه میخوانید دقیقاً همان چیزی است که سرور اجرا میکند.

---

## ۱. قراردادهای سراسری پروتکل

| موضوع | قرارداد |
| --- | --- |
| واحد پول | ورودی **ریال صحیح** (`int` مضرب ۱۰)؛ خروجی همیشه جفت `*_rial` و `*_toman`. حرکتهای سهممحور فقط `shares_count` میگیرند. |
| تاریخ | ISO-8601 UTC + فیلد آمادهٔ `*_jalali`؛ منطقهٔ زمانی `Asia/Tehran`، تقویم شمسی. |
| شناسهها | `UUIDv7`؛ مسیرهای عمومی `slug` / `short_code` / `verification_code` / `public_token` میپذیرند. |
| بدنه | فقط `application/json`؛ پاسخ خطا **`application/problem+json`** (RFC 9457). |
| نسخه | `GET /api/v1/meta` → `supported_versions`، `app_version` (نسخهٔ استقراری بکاند) و `features` (پرچمهای ویژگی). |
| همتوانی | هدر `Idempotency-Key` (UUID) روی عملیات نوشتنی؛ پاسخ بازپخششده هدر `X-Idempotent-Replayed: true` دارد. بدنهٔ متفاوت با همان کلید ⇒ `409 idempotency_conflict`. |
| ردیابی | `X-Request-ID` (اختیاری، ۸–۶۴ کاراکتر امن)؛ همان مقدار در پاسخ و فیلد `trace_id` خطاها. |
| کش | `ETag` + `If-None-Match` → `304 Not Modified`؛ هدر `Cache-Control` روی دادههای شخصی/خطاها `private, no-store` است. |
| صفحهبندی | مکاننمایی `{results, meta}` با `cursor` و `page_size` در **پنج** نقطهٔ پایانی (در §۳ مشخص شدهاند). بقیه آرایهٔ مستقیماند. |
| نرخ | سقف پیشفرض `120/min` بهازای IP؛ OTP / MFA / checkout سقفهای سختگیرانهتر دارند. `429` همراه `Retry-After`. |

### ۱٫۱ احراز هویت دوگانه

| حالت | طرح امنیتی OpenAPI | نحوهٔ ارسال |
| --- | --- | --- |
| وب همدامنه / زیردامنه | `cookieAuth` (کوکی `cf_session`، `HttpOnly`) + `csrfToken` | `credentials: include` و هدر `X-CSRFToken` از `GET /api/v1/auth/csrf` |
| موبایل / SPA مستقل | `bearerAuth` (JWT) | `Authorization: Bearer <access_token>` |

- `access_token` ۱۵ دقیقه و `refresh_token` ۳۰ روز اعتبار دارند.
- `POST /auth/token/refresh` **چرخشی** است: توکن قبلی باطل میشود؛ استفادهٔ مجدد از refresh قدیمی
  تمام نشست را میبندد (Reuse Detection). حتماً الگوی Single-Flight را رعایت کنید.
- عملیات حساس ادمین نیازمند `mfa_required` / `step_up_required` (TOTP تازه در ۱۰ دقیقهٔ اخیر) هستند.
  کاتالوگ کامل کدها: [`../../frontend/ERRORS.md`](../../frontend/ERRORS.md)

### ۱٫۲ پاسخ خطای استاندارد (تمام وضعیتهای ۴xx/۵xx)

```json
{
  "type": "https://github.com/mohebbibrothers/Crowdfunding-Back/blob/main/docs/frontend/ERRORS.md#error-validation_error",
  "title": "خطای اعتبارسنجی ورودی",
  "status": 422,
  "detail": "لطفاً خطاهای مشخصشده در فیلدها را برطرف کنید.",
  "code": "validation_error",
  "instance": "/api/v1/contributions/checkout",
  "trace_id": "01936f...",
  "errors": { "shares_count": ["باید بزرگتر از صفر باشد."] }
}
```

تمام ۸۳ عملیات، پاسخهای استاندارد `400 / 401 / 403 / 404 / 405 / 409 / 410 / 422 / 429 / 500 / 503`
را بهصورت `#/components/responses/Problem*` اعلام کردهاند.

---

## ۲. نقشهٔ کامل نقاط پایانی (تولیدشده از قرارداد)

### سلامت، متادیتا و CSRF
<sub>`System` · 4 عملیات</sub>

| متد | مسیر | operationId | خلاصه |
| --- | --- | --- | --- |
| `GET` | `/api/v1/auth/csrf` | `v1_csrf_bootstrap` | دریافت و کاشت توکن CSRF برای نشست‌های کوکی‌محور |
| `GET` | `/api/v1/health/live` | `v1_health_live` | بررسی زنده بودن فرآیند برنامه (Liveness) |
| `GET` | `/api/v1/health/ready` | `v1_health_ready` | بررسی آمادگی دیتابیس و کش (Readiness) |
| `GET` | `/api/v1/meta` | `v1_meta_retrieve` | دریافت متادیتای نسخهٔ API و قابلیت‌های فعال سامانه |

### ورود، توکن و خروج
<sub>`Auth` · 6 عملیات</sub>

| متد | مسیر | operationId | خلاصه |
| --- | --- | --- | --- |
| `POST` | `/api/v1/auth/logout` | `v1_auth_logout` | خروج از نشست جاری |
| `POST` | `/api/v1/auth/logout-others` | `v1_auth_logout_others` | ابطال تمام نشست‌های دیگر به‌جز دستگاه فعلی |
| `POST` | `/api/v1/auth/otp/request` | `v1_auth_otp_request` | درخواست کد یک‌بارمصرف پیامکی (ورود / ثبت‌نام) |
| `POST` | `/api/v1/auth/otp/verify` | `v1_auth_otp_verify` | تأیید کد پیامکی و دریافت نشست (Cookie + JWT) |
| `POST` | `/api/v1/auth/staff/password-login` | `v1_auth_staff_password_login` | ورود کارکنان با شماره موبایل و گذرواژه |
| `POST` | `/api/v1/auth/token/refresh` | `v1_auth_token_refresh` | نوسازی چرخشی توکن JWT با تشخیص سرقت توکن |

### تأیید دومرحلهای کارکنان
<sub>`Auth - Staff MFA` · 4 عملیات</sub>

| متد | مسیر | operationId | خلاصه |
| --- | --- | --- | --- |
| `GET` | `/api/v1/auth/mfa/status` | `v1_auth_mfa_status` | مشاهدهٔ وضعیت تأیید دومرحله‌ای کارمند |
| `POST` | `/api/v1/auth/mfa/totp/confirm` | `v1_auth_mfa_totp_confirm` | تأیید نهایی دستگاه TOTP و دریافت کدهای بازیابی |
| `POST` | `/api/v1/auth/mfa/totp/setup` | `v1_auth_mfa_totp_setup` | شروع راه‌اندازی TOTP کارمند و دریافت QR SVG |
| `POST` | `/api/v1/auth/mfa/verify` | `v1_auth_mfa_verify` | تأیید کد دومرحله‌ای روی نشست فعال یا ارتقای Step-Up |

### پروفایل و نشستهای خیر
<sub>`Donor - Profile & Sessions` · 4 عملیات</sub>

| متد | مسیر | operationId | خلاصه |
| --- | --- | --- | --- |
| `GET` | `/api/v1/me` | `v1_me_profile_retrieve` | مشاهدهٔ اطلاعات حساب و پروفایل کاربر جاری |
| `PATCH` | `/api/v1/me` | `v1_me_profile_update` | تکمیل یا ویرایش پروفایل خیر (نام، استان، شهر، کد ملی رمزشده) |
| `GET` | `/api/v1/me/sessions` | `v1_me_sessions_list` | مشاهدهٔ فهرست دستگاه‌ها و نشست‌های فعال من |
| `POST` | `/api/v1/me/sessions/{session_id}/revoke` | `v1_me_sessions_revoke` | ابطال یک نشست مشخص از راه دور |

### اعلانهای خیر
<sub>`Donor - Notifications` · 3 عملیات</sub>

| متد | مسیر | operationId | خلاصه |
| --- | --- | --- | --- |
| `GET` | `/api/v1/me/notifications` | `v1_me_notifications_list` | مشاهدهٔ فهرست اعلان‌ها و مژده‌های حرکت‌های همراهی‌شده |
| `POST` | `/api/v1/me/notifications/read-all` | `v1_me_notifications_read_all` | علامت‌گذاری تمام اعلان‌های من به‌عنوان خوانده‌شده |
| `POST` | `/api/v1/me/notifications/{notification_id}/read` | `v1_me_notifications_read` | ثبت مطالعهٔ یک اعلان |

### آغاز مشارکت و رزرو سهم
<sub>`Donor - Contributions & Checkout` · 1 عملیات</sub>

| متد | مسیر | operationId | خلاصه |
| --- | --- | --- | --- |
| `POST` | `/api/v1/contributions/checkout` | `v1_contributions_checkout_create` | رزرو ۱۵ دقیقه‌ای سهم حرکت یا واریز به قلک و دریافت لینک درگاه پرداخت |

### داشبورد و تاریخچهٔ خیر
<sub>`Donor - Motivation Dashboard` · 2 عملیات</sub>

| متد | مسیر | operationId | خلاصه |
| --- | --- | --- | --- |
| `GET` | `/api/v1/me/contributions` | `v1_me_contributions_list` | تاریخچهٔ تمام مشارکت‌های من در حرکت‌ها و قلک‌ها |
| `GET` | `/api/v1/me/dashboard` | `v1_me_dashboard_retrieve` | داشبورد جامع و انگیزه‌بخش خیر (کارنامهٔ معنوی، مالی، سفیران و مژده‌های میدانی) |

### خیریهها و قلکهای عام
<sub>`Public - Benefactors & Jars` · 4 عملیات</sub>

| متد | مسیر | operationId | خلاصه |
| --- | --- | --- | --- |
| `GET` | `/api/v1/benefactors` | `v1_benefactors_list` | فهرست خیریه‌ها و نهادهای نیکوکاری فعال |
| `GET` | `/api/v1/benefactors/{slug}` | `v1_benefactors_retrieve` | دریافت جزئیات خیریه و قلک‌های عام آن |
| `GET` | `/api/v1/jars` | `v1_jars_list` | فهرست قلک‌های عام فعال خیریه‌ها |
| `GET` | `/api/v1/jars/{identifier}` | `v1_jars_retrieve` | جزئیات قلک عام خیریه از روی نامک یا کد پیوندک |

### حرکتهای خیرخواهانه
<sub>`Public - Campaigns` · 4 عملیات</sub>

| متد | مسیر | operationId | خلاصه |
| --- | --- | --- | --- |
| `GET` | `/api/v1/campaign-categories` | `v1_campaign_categories_list` | فهرست دسته‌بندی‌های موضوعی حرکت‌ها |
| `GET` | `/api/v1/campaigns` | `v1_campaigns_list` | فهرست حرکت‌های خیرخواهانه با رتبه‌بندی توزیع منصفانه |
| `GET` | `/api/v1/campaigns/{identifier}` | `v1_campaigns_retrieve` | مشاهدهٔ جزئیات حرکت خیرخواهانه، سهم‌های آزاد و گزارش‌های میدانی |
| `GET` | `/api/v1/campaigns/{identifier}/supporters` | `v1_campaigns_supporters_list` | فهرست همراهان حرکت خیرخواهانه (با حفظ گمنامی خیرین ناشناس) |

### مشارکت سریع مهمان
<sub>`Public - Express 30s Checkout` · 2 عملیات</sub>

| متد | مسیر | operationId | خلاصه |
| --- | --- | --- | --- |
| `POST` | `/api/v1/contributions/express/confirm` | `v1_contributions_express_confirm` | مشارکت سریع ۳۰ ثانیه‌ای مهمان — گام ۲ (تایید OTP، ورود خودکار و دریافت لینک درگاه) |
| `POST` | `/api/v1/contributions/express/start` | `v1_contributions_express_start` | مشارکت سریع ۳۰ ثانیه‌ای مهمان — گام ۱ (ثبت نیت خرید و ارسال OTP) |

### پرداخت، Sandbox و رسید
<sub>`Public - Payments & Receipts` · 4 عملیات</sub>

| متد | مسیر | operationId | خلاصه |
| --- | --- | --- | --- |
| `GET` | `/api/v1/payments/callback` | `v1_payments_callback_get` | بازگشت GET از درگاه پرداخت اینترنتی (Authority & Status) |
| `POST` | `/api/v1/payments/callback` | `v1_payments_verify_post` | تأیید تراکنش درگاه پرداخت از طریق فرانت‌اند (POST) |
| `GET` | `/api/v1/payments/sandbox/{authority}` | `v1_payments_sandbox_retrieve` | اطلاعات تراکنش درگاه تعاملی Sandbox |
| `GET` | `/api/v1/receipts/verify/{verification_code}` | `v1_receipts_verify_retrieve` | استعلام اصالت رسید رسمی مشارکت با کد رهگیری |

### شفافیت رمزنگاری مرکل
<sub>`Public - Cryptographic Transparency` · 3 عملیات</sub>

| متد | مسیر | operationId | خلاصه |
| --- | --- | --- | --- |
| `GET` | `/api/v1/campaigns/{identifier}/transparency` | `v1_campaigns_transparency_retrieve` | گزارش شفافیت مالی، تفکیک منابع آنلاین/آفلاین و ریشه درخت مرکل حرکت |
| `GET` | `/api/v1/me/contributions/{contribution_id}/merkle-proof` | `v1_me_contributions_merkle_proof_retrieve` | دریافت گواهی اثبات شمول مرکل (Merkle Inclusion Proof) برای مشارکت من |
| `POST` | `/api/v1/transparency/verify-proof` | `v1_transparency_verify_merkle_proof` | راستی‌آزمایی ریاضی اثبات شمول مرکل (Merkle Inclusion Proof) |

### گواهی نیتنامه
<sub>`Public - Dedication Certificates` · 1 عملیات</sub>

| متد | مسیر | operationId | خلاصه |
| --- | --- | --- | --- |
| `GET` | `/api/v1/dedications/{public_token}` | `v1_dedications_retrieve` | مشاهدهٔ گواهی نیت‌نامه و کارت هدیه معنوی با توکن عمومی |

### پیوندک و سفیران
<sub>`Public - Short-Links & Ambassadors` · 3 عملیات</sub>

| متد | مسیر | operationId | خلاصه |
| --- | --- | --- | --- |
| `GET` | `/api/v1/me/ambassador-links` | `v1_me_ambassador_links_list` | فهرست لینک‌های سفیر اجتماعی من و آمار اثرگذاری هرکدام |
| `POST` | `/api/v1/me/ambassador-links` | `v1_me_ambassador_links_create` | ساخت لینک اختصاصی سفیر اجتماعی برای دعوت به حرکت یا قلک |
| `GET` | `/api/v1/short-links/{short_code}` | `v1_short_links_resolve` | حل نشانی پیوندک کوتاه (حرکت، قلک عام یا لینک سفیر اجتماعی) |

### پایش عملیاتی
<sub>`Admin - System` · 1 عملیات</sub>

| متد | مسیر | operationId | خلاصه |
| --- | --- | --- | --- |
| `GET` | `/api/v1/health/detailed` | `v1_health_detailed` | بررسی عمیق سلامت دیتابیس، کش، Outbox و زنجیرهٔ حسابرسی |

### سیاستها و پرچمها
<sub>`Admin - Governance` · 2 عملیات</sub>

| متد | مسیر | operationId | خلاصه |
| --- | --- | --- | --- |
| `GET` | `/api/v1/admin/policies` | `v1_admin_policies_list` | مشاهدهٔ فهرست سیاست‌های زمان اجرا و وضعیت کلیدهای قابلیت‌ها |
| `POST` | `/api/v1/admin/policies/{policy_key}` | `v1_admin_policies_update` | تغییر نسخه‌دار یک سیاست سامانه با الزام دلیل و Step-Up MFA |

### زنجیرهٔ حسابرسی
<sub>`Admin - Audit` · 2 عملیات</sub>

| متد | مسیر | operationId | خلاصه |
| --- | --- | --- | --- |
| `GET` | `/api/v1/admin/audit/logs` | `v1_admin_audit_logs_list` | فهرست رکوردهای زنجیرهٔ حسابرسی با فیلتر کنش و هدف |
| `GET` | `/api/v1/admin/audit/verify` | `v1_admin_audit_verify` | بررسی سلامت زنجیرهٔ هش حسابرسی و لنگرهای امضاشده |

### کاربران و ریسک
<sub>`Admin - Identity` · 5 عملیات</sub>

| متد | مسیر | operationId | خلاصه |
| --- | --- | --- | --- |
| `GET` | `/api/v1/admin/auth/risk-signals` | `v1_admin_auth_risks_list` | فهرست سیگنال‌های ریسک امنیتی ورود و توکن‌ها |
| `POST` | `/api/v1/admin/auth/risk-signals/{signal_id}/review` | `v1_admin_auth_risks_review` | بررسی و تعیین وضعیت سیگنال ریسک احراز هویت |
| `GET` | `/api/v1/admin/users` | `v1_admin_users_list` | فهرست کاربران سامانه (با تلفن پوشانده در حالت عادی) |
| `POST` | `/api/v1/admin/users/{user_id}/reveal-phone` | `v1_admin_users_reveal_phone` | مشاهدهٔ شماره موبایل کامل خیر با ثبت هدف ممیزی و Step-Up MFA |
| `POST` | `/api/v1/admin/users/{user_id}/role` | `v1_admin_users_role_update` | تغییر نقش کاربر با الزام Step-Up MFA و ثبت دلیل |

### مدیریت خیریهها و قلکها
<sub>`Admin - Benefactors & Jars` · 8 عملیات</sub>

| متد | مسیر | operationId | خلاصه |
| --- | --- | --- | --- |
| `GET` | `/api/v1/admin/benefactors` | `v1_admin_benefactors_list` | فهرست مدیریتی تمام خیریه‌ها |
| `POST` | `/api/v1/admin/benefactors` | `v1_admin_benefactors_create` | ایجاد خیریه/نهاد نیکوکاری جدید |
| `DELETE` | `/api/v1/admin/benefactors/{benefactor_id}` | `v1_admin_benefactors_destroy` | حذف خیریهٔ بدون سابقه یا غیرفعال‌سازی ایمن آن |
| `GET` | `/api/v1/admin/benefactors/{benefactor_id}` | `v1_admin_benefactors_retrieve` | دریافت مشخصات کامل مدیریتی خیریه |
| `PATCH` | `/api/v1/admin/benefactors/{benefactor_id}` | `v1_admin_benefactors_partial_update` | ویرایش جزئی مشخصات خیریه |
| `GET` | `/api/v1/admin/jars` | `v1_admin_jars_list` | فهرست مدیریتی قلک‌های عام خیریه‌ها |
| `POST` | `/api/v1/admin/jars` | `v1_admin_jars_create` | ایجاد قلک عام جدید برای خیریه |
| `PATCH` | `/api/v1/admin/jars/{jar_id}` | `v1_admin_jars_partial_update` | ویرایش تنظیمات قلک عام خیریه |

### مدیریت حرکتها
<sub>`Admin - Campaigns` · 7 عملیات</sub>

| متد | مسیر | operationId | خلاصه |
| --- | --- | --- | --- |
| `POST` | `/api/v1/admin/campaign-categories` | `v1_admin_campaign_categories_create` | ایجاد دسته‌بندی موضوعی حرکت |
| `GET` | `/api/v1/admin/campaigns` | `v1_admin_campaigns_list` | فهرست مدیریتی همهٔ حرکت‌ها |
| `POST` | `/api/v1/admin/campaigns` | `v1_admin_campaigns_create` | تعریف حرکت خیرخواهانهٔ سهم‌محور جدید |
| `GET` | `/api/v1/admin/campaigns/{campaign_id}` | `v1_admin_campaigns_retrieve` | دریافت جزئیات مدیریتی یک حرکت |
| `PATCH` | `/api/v1/admin/campaigns/{campaign_id}` | `v1_admin_campaigns_partial_update` | ویرایش حرکت (محافظت از قیمت سهم و خیریه پس از اولین مشارکت) |
| `POST` | `/api/v1/admin/campaigns/{campaign_id}/impact-updates` | `v1_admin_campaigns_impact_updates_create` | انتشار گزارش پیشرفت میدانی حرکت برای سهام‌داران |
| `POST` | `/api/v1/admin/campaigns/{campaign_id}/matching-grants` | `v1_admin_campaigns_matching_grants_create` | ثبت تعهد حامی مضاعف‌کننده برای حرکت |

### دفترکل، تسویه و مغایرتگیری
<sub>`Admin - Ledger & Disbursements` · 8 عملیات</sub>

| متد | مسیر | operationId | خلاصه |
| --- | --- | --- | --- |
| `GET` | `/api/v1/admin/disbursements` | `v1_admin_disbursements_list` | فهرست درخواست‌های تسویه با خیریه‌ها |
| `POST` | `/api/v1/admin/disbursements` | `v1_admin_disbursements_create` | ثبت درخواست تسویه وجه با خیریه (گام Maker) |
| `POST` | `/api/v1/admin/disbursements/{disbursement_id}/review` | `v1_admin_disbursements_review` | تأیید یا رد چهارچشمی درخواست تسویه با خیریه (Checker + Step-Up MFA) |
| `GET` | `/api/v1/admin/ledger/accounts` | `v1_admin_ledger_accounts_list` | مشاهدهٔ تراز سرفصل‌های دفترکل حسابداری دوطرفه |
| `POST` | `/api/v1/admin/ledger/control-snapshot` | `v1_admin_ledger_control_snapshot_create` | محاسبه و ثبت اسنپ‌شات کنترل تراز دفترکل و انطباق شمارنده‌ها |
| `GET` | `/api/v1/admin/ledger/entries` | `v1_admin_ledger_entries_list` | فهرست اسناد روزنامهٔ حسابداری |
| `GET` | `/api/v1/admin/reconciliations` | `v1_admin_reconciliations_list` | فهرست دسته‌های مغایرت‌گیری درگاه پرداخت |
| `POST` | `/api/v1/admin/reconciliations` | `v1_admin_reconciliations_create` | اجرای مغایرت‌گیری فایل تسویه درگاه پرداخت با دفتر داخلی |

### پرداختها و استرداد
<sub>`Admin - Payments & Refunds` · 3 عملیات</sub>

| متد | مسیر | operationId | خلاصه |
| --- | --- | --- | --- |
| `POST` | `/api/v1/admin/campaigns/{campaign_id}/external-contributions` | `v1_admin_campaigns_external_contributions_create` | ثبت سهم‌های تامین‌شده خارج از درگاه آنلاین در حساب انتظامی مجزا |
| `GET` | `/api/v1/admin/payments` | `v1_admin_payments_list` | فهرست مدیریتی تراکنش‌های درگاه پرداخت |
| `POST` | `/api/v1/admin/payments/{payment_id}/refund` | `v1_admin_payments_refund` | ثبت استرداد وجه پرداخت و آزادسازی سهم‌ها (نیازمند Step-Up MFA) |

### گزارشهای اکسل
<sub>`Admin - Executive Excel Reports` · 2 عملیات</sub>

| متد | مسیر | operationId | خلاصه |
| --- | --- | --- | --- |
| `GET` | `/api/v1/admin/reports/excel` | `v1_admin_reports_excel_export` | دانلود گزارش اکسل ۸ کاربرگهٔ اجرایی، مالی و مغایرت‌گیری (مهرشده با SHA-256) |
| `GET` | `/api/v1/admin/reports/exports-history` | `v1_admin_reports_export_history_list` | فهرست ممیزی و هش SHA-256 گزارش‌های اکسل صادرشده |


---

## ۳. پنج نقطهٔ پایانی صفحهبندیشده (`{results, meta}`)

| مسیر | اسکیمای پاسخ | `meta.total` |
| --- | --- | --- |
| `GET /api/v1/me/contributions` | `PaginatedContributionUser` | ✅ دارد |
| `GET /api/v1/me/notifications` | `PaginatedUserNotification` | ✅ دارد |
| `GET /api/v1/admin/audit/logs` | `PaginatedAuditRecord` | ❌ |
| `GET /api/v1/admin/users` | `PaginatedAdminUser` | ❌ |
| `GET /api/v1/admin/auth/risk-signals` | `PaginatedAuthRiskSignal` | ❌ |

```ts
type CursorPage<T> = {
  results: T[];
  meta: { next: string | null; previous: string | null; page_size: number; total?: number };
};
```
`meta.next` را عیناً در درخواست بعدی بفرستید؛ ساخت دستی `cursor` ⇒ `404 invalid_cursor`.

---

## ۴. نمونههای بدنهٔ درخواست (در Swagger/Postman هم تزریق شدهاند)

| operationId | نمونه |
| --- | --- |
| `v1_auth_otp_request` | `{"phone":"09121112233"}` |
| `v1_auth_otp_verify` | `{"phone":"09121112233","code":"48321"}` |
| `v1_contributions_checkout_create` | `{"target_kind":"campaign_shares","campaign_id":"<uuid>","shares_count":3,"gateway_name":"sandbox"}` |
| `v1_contributions_express_start` | `{"phone":"09121112233","target_kind":"campaign_shares","campaign_id":"<uuid>","shares_count":1}` |
| `v1_transparency_verify_merkle_proof` | `{"leaf_hash":"<sha256>","merkle_root":"<sha256>","proof":[...]}` |
| `v1_me_ambassador_links_create` | `{"campaign_id":"<uuid>"}` |
| `v1_admin_payments_refund` | `{"reason":"درخواست رسمی خیر","amount_rial":1500000}` |

---

## ۵. منابع تکمیلی

| نیاز | مسیر |
| --- | --- |
| راهنمای گامبهگام فرانتاند | [`docs/frontend/HANDOFF.md`](../../frontend/HANDOFF.md) |
| پورتال بصری آفلاین | [`docs/frontend/index.html`](../../frontend/index.html) |
| تایپهای TypeScript | [`docs/frontend/api-types.d.ts`](../../frontend/api-types.d.ts) |
| کلاینت HTTP آماده | [`docs/frontend/api-client.ts`](../../frontend/api-client.ts) |
| کالکشن Postman | [`docs/frontend/postman_collection.json`](../../frontend/postman_collection.json) |
| کاتالوگ خطاها | [`docs/frontend/ERRORS.md`](../../frontend/ERRORS.md) |
| ماتریس تخت نقاط پایانی | [`docs/frontend/ENDPOINTS.md`](../../frontend/ENDPOINTS.md) |
| معماری و ADR | [`docs/architecture.md`](../../architecture.md) · [`docs/adr/`](../../adr/) |
| امنیت ASVS | [`docs/security-asvs.md`](../../security-asvs.md) |
| استقرار و عملیات | [`docs/runbook.md`](../../runbook.md) · [`deploy/cpanel/README.md`](../../../deploy/cpanel/README.md) |
