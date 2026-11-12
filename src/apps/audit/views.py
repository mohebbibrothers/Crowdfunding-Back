"""نماهای HTTP حسابرسی برای مدیران ارشد و ممیزان."""

from __future__ import annotations

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.models import AuditRecord
from apps.audit.selectors import list_audit_records
from apps.audit.serializers import AuditChainVerificationSerializer, AuditRecordSerializer
from apps.audit.services import verify_anchors, verify_chain
from apps.core.pagination import StaffTableCursorPagination
from apps.identity.permissions import IsFinanceOrSuperAdmin


class AdminAuditRecordListView(APIView):
    """فهرست صفحه‌بندی‌شدهٔ رکوردهای زنجیرهٔ حسابرسی مخصوص مدیران."""

    permission_classes = [IsFinanceOrSuperAdmin]

    @extend_schema(
        operation_id="v1_admin_audit_logs_list",
        summary="فهرست رکوردهای زنجیرهٔ حسابرسی با فیلتر کنش و هدف",
        parameters=[
            OpenApiParameter(name="action", type=str, required=False),
            OpenApiParameter(name="target_type", type=str, required=False),
            OpenApiParameter(name="target_id", type=str, required=False),
        ],
        responses={200: AuditRecordSerializer(many=True)},
        tags=["Admin - Audit"],
    )
    def get(self, request: Request) -> Response:
        """واکشی رکوردهای حسابرسی از سلکتور."""
        qs = list_audit_records(
            action=request.query_params.get("action", "").strip(),
            target_type=request.query_params.get("target_type", "").strip(),
            target_id=request.query_params.get("target_id", "").strip(),
        )
        paginator = StaffTableCursorPagination()
        paginator.ordering = ("-sequence",)
        page = paginator.paginate_queryset(qs, request, view=self)
        data = AuditRecordSerializer(page, many=True).data
        return paginator.get_paginated_response(data)


class AdminAuditVerifyView(APIView):
    """اجرای راستی‌آزمایی رمزنگاری زنجیرهٔ هش و لنگرهای امضاشده."""

    permission_classes = [IsFinanceOrSuperAdmin]

    @extend_schema(
        operation_id="v1_admin_audit_verify",
        summary="بررسی سلامت زنجیرهٔ هش حسابرسی و لنگرهای امضاشده",
        responses={200: AuditChainVerificationSerializer},
        tags=["Admin - Audit"],
    )
    def get(self, request: Request) -> Response:
        """راستی‌آزمایی زنجیرهٔ هش و لنگرها."""
        del request
        chain_ok, broken_seq = verify_chain()
        anchors_ok, broken_anchors = verify_anchors()
        total = AuditRecord.all_objects.count()
        return Response(
            {
                "chain_valid": chain_ok,
                "first_broken_sequence": broken_seq,
                "anchors_valid": anchors_ok,
                "broken_anchors": broken_anchors,
                "total_records": total,
            }
        )
