"""شمارشی‌های نوع مشارکت، وضعیت رزرو/پرداخت، درگاه‌ها، نیت‌نامه و سیگنال‌های ریسک پرداخت."""

from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _


class ContributionTargetKind(models.TextChoices):
    """مقصد مشارکت خیر (سهم‌های یک حرکت مشخص یا واریز آزاد به قلک عام خیریه)."""

    CAMPAIGN_SHARES = "campaign_shares", _("خرید سهم از حرکت خیرخواهانه")
    CHARITY_JAR = "charity_jar", _("واریز آزاد به قلک عام خیریه")


class ContributionStatus(models.TextChoices):
    """وضعیت چرخهٔ حیات یک مشارکت."""

    RESERVED = "reserved", _("رزرو موقت ۱۵ دقیقه‌ای در انتظار پرداخت")
    PAID = "paid", _("پرداخت موفق و قطعی‌شده")
    EXPIRED = "expired", _("منقضی‌شده (آزادسازی سهم رزروشده)")
    FAILED = "failed", _("لغو یا خطا در درگاه پرداخت")
    REFUNDED = "refunded", _("مستردشده")


class GatewayName(models.TextChoices):
    """درگاه‌های پرداخت پشتیبانی‌شده."""

    SANDBOX = "sandbox", _("درگاه تعاملی آزمایشی (Sandbox)")
    ZARINPAL = "zarinpal", _("درگاه پرداخت زرین‌پال")


class PaymentStatus(models.TextChoices):
    """وضعیت تراکنش درگاه پرداخت."""

    INITIATED = "initiated", _("هدایت‌شده به درگاه")
    VERIFIED = "verified", _("تأیید نهایی شاپرک/درگاه")
    FAILED = "failed", _("ناموفق یا انصراف کاربر")
    REFUNDED = "refunded", _("مستردشده")


class DedicationType(models.TextChoices):
    """نوع نیت‌نامه و کارت هدیهٔ معنوی (بدون نمایش مبلغ ریالی روی گواهی عمومی)."""

    IN_MEMORY = "in_memory", _("ثواب به یاد درگذشتگان و اموات")
    GIFT_HONOR = "gift_honor", _("هدیهٔ معنوی به عزیزان (تولد، سالگرد، قدردانی)")
    HEALING_PRAYER = "healing_prayer", _("به نیت سلامتی و شفای بیماران")
    GENERAL_NIYYAT = "general_niyyat", _("نیت قلبی و شکرگزاری")


class PaymentRiskKind(models.TextChoices):
    """نوع سیگنال ریسک در فرآیند رزرو سهم و پرداخت."""

    HOLD_HOARDING_BLOCKED = "hold_hoarding_blocked", _("تلاش برای قفل‌کردن بیش از سقف مجاز سهم‌ها")
    CALLBACK_TAMPER_ATTEMPT = (
        "callback_tamper_attempt",
        _("تلاش بازپخش یا دستکاری پارامتر بازگشت درگاه"),
    )
