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


class SettlementSourceKind(models.TextChoices):
    """منبع ورود صورت‌حساب تسویهٔ درگاه."""

    CSV = "csv", _("فایل CSV Export درگاه")
    XLSX = "xlsx", _("کارپوشهٔ اکسل صورتحساب")
    API = "api", _("دریافت مستقیم از API درگاه")
    MANUAL = "manual", _("ورود دستی ردیف‌ها توسط اپراتور")


class SettlementStatementStatus(models.TextChoices):
    """چرخهٔ پردازش یک سند صورت‌حساب تسویه."""

    INGESTED = "ingested", _("ورود یافته؛ تطبیق انجام نشده")
    MATCHED = "matched", _("تطبیق انجام شد و در انتظار اقدام")
    CLOSED = "closed", _("همهٔ مغایرت‌ها حل و پرونده بسته شد")


class SettlementRowMatchStatus(models.TextChoices):
    """نتیجهٔ تطبیق یک ردیف صورت‌حساب با دفتر داخلی.

    تفاوت کلیدی با ``ReconciliationItemStatus`` قدیمی: این شمارش، حالت
    ``DUPLICATE_IN_FILE`` و ``INTERNAL_NOT_VERIFIED`` را هم تفکیک می‌کند، چون
    این دو، دو *سناریوی اقدام متفاوت* هستند نه یک «مغایرت» کلی.
    """

    PENDING = "pending", _("در انتظار تطبیق")
    MATCHED = "matched", _("منطبق با پرداخت تأییدشدهٔ داخلی")
    DUPLICATE_IN_FILE = "duplicate_in_file", _("Authority تکراری در خود فایل (فایل معیوب)")
    MISSING_INTERNAL = "missing_internal", _("در صورتحساب هست، پرداخت داخلی ندارد (پول بی‌مالک)")
    AMOUNT_MISMATCH = "amount_mismatch", _("مبلغ صورتحساب با مبلغ داخلی برابر نیست")
    INTERNAL_NOT_VERIFIED = (
        "internal_not_verified",
        _("درگاه پول را گرفته ولی پرداخت داخلی تأیید نشده است"),
    )
    MISSING_GATEWAY = "missing_gateway", _("پرداخت تأییدشدهٔ داخلی در صورتحساب درگاه غایب است")


class SettlementRemediation(models.TextChoices):
    """اقدام انجام‌شده (یا تجویزشده) برای یک ردیف مغایرت."""

    NONE = "none", _("اقدامی لازم نبود")
    AUTO_HEALED = "auto_healed", _("با موتور داوری خودکار درمان شد")
    QUEUED_REVIEW = "queued_review", _("در صف بررسی انسانی قرار گرفت")
    MANUAL_RESOLVED = "manual_resolved", _("توسط اپراتور دستی حل شد")
    BLOCKED = "blocked", _("به‌دلیل نقض صحت سند، اقدام خودکار مسدود شد")


class PaymentTruthState(models.TextChoices):
    """وضعیت «حقیقت» یک پرداخت از منظر یک منبع مستقل (صورتحساب بانک/درگاه).

    این شمارش قلب لایهٔ حقیقت وجه است و عمداً از ``PaymentStatus`` جدا است:

      • ``PaymentStatus`` می‌گوید **ما چه فکر می‌کنیم**.
      • ``PaymentTruthState`` می‌گوید **صورتحساب مستقل چه می‌گوید**.

    تا وقتی این دو در یک ستون قاطی شوند، «تأییدشده» یعنی «خودمان گفتیم».
    """

    UNVERIFIED = "unverified", _("هیچ منبع مستقلی دربارهٔ آن اظهارنظر نکرده است")
    SELF_REPORTED = "self_reported", _("فقط استعلام خودگواه درگاه را داریم")
    STATEMENT_CONFIRMED = "statement_confirmed", _("صورتحساب مستقل آن را تأیید کرده است")
    STATEMENT_MISSING = "statement_missing", _("در سامانه تأیید شده ولی در صورتحساب نیست")
    CONFLICT = "conflict", _("دفتر ما و صورتحساب در تناقض‌اند")


class PledgeFrequency(models.TextChoices):
    """تناوب تعهد کمک مستمر (Recurring Pledge)."""

    MONTHLY = "monthly", _("ماهانه")
    QUARTERLY = "quarterly", _("سه‌ماهه")


class PledgeStatus(models.TextChoices):
    """چرخهٔ حیات یک تعهد کمک مستمر.

    ``EXPIRED`` عمداً از ``CANCELLED`` جدا است: لغو تصمیم خودِ خیر است،
    انقضا نتیجهٔ سه شکست متوالی است. یکی باید در آمار ریزش دیده شود، دیگری
    نباید — و قاطی‌کردنشان آمار را دروغ می‌کند.
    """

    ACTIVE = "active", _("فعال — قسط بعدی ساخته می‌شود")
    PAUSED = "paused", _("موقتاً متوقف به خواست خیر")
    EXPIRED = "expired", _("منقضی پس از شکست‌های متوالی پرداخت")
    CANCELLED = "cancelled", _("لغو‌شده به خواست خیر")
    COMPLETED = "completed", _("به پایان رسیده (تعداد قسط تکمیل شد)")


class InstallmentStatus(models.TextChoices):
    """وضعیت یک قسط در چرخهٔ تعهد."""

    SCHEDULED = "scheduled", _("زمان‌بندی‌شده و در انتظار سررسید")
    REMINDED = "reminded", _("سررسید شد و یادآوری ارسال شده")
    PAID = "paid", _("پرداخت‌شده")
    FAILED = "failed", _("سررسید و مهلت گذشت بدون پرداخت")
    SKIPPED = "skipped", _("از سوی خیر رد شد (این ماه پرداخت نمی‌کند)")
    EXPIRED = "expired", _("منقضی بدون پرداخت پس از پایان تعهد")
    VOIDED = "voided", _("باطل‌شده (تعهد لغو یا مبلغ اصلاح شد)")


class PledgeCancelReason(models.TextChoices):
    """دلیل لغو تعهد — برای تحلیل ریزش، نه برای نمایش به خیر."""

    USER_REQUEST = "user_request", _("درخواست خود خیر")
    TOO_EXPENSIVE = "too_expensive", _("مبلغ برای خیر سنگین بود")
    NOT_NEEDED = "not_needed", _("دیگر تمایلی به ادامه ندارد")
    CHARITY_REQUEST = "charity_request", _("درخواست خیریه")
    ADMIN_ACTION = "admin_action", _("اقدام مدیریتی")
    OTHER = "other", _("سایر")
