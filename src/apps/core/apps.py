"""پیکربندی اپلیکیشن هستهٔ مشترک و بارگذاری سیستم‌چک‌های استقرار."""

from __future__ import annotations

from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class CoreConfig(AppConfig):
    """تنظیمات اپ ``apps.core``."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.core"
    verbose_name = _("هستهٔ مشترک سامانه")

    def ready(self) -> None:
        """ثبت سیستم‌چک‌های امنیتی و لاگ ساخت‌یافته هنگام راه‌اندازی."""
        from apps.core import checks  # noqa: F401
        from apps.core.logging import configure_structlog

        configure_structlog()
