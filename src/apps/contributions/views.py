"""نماهای HTTP مشارکت‌ها، خرید سریع ۳۰ ثانیه‌ای، بازگشت درگاه، رسید، نیت‌نامه، مرکل و داشبورد خیر."""

from __future__ import annotations

from typing import Any

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.benefactors.models import CharityJar
from apps.campaigns.models import Campaign
from apps.contributions.choices import PaymentStatus
from apps.contributions.dashboard import build_donor_dashboard
from apps.contributions.merkle import verify_inclusion_proof
from apps.contributions.models import (
    DedicationCard,
    Payment,
    PledgeInstallment,
    RecurringPledge,
)
from apps.contributions.recurring import (
    build_pledge_stats,
    cancel_pledge,
    create_recurring_pledge,
    dispatch_pledge_reminders,
    expire_stale_installments,
    get_owned_pledge,
    materialize_due_installments,
    pause_pledge,
    pay_installment,
    resume_paused_pledges,
    skip_installment,
    update_pledge,
)
from apps.contributions.selectors import (
    get_public_campaign_transparency,
    get_public_dedication_certificate,
    get_public_receipt_verification,
    list_admin_payments,
    list_public_campaign_supporters,
    list_user_ambassador_links,
    list_user_contributions,
)
from apps.contributions.serializers import (
    AdminPaymentSerializer,
    AdminPledgeSerializer,
    AmbassadorCreateInputSerializer,
    AmbassadorLinkSerializer,
    CampaignSupporterOutputSerializer,
    CampaignTransparencyOutputSerializer,
    CheckoutInitiateInputSerializer,
    CheckoutInitiateResponseSerializer,
    ContributionUserSerializer,
    DedicationCertificateOutputSerializer,
    DonorDashboardOutputSerializer,
    ExpressConfirmInputSerializer,
    ExpressStartInputSerializer,
    ExpressStartResponseSerializer,
    ExternalContributionSerializer,
    ExternalContributionWriteSerializer,
    MerkleInclusionProofOutputSerializer,
    MerkleProofVerifyInputSerializer,
    MerkleProofVerifyOutputSerializer,
    PaymentCallbackVerifyInputSerializer,
    PaymentRefundInputSerializer,
    PaymentVerifyResponseSerializer,
    PledgeCancelInputSerializer,
    PledgeCreateInputSerializer,
    PledgeCycleOutputSerializer,
    PledgeInstallmentOutputSerializer,
    PledgeOutputSerializer,
    PledgePayInputSerializer,
    PledgePayOutputSerializer,
    PledgeStatsOutputSerializer,
    PledgeUpdateInputSerializer,
    ReceiptVerificationOutputSerializer,
    RefundResultOutputSerializer,
    SandboxPaymentOutputSerializer,
)
from apps.contributions.services import (
    confirm_express_checkout,
    create_ambassador_link,
    get_donor_merkle_inclusion_proof,
    initiate_contribution_checkout,
    record_external_contribution,
    refund_verified_payment,
    start_express_checkout,
    verify_payment_callback,
)
from apps.core.crypto import mask_phone
from apps.core.errors import NotFoundError
from apps.core.idempotency import IDEMPOTENCY_HEADER, execute_idempotent
from apps.core.money import rial_to_toman
from apps.core.pagination import UserListCursorPagination
from apps.core.schema import CURSOR_PAGINATION_PARAMETERS, paginated_response
from apps.identity.permissions import (
    HasFreshMfa,
    IsFinanceOrSuperAdmin,
    IsStaffRole,
    authenticated_user,
)
from apps.identity.throttles import CheckoutThrottle, OtpRequestThrottle, OtpVerifyThrottle


class ContributionInitiateView(APIView):
    """آغاز مشارکت آنلاین (رزرو ۱۵ دقیقه‌ای سهم حرکت یا واریز آزاد قلک عام) با پشتیبانی Idempotency-Key."""

    permission_classes = [IsAuthenticated]
    throttle_classes = [CheckoutThrottle]

    @extend_schema(
        operation_id="v1_contributions_checkout_create",
        summary="رزرو ۱۵ دقیقه‌ای سهم حرکت یا واریز به قلک و دریافت لینک درگاه پرداخت",
        request=CheckoutInitiateInputSerializer,
        responses={201: CheckoutInitiateResponseSerializer},
        tags=["Donor - Contributions & Checkout"],
    )
    def post(self, request: Request) -> Response:
        ser = CheckoutInitiateInputSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        user = authenticated_user(request)
        idem_key = request.headers.get(IDEMPOTENCY_HEADER)

        def _run() -> tuple[int, dict[str, Any]]:
            contribution, payment = initiate_contribution_checkout(
                user=user,
                target_kind=str(d["target_kind"]),
                campaign_id=str(d["campaign_id"]) if d.get("campaign_id") else None,
                charity_jar_id=str(d["charity_jar_id"]) if d.get("charity_jar_id") else None,
                shares_count=int(d.get("shares_count") or 0),
                amount_rial=int(d.get("amount_rial") or 0),
                is_anonymous=bool(d.get("is_anonymous", False)),
                public_note=str(d.get("public_note") or ""),
                ambassador_code=str(d.get("ambassador_code") or ""),
                dedication_payload=dict(d["dedication"]) if d.get("dedication") else None,
                gateway_name=str(d.get("gateway_name") or ""),
                request=request,
            )
            return (
                status.HTTP_201_CREATED,
                {
                    "contribution_id": str(contribution.id),
                    "payment_id": str(payment.id),
                    "authority": payment.authority,
                    "gateway_name": payment.gateway_name,
                    "gateway_redirect_url": payment.redirect_url,
                    "shares_count": contribution.shares_count,
                    "amount_rial": contribution.amount_rial,
                    "amount_toman": rial_to_toman(contribution.amount_rial),
                    "hold_expires_at": contribution.hold_expires_at.isoformat(),
                },
            )

        idem_res = execute_idempotent(
            key=idem_key,
            scope="contributions.checkout",
            actor_ref=str(user.id),
            payload=request.data,
            action=_run,
        )
        resp = Response(idem_res.body, status=idem_res.status)
        if idem_res.replayed:
            resp["X-Idempotent-Replayed"] = "true"
        return resp


class ExpressCheckoutStartView(APIView):
    """گام اول مشارکت سریع ۳۰ ثانیه‌ای مهمان: ثبت مشخصات مشارکت و ارسال آنی کد تایید پیامکی."""

    permission_classes = [AllowAny]
    authentication_classes: list[Any] = []
    throttle_classes = [OtpRequestThrottle]

    @extend_schema(
        operation_id="v1_contributions_express_start",
        summary="مشارکت سریع ۳۰ ثانیه‌ای مهمان — گام ۱ (ثبت نیت خرید و ارسال OTP)",
        request=ExpressStartInputSerializer,
        responses={201: ExpressStartResponseSerializer},
        tags=["Public - Express 30s Checkout"],
    )
    def post(self, request: Request) -> Response:
        ser = ExpressStartInputSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        out = start_express_checkout(data=ser.validated_data, request=request)
        return Response(ExpressStartResponseSerializer(out).data, status=status.HTTP_201_CREATED)


class ExpressCheckoutConfirmView(APIView):
    """گام دوم مشارکت سریع ۳۰ ثانیه‌ای مهمان: تأیید OTP + صدور نشست + رزرو سهم + هدایت مستقیم به درگاه."""

    permission_classes = [AllowAny]
    authentication_classes: list[Any] = []
    throttle_classes = [OtpVerifyThrottle]

    @extend_schema(
        operation_id="v1_contributions_express_confirm",
        summary="مشارکت سریع ۳۰ ثانیه‌ای مهمان — گام ۲ (تایید OTP، ورود خودکار و دریافت لینک درگاه)",
        request=ExpressConfirmInputSerializer,
        responses={201: CheckoutInitiateResponseSerializer},
        tags=["Public - Express 30s Checkout"],
    )
    def post(self, request: Request) -> Response:
        ser = ExpressConfirmInputSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        bundle, contribution, payment = confirm_express_checkout(
            intent_id=str(ser.validated_data["intent_id"]),
            otp_code=str(ser.validated_data["code"]),
            request=request,
        )
        return Response(
            {
                "access_token": bundle.access_token,
                "refresh_token": bundle.refresh_token,
                "session_id": str(bundle.session.id),
                "contribution_id": str(contribution.id),
                "payment_id": str(payment.id),
                "authority": payment.authority,
                "gateway_name": payment.gateway_name,
                "gateway_redirect_url": payment.redirect_url,
                "shares_count": contribution.shares_count,
                "amount_rial": contribution.amount_rial,
                "amount_toman": rial_to_toman(contribution.amount_rial),
                "hold_expires_at": contribution.hold_expires_at,
            },
            status=status.HTTP_201_CREATED,
        )


class PaymentCallbackVerifyView(APIView):
    """تأیید تکرارناپذیر (Idempotent) بازگشت کاربر از درگاه پرداخت (پشتیبانی از GET شاپرکی و POST JSON)."""

    permission_classes = [AllowAny]
    authentication_classes: list[Any] = []

    def _handle(self, authority: str, gw_status: str) -> Response:
        payment, receipt = verify_payment_callback(authority=authority, gateway_status=gw_status)
        contrib = payment.contribution
        ded = DedicationCard.objects.filter(contribution=contrib, is_active=True).first()
        return Response(
            {
                "verified": payment.status == PaymentStatus.VERIFIED,
                "payment_status": payment.status,
                "contribution_id": str(contrib.id),
                "ref_id": payment.ref_id,
                "shares_count": contrib.shares_count,
                "matched_shares_awarded": contrib.matched_shares_awarded,
                "amount_rial": contrib.amount_rial,
                "amount_toman": rial_to_toman(contrib.amount_rial),
                "receipt_number": receipt.receipt_number if receipt else None,
                "verification_code": receipt.verification_code if receipt else None,
                "dedication_token": ded.public_token if ded else None,
            }
        )

    @extend_schema(
        operation_id="v1_payments_callback_get",
        summary="بازگشت GET از درگاه پرداخت اینترنتی (Authority & Status)",
        parameters=[
            OpenApiParameter(
                name="Authority",
                type=str,
                location=OpenApiParameter.QUERY,
                required=True,
                description="شناسهٔ authority دریافتشده از درگاه (زرینپال / Sandbox).",
            ),
            OpenApiParameter(
                name="Status",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="وضعیت اعلامشدهٔ درگاه (OK / NOK)؛ صرفاً سیگنال اولیه است.",
            ),
        ],
        responses={200: PaymentVerifyResponseSerializer},
        tags=["Public - Payments & Receipts"],
    )
    def get(self, request: Request) -> Response:
        authority = str(
            request.query_params.get("Authority") or request.query_params.get("authority") or ""
        ).strip()
        gw_status = str(
            request.query_params.get("Status") or request.query_params.get("status") or "NOK"
        ).strip()
        if not authority:
            raise NotFoundError("پارامتر Authority در بازگشت درگاه یافت نشد.")
        return self._handle(authority, gw_status)

    @extend_schema(
        operation_id="v1_payments_verify_post",
        summary="تأیید تراکنش درگاه پرداخت از طریق فرانت‌اند (POST)",
        request=PaymentCallbackVerifyInputSerializer,
        responses={200: PaymentVerifyResponseSerializer},
        tags=["Public - Payments & Receipts"],
    )
    def post(self, request: Request) -> Response:
        ser = PaymentCallbackVerifyInputSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        return self._handle(
            str(ser.validated_data["authority"]),
            str(ser.validated_data["status"]),
        )


class SandboxPaymentDetailView(APIView):
    """مشاهدهٔ اطلاعات تراکنش درگاه آزمایشی Sandbox برای رندر شبیه‌ساز درگاه در فرانت‌اند."""

    permission_classes = [AllowAny]
    authentication_classes: list[Any] = []

    @extend_schema(
        operation_id="v1_payments_sandbox_retrieve",
        summary="اطلاعات تراکنش درگاه تعاملی Sandbox",
        responses={200: SandboxPaymentOutputSerializer},
        tags=["Public - Payments & Receipts"],
    )
    def get(self, request: Request, authority: str) -> Response:
        del request
        p = Payment.objects.filter(authority=authority, gateway_name="sandbox").first()
        if p is None:
            raise NotFoundError("تراکنش Sandbox یافت نشد.")
        return Response(
            {
                "authority": p.authority,
                "amount_rial": p.amount_rial,
                "amount_toman": rial_to_toman(p.amount_rial),
                "status": p.status,
            }
        )


# ── نقاط انتهایی شفافیت عمومی، دیوار همراهان، استعلام رسید و نیت‌نامه ────────


class PublicCampaignSupportersView(APIView):
    """دیوار عمومی خیرین همراه یک حرکت (نمایش «خیر گمنام» برای مشارکت‌های ناشناس)."""

    permission_classes = [AllowAny]
    authentication_classes: list[Any] = []

    @extend_schema(
        operation_id="v1_campaigns_supporters_list",
        summary="فهرست همراهان حرکت خیرخواهانه (با حفظ گمنامی خیرین ناشناس)",
        responses={200: CampaignSupporterOutputSerializer(many=True)},
        tags=["Public - Campaigns"],
    )
    def get(self, request: Request, identifier: str) -> Response:
        del request
        return Response(list_public_campaign_supporters(identifier=identifier))


class PublicCampaignTransparencyView(APIView):
    """گزارش شفافیت مالی و ریشهٔ درخت مرکل (Merkle Root) برای یک حرکت."""

    permission_classes = [AllowAny]
    authentication_classes: list[Any] = []

    @extend_schema(
        operation_id="v1_campaigns_transparency_retrieve",
        summary="گزارش شفافیت مالی، تفکیک منابع آنلاین/آفلاین و ریشه درخت مرکل حرکت",
        responses={200: CampaignTransparencyOutputSerializer},
        tags=["Public - Cryptographic Transparency"],
    )
    def get(self, request: Request, identifier: str) -> Response:
        del request
        return Response(get_public_campaign_transparency(identifier=identifier))


class PublicMerkleVerifyView(APIView):
    """راستی‌آزمایی ریاضی مستقل یک برگ مشارکت در برابر ریشهٔ مرکل منتشرشده."""

    permission_classes = [AllowAny]
    authentication_classes: list[Any] = []

    @extend_schema(
        operation_id="v1_transparency_verify_merkle_proof",
        summary="راستی‌آزمایی ریاضی اثبات شمول مرکل (Merkle Inclusion Proof)",
        request=MerkleProofVerifyInputSerializer,
        responses={200: MerkleProofVerifyOutputSerializer},
        tags=["Public - Cryptographic Transparency"],
    )
    def post(self, request: Request) -> Response:
        ser = MerkleProofVerifyInputSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        valid = verify_inclusion_proof(
            leaf_hash=str(ser.validated_data["leaf_hash"]),
            proof=list(ser.validated_data["proof"]),
            expected_root=str(ser.validated_data["merkle_root"]),
        )
        return Response({"valid": valid})


class PublicReceiptVerifyView(APIView):
    """استعلام اصالت عمومی رسید مشارکت از روی کد رهگیری امضاشده."""

    permission_classes = [AllowAny]
    authentication_classes: list[Any] = []

    @extend_schema(
        operation_id="v1_receipts_verify_retrieve",
        summary="استعلام اصالت رسید رسمی مشارکت با کد رهگیری",
        responses={200: ReceiptVerificationOutputSerializer},
        tags=["Public - Payments & Receipts"],
    )
    def get(self, request: Request, verification_code: str) -> Response:
        del request
        return Response(get_public_receipt_verification(verification_code=verification_code))


class PublicDedicationCertificateView(APIView):
    """مشاهدهٔ عمومی گواهی نیت‌نامه و کارت هدیهٔ معنوی (بدون افشای مبلغ ریالی)."""

    permission_classes = [AllowAny]
    authentication_classes: list[Any] = []

    @extend_schema(
        operation_id="v1_dedications_retrieve",
        summary="مشاهدهٔ گواهی نیت‌نامه و کارت هدیه معنوی با توکن عمومی",
        responses={200: DedicationCertificateOutputSerializer},
        tags=["Public - Dedication Certificates"],
    )
    def get(self, request: Request, public_token: str) -> Response:
        del request
        return Response(get_public_dedication_certificate(public_token=public_token))


# ── نقاط انتهایی اختصاصی داشبورد خیر، سفیران و اثبات مرکل شخصی ───────────────


class MeDonorDashboardView(APIView):
    """داشبورد جامع و انگیزه‌بخش خیر (سهم‌ها، قلک‌ها، اثر سفیر، نشان‌های افتخار، مژده‌ها و پیشنهادها)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="v1_me_dashboard_retrieve",
        summary="داشبورد جامع و انگیزه‌بخش خیر (کارنامهٔ معنوی، مالی، سفیران و مژده‌های میدانی)",
        responses={200: DonorDashboardOutputSerializer},
        tags=["Donor - Motivation Dashboard"],
    )
    def get(self, request: Request) -> Response:
        user = authenticated_user(request)
        return Response(build_donor_dashboard(user=user))


class MeContributionListView(APIView):
    """تاریخچهٔ کامل صفحه‌بندی‌شدهٔ تمام مشارکت‌های خیر (حرکت‌ها و قلک‌ها)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="v1_me_contributions_list",
        summary="تاریخچهٔ تمام مشارکت‌های من در حرکت‌ها و قلک‌ها",
        parameters=CURSOR_PAGINATION_PARAMETERS,
        responses={
            200: paginated_response(
                ContributionUserSerializer,
                name="PaginatedContributionUser",
                include_total=True,
            )
        },
        tags=["Donor - Motivation Dashboard"],
    )
    def get(self, request: Request) -> Response:
        user = authenticated_user(request)
        qs = list_user_contributions(user_id=user.id)
        paginator = UserListCursorPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response(ContributionUserSerializer(page, many=True).data)


class MeContributionMerkleProofView(APIView):
    """دریافت مسیر اثبات شمول رمزنگاری‌شده (Merkle Inclusion Proof) برای یک مشارکت قطعی خیر."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="v1_me_contributions_merkle_proof_retrieve",
        summary="دریافت گواهی اثبات شمول مرکل (Merkle Inclusion Proof) برای مشارکت من",
        responses={200: MerkleInclusionProofOutputSerializer},
        tags=["Public - Cryptographic Transparency"],
    )
    def get(self, request: Request, contribution_id: str) -> Response:
        user = authenticated_user(request)
        return Response(
            get_donor_merkle_inclusion_proof(user=user, contribution_id=contribution_id)
        )


class MeAmbassadorLinkListCreateView(APIView):
    """مشاهدهٔ کارنامهٔ لینک‌های سفیر من و ساخت لینک دعوت اختصاصی جدید."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="v1_me_ambassador_links_list",
        summary="فهرست لینک‌های سفیر اجتماعی من و آمار اثرگذاری هرکدام",
        responses={200: AmbassadorLinkSerializer(many=True)},
        tags=["Public - Short-Links & Ambassadors"],
    )
    def get(self, request: Request) -> Response:
        user = authenticated_user(request)
        qs = list_user_ambassador_links(user_id=user.id)
        return Response(AmbassadorLinkSerializer(qs, many=True).data)

    @extend_schema(
        operation_id="v1_me_ambassador_links_create",
        summary="ساخت لینک اختصاصی سفیر اجتماعی برای دعوت به حرکت یا قلک",
        request=AmbassadorCreateInputSerializer,
        responses={201: AmbassadorLinkSerializer},
        tags=["Public - Short-Links & Ambassadors"],
    )
    def post(self, request: Request) -> Response:
        ser = AmbassadorCreateInputSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        user = authenticated_user(request)
        link = create_ambassador_link(
            user=user,
            campaign_id=(
                str(ser.validated_data["campaign_id"])
                if ser.validated_data.get("campaign_id")
                else None
            ),
            charity_jar_id=(
                str(ser.validated_data["charity_jar_id"])
                if ser.validated_data.get("charity_jar_id")
                else None
            ),
            custom_note=str(ser.validated_data.get("custom_note") or ""),
        )
        return Response(AmbassadorLinkSerializer(link).data, status=status.HTTP_201_CREATED)


# ── نقاط انتهایی مدیریتی پرداخت‌ها، استرداد و ثبت مشارکت خارجی ───────────────


class AdminPaymentListView(APIView):
    """فهرست مدیریتی پرداخت‌ها (شماره موبایل خیر به صورت پیش‌فرض پوشانده است)."""

    permission_classes = [IsStaffRole]

    @extend_schema(
        operation_id="v1_admin_payments_list",
        summary="فهرست مدیریتی تراکنش‌های درگاه پرداخت",
        parameters=[OpenApiParameter(name="status", type=str, required=False)],
        responses={200: AdminPaymentSerializer(many=True)},
        tags=["Admin - Payments & Refunds"],
    )
    def get(self, request: Request) -> Response:
        status_filter = request.query_params.get("status")
        qs = list_admin_payments(status_filter=status_filter)
        return Response(AdminPaymentSerializer(qs[:200], many=True).data)


class AdminPaymentRefundView(APIView):
    """استرداد وجه پرداخت تاییدشده با سند معکوس دفترکل و احراز هویت چندعاملی تازه."""

    permission_classes = [IsFinanceOrSuperAdmin, HasFreshMfa]

    @extend_schema(
        operation_id="v1_admin_payments_refund",
        summary="ثبت استرداد وجه پرداخت و آزادسازی سهم‌ها (نیازمند Step-Up MFA)",
        request=PaymentRefundInputSerializer,
        responses={200: RefundResultOutputSerializer},
        tags=["Admin - Payments & Refunds"],
    )
    def post(self, request: Request, payment_id: str) -> Response:
        ser = PaymentRefundInputSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        actor = authenticated_user(request)
        refund = refund_verified_payment(
            actor=actor,
            payment_id=payment_id,
            reason=str(ser.validated_data["reason"]),
            bank_reference=str(ser.validated_data.get("bank_reference") or ""),
            request=request,
        )
        return Response(
            {
                "refund_id": str(refund.id),
                "amount_rial": refund.amount_rial,
                "status": "refunded",
            }
        )


class AdminExternalContributionCreateView(APIView):
    """ثبت مشارکت خارج از درگاه آنلاین (آفلاین/فیش بانکی) در حساب انتظامی مجزا."""

    permission_classes = [IsFinanceOrSuperAdmin]

    @extend_schema(
        operation_id="v1_admin_campaigns_external_contributions_create",
        summary="ثبت سهم‌های تامین‌شده خارج از درگاه آنلاین در حساب انتظامی مجزا",
        request=ExternalContributionWriteSerializer,
        responses={201: ExternalContributionSerializer},
        tags=["Admin - Payments & Refunds"],
    )
    def post(self, request: Request, campaign_id: str) -> Response:
        ser = ExternalContributionWriteSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        actor = authenticated_user(request)
        ext = record_external_contribution(
            actor=actor,
            campaign_id=campaign_id,
            shares_count=int(ser.validated_data["shares_count"]),
            donor_display_name=str(ser.validated_data["donor_display_name"]),
            reference_code=str(ser.validated_data["reference_code"]),
            note=str(ser.validated_data.get("note") or ""),
            request=request,
        )
        return Response(
            ExternalContributionSerializer(ext).data,
            status=status.HTTP_201_CREATED,
        )


# ══════════════════════════════════════════════════════════════════════════════
# تعهد کمک مستمر (v1.4.0)
#
# قاعدهٔ مشترک همهٔ نماها: خروجی همیشه با ``rial_to_toman`` هم‌راستا می‌شود.
# هیچ جا تبدیل در پایگاه داده انجام نمی‌شود — ریال منبع حقیقت است.
# ══════════════════════════════════════════════════════════════════════════════


def _serialize_installment(installment: PledgeInstallment) -> dict[str, Any]:
    """تبدیل قسط به دیکشنری قابل‌سریالایز — با پرچم‌های «چه کاری می‌توان کرد»."""
    return {
        "id": str(installment.pk),
        "sequence": int(installment.sequence),
        "due_date": installment.due_date,
        "grace_until": installment.grace_until,
        "amount_rial": int(installment.amount_rial),
        "amount_toman": rial_to_toman(int(installment.amount_rial)),
        "status": str(installment.status),
        "status_display": installment.get_status_display(),
        "is_open": installment.is_open,
        "reminder_count": int(installment.reminder_count),
        "failure_reason": installment.failure_reason or "",
        "can_pay": installment.is_open
        and installment.pledge.status
        in {
            "active",
            "paused",
        },
        "can_skip": installment.is_open,
        "contribution_id": str(installment.contribution_id)
        if installment.contribution_id
        else None,
    }


def _serialize_pledge(
    pledge: RecurringPledge, open_installments: list[PledgeInstallment]
) -> dict[str, Any]:
    """تبدیل تعهد به دیکشنری — با شمارش اقساط باز و شناسهٔ قسط قابل پرداخت."""
    payable = [i for i in open_installments if i.pledge_id == pledge.pk and i.is_open]
    return {
        "id": str(pledge.pk),
        "status": str(pledge.status),
        "status_display": pledge.get_status_display(),
        "target_kind": str(pledge.target_kind),
        "target_title": _pledge_target_title(pledge),
        "amount_rial": int(pledge.amount_rial),
        "amount_toman": rial_to_toman(int(pledge.amount_rial)),
        "frequency": str(pledge.frequency),
        "frequency_display": pledge.get_frequency_display(),
        "interval_months": int(pledge.interval_months),
        "anchor_day": int(pledge.anchor_day),
        "next_due_date": pledge.next_due_date,
        "total_paid_rial": int(pledge.total_paid_rial),
        "total_paid_toman": rial_to_toman(int(pledge.total_paid_rial)),
        "installments_paid": int(pledge.installments_paid),
        "installments_skipped": int(pledge.installments_skipped),
        "consecutive_failures": int(pledge.consecutive_failures),
        "pause_until": pledge.pause_until,
        "created_at": pledge.created_at,
        "open_installments": len(payable),
        "next_payable_installment_id": str(payable[0].pk) if payable else None,
    }


def _pledge_target_title(pledge: RecurringPledge) -> str:
    """عنوان خوانا مقصد تعهد."""
    if pledge.campaign_id:
        return str(getattr(pledge.campaign, "title", "") or "")
    if pledge.charity_jar_id:
        return str(getattr(pledge.charity_jar, "title", "") or "")
    return ""


class MePledgeListCreateView(APIView):
    """فهرست و ساخت تعهد کمک مستمر برای خیر وارد‌شده."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="v1_me_pledges_list",
        summary="فهرست تعهدهای کمک مستمر من",
        parameters=[OpenApiParameter(name="status", type=str, required=False)],
        responses={200: PledgeOutputSerializer(many=True)},
        tags=["Donor - Recurring Pledges"],
    )
    def get(self, request: Request) -> Response:
        user = authenticated_user(request)
        qs = RecurringPledge.objects.filter(user=user).select_related("campaign", "charity_jar")
        status_filter = (request.query_params.get("status") or "").strip()
        if status_filter:
            qs = qs.filter(status=status_filter)
        pledges = list(qs.order_by("-created_at")[:100])
        open_inst = list(
            PledgeInstallment.objects.filter(
                pledge__in=pledges,
                status__in=["scheduled", "reminded"],
            ).order_by("due_date")
        )
        return Response([_serialize_pledge(p, open_inst) for p in pledges])

    @extend_schema(
        operation_id="v1_me_pledges_create",
        summary="ساخت تعهد کمک مستمر (ماهانه یا سه‌ماهه)",
        request=PledgeCreateInputSerializer,
        responses={201: PledgeOutputSerializer},
        tags=["Donor - Recurring Pledges"],
    )
    def post(self, request: Request) -> Response:
        user = authenticated_user(request)
        serializer = PledgeCreateInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        campaign = None
        charity_jar = None
        if data.get("campaign_id"):
            campaign = Campaign.objects.filter(pk=data["campaign_id"]).first()
            if campaign is None:
                raise NotFoundError("حرکت یافت نشد.")
        if data.get("charity_jar_id"):
            charity_jar = CharityJar.objects.filter(pk=data["charity_jar_id"]).first()
            if charity_jar is None:
                raise NotFoundError("قلک یافت نشد.")

        if campaign is not None:
            benefactor = campaign.benefactor
        elif charity_jar is not None:
            benefactor = charity_jar.benefactor
        else:  # pragma: no cover - serializer هر دو را رد می‌کند
            raise NotFoundError("مقصد تعهد یافت نشد.")
        result = create_recurring_pledge(
            user=user,
            benefactor=benefactor,
            target_kind=data["target_kind"],
            amount_rial=int(data["amount_rial"]),
            frequency=data["frequency"],
            campaign=campaign,
            charity_jar=charity_jar,
            shares_count=int(data.get("shares_count") or 0),
            start_day=data.get("start_day"),
        )
        pledge = RecurringPledge.objects.select_related("campaign", "charity_jar").get(
            pk=result.pledge.pk
        )
        return Response(
            _serialize_pledge(pledge, [result.first_installment]),
            status=status.HTTP_201_CREATED,
        )


class MePledgeDetailView(APIView):
    """جزئیات، ویرایش و لغو یک تعهد متعلق به خیر."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="v1_me_pledges_retrieve",
        summary="جزئیات یک تعهد کمک مستمر",
        responses={200: PledgeOutputSerializer},
        tags=["Donor - Recurring Pledges"],
    )
    def get(self, request: Request, pledge_id: str) -> Response:
        user = authenticated_user(request)
        pledge = get_owned_pledge(pledge_id=pledge_id, user=user)
        open_inst = list(
            PledgeInstallment.objects.filter(
                pledge=pledge, status__in=["scheduled", "reminded"]
            ).order_by("due_date")
        )
        return Response(_serialize_pledge(pledge, open_inst))

    @extend_schema(
        operation_id="v1_me_pledges_update",
        summary="ویرایش تعهد (مبلغ، تناوب، روز شروع) یا توقف موقت",
        request=PledgeUpdateInputSerializer,
        responses={200: PledgeOutputSerializer},
        tags=["Donor - Recurring Pledges"],
    )
    def patch(self, request: Request, pledge_id: str) -> Response:
        user = authenticated_user(request)
        serializer = PledgeUpdateInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        if "pause_until" in serializer.validated_data:
            if data.get("pause_until") is None and "amount_rial" not in data:
                pause_pledge(pledge_id=pledge_id, user=user, until=None)
            else:
                pause_pledge(pledge_id=pledge_id, user=user, until=data.get("pause_until"))

        pledge = update_pledge(
            pledge_id=pledge_id,
            user=user,
            amount_rial=data.get("amount_rial"),
            frequency=data.get("frequency"),
            start_day=data.get("start_day"),
        )
        pledge = RecurringPledge.objects.select_related("campaign", "charity_jar").get(pk=pledge.pk)
        open_inst = list(
            PledgeInstallment.objects.filter(
                pledge=pledge, status__in=["scheduled", "reminded"]
            ).order_by("due_date")
        )
        return Response(_serialize_pledge(pledge, open_inst))

    @extend_schema(
        operation_id="v1_me_pledges_destroy",
        summary="لغو دائمی تعهد کمک مستمر",
        request=PledgeCancelInputSerializer,
        responses={200: PledgeOutputSerializer},
        tags=["Donor - Recurring Pledges"],
    )
    def delete(self, request: Request, pledge_id: str) -> Response:
        user = authenticated_user(request)
        body = PledgeCancelInputSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        pledge = cancel_pledge(
            pledge_id=pledge_id,
            user=user,
            reason=body.validated_data.get("reason") or "user_request",
        )
        pledge = RecurringPledge.objects.select_related("campaign", "charity_jar").get(pk=pledge.pk)
        return Response(_serialize_pledge(pledge, []))


class MePledgeInstallmentListView(APIView):
    """تاریخچهٔ اقساط یک تعهد."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="v1_me_pledges_installments_list",
        summary="فهرست اقساط یک تعهد کمک مستمر",
        responses={200: PledgeInstallmentOutputSerializer(many=True)},
        tags=["Donor - Recurring Pledges"],
    )
    def get(self, request: Request, pledge_id: str) -> Response:
        user = authenticated_user(request)
        pledge = get_owned_pledge(pledge_id=pledge_id, user=user)
        installments = PledgeInstallment.objects.filter(pledge=pledge).order_by("sequence")
        return Response([_serialize_installment(i) for i in installments])


class MePledgePayView(APIView):
    """آغاز پرداخت یک قسط سررسیدشده — از طریق درگاه همیشگی."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="v1_me_pledges_pay",
        summary="پرداخت قسط تعهد مستمر (هدایت به درگاه)",
        request=PledgePayInputSerializer,
        responses={200: PledgePayOutputSerializer},
        tags=["Donor - Recurring Pledges"],
    )
    def post(self, request: Request, pledge_id: str) -> Response:
        user = authenticated_user(request)
        body = PledgePayInputSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        result = pay_installment(
            pledge_id=pledge_id,
            installment_id=body.validated_data["installment_id"],
            user=user,
            request=request,
        )
        result["amount_toman"] = rial_to_toman(int(result.get("amount_rial") or 0))
        return Response(result)


class MePledgeSkipInstallmentView(APIView):
    """رد یک قسط — «این ماه نمی‌پردازم» بدون از دست دادن تعهد."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="v1_me_pledges_skip_installment",
        summary="رد قسط جاری (تعهد باقی می‌ماند)",
        request=PledgeCancelInputSerializer,
        responses={200: PledgeInstallmentOutputSerializer},
        tags=["Donor - Recurring Pledges"],
    )
    def post(self, request: Request, pledge_id: str, installment_id: str) -> Response:
        user = authenticated_user(request)
        body = PledgeCancelInputSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        installment = skip_installment(
            pledge_id=pledge_id,
            installment_id=installment_id,
            user=user,
            reason=body.validated_data.get("reason") or "",
        )
        return Response(_serialize_installment(installment))


class AdminPledgeListView(APIView):
    """فهرست مدیریتی تعهدهای مستمر با پوشاندن شمارهٔ خیر."""

    permission_classes = [IsStaffRole]

    @extend_schema(
        operation_id="v1_admin_pledges_list",
        summary="فهرست تعهدهای کمک مستمر (مدیریت)",
        parameters=[
            OpenApiParameter(name="status", type=str, required=False),
            OpenApiParameter(name="frequency", type=str, required=False),
        ],
        responses={200: AdminPledgeSerializer(many=True)},
        tags=["Admin - Recurring Pledges"],
    )
    def get(self, request: Request) -> Response:
        qs = RecurringPledge.objects.select_related("user", "campaign", "charity_jar").order_by(
            "-created_at"
        )
        status_filter = (request.query_params.get("status") or "").strip()
        freq_filter = (request.query_params.get("frequency") or "").strip()
        if status_filter:
            qs = qs.filter(status=status_filter)
        if freq_filter:
            qs = qs.filter(frequency=freq_filter)
        rows = []
        for pledge in qs[:200]:
            rows.append(
                {
                    "id": str(pledge.pk),
                    "user_id": str(pledge.user_id),
                    "user_phone_masked": mask_phone(str(getattr(pledge.user, "phone", "") or "")),
                    "status": str(pledge.status),
                    "target_kind": str(pledge.target_kind),
                    "target_title": _pledge_target_title(pledge),
                    "amount_rial": int(pledge.amount_rial),
                    "amount_toman": rial_to_toman(int(pledge.amount_rial)),
                    "frequency": str(pledge.frequency),
                    "next_due_date": pledge.next_due_date,
                    "total_paid_rial": int(pledge.total_paid_rial),
                    "installments_paid": int(pledge.installments_paid),
                    "consecutive_failures": int(pledge.consecutive_failures),
                    "created_at": pledge.created_at,
                }
            )
        return Response(rows)


class AdminPledgeStatsView(APIView):
    """آمار تعهدهای مستمر: MRR، نرخ وصول، ریزش و علل شکست."""

    permission_classes = [IsStaffRole]

    @extend_schema(
        operation_id="v1_admin_pledges_stats",
        summary="آمار تجمیعی تعهدهای مستمر (MRR، نرخ وصول، ریزش)",
        parameters=[OpenApiParameter(name="window_days", type=int, required=False)],
        responses={200: PledgeStatsOutputSerializer},
        tags=["Admin - Recurring Pledges"],
    )
    def get(self, request: Request) -> Response:
        raw = request.query_params.get("window_days") or "90"
        try:
            window_days = max(1, min(int(raw), 3650))
        except (TypeError, ValueError):
            window_days = 90
        stats = build_pledge_stats(window_days=window_days)
        stats["monthly_recurring_revenue_toman"] = rial_to_toman(
            int(stats["monthly_recurring_revenue_rial"])
        )
        return Response(stats)


class AdminPledgeRunCycleView(APIView):
    """اجرای دستی چرخهٔ تعهد مستمر — همان کاری که کرون شبانه می‌کند."""

    permission_classes = [IsFinanceOrSuperAdmin]

    @extend_schema(
        operation_id="v1_admin_pledges_run_cycle",
        summary="اجرای دستی چرخهٔ تعهد مستمر (تولید قسط، یادآوری، انقضا)",
        request=None,
        responses={200: PledgeCycleOutputSerializer},
        tags=["Admin - Recurring Pledges"],
    )
    def post(self, request: Request) -> Response:
        del request  # چرخه به ورودی HTTP وابسته نیست؛ زمان از سیاست خوانده می‌شود
        resumed = resume_paused_pledges()
        materialize = materialize_due_installments()
        reminders = dispatch_pledge_reminders()
        expiry = expire_stale_installments()
        return Response(
            {
                "materialize": materialize.as_dict(),
                "reminders": reminders.as_dict(),
                "expiry": expiry.as_dict(),
                "resumed": resumed,
            }
        )
