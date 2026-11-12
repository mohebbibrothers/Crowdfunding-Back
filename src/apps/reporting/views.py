"""نماهای HTTP گزارش‌گیری اجرایی و خروجی اکسل مدیریتی."""

from __future__ import annotations

from django.http import HttpResponse
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.identity.permissions import (
    IsFinanceOrSuperAdmin,
    IsStaffRole,
    authenticated_user,
)
from apps.reporting.selectors import list_report_export_logs
from apps.reporting.serializers import (
    ExcelExportQuerySerializer,
    ReportExportLogSerializer,
)
from apps.reporting.services import generate_and_audit_excel_export


class AdminExcelExportDownloadView(APIView):
    """دانلود کتابچهٔ ۸ کاربرگهٔ اکسل مدیریتی (راست‌به‌چپ، چاپی A4، نموداردار و مهرشده با SHA-256)."""

    permission_classes = [IsFinanceOrSuperAdmin]

    @extend_schema(
        operation_id="v1_admin_reports_excel_export",
        summary="دانلود گزارش اکسل ۸ کاربرگهٔ اجرایی، مالی و مغایرت‌گیری (مهرشده با SHA-256)",
        parameters=[
            OpenApiParameter("date_from", OpenApiTypes.DATETIME, required=False),
            OpenApiParameter("date_to", OpenApiTypes.DATETIME, required=False),
            OpenApiParameter("benefactor_id", OpenApiTypes.UUID, required=False),
            OpenApiParameter("campaign_id", OpenApiTypes.UUID, required=False),
            OpenApiParameter("include_raw_phones", OpenApiTypes.BOOL, required=False),
            OpenApiParameter("reason", OpenApiTypes.STR, required=False),
        ],
        responses={
            (
                200,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ): OpenApiTypes.BINARY
        },
        tags=["Admin - Executive Excel Reports"],
    )
    def get(self, request: Request) -> HttpResponse:
        ser = ExcelExportQuerySerializer(data=request.query_params)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        actor = authenticated_user(request)

        xlsx_bytes, export_log = generate_and_audit_excel_export(
            actor=actor,
            date_from=d.get("date_from"),
            date_to=d.get("date_to"),
            benefactor_id=str(d["benefactor_id"]) if d.get("benefactor_id") else None,
            campaign_id=str(d["campaign_id"]) if d.get("campaign_id") else None,
            include_raw_phones=bool(d.get("include_raw_phones", False)),
            reason=str(d.get("reason") or ""),
            request=request,
        )
        filename = f"crowdfunding-executive-report-{timezone.now().strftime('%Y%m%d-%H%M%S')}.xlsx"
        response = HttpResponse(
            xlsx_bytes,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        response["X-Document-SHA256"] = export_log.file_sha256
        response["X-Export-Log-Id"] = str(export_log.id)
        return response


class AdminExportAuditHistoryView(APIView):
    """مشاهدهٔ تاریخچه و هش‌های SHA-256 فایل‌های اکسل صادرشده برای ممیزی اصالت."""

    permission_classes = [IsStaffRole]

    @extend_schema(
        operation_id="v1_admin_reports_export_history_list",
        summary="فهرست ممیزی و هش SHA-256 گزارش‌های اکسل صادرشده",
        responses={200: ReportExportLogSerializer(many=True)},
        tags=["Admin - Executive Excel Reports"],
    )
    def get(self, request: Request) -> Response:
        del request
        qs = list_report_export_logs()[:100]
        return Response(ReportExportLogSerializer(qs, many=True).data)
