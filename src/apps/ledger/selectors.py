"""سلکتورهای خوانشی دفترکل حسابداری دوطرفه، تسویه‌ها و مغایرت‌گیری."""

from __future__ import annotations

from django.db.models import QuerySet

from apps.ledger.models import (
    DisbursementRequest,
    JournalEntry,
    LedgerAccount,
    ReconciliationBatch,
)


def list_ledger_accounts() -> QuerySet[LedgerAccount]:
    """فهرست سرفصل‌های دفترکل به ترتیب کد."""
    return LedgerAccount.objects.order_by("code")


def list_journal_entries(*, kind: str | None = None) -> QuerySet[JournalEntry]:
    """فهرست اسناد روزنامهٔ ثبت‌شده در دفترکل."""
    qs = JournalEntry.objects.order_by("-created_at")
    if kind:
        qs = qs.filter(kind=kind)
    return qs


def list_disbursement_requests(
    *, status_filter: str | None = None
) -> QuerySet[DisbursementRequest]:
    """فهرست درخواست‌های تسویه با خیریه‌ها."""
    qs = DisbursementRequest.objects.select_related("benefactor").order_by("-created_at")
    if status_filter:
        qs = qs.filter(status=status_filter)
    return qs


def list_reconciliation_batches() -> QuerySet[ReconciliationBatch]:
    """فهرست دسته‌های مغایرت‌گیری درگاه پرداخت."""
    return ReconciliationBatch.objects.prefetch_related("items").order_by("-created_at")
