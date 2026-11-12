"""سلکتورهای فقط‌خواندنی زنجیرهٔ حسابرسی مخصوص پنل مدیریت و گزارش اکسل."""

from __future__ import annotations

from django.db.models import QuerySet

from apps.audit.models import AuditRecord


def list_audit_records(
    *,
    action: str = "",
    target_type: str = "",
    target_id: str = "",
) -> QuerySet[AuditRecord]:
    """بازگرداندن کوئری‌ست فیلترشدهٔ رکوردهای حسابرسی به ترتیب نزولی شمارهٔ ترتیب."""
    qs = AuditRecord.all_objects.all().order_by("-sequence")
    if action:
        qs = qs.filter(action=action)
    if target_type:
        qs = qs.filter(target_type=target_type)
    if target_id:
        qs = qs.filter(target_id=target_id)
    return qs
