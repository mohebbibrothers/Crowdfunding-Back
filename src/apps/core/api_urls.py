"""مسیرهای API هستهٔ مشترک زیر ``/api/v1/``."""

from __future__ import annotations

from django.urls import path

from apps.core.views import (
    AdminFinancialHealthView,
    AdminLateCaptureReconcileView,
    AdminMoneyTruthPanelView,
    AdminPolicyListView,
    AdminPolicyUpdateView,
    AdminRefundDispatchView,
    AdminSettlementDetailView,
    AdminSettlementListCreateView,
    AdminSettlementReconcileView,
    AdminSettlementRemediateView,
    AdminSettlementRowsView,
    CsrfBootstrapView,
    HealthDetailedView,
    HealthLiveView,
    HealthReadyView,
    PlatformMetaView,
)

urlpatterns = [
    path("meta", PlatformMetaView.as_view(), name="v1-meta"),
    path("auth/csrf", CsrfBootstrapView.as_view(), name="v1-csrf"),
    path("health/live", HealthLiveView.as_view(), name="v1-health-live"),
    path("health/ready", HealthReadyView.as_view(), name="v1-health-ready"),
    path("health/detailed", HealthDetailedView.as_view(), name="v1-health-detailed"),
    path("admin/policies", AdminPolicyListView.as_view(), name="v1-admin-policies-list"),
    path(
        "admin/policies/<str:policy_key>",
        AdminPolicyUpdateView.as_view(),
        name="v1-admin-policies-update",
    ),
    path(
        "admin/financial-health",
        AdminFinancialHealthView.as_view(),
        name="v1-admin-financial-health",
    ),
    path(
        "admin/late-captures/reconcile",
        AdminLateCaptureReconcileView.as_view(),
        name="v1-admin-late-captures-reconcile",
    ),
    path(
        "admin/refunds/dispatch",
        AdminRefundDispatchView.as_view(),
        name="v1-admin-refunds-dispatch",
    ),
    # ── لایهٔ حقیقت وجه: صورت‌حساب تسویهٔ درگاه ────────────────────────────────
    path(
        "admin/settlements",
        AdminSettlementListCreateView.as_view(),
        name="v1-admin-settlements",
    ),
    path(
        "admin/settlements/<uuid:settlement_id>",
        AdminSettlementDetailView.as_view(),
        name="v1-admin-settlements-detail",
    ),
    path(
        "admin/settlements/<uuid:settlement_id>/rows",
        AdminSettlementRowsView.as_view(),
        name="v1-admin-settlements-rows",
    ),
    path(
        "admin/settlements/<uuid:settlement_id>/reconcile",
        AdminSettlementReconcileView.as_view(),
        name="v1-admin-settlements-reconcile",
    ),
    path(
        "admin/settlements/<uuid:settlement_id>/remediate",
        AdminSettlementRemediateView.as_view(),
        name="v1-admin-settlements-remediate",
    ),
    path(
        "admin/money-truth",
        AdminMoneyTruthPanelView.as_view(),
        name="v1-admin-money-truth",
    ),
]
