"""پیکربندی اپلیکیشن حرکت‌های خیرخواهانه."""

from __future__ import annotations

from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class CampaignsConfig(AppConfig):
    """تنظیمات اپ ``apps.campaigns``."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.campaigns"
    verbose_name = _("حرکت‌های خیرخواهانهٔ سهم‌محور")
