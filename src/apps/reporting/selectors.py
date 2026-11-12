"""سلکتورهای خوانشی تاریخچهٔ خروجی‌های اکسل."""

from __future__ import annotations

from django.db.models import QuerySet

from apps.reporting.models import ReportExportLog


def list_report_export_logs() -> QuerySet[ReportExportLog]:
    """فهرست ۱۰۰ خروجی اکسل اخیر به ترتیب زمان تولید."""
    return ReportExportLog.objects.order_by("-created_at")
