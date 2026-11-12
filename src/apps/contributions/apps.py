"""پیکربندی اپلیکیشن مشارکت‌ها و ثبت مشترکین صندوق خروجی."""

from __future__ import annotations

from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class ContributionsConfig(AppConfig):
    """تنظیمات اپ ``apps.contributions``."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.contributions"
    verbose_name = _("مشارکت‌ها، درگاه پرداخت، شفافیت مرکل و داشبورد خیر")

    def ready(self) -> None:
        """ثبت پردازشگرهای Outbox مرتبط با سهام‌داران حرکت‌ها."""
        from apps.contributions.services import register_contribution_outbox_handlers

        register_contribution_outbox_handlers()
