"""مسیرهای API مشارکت‌ها، خرید سریع ۳۰ ثانیه‌ای، درگاه پرداخت، شفافیت مرکل و داشبورد خیر."""

from __future__ import annotations

from django.urls import path

from apps.contributions.views import (
    AdminExternalContributionCreateView,
    AdminPaymentListView,
    AdminPaymentRefundView,
    ContributionInitiateView,
    ExpressCheckoutConfirmView,
    ExpressCheckoutStartView,
    MeAmbassadorLinkListCreateView,
    MeContributionListView,
    MeContributionMerkleProofView,
    MeDonorDashboardView,
    PaymentCallbackVerifyView,
    PublicCampaignSupportersView,
    PublicCampaignTransparencyView,
    PublicDedicationCertificateView,
    PublicMerkleVerifyView,
    PublicReceiptVerifyView,
    SandboxPaymentDetailView,
)

urlpatterns = [
    # خرید سهم / قلک و مشارکت سریع ۳۰ ثانیه‌ای
    path(
        "contributions/checkout",
        ContributionInitiateView.as_view(),
        name="v1-contributions-checkout",
    ),
    path(
        "contributions/express/start",
        ExpressCheckoutStartView.as_view(),
        name="v1-contributions-express-start",
    ),
    path(
        "contributions/express/confirm",
        ExpressCheckoutConfirmView.as_view(),
        name="v1-contributions-express-confirm",
    ),
    # بازگشت درگاه، Sandbox، استعلام رسید، نیت‌نامه و شفافیت مرکل
    path(
        "payments/callback",
        PaymentCallbackVerifyView.as_view(),
        name="v1-payments-callback",
    ),
    path(
        "payments/sandbox/<str:authority>",
        SandboxPaymentDetailView.as_view(),
        name="v1-payments-sandbox-detail",
    ),
    path(
        "campaigns/<str:identifier>/supporters",
        PublicCampaignSupportersView.as_view(),
        name="v1-campaigns-supporters",
    ),
    path(
        "campaigns/<str:identifier>/transparency",
        PublicCampaignTransparencyView.as_view(),
        name="v1-campaigns-transparency",
    ),
    path(
        "transparency/verify-proof",
        PublicMerkleVerifyView.as_view(),
        name="v1-transparency-verify-proof",
    ),
    path(
        "receipts/verify/<str:verification_code>",
        PublicReceiptVerifyView.as_view(),
        name="v1-receipts-verify",
    ),
    path(
        "dedications/<str:public_token>",
        PublicDedicationCertificateView.as_view(),
        name="v1-dedications-detail",
    ),
    # داشبورد انگیزشی خیر، تاریخچه و لینک‌های سفیر اجتماعی
    path("me/dashboard", MeDonorDashboardView.as_view(), name="v1-me-dashboard"),
    path(
        "me/contributions",
        MeContributionListView.as_view(),
        name="v1-me-contributions",
    ),
    path(
        "me/contributions/<str:contribution_id>/merkle-proof",
        MeContributionMerkleProofView.as_view(),
        name="v1-me-contributions-merkle-proof",
    ),
    path(
        "me/ambassador-links",
        MeAmbassadorLinkListCreateView.as_view(),
        name="v1-me-ambassador-links",
    ),
    # مسیرهای مدیریتی پرداخت‌ها، استرداد و مشارکت خارجی
    path("admin/payments", AdminPaymentListView.as_view(), name="v1-admin-payments-list"),
    path(
        "admin/payments/<str:payment_id>/refund",
        AdminPaymentRefundView.as_view(),
        name="v1-admin-payments-refund",
    ),
    path(
        "admin/campaigns/<str:campaign_id>/external-contributions",
        AdminExternalContributionCreateView.as_view(),
        name="v1-admin-campaigns-external-contributions",
    ),
]
