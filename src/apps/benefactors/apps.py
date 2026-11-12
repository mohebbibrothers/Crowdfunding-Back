"""پیکربندی اپلیکیشن خیریه‌ها و قلک‌های عام."""

from __future__ import annotations

from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class BenefactorsConfig(AppConfig):
    """تنظیمات اپ ``apps.benefactors``."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.benefactors"
    verbose_name = _("خیریه‌ها و قلک‌های عام")
