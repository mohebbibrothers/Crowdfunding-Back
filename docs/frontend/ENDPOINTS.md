# ماتریس کامل نقاط پایانی API نسخهٔ ۱ (تولیدشدهٔ خودکار)

> این جدول مستقیماً از [`openapi.yaml`](../api/v1/openapi.yaml) ساخته شده است. هرگونه تغییر مسیر، متد یا پارامتر بدون بازتولید این فایل توسط CI رد میشود.

- تعداد مسیرها: **89**
- تعداد عملیاتها: **104**
- تعداد اسکیماها: **140**
- تعداد تگها: **26**
- سرورها: `https://api.charity.example.org`, `http://localhost:8000`

| متد | مسیر | operationId | احراز هویت | خلاصه |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/admin/audit/logs` | `v1_admin_audit_logs_list` | الزامی | فهرست رکوردهای زنجیرهٔ حسابرسی با فیلتر کنش و هدف |
| `GET` | `/api/v1/admin/audit/verify` | `v1_admin_audit_verify` | الزامی | بررسی سلامت زنجیرهٔ هش حسابرسی و لنگرهای امضاشده |
| `GET` | `/api/v1/admin/benefactors` | `v1_admin_benefactors_list` | الزامی | فهرست مدیریتی تمام خیریه‌ها |
| `POST` | `/api/v1/admin/benefactors` | `v1_admin_benefactors_create` | الزامی | ایجاد خیریه/نهاد نیکوکاری جدید |
| `DELETE` | `/api/v1/admin/benefactors/{benefactor_id}` | `v1_admin_benefactors_destroy` | الزامی | حذف خیریهٔ بدون سابقه یا غیرفعال‌سازی ایمن آن |
| `GET` | `/api/v1/admin/benefactors/{benefactor_id}` | `v1_admin_benefactors_retrieve` | الزامی | دریافت مشخصات کامل مدیریتی خیریه |
| `PATCH` | `/api/v1/admin/benefactors/{benefactor_id}` | `v1_admin_benefactors_partial_update` | الزامی | ویرایش جزئی مشخصات خیریه |
| `GET` | `/api/v1/admin/jars` | `v1_admin_jars_list` | الزامی | فهرست مدیریتی قلک‌های عام خیریه‌ها |
| `POST` | `/api/v1/admin/jars` | `v1_admin_jars_create` | الزامی | ایجاد قلک عام جدید برای خیریه |
| `PATCH` | `/api/v1/admin/jars/{jar_id}` | `v1_admin_jars_partial_update` | الزامی | ویرایش تنظیمات قلک عام خیریه |
| `POST` | `/api/v1/admin/campaign-categories` | `v1_admin_campaign_categories_create` | الزامی | ایجاد دسته‌بندی موضوعی حرکت |
| `GET` | `/api/v1/admin/campaigns` | `v1_admin_campaigns_list` | الزامی | فهرست مدیریتی همهٔ حرکت‌ها |
| `POST` | `/api/v1/admin/campaigns` | `v1_admin_campaigns_create` | الزامی | تعریف حرکت خیرخواهانهٔ سهم‌محور جدید |
| `GET` | `/api/v1/admin/campaigns/{campaign_id}` | `v1_admin_campaigns_retrieve` | الزامی | دریافت جزئیات مدیریتی یک حرکت |
| `PATCH` | `/api/v1/admin/campaigns/{campaign_id}` | `v1_admin_campaigns_partial_update` | الزامی | ویرایش حرکت (محافظت از قیمت سهم و خیریه پس از اولین مشارکت) |
| `POST` | `/api/v1/admin/campaigns/{campaign_id}/impact-updates` | `v1_admin_campaigns_impact_updates_create` | الزامی | انتشار گزارش پیشرفت میدانی حرکت برای سهام‌داران |
| `POST` | `/api/v1/admin/campaigns/{campaign_id}/matching-grants` | `v1_admin_campaigns_matching_grants_create` | الزامی | ثبت تعهد حامی مضاعف‌کننده برای حرکت |
| `GET` | `/api/v1/admin/reports/excel` | `v1_admin_reports_excel_export` | الزامی | دانلود گزارش اکسل ۸ کاربرگهٔ اجرایی، مالی و مغایرت‌گیری (مهرشده با SHA-256) |
| `GET` | `/api/v1/admin/reports/exports-history` | `v1_admin_reports_export_history_list` | الزامی | فهرست ممیزی و هش SHA-256 گزارش‌های اکسل صادرشده |
| `GET` | `/api/v1/admin/policies` | `v1_admin_policies_list` | الزامی | مشاهدهٔ فهرست سیاست‌های زمان اجرا و وضعیت کلیدهای قابلیت‌ها |
| `POST` | `/api/v1/admin/policies/{policy_key}` | `v1_admin_policies_update` | الزامی | تغییر نسخه‌دار یک سیاست سامانه با الزام دلیل و Step-Up MFA |
| `GET` | `/api/v1/admin/auth/risk-signals` | `v1_admin_auth_risks_list` | الزامی | فهرست سیگنال‌های ریسک امنیتی ورود و توکن‌ها |
| `POST` | `/api/v1/admin/auth/risk-signals/{signal_id}/review` | `v1_admin_auth_risks_review` | الزامی | بررسی و تعیین وضعیت سیگنال ریسک احراز هویت |
| `GET` | `/api/v1/admin/users` | `v1_admin_users_list` | الزامی | فهرست کاربران سامانه (با تلفن پوشانده در حالت عادی) |
| `POST` | `/api/v1/admin/users/{user_id}/reveal-phone` | `v1_admin_users_reveal_phone` | الزامی | مشاهدهٔ شماره موبایل کامل خیر با ثبت هدف ممیزی و Step-Up MFA |
| `POST` | `/api/v1/admin/users/{user_id}/role` | `v1_admin_users_role_update` | الزامی | تغییر نقش کاربر با الزام Step-Up MFA و ثبت دلیل |
| `GET` | `/api/v1/admin/disbursements` | `v1_admin_disbursements_list` | الزامی | فهرست درخواست‌های تسویه با خیریه‌ها |
| `POST` | `/api/v1/admin/disbursements` | `v1_admin_disbursements_create` | الزامی | ثبت درخواست تسویه وجه با خیریه (گام Maker) |
| `POST` | `/api/v1/admin/disbursements/{disbursement_id}/review` | `v1_admin_disbursements_review` | الزامی | تأیید یا رد چهارچشمی درخواست تسویه با خیریه (Checker + Step-Up MFA) |
| `GET` | `/api/v1/admin/ledger/accounts` | `v1_admin_ledger_accounts_list` | الزامی | مشاهدهٔ تراز سرفصل‌های دفترکل حسابداری دوطرفه |
| `POST` | `/api/v1/admin/ledger/control-snapshot` | `v1_admin_ledger_control_snapshot_create` | الزامی | محاسبه و ثبت اسنپ‌شات کنترل تراز دفترکل و انطباق شمارنده‌ها |
| `GET` | `/api/v1/admin/ledger/entries` | `v1_admin_ledger_entries_list` | الزامی | فهرست اسناد روزنامهٔ حسابداری |
| `GET` | `/api/v1/admin/reconciliations` | `v1_admin_reconciliations_list` | الزامی | فهرست دسته‌های مغایرت‌گیری درگاه پرداخت |
| `POST` | `/api/v1/admin/reconciliations` | `v1_admin_reconciliations_create` | الزامی | اجرای مغایرت‌گیری فایل تسویه درگاه پرداخت با دفتر داخلی |
| `GET` | `/api/v1/admin/money-truth` | `v1_admin_money_truth_retrieve` | الزامی | پنل حقیقت وجه: فاصلهٔ «چیزی که می‌گوییم» و «چیزی که بانک می‌گوید» |
| `GET` | `/api/v1/admin/settlements` | `v1_admin_settlements_list` | الزامی | فهرست صورت‌حساب‌های تسویهٔ درگاه |
| `POST` | `/api/v1/admin/settlements` | `v1_admin_settlements_create` | الزامی | ورود یک صورت‌حساب تسویهٔ درگاه |
| `GET` | `/api/v1/admin/settlements/{settlement_id}` | `v1_admin_settlements_retrieve` | الزامی | دریافت یک صورت‌حساب تسویه با خلاصهٔ تطبیق |
| `POST` | `/api/v1/admin/settlements/{settlement_id}/reconcile` | `v1_admin_settlements_reconcile` | الزامی | تطبیق صورت‌حساب تسویه با پرداخت‌های داخلی |
| `POST` | `/api/v1/admin/settlements/{settlement_id}/remediate` | `v1_admin_settlements_remediate` | الزامی | اجرای اقدام خودکار مجاز روی مغایرت‌های صورت‌حساب |
| `GET` | `/api/v1/admin/settlements/{settlement_id}/rows` | `v1_admin_settlements_rows_list` | الزامی | فهرست ردیف‌های صورت‌حساب با نتیجهٔ تطبیق |
| `POST` | `/api/v1/admin/campaigns/{campaign_id}/external-contributions` | `v1_admin_campaigns_external_contributions_create` | الزامی | ثبت سهم‌های تامین‌شده خارج از درگاه آنلاین در حساب انتظامی مجزا |
| `GET` | `/api/v1/admin/payments` | `v1_admin_payments_list` | الزامی | فهرست مدیریتی تراکنش‌های درگاه پرداخت |
| `POST` | `/api/v1/admin/payments/{payment_id}/refund` | `v1_admin_payments_refund` | الزامی | ثبت استرداد وجه پرداخت و آزادسازی سهم‌ها (نیازمند Step-Up MFA) |
| `GET` | `/api/v1/admin/pledges` | `v1_admin_pledges_list` | الزامی | فهرست تعهدهای کمک مستمر (مدیریت) |
| `POST` | `/api/v1/admin/pledges/run-cycle` | `v1_admin_pledges_run_cycle` | الزامی | اجرای دستی چرخهٔ تعهد مستمر (تولید قسط، یادآوری، انقضا) |
| `GET` | `/api/v1/admin/pledges/stats` | `v1_admin_pledges_stats` | الزامی | آمار تجمیعی تعهدهای مستمر (MRR، نرخ وصول، ریزش) |
| `GET` | `/api/v1/admin/financial-health` | `v1_admin_financial_health_retrieve` | الزامی | گزارش سلامت حلقهٔ وجه: پرداخت‌های رهاشده، تعهدهای بازپرداخت و هشدارها |
| `POST` | `/api/v1/admin/late-captures/reconcile` | `v1_admin_late_captures_reconcile` | الزامی | اجرای دستی داوری پرداخت‌های رهاشده با استعلام مستقیم از درگاه |
| `POST` | `/api/v1/admin/refunds/dispatch` | `v1_admin_refunds_dispatch` | الزامی | ارسال تعهدهای بازپرداخت معلق به درگاه پرداخت |
| `GET` | `/api/v1/health/detailed` | `v1_health_detailed` | الزامی | بررسی عمیق سلامت دیتابیس، کش، Outbox و زنجیرهٔ حسابرسی |
| `POST` | `/api/v1/auth/logout` | `v1_auth_logout` | الزامی | خروج از نشست جاری |
| `POST` | `/api/v1/auth/logout-others` | `v1_auth_logout_others` | الزامی | ابطال تمام نشست‌های دیگر به‌جز دستگاه فعلی |
| `POST` | `/api/v1/auth/otp/request` | `v1_auth_otp_request` | اختیاری | درخواست کد یک‌بارمصرف پیامکی (ورود / ثبت‌نام) |
| `POST` | `/api/v1/auth/otp/verify` | `v1_auth_otp_verify` | اختیاری | تأیید کد پیامکی و دریافت نشست (Cookie + JWT) |
| `POST` | `/api/v1/auth/staff/password-login` | `v1_auth_staff_password_login` | اختیاری | ورود کارکنان با شماره موبایل و گذرواژه |
| `POST` | `/api/v1/auth/token/refresh` | `v1_auth_token_refresh` | اختیاری | نوسازی چرخشی توکن JWT با تشخیص سرقت توکن |
| `GET` | `/api/v1/auth/mfa/status` | `v1_auth_mfa_status` | الزامی | مشاهدهٔ وضعیت تأیید دومرحله‌ای کارمند |
| `POST` | `/api/v1/auth/mfa/totp/confirm` | `v1_auth_mfa_totp_confirm` | الزامی | تأیید نهایی دستگاه TOTP و دریافت کدهای بازیابی |
| `POST` | `/api/v1/auth/mfa/totp/setup` | `v1_auth_mfa_totp_setup` | الزامی | شروع راه‌اندازی TOTP کارمند و دریافت QR SVG |
| `POST` | `/api/v1/auth/mfa/verify` | `v1_auth_mfa_verify` | الزامی | تأیید کد دومرحله‌ای روی نشست فعال یا ارتقای Step-Up |
| `POST` | `/api/v1/contributions/checkout` | `v1_contributions_checkout_create` | الزامی | رزرو ۱۵ دقیقه‌ای سهم حرکت یا واریز به قلک و دریافت لینک درگاه پرداخت |
| `GET` | `/api/v1/me/contributions` | `v1_me_contributions_list` | الزامی | تاریخچهٔ تمام مشارکت‌های من در حرکت‌ها و قلک‌ها |
| `GET` | `/api/v1/me/dashboard` | `v1_me_dashboard_retrieve` | الزامی | داشبورد جامع و انگیزه‌بخش خیر (کارنامهٔ معنوی، مالی، سفیران و مژده‌های میدانی) |
| `GET` | `/api/v1/me/notifications` | `v1_me_notifications_list` | الزامی | مشاهدهٔ فهرست اعلان‌ها و مژده‌های حرکت‌های همراهی‌شده |
| `POST` | `/api/v1/me/notifications/read-all` | `v1_me_notifications_read_all` | الزامی | علامت‌گذاری تمام اعلان‌های من به‌عنوان خوانده‌شده |
| `POST` | `/api/v1/me/notifications/{notification_id}/read` | `v1_me_notifications_read` | الزامی | ثبت مطالعهٔ یک اعلان |
| `GET` | `/api/v1/me` | `v1_me_profile_retrieve` | الزامی | مشاهدهٔ اطلاعات حساب و پروفایل کاربر جاری |
| `PATCH` | `/api/v1/me` | `v1_me_profile_update` | الزامی | تکمیل یا ویرایش پروفایل خیر (نام، استان، شهر، کد ملی رمزشده) |
| `GET` | `/api/v1/me/sessions` | `v1_me_sessions_list` | الزامی | مشاهدهٔ فهرست دستگاه‌ها و نشست‌های فعال من |
| `POST` | `/api/v1/me/sessions/{session_id}/revoke` | `v1_me_sessions_revoke` | الزامی | ابطال یک نشست مشخص از راه دور |
| `GET` | `/api/v1/me/pledges` | `v1_me_pledges_list` | الزامی | فهرست تعهدهای کمک مستمر من |
| `POST` | `/api/v1/me/pledges` | `v1_me_pledges_create` | الزامی | ساخت تعهد کمک مستمر (ماهانه یا سه‌ماهه) |
| `DELETE` | `/api/v1/me/pledges/{pledge_id}` | `v1_me_pledges_destroy` | الزامی | لغو دائمی تعهد کمک مستمر |
| `GET` | `/api/v1/me/pledges/{pledge_id}` | `v1_me_pledges_retrieve` | الزامی | جزئیات یک تعهد کمک مستمر |
| `PATCH` | `/api/v1/me/pledges/{pledge_id}` | `v1_me_pledges_update` | الزامی | ویرایش تعهد (مبلغ، تناوب، روز شروع) یا توقف موقت |
| `GET` | `/api/v1/me/pledges/{pledge_id}/installments` | `v1_me_pledges_installments_list` | الزامی | فهرست اقساط یک تعهد کمک مستمر |
| `POST` | `/api/v1/me/pledges/{pledge_id}/installments/{installment_id}/skip` | `v1_me_pledges_skip_installment` | الزامی | رد قسط جاری (تعهد باقی می‌ماند) |
| `POST` | `/api/v1/me/pledges/{pledge_id}/pay` | `v1_me_pledges_pay` | الزامی | پرداخت قسط تعهد مستمر (هدایت به درگاه) |
| `GET` | `/api/v1/benefactors` | `v1_benefactors_list` | عمومی | فهرست خیریه‌ها و نهادهای نیکوکاری فعال |
| `GET` | `/api/v1/benefactors/{slug}` | `v1_benefactors_retrieve` | عمومی | دریافت جزئیات خیریه و قلک‌های عام آن |
| `GET` | `/api/v1/jars` | `v1_jars_list` | عمومی | فهرست قلک‌های عام فعال خیریه‌ها |
| `GET` | `/api/v1/jars/{identifier}` | `v1_jars_retrieve` | عمومی | جزئیات قلک عام خیریه از روی نامک یا کد پیوندک |
| `GET` | `/api/v1/campaign-categories` | `v1_campaign_categories_list` | عمومی | فهرست دسته‌بندی‌های موضوعی حرکت‌ها |
| `GET` | `/api/v1/campaigns` | `v1_campaigns_list` | عمومی | فهرست حرکت‌های خیرخواهانه با رتبه‌بندی توزیع منصفانه |
| `GET` | `/api/v1/campaigns/{identifier}` | `v1_campaigns_retrieve` | عمومی | مشاهدهٔ جزئیات حرکت خیرخواهانه، سهم‌های آزاد و گزارش‌های میدانی |
| `GET` | `/api/v1/campaigns/{identifier}/supporters` | `v1_campaigns_supporters_list` | عمومی | فهرست همراهان حرکت خیرخواهانه (با حفظ گمنامی خیرین ناشناس) |
| `GET` | `/api/v1/campaigns/{identifier}/transparency` | `v1_campaigns_transparency_retrieve` | عمومی | گزارش شفافیت مالی، تفکیک منابع آنلاین/آفلاین و ریشه درخت مرکل حرکت |
| `GET` | `/api/v1/me/contributions/{contribution_id}/merkle-proof` | `v1_me_contributions_merkle_proof_retrieve` | الزامی | دریافت گواهی اثبات شمول مرکل (Merkle Inclusion Proof) برای مشارکت من |
| `POST` | `/api/v1/transparency/verify-proof` | `v1_transparency_verify_merkle_proof` | عمومی | راستی‌آزمایی ریاضی اثبات شمول مرکل (Merkle Inclusion Proof) |
| `GET` | `/api/v1/dedications/{public_token}` | `v1_dedications_retrieve` | عمومی | مشاهدهٔ گواهی نیت‌نامه و کارت هدیه معنوی با توکن عمومی |
| `POST` | `/api/v1/contributions/express/confirm` | `v1_contributions_express_confirm` | عمومی | مشارکت سریع ۳۰ ثانیه‌ای مهمان — گام ۲ (تایید OTP، ورود خودکار و دریافت لینک درگاه) |
| `POST` | `/api/v1/contributions/express/start` | `v1_contributions_express_start` | عمومی | مشارکت سریع ۳۰ ثانیه‌ای مهمان — گام ۱ (ثبت نیت خرید و ارسال OTP) |
| `GET` | `/api/v1/payments/callback` | `v1_payments_callback_get` | عمومی | بازگشت GET از درگاه پرداخت اینترنتی (Authority & Status) |
| `POST` | `/api/v1/payments/callback` | `v1_payments_verify_post` | عمومی | تأیید تراکنش درگاه پرداخت از طریق فرانت‌اند (POST) |
| `GET` | `/api/v1/payments/sandbox/{authority}` | `v1_payments_sandbox_retrieve` | عمومی | اطلاعات تراکنش درگاه تعاملی Sandbox |
| `GET` | `/api/v1/receipts/verify/{verification_code}` | `v1_receipts_verify_retrieve` | عمومی | استعلام اصالت رسید رسمی مشارکت با کد رهگیری |
| `GET` | `/api/v1/me/ambassador-links` | `v1_me_ambassador_links_list` | الزامی | فهرست لینک‌های سفیر اجتماعی من و آمار اثرگذاری هرکدام |
| `POST` | `/api/v1/me/ambassador-links` | `v1_me_ambassador_links_create` | الزامی | ساخت لینک اختصاصی سفیر اجتماعی برای دعوت به حرکت یا قلک |
| `GET` | `/api/v1/short-links/{short_code}` | `v1_short_links_resolve` | عمومی | حل نشانی پیوندک کوتاه (حرکت، قلک عام یا لینک سفیر اجتماعی) |
| `GET` | `/api/v1/auth/csrf` | `v1_csrf_bootstrap` | اختیاری | دریافت و کاشت توکن CSRF برای نشست‌های کوکی‌محور |
| `GET` | `/api/v1/health/live` | `v1_health_live` | اختیاری | بررسی زنده بودن فرآیند برنامه (Liveness) |
| `GET` | `/api/v1/health/ready` | `v1_health_ready` | اختیاری | بررسی آمادگی دیتابیس و کش (Readiness) |
| `GET` | `/api/v1/meta` | `v1_meta_retrieve` | اختیاری | دریافت متادیتای نسخهٔ API و قابلیت‌های فعال سامانه |

## پارامترهای پرکاربرد

| مسیر | پارامتر | محل | الزامی |
| --- | --- | --- | --- |
| `/api/v1/admin/audit/logs` | `action` | query | خیر |
| `/api/v1/admin/audit/logs` | `cursor` | query | خیر |
| `/api/v1/admin/audit/logs` | `page_size` | query | خیر |
| `/api/v1/admin/audit/logs` | `target_id` | query | خیر |
| `/api/v1/admin/audit/logs` | `target_type` | query | خیر |
| `/api/v1/admin/benefactors` | `active_only` | query | خیر |
| `/api/v1/admin/benefactors/{benefactor_id}` | `benefactor_id` | path | بله |
| `/api/v1/admin/benefactors/{benefactor_id}` | `reason` | query | خیر |
| `/api/v1/admin/benefactors/{benefactor_id}` | `benefactor_id` | path | بله |
| `/api/v1/admin/benefactors/{benefactor_id}` | `benefactor_id` | path | بله |
| `/api/v1/admin/jars/{jar_id}` | `jar_id` | path | بله |
| `/api/v1/admin/campaigns` | `benefactor_id` | query | خیر |
| `/api/v1/admin/campaigns` | `status` | query | خیر |
| `/api/v1/admin/campaigns/{campaign_id}` | `campaign_id` | path | بله |
| `/api/v1/admin/campaigns/{campaign_id}` | `campaign_id` | path | بله |
| `/api/v1/admin/campaigns/{campaign_id}/impact-updates` | `campaign_id` | path | بله |
| `/api/v1/admin/campaigns/{campaign_id}/matching-grants` | `campaign_id` | path | بله |
| `/api/v1/admin/reports/excel` | `benefactor_id` | query | خیر |
| `/api/v1/admin/reports/excel` | `campaign_id` | query | خیر |
| `/api/v1/admin/reports/excel` | `date_from` | query | خیر |
| `/api/v1/admin/reports/excel` | `date_to` | query | خیر |
| `/api/v1/admin/reports/excel` | `include_raw_phones` | query | خیر |
| `/api/v1/admin/reports/excel` | `reason` | query | خیر |
| `/api/v1/admin/policies/{policy_key}` | `policy_key` | path | بله |
| `/api/v1/admin/auth/risk-signals` | `cursor` | query | خیر |
| `/api/v1/admin/auth/risk-signals` | `page_size` | query | خیر |
| `/api/v1/admin/auth/risk-signals` | `status` | query | خیر |
| `/api/v1/admin/auth/risk-signals/{signal_id}/review` | `signal_id` | path | بله |
| `/api/v1/admin/users` | `cursor` | query | خیر |
| `/api/v1/admin/users` | `page_size` | query | خیر |
| `/api/v1/admin/users` | `q` | query | خیر |
| `/api/v1/admin/users` | `role` | query | خیر |
| `/api/v1/admin/users/{user_id}/reveal-phone` | `user_id` | path | بله |
| `/api/v1/admin/users/{user_id}/role` | `user_id` | path | بله |
| `/api/v1/admin/disbursements` | `status` | query | خیر |
| `/api/v1/admin/disbursements/{disbursement_id}/review` | `disbursement_id` | path | بله |
| `/api/v1/admin/ledger/entries` | `kind` | query | خیر |
| `/api/v1/admin/settlements` | `cursor` | query | خیر |
| `/api/v1/admin/settlements` | `gateway_name` | query | خیر |
| `/api/v1/admin/settlements` | `page_size` | query | خیر |
| `/api/v1/admin/settlements` | `status` | query | خیر |
| `/api/v1/admin/settlements/{settlement_id}` | `settlement_id` | path | بله |
| `/api/v1/admin/settlements/{settlement_id}/reconcile` | `settlement_id` | path | بله |
| `/api/v1/admin/settlements/{settlement_id}/remediate` | `settlement_id` | path | بله |
| `/api/v1/admin/settlements/{settlement_id}/rows` | `cursor` | query | خیر |
| `/api/v1/admin/settlements/{settlement_id}/rows` | `match_status` | query | خیر |
| `/api/v1/admin/settlements/{settlement_id}/rows` | `page_size` | query | خیر |
| `/api/v1/admin/settlements/{settlement_id}/rows` | `settlement_id` | path | بله |
| `/api/v1/admin/campaigns/{campaign_id}/external-contributions` | `campaign_id` | path | بله |
| `/api/v1/admin/payments` | `status` | query | خیر |
| `/api/v1/admin/payments/{payment_id}/refund` | `payment_id` | path | بله |
| `/api/v1/admin/pledges` | `frequency` | query | خیر |
| `/api/v1/admin/pledges` | `status` | query | خیر |
| `/api/v1/admin/pledges/stats` | `window_days` | query | خیر |
| `/api/v1/me/contributions` | `cursor` | query | خیر |
| `/api/v1/me/contributions` | `page_size` | query | خیر |
| `/api/v1/me/notifications` | `cursor` | query | خیر |
| `/api/v1/me/notifications` | `page_size` | query | خیر |
| `/api/v1/me/notifications` | `unread` | query | خیر |
| `/api/v1/me/notifications/{notification_id}/read` | `notification_id` | path | بله |
| `/api/v1/me/sessions/{session_id}/revoke` | `session_id` | path | بله |
| `/api/v1/me/pledges` | `status` | query | خیر |
| `/api/v1/me/pledges/{pledge_id}` | `pledge_id` | path | بله |
| `/api/v1/me/pledges/{pledge_id}` | `pledge_id` | path | بله |
| `/api/v1/me/pledges/{pledge_id}` | `pledge_id` | path | بله |
| `/api/v1/me/pledges/{pledge_id}/installments` | `pledge_id` | path | بله |
| `/api/v1/me/pledges/{pledge_id}/installments/{installment_id}/skip` | `installment_id` | path | بله |
| `/api/v1/me/pledges/{pledge_id}/installments/{installment_id}/skip` | `pledge_id` | path | بله |
| `/api/v1/me/pledges/{pledge_id}/pay` | `pledge_id` | path | بله |
| `/api/v1/benefactors` | `province` | query | خیر |
| `/api/v1/benefactors` | `q` | query | خیر |
| `/api/v1/benefactors/{slug}` | `slug` | path | بله |
| `/api/v1/jars` | `benefactor` | query | خیر |
| `/api/v1/jars/{identifier}` | `identifier` | path | بله |
| `/api/v1/campaigns` | `benefactor` | query | خیر |
| `/api/v1/campaigns` | `category` | query | خیر |
| `/api/v1/campaigns` | `has_matching` | query | خیر |
| `/api/v1/campaigns` | `order` | query | خیر |
| `/api/v1/campaigns` | `province` | query | خیر |
| `/api/v1/campaigns` | `q` | query | خیر |
| `/api/v1/campaigns` | `status` | query | خیر |
| `/api/v1/campaigns` | `urgency` | query | خیر |
| `/api/v1/campaigns/{identifier}` | `identifier` | path | بله |
| `/api/v1/campaigns/{identifier}/supporters` | `identifier` | path | بله |
| `/api/v1/campaigns/{identifier}/transparency` | `identifier` | path | بله |
| `/api/v1/me/contributions/{contribution_id}/merkle-proof` | `contribution_id` | path | بله |
| `/api/v1/dedications/{public_token}` | `public_token` | path | بله |
| `/api/v1/payments/callback` | `Authority` | query | بله |
| `/api/v1/payments/callback` | `Status` | query | خیر |
| `/api/v1/payments/sandbox/{authority}` | `authority` | path | بله |
| `/api/v1/receipts/verify/{verification_code}` | `verification_code` | path | بله |
| `/api/v1/short-links/{short_code}` | `short_code` | path | بله |

---

بازتولید: `python scripts/build_frontend_kit.py` یا `make handoff`.
