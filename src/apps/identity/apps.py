"""پیکربندی اپلیکیشن هویت و دسترسی."""

from __future__ import annotations

from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class IdentityConfig(AppConfig):
    """تنظیمات اپ ``apps.identity``."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.identity"
    verbose_name = _("هویت، نشست‌ها و دسترسی")
