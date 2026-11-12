"""سرویس تراکنشی تولید و ثبت ممیزی گزارش اکسل مدیریتی."""

from __future__ import annotations

from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.audit.choices import AuditAction
from apps.audit.services import record_audit_event
from apps.core.errors import ValidationError as DomainValidationError
from apps.identity.models import User
from apps.identity.permissions import assert_fresh_step_up_mfa
from apps.reporting.excel import build_executive_excel_workbook
from apps.reporting.models import ReportExportLog


@transaction.atomic
def generate_and_audit_excel_export(
    *,
    actor: User,
    date_from: Any = None,
    date_to: Any = None,
    benefactor_id: str | None = None,
    campaign_id: str | None = None,
    include_raw_phones: bool = False,
    reason: str = "",
    request: Any = None,
) -> tuple[bytes, ReportExportLog]:
    """تولید کتابچهٔ اکسل با بررسی الزامی Step-Up MFA در صورت درخواست شماره‌های کامل خیرین."""
    if include_raw_phones:
        assert_fresh_step_up_mfa(request, actor)
        if len(reason.strip()) < 5:
            raise DomainValidationError(
                "برای دریافت فایل اکسل حاوی شماره‌های کامل خیرین، ذکر علت اداری (حداقل ۵ کاراکتر) الزامی است."
            )

    xlsx_bytes, sha256_hex, row_counts = build_executive_excel_workbook(
        date_from=date_from,
        date_to=date_to,
        benefactor_id=benefactor_id,
        campaign_id=campaign_id,
        include_raw_phones=include_raw_phones,
        exported_by_label=f"{actor.display_name or actor.phone} ({actor.role})",
        generated_at=timezone.now(),
    )

    filters_dict = {
        "date_from": date_from.isoformat() if date_from else None,
        "date_to": date_to.isoformat() if date_to else None,
        "benefactor_id": benefactor_id,
        "campaign_id": campaign_id,
    }
    export_log = ReportExportLog.objects.create(
        exported_by=actor,
        filters=filters_dict,
        include_raw_phones=include_raw_phones,
        reason=reason.strip()[:400],
        file_sha256=sha256_hex,
        byte_size=len(xlsx_bytes),
        row_counts=row_counts,
    )
    record_audit_event(
        action=AuditAction.EXCEL_EXPORTED,
        actor=actor,
        target_type="ReportExportLog",
        target_id=str(export_log.id),
        reason=reason if include_raw_phones else "",
        metadata={
            "file_sha256": sha256_hex,
            "byte_size": len(xlsx_bytes),
            "include_raw_phones": include_raw_phones,
            "row_counts": row_counts,
        },
        request=request,
    )
    return xlsx_bytes, export_log
