"""پیکربندی اپلیکیشن گزارش‌گیری مدیریتی."""

from __future__ import annotations

from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class ReportingConfig(AppConfig):
    """تنظیمات اپ ``apps.reporting``."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.reporting"
    verbose_name = _("گزارش‌گیری اجرایی و خروجی اکسل")
