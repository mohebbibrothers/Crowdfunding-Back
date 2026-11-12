"""مسیرهای API گزارش‌گیری مدیریتی و خروجی اکسل."""

from __future__ import annotations

from django.urls import path

from apps.reporting.views import (
    AdminExcelExportDownloadView,
    AdminExportAuditHistoryView,
)

urlpatterns = [
    path(
        "admin/reports/excel",
        AdminExcelExportDownloadView.as_view(),
        name="v1-admin-reports-excel",
    ),
    path(
        "admin/reports/exports-history",
        AdminExportAuditHistoryView.as_view(),
        name="v1-admin-reports-exports-history",
    ),
]
