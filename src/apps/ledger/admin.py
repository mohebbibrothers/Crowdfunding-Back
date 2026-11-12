"""ثبت مدل‌های دفترکل و تسویه در ادمین جنگو (فقط خواندنی برای اسناد روزنامه و آرتیکل‌ها)."""

from __future__ import annotations

from typing import Any

from django.contrib import admin
from django.http import HttpRequest

from apps.ledger.models import (
    DisbursementRequest,
    FinancialControlSnapshot,
    JournalEntry,
    LedgerAccount,
    LedgerPosting,
    ReconciliationBatch,
)


@admin.register(LedgerAccount)
class LedgerAccountAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("code", "title", "account_type", "debit_total_rial", "credit_total_rial")
    readonly_fields = [f.name for f in LedgerAccount._meta.fields]


@admin.register(JournalEntry)
class JournalEntryAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("reference_key", "kind", "total_amount_rial", "created_at")
    readonly_fields = [f.name for f in JournalEntry._meta.fields]

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        del request, obj
        return False


@admin.register(LedgerPosting)
class LedgerPostingAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("journal_entry", "account", "debit_rial", "credit_rial")
    readonly_fields = [f.name for f in LedgerPosting._meta.fields]


@admin.register(DisbursementRequest)
class DisbursementRequestAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("benefactor", "amount_rial", "destination_iban", "status", "created_at")


@admin.register(ReconciliationBatch)
class ReconciliationBatchAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("gateway_name", "matched_count", "discrepancy_count", "created_at")


@admin.register(FinancialControlSnapshot)
class FinancialControlSnapshotAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = (
        "is_balanced",
        "total_debits_rial",
        "benefactor_payable_rial",
        "counter_drift_rial",
        "created_at",
    )
