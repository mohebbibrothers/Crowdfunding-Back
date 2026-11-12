"""شمارشی‌های هستهٔ مشترک — وضعیت Outbox، هم‌توانی و انواع مقدار سیاست‌ها."""

from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _


class OutboxStatus(models.TextChoices):
    """وضعیت چرخهٔ حیات پیام‌های صندوق خروجی تراکنشی (Transactional Outbox)."""

    PENDING = "pending", _("در انتظار ارسال")
    PROCESSING = "processing", _("در حال پردازش")
    DELIVERED = "delivered", _("تحویل‌شده")
    FAILED = "failed", _("ناموفق (در صف تلاش مجدد)")
    DEAD = "dead", _("متوقف‌شده پس از سقف تلاش")


class IdempotencyOutcome(models.TextChoices):
    """نتیجهٔ بررسی کلید هم‌توانی پیش از اجرای عملیات نوشتنی."""

    RESERVED = "reserved", _("کلید رزرو شد — ادامهٔ اجرا")
    REPLAY = "replay", _("بازپخش پاسخ ذخیره‌شدهٔ قبلی")
    CONFLICT = "conflict", _("تعارض کلید با بدنه یا کنش‌گر متفاوت")
    IN_PROGRESS = "in_progress", _("درخواست هم‌زمان در حال پردازش")


class PolicyValueType(models.TextChoices):
    """نوع دادهٔ قوانین پویا در جدول Policy-as-Data."""

    BOOL = "bool", _("بولی (روشن/خاموش)")
    INT = "int", _("عدد صحیح")
    FLOAT = "float", _("عدد اعشاری (ضرایب رتبه‌بندی)")
    STRING = "string", _("رشته")
    JSON = "json", _("ساختار JSON")
