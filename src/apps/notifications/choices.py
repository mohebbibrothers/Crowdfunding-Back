"""شمارشی‌های قالب‌های الگوی پیامک، وضعیت تحویل و دسته‌بندی اعلان‌های کاربر."""

from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _


class SmsPatternCode(models.TextChoices):
    """کدهای منطقی الگوهای پیامک (بدون ارسال متن آزاد برای پیشگیری از تزریق پیامک)."""

    OTP_LOGIN = "otp_login", _("کد یک‌بارمصرف ورود/ثبت‌نام")
    OTP_EXPRESS = "otp_express", _("کد یک‌بارمصرف مشارکت سریع")
    RECEIPT_ISSUED = "receipt_issued", _("صدور رسید مشارکت موفق")
    DEDICATION_GIFT = "dedication_gift", _("کارت هدیهٔ معنوی و نیت‌نامه")
    IMPACT_PUBLISHED = "impact_published", _("انتشار گزارش پیشرفت میدانی حرکت")


class SmsDeliveryStatus(models.TextChoices):
    """وضعیت تحویل پیامک در لاگ حاکمیت ارسال."""

    MOCKED = "mocked", _("ثبت‌شده در حالت آزمایشی (غیرفعال در تولید)")
    SENT = "sent", _("ارسال‌شده به اپراتور پیامک")
    FAILED = "failed", _("خطا در ارسال به اپراتور")


class UserNotificationKind(models.TextChoices):
    """نوع اعلان درون‌برنامه‌ای در صندوق پیام خیر."""

    RECEIPT_READY = "receipt_ready", _("صدور رسید مشارکت")
    CAMPAIGN_COMPLETED = "campaign_completed", _("تکمیل ۱۰۰٪ سهم‌های حرکت")
    IMPACT_UPDATE = "impact_update", _("گزارش تصویری اجرای حرکت")
    AMBASSADOR_IMPACT = "ambassador_impact", _("مشارکت جدید از طریق لینک سفیر شما")
    DEDICATION_ISSUED = "dedication_issued", _("صدور گواهی نیت‌نامه")
    REFUND_INITIATED = "refund_initiated", _("آغاز فرآیند بازپرداخت وجه")
    REFUND_COMPLETED = "refund_completed", _("تکمیل بازپرداخت وجه")
