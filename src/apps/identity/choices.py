"""شمارشی‌های نقش‌های کاربری، هدف کد یک‌بارمصرف و سیگنال‌های ریسک هویتی."""

from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _


class UserRole(models.TextChoices):
    """نقش‌های چهارسطحی سامانه بر پایهٔ اصل کمترین اختیار."""

    DONOR = "donor", _("نیکوکار (کاربر عادی)")
    OPERATOR = "operator", _("کارشناس عملیات")
    FINANCE_MANAGER = "finance_manager", _("مدیر مالی و ممیزی")
    SUPER_ADMIN = "super_admin", _("مدیر ارشد سامانه")


class OtpPurpose(models.TextChoices):
    """هدف صدور کد یک‌بارمصرف پیامکی."""

    LOGIN = "login", _("ورود یا ثبت‌نام")
    EXPRESS_CHECKOUT = "express_checkout", _("مشارکت سریع ۳۰ ثانیه‌ای")


class AuthRiskType(models.TextChoices):
    """نوع ناهنجاری یا ریسک تشخیص‌داده‌شده در احراز هویت."""

    OTP_BRUTE_FORCE = "otp_brute_force", _("تلاش مکرر ناموفق کد یک‌بارمصرف")
    REFRESH_TOKEN_REUSE = "refresh_token_reuse", _("تلاش برای استفادهٔ مجدد از توکن چرخشی")
    MFA_LOCKOUT = "mfa_lockout", _("قفل شدن عامل دوم کارمند")
    HIGH_IP_VELOCITY = "high_ip_velocity", _("درخواست غیرعادی کد از یک آدرس IP")


class RiskReviewStatus(models.TextChoices):
    """وضعیت بررسی سیگنال ریسک توسط تیم امنیت/مدیریت."""

    OPEN = "open", _("باز")
    REVIEWED = "reviewed", _("بررسی‌شده")
    DISMISSED = "dismissed", _("بی‌خطر تشخیص داده‌شده")
