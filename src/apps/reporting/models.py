"""مدل ممیزی خروجی‌های اکسل مدیریتی (ثبت هش SHA-256 فایل و سطح دسترسی داده‌های هویتی)."""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import BaseModel


class ReportExportLog(BaseModel):
    """لاگ تغییرناپذیر هر بار تولید گزارش اکسل مدیریتی به همراه هش SHA-256 محتوای باینری."""

    exported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="excel_exports",
        verbose_name=_("کاربر صادرکننده"),
    )
    filters = models.JSONField(default=dict, blank=True, verbose_name=_("فیلترهای گزارش"))
    include_raw_phones = models.BooleanField(
        default=False, verbose_name=_("شامل شماره‌های کامل بدون پوشش")
    )
    reason = models.CharField(
        max_length=400, blank=True, default="", verbose_name=_("علت در صورت افشای PII")
    )
    file_sha256 = models.CharField(
        max_length=64, db_index=True, verbose_name=_("هش SHA-256 فایل اکسل")
    )
    byte_size = models.PositiveIntegerField(verbose_name=_("حجم فایل به بایت"))
    row_counts = models.JSONField(
        default=dict, blank=True, verbose_name=_("تعداد ردیف‌های هر کاربرگ")
    )

    class Meta:
        verbose_name = _("لاگ خروجی اکسل مدیریتی")
        verbose_name_plural = _("لاگ‌های خروجی اکسل مدیریتی")
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"ExcelExport {self.id} [{self.file_sha256[:12]}]"
