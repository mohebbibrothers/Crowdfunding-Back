"""شمارشی‌های نوع مشارکت، وضعیت رزرو/پرداخت، درگاه‌ها، نیت‌نامه و سیگنال‌های ریسک پرداخت."""

from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _


class ContributionTargetKind(models.TextChoices):
    """مقصد مشارکت خیر (سهم‌های یک حرکت مشخص یا واریز آزاد به قلک عام خیریه)."""

    CAMPAIGN_SHARES = "campaign_shares", _("خرید سهم از حرکت خیرخواهانه")
    CHARITY_JAR = "charity_jar", _("واریز آزاد به قلک عام خیریه")


class ContributionStatus(models.TextChoices):
    """وضعیت چرخهٔ حیات یک مشارکت.

    گذارهای مجاز در ``apps.contributions.state_machine`` تعریف و با گیت آزمون
    اجبار شده‌اند؛ هر وضعیت تازه باید همان‌جا ورودی خروجی بگیرد.
    """

    RESERVED = "reserved", _("رزرو موقت ۱۵ دقیقه‌ای در انتظار پرداخت")
    PAID = "paid", _("پرداخت موفق و قطعی‌شده")
    EXPIRED = "expired", _("منقضی‌شده (آزادسازی سهم رزروشده)")
    FAILED = "failed", _("لغو یا خطا در درگاه پرداخت")
    REFUNDED = "refunded", _("مستردشده")
    # ── چرخهٔ بازیافت وجه پس از انقضای رزرو (Capture Recovery) ──────────────
    CAPTURED_LATE = (
        "captured_late",
        _("وجه پس از انقضای رزرو در درگاه گرفته شد و سهم دوباره تخصیص یافت"),
    )
    AWAITING_REFUND = (
        "awaiting_refund",
        _("وجه گرفته شد اما سهم دیگر در دسترس نیست؛ در انتظار بازپرداخت"),
    )


class GatewayName(models.TextChoices):
    """درگاه‌های پرداخت پشتیبانی‌شده."""

    SANDBOX = "sandbox", _("درگاه تعاملی آزمایشی (Sandbox)")
    ZARINPAL = "zarinpal", _("درگاه پرداخت زرین‌پال")


class PaymentStatus(models.TextChoices):
    """وضعیت تراکنش درگاه پرداخت.

    تفکیک حیاتی: ``FAILED`` یعنی «درگاه تأییداً رد کرد»؛ ``ABANDONED`` یعنی
    «ما از بازگشت کاربر ناامید شدیم ولی از وضعیت پول خبر نداریم». این دو
    نباید هرگز یکی شوند، چون اولی پول نیست و دومی ممکن است پول باشد.
    """

    INITIATED = "initiated", _("هدایت‌شده به درگاه")
    VERIFIED = "verified", _("تأیید نهایی شاپرک/درگاه")
    FAILED = "failed", _("ناموفق یا انصراف تأییدشدهٔ کاربر در درگاه")
    ABANDONED = "abandoned", _("رها‌شده: رزرو منقضی شد و وضعیت پول نامعلوم است")
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


class LateCaptureOutcome(models.TextChoices):
    """نتیجهٔ داوری خودکار روی پرداختی که با وضعیت نامعلوم رها شده بود."""

    NOT_CAPTURED = "not_captured", _("درگاه تأیید نکرد؛ وجهی دریافت نشده است")
    RECOVERED = "recovered", _("وجه دریافت شده بود و سهم همان لحظه تخصیص یافت")
    REFUND_PENDING = "refund_pending", _("وجه دریافت شده ولی سهم در دسترس نبود؛ بازپرداخت لازم است")
    MANUAL_REVIEW = "manual_review", _("نتیجه مبهم؛ برای داوری انسانی علامت‌گذاری شد")


class RefundOutcome(models.TextChoices):
    """وضعیت اجرای بازپرداخت در درگاه (مسیر خودکار یا دستی)."""

    PENDING = "pending", _("در انتظار ارسال به درگاه")
    SENT = "sent", _("به درگاه ارسال شد")
    COMPLETED = "completed", _("بازپرداخت تکمیل و تأیید شد")
    FAILED = "failed", _("ارسال یا تأیید بازپرداخت ناموفق بود")
    MANUAL = "manual", _("نیازمند بازپرداخت دستی خارج از سامانه (مرجع بانکی ثبت شد)")
    NOT_REQUIRED = "not_required", _("بازپرداخت لازم نبود (وجهی دریافت نشده بود)")
