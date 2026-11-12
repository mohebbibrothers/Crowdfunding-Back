"""شمارشی‌های وضعیت چرخهٔ حیات حرکت، سطح فوریت، رسانه و مراحل اجرای میدانی."""

from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _


class CampaignStatus(models.TextChoices):
    """وضعیت چرخهٔ حیات یک حرکت سهم‌محور."""

    DRAFT = "draft", _("پیش‌نویس")
    ACTIVE = "active", _("در حال جذب مشارکت")
    PAUSED = "paused", _("متوقف موقت")
    COMPLETED = "completed", _("تکمیل ظرفیت سهم‌ها")
    EXECUTING = "executing", _("در حال اجرای میدانی")
    FULFILLED = "fulfilled", _("اجرا و گزارش نهایی شد")
    CANCELLED = "cancelled", _("لغوشده")


class CampaignUrgency(models.TextChoices):
    """سطح فوریت حرکت (مؤثر در الگوریتم رتبه‌بندی منصفانه)."""

    NORMAL = "normal", _("عادی")
    URGENT = "urgent", _("فوری")
    EMERGENCY = "emergency", _("اضطراری / حیاتی")


class CampaignMediaKind(models.TextChoices):
    """نوع فایل پیوست گالری حرکت."""

    IMAGE = "image", _("تصویر")
    VIDEO = "video", _("ویدیو")
    DOCUMENT = "document", _("مستند تاییدیه")


class ImpactMilestoneType(models.TextChoices):
    """نوع گام گزارش پیشرفت میدانی حرکت."""

    FUNDING_COMPLETE = "funding_complete", _("تکمیل جذب منابع")
    DISBURSED = "disbursed", _("واریز وجه به خیریه مجری")
    PROCUREMENT = "procurement", _("تهیه اقلام / شروع عملیات")
    FIELD_DELIVERY = "field_delivery", _("تحویل و اجرای میدانی")
    FINAL_REPORT = "final_report", _("گزارش پایانی و مستندات تکمیل")
