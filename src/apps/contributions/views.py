"""نماهای HTTP مشارکت‌ها، خرید سریع ۳۰ ثانیه‌ای، بازگشت درگاه، رسید، نیت‌نامه، مرکل و داشبورد خیر."""

from __future__ import annotations

from typing import Any

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.contributions.choices import PaymentStatus
from apps.contributions.dashboard import build_donor_dashboard
from apps.contributions.merkle import verify_inclusion_proof
from apps.contributions.models import DedicationCard, Payment
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
    AmbassadorCreateInputSerializer,
    AmbassadorLinkSerializer,
    CheckoutInitiateInputSerializer,
    CheckoutInitiateResponseSerializer,
    ContributionUserSerializer,
    ExpressConfirmInputSerializer,
    ExpressStartInputSerializer,
    ExpressStartResponseSerializer,
    ExternalContributionSerializer,
    ExternalContributionWriteSerializer,
    MerkleProofVerifyInputSerializer,
    PaymentCallbackVerifyInputSerializer,
    PaymentRefundInputSerializer,
    PaymentVerifyResponseSerializer,
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
from apps.core.errors import NotFoundError
from apps.core.idempotency import IDEMPOTENCY_HEADER, execute_idempotent
from apps.core.money import rial_to_toman
from apps.core.pagination import UserListCursorPagination
from apps.identity.permissions import (
    HasFreshMfa,
    IsFinanceOrSuperAdmin,
    IsStaffRole,
    authenticated_user,
)
from apps.identity.throttles import OtpRequestThrottle, OtpVerifyThrottle


class ContributionInitiateView(APIView):
    """آغاز مشارکت آنلاین (رزرو ۱۵ دقیقه‌ای سهم حرکت یا واریز آزاد قلک عام) با پشتیبانی Idempotency-Key."""

    permission_classes = [IsAuthenticated]

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
        responses={
            200: {
                "type": "object",
                "properties": {
                    "authority": {"type": "string"},
                    "amount_rial": {"type": "integer"},
                    "amount_toman": {"type": "integer"},
                    "status": {"type": "string"},
                },
            }
        },
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
        responses={200: {"type": "array", "items": {"type": "object"}}},
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
        responses={200: {"type": "object"}},
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
        responses={
            200: {
                "type": "object",
                "properties": {"valid": {"type": "boolean"}},
                "required": ["valid"],
            }
        },
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
        responses={200: {"type": "object"}},
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
        responses={200: {"type": "object"}},
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
        responses={200: {"type": "object"}},
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
        responses={200: ContributionUserSerializer(many=True)},
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
        responses={200: {"type": "object"}},
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
        responses={
            200: {
                "type": "object",
                "properties": {
                    "refund_id": {"type": "string"},
                    "amount_rial": {"type": "integer"},
                    "status": {"type": "string"},
                },
            }
        },
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
