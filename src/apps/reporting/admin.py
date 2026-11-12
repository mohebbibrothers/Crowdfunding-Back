"""ثبت لاگ خروجی اکسل در پنل ادمین جنگو."""

from __future__ import annotations

from django.contrib import admin

from apps.reporting.models import ReportExportLog


@admin.register(ReportExportLog)
class ReportExportLogAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = (
        "id",
        "exported_by",
        "include_raw_phones",
        "file_sha256",
        "byte_size",
        "created_at",
    )
    readonly_fields = [f.name for f in ReportExportLog._meta.fields]
