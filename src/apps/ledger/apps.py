"""پیکربندی اپلیکیشن دفترکل مالی."""

from __future__ import annotations

from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class LedgerConfig(AppConfig):
    """تنظیمات اپ ``apps.ledger``."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.ledger"
    verbose_name = _("دفترکل دوطرفه، تسویه و مغایرت‌گیری")
