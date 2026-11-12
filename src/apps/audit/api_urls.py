"""مسیرهای API ماژول حسابرسی زیر ``/api/v1/admin/audit/``."""

from __future__ import annotations

from django.urls import path

from apps.audit.views import AdminAuditRecordListView, AdminAuditVerifyView

urlpatterns = [
    path("admin/audit/logs", AdminAuditRecordListView.as_view(), name="v1-admin-audit-logs"),
    path("admin/audit/verify", AdminAuditVerifyView.as_view(), name="v1-admin-audit-verify"),
]
