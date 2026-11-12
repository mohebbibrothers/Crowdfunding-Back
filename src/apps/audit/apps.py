"""پیکربندی اپلیکیشن حسابرسی زنجیره‌ای."""

from __future__ import annotations

from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class AuditConfig(AppConfig):
    """تنظیمات اپ ``apps.audit``."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.audit"
    verbose_name = _("حسابرسی و عدم‌انکار")
