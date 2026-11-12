"""مدل‌های صندوق اعلان کاربر و لاگ حاکمیت ارسال پیامک (با شماره تلفن پوشانده)."""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import BaseModel
from apps.notifications.choices import SmsDeliveryStatus, SmsPatternCode, UserNotificationKind


class UserNotification(BaseModel):
    """اعلان درون‌برنامه‌ای برای نمایش مژده‌های پیشرفت حرکت‌ها، رسیدها و اثر سفیر به خیر."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
        verbose_name=_("کاربر"),
    )
    kind = models.CharField(
        max_length=32,
        choices=UserNotificationKind.choices,
        db_index=True,
        verbose_name=_("نوع اعلان"),
    )
    title = models.CharField(max_length=200, verbose_name=_("عنوان"))
    body = models.TextField(verbose_name=_("متن پیام"))
    action_url = models.CharField(
        max_length=300, blank=True, default="", verbose_name=_("پیوند مقصد")
    )
    metadata = models.JSONField(default=dict, blank=True, verbose_name=_("فراداده"))
    read_at = models.DateTimeField(
        null=True, blank=True, db_index=True, verbose_name=_("زمان مطالعه")
    )

    class Meta:
        verbose_name = _("اعلان کاربر")
        verbose_name_plural = _("اعلان‌های کاربران")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "read_at", "-created_at"], name="notif_user_unread_idx"),
        ]

    def __str__(self) -> str:
        """نمایش عنوان و نوع اعلان."""
        return f"{self.kind}: {self.title}"


class SmsDeliveryLog(BaseModel):
    """دفتر ممیزی ارسال پیامک‌های الگومحور با شماره موبایل پوشانده‌شده (بدون ذخیرهٔ کد OTP خام)."""

    phone_masked = models.CharField(max_length=24, db_index=True, verbose_name=_("شماره پوشانده"))
    pattern_code = models.CharField(
        max_length=32, choices=SmsPatternCode.choices, db_index=True, verbose_name=_("کد الگو")
    )
    provider_name = models.CharField(max_length=40, verbose_name=_("ارائه‌دهنده"))
    status = models.CharField(
        max_length=20, choices=SmsDeliveryStatus.choices, db_index=True, verbose_name=_("وضعیت")
    )
    provider_message_id = models.CharField(
        max_length=100, blank=True, default="", verbose_name=_("شناسهٔ پیام اپراتور")
    )
    sanitized_tokens = models.JSONField(
        default=dict, blank=True, verbose_name=_("متغیرهای غیرحساس الگو")
    )
    error_message = models.CharField(
        max_length=400, blank=True, default="", verbose_name=_("خطای احتمالی")
    )

    class Meta:
        verbose_name = _("لاگ ارسال پیامک")
        verbose_name_plural = _("لاگ‌های ارسال پیامک")
        ordering = ["-created_at"]

    def __str__(self) -> str:
        """نمایش الگو، شماره پوشانده و وضعیت."""
        return f"{self.pattern_code} -> {self.phone_masked} [{self.status}]"
