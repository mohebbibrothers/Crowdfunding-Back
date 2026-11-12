"""پیکربندی اپلیکیشن اعلان‌ها و ثبت مشترکین صندوق خروجی (Outbox Subscribers)."""

from __future__ import annotations

from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class NotificationsConfig(AppConfig):
    """تنظیمات اپ ``apps.notifications``."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.notifications"
    verbose_name = _("اعلان‌ها و حاکمیت ارسال پیامک")

    def ready(self) -> None:
        """ثبت پردازشگرهای Outbox هنگام راه‌اندازی برنامه."""
        from apps.notifications.services import register_notification_outbox_handlers

        register_notification_outbox_handlers()
