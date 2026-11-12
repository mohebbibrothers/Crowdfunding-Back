"""مسیرهای API مدیریتی دفترکل دوطرفه، تسویهٔ چهارچشمی با خیریه‌ها و مغایرت‌گیری درگاه."""

from __future__ import annotations

from django.urls import path

from apps.ledger.views import (
    AdminDisbursementListCreateView,
    AdminDisbursementReviewView,
    AdminFinancialControlSnapshotView,
    AdminJournalEntryListView,
    AdminLedgerAccountListView,
    AdminReconciliationListCreateView,
)

urlpatterns = [
    path(
        "admin/ledger/accounts",
        AdminLedgerAccountListView.as_view(),
        name="v1-admin-ledger-accounts",
    ),
    path(
        "admin/ledger/entries",
        AdminJournalEntryListView.as_view(),
        name="v1-admin-ledger-entries",
    ),
    path(
        "admin/ledger/control-snapshot",
        AdminFinancialControlSnapshotView.as_view(),
        name="v1-admin-ledger-control-snapshot",
    ),
    path(
        "admin/disbursements",
        AdminDisbursementListCreateView.as_view(),
        name="v1-admin-disbursements-list",
    ),
    path(
        "admin/disbursements/<str:disbursement_id>/review",
        AdminDisbursementReviewView.as_view(),
        name="v1-admin-disbursements-review",
    ),
    path(
        "admin/reconciliations",
        AdminReconciliationListCreateView.as_view(),
        name="v1-admin-reconciliations-list",
    ),
]
