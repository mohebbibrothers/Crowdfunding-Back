"""شمارشی‌های کنش‌ها و نتایج حسابرسی زنجیره‌ای."""

from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _


class AuditAction(models.TextChoices):
    """فهرست کنش‌های حساس امنیتی، مدیریتی و مالی قابل ثبت در زنجیرهٔ حسابرسی."""

    OTP_REQUESTED = "auth.otp_requested", _("درخواست کد یک‌بارمصرف")
    LOGIN_SUCCESS = "auth.login_success", _("ورود موفق")
    LOGOUT = "auth.logout", _("خروج از نشست")
    SESSION_REVOKED = "auth.session_revoked", _("ابطال نشست")
    MFA_ENROLLED = "auth.mfa_enrolled", _("فعال‌سازی تأیید دومرحله‌ای")
    MFA_VERIFIED = "auth.mfa_verified", _("تأیید موفق عامل دوم")
    MFA_FAILED = "auth.mfa_failed", _("تلاش ناموفق عامل دوم")
    MFA_RECOVERY_REGENERATED = "auth.mfa_recovery_regenerated", _("بازتولید کدهای بازیابی")
    MFA_RESET = "auth.mfa_reset", _("بازنشانی اضطراری عامل دوم")
    ROLE_CHANGED = "identity.role_changed", _("تغییر نقش کاربری")
    PII_PHONE_REVEALED = "privacy.phone_revealed", _("مشاهدهٔ شماره تلفن کامل خیر")
    POLICY_CHANGED = "governance.policy_changed", _("تغییر سیاست سامانه")
    BENEFACTOR_SAVED = "benefactor.saved", _("ایجاد یا ویرایش خیریه/نهاد")
    CAMPAIGN_SAVED = "campaign.saved", _("ایجاد یا ویرایش حرکت")
    CAMPAIGN_PUBLISHED = "campaign.published", _("انتشار حرکت")
    CAMPAIGN_CLOSED = "campaign.closed", _("بستن حرکت")
    IMPACT_UPDATE_PUBLISHED = "campaign.impact_published", _("انتشار گزارش پیشرفت میدانی")
    MATCHING_GRANT_CREATED = "campaign.matching_created", _("ثبت تعهد حامی مضاعف‌کننده")
    EXTERNAL_FUNDING_RECORDED = "finance.external_recorded", _("ثبت کمک خارج از سایت")
    EXTERNAL_FUNDING_VOIDED = "finance.external_voided", _("ابطال کمک خارج از سایت")
    PAYMENT_VERIFIED = "finance.payment_verified", _("تأیید تراکنش درگاه پرداخت")
    REFUND_APPROVED = "finance.refund_approved", _("تأیید استرداد وجه")
    ADJUSTMENT_APPLIED = "finance.adjustment_applied", _("اعمال سند اصلاح مالی")
    DISBURSEMENT_REQUESTED = "finance.disbursement_requested", _("ثبت درخواست تسویه با خیریه")
    DISBURSEMENT_APPROVED = "finance.disbursement_approved", _("تأیید چهارچشمی تسویه با خیریه")
    DISBURSEMENT_REJECTED = "finance.disbursement_rejected", _("رد درخواست تسویه با خیریه")
    DISBURSEMENT_PAID = "finance.disbursement_paid", _("ثبت پرداخت نهایی به شبای خیریه")
    RECONCILIATION_IMPORTED = "finance.reconciliation_imported", _("ورود فایل مغایرت‌گیری درگاه")
    EXCEL_EXPORTED = "reporting.excel_exported", _("دریافت خروجی اکسل مدیریتی")


class AuditOutcome(models.TextChoices):
    """نتیجهٔ اجرای کنش ثبت‌شده در حسابرسی."""

    SUCCESS = "success", _("موفق")
    FAILURE = "failure", _("ناموفق")
