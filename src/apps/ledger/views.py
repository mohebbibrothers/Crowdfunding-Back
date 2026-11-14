"""نماهای مدیریتی دفترکل دوطرفه، تسویهٔ چهارچشمی با خیریه‌ها و مغایرت‌گیری درگاه."""

from __future__ import annotations

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.identity.permissions import (
    HasFreshMfa,
    IsFinanceOrSuperAdmin,
    authenticated_user,
)
from apps.ledger.models import ReconciliationBatch
from apps.ledger.selectors import (
    list_disbursement_requests,
    list_journal_entries,
    list_ledger_accounts,
    list_reconciliation_batches,
)
from apps.ledger.serializers import (
    DisbursementCreateInputSerializer,
    DisbursementRequestSerializer,
    DisbursementReviewInputSerializer,
    FinancialControlSnapshotSerializer,
    JournalEntrySerializer,
    LedgerAccountSerializer,
    ReconciliationBatchSerializer,
    ReconciliationRunInputSerializer,
)
from apps.ledger.services import (
    approve_or_reject_disbursement,
    capture_financial_control_snapshot,
    create_disbursement_request,
    run_gateway_reconciliation,
)


class AdminLedgerAccountListView(APIView):
    """فهرست سرفصل‌های دفترکل دوطرفه و ماندهٔ هر حساب."""

    permission_classes = [IsFinanceOrSuperAdmin]

    @extend_schema(
        operation_id="v1_admin_ledger_accounts_list",
        summary="مشاهدهٔ تراز سرفصل‌های دفترکل حسابداری دوطرفه",
        responses={200: LedgerAccountSerializer(many=True)},
        tags=["Admin - Ledger & Disbursements"],
    )
    def get(self, request: Request) -> Response:
        del request
        qs = list_ledger_accounts()
        return Response(LedgerAccountSerializer(qs, many=True).data)


class AdminJournalEntryListView(APIView):
    """فهرست اسناد روزنامهٔ ثبت‌شده در دفترکل."""

    permission_classes = [IsFinanceOrSuperAdmin]

    @extend_schema(
        operation_id="v1_admin_ledger_entries_list",
        summary="فهرست اسناد روزنامهٔ حسابداری",
        parameters=[OpenApiParameter(name="kind", type=str, required=False)],
        responses={200: JournalEntrySerializer(many=True)},
        tags=["Admin - Ledger & Disbursements"],
    )
    def get(self, request: Request) -> Response:
        kind = request.query_params.get("kind")
        qs = list_journal_entries(kind=kind)
        return Response(JournalEntrySerializer(qs[:200], many=True).data)


class AdminDisbursementListCreateView(APIView):
    """فهرست درخواست‌های تسویه با خیریه‌ها و ثبت درخواست جدید (Maker)."""

    permission_classes = [IsFinanceOrSuperAdmin]

    @extend_schema(
        operation_id="v1_admin_disbursements_list",
        summary="فهرست درخواست‌های تسویه با خیریه‌ها",
        parameters=[OpenApiParameter(name="status", type=str, required=False)],
        responses={200: DisbursementRequestSerializer(many=True)},
        tags=["Admin - Ledger & Disbursements"],
    )
    def get(self, request: Request) -> Response:
        status_filter = request.query_params.get("status")
        qs = list_disbursement_requests(status_filter=status_filter)
        return Response(DisbursementRequestSerializer(qs[:200], many=True).data)

    @extend_schema(
        operation_id="v1_admin_disbursements_create",
        summary="ثبت درخواست تسویه وجه با خیریه (گام Maker)",
        request=DisbursementCreateInputSerializer,
        responses={201: DisbursementRequestSerializer},
        tags=["Admin - Ledger & Disbursements"],
    )
    def post(self, request: Request) -> Response:
        ser = DisbursementCreateInputSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        actor = authenticated_user(request)
        disb = create_disbursement_request(
            actor=actor,
            benefactor_id=str(ser.validated_data["benefactor_id"]),
            campaign_id=(
                str(ser.validated_data["campaign_id"])
                if ser.validated_data.get("campaign_id")
                else None
            ),
            amount_rial=int(ser.validated_data["amount_rial"]),
            request_note=str(ser.validated_data.get("request_note") or ""),
            request=request,
        )
        return Response(DisbursementRequestSerializer(disb).data, status=status.HTTP_201_CREATED)


class AdminDisbursementReviewView(APIView):
    """تأیید نهایی (به همراه ثبت سند دفترکل) یا رد درخواست تسویه توسط مدیر دوم با MFA تازه."""

    permission_classes = [IsFinanceOrSuperAdmin, HasFreshMfa]

    @extend_schema(
        operation_id="v1_admin_disbursements_review",
        summary="تأیید یا رد چهارچشمی درخواست تسویه با خیریه (Checker + Step-Up MFA)",
        request=DisbursementReviewInputSerializer,
        responses={200: DisbursementRequestSerializer},
        tags=["Admin - Ledger & Disbursements"],
    )
    def post(self, request: Request, disbursement_id: str) -> Response:
        ser = DisbursementReviewInputSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        actor = authenticated_user(request)
        updated = approve_or_reject_disbursement(
            actor=actor,
            disbursement_id=disbursement_id,
            approve=bool(ser.validated_data["approve"]),
            reason=str(ser.validated_data["reason"]),
            bank_reference_number=str(ser.validated_data.get("bank_reference_number") or ""),
            request=request,
        )
        return Response(DisbursementRequestSerializer(updated).data)


class AdminReconciliationListCreateView(APIView):
    """فهرست دسته‌های مغایرت‌گیری درگاه و اجرای مغایرت‌گیری جدید."""

    permission_classes = [IsFinanceOrSuperAdmin]

    @extend_schema(
        operation_id="v1_admin_reconciliations_list",
        summary="فهرست دسته‌های مغایرت‌گیری درگاه پرداخت",
        responses={200: ReconciliationBatchSerializer(many=True)},
        tags=["Admin - Ledger & Disbursements"],
    )
    def get(self, request: Request) -> Response:
        del request
        qs = list_reconciliation_batches()[:50]
        return Response(ReconciliationBatchSerializer(qs, many=True).data)

    @extend_schema(
        operation_id="v1_admin_reconciliations_create",
        summary="اجرای مغایرت‌گیری فایل تسویه درگاه پرداخت با دفتر داخلی",
        request=ReconciliationRunInputSerializer,
        responses={201: ReconciliationBatchSerializer},
        tags=["Admin - Ledger & Disbursements"],
    )
    def post(self, request: Request) -> Response:
        ser = ReconciliationRunInputSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        actor = authenticated_user(request)
        batch = run_gateway_reconciliation(
            actor=actor,
            gateway_name=str(ser.validated_data["gateway_name"]),
            period_start=ser.validated_data["period_start"],
            period_end=ser.validated_data["period_end"],
            settlement_rows=list(ser.validated_data["rows"]),
            request=request,
        )
        batch_loaded = ReconciliationBatch.objects.prefetch_related("items").get(pk=batch.pk)
        return Response(
            ReconciliationBatchSerializer(batch_loaded).data,
            status=status.HTTP_201_CREATED,
        )


class AdminFinancialControlSnapshotView(APIView):
    """ثبت و مشاهدهٔ اسنپ‌شات تراز آزمایشی دفترکل و کنترل انطباق شمارنده‌ها."""

    permission_classes = [IsFinanceOrSuperAdmin]

    @extend_schema(
        operation_id="v1_admin_ledger_control_snapshot_create",
        summary="محاسبه و ثبت اسنپ‌شات کنترل تراز دفترکل و انطباق شمارنده‌ها",
        request=None,
        responses={200: FinancialControlSnapshotSerializer},
        tags=["Admin - Ledger & Disbursements"],
    )
    def post(self, request: Request) -> Response:
        actor = authenticated_user(request)
        snap = capture_financial_control_snapshot(actor=actor)
        return Response(FinancialControlSnapshotSerializer(snap).data)
