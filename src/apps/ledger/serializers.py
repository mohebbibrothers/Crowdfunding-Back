"""سریالایزرهای دفترکل حسابداری دوطرفه، درخواست‌های تسویه و مغایرت‌گیری."""

from __future__ import annotations

from typing import Any

from rest_framework import serializers

from apps.core.jalali import format_jalali_datetime
from apps.core.money import rial_to_toman
from apps.ledger.choices import DisbursementStatus, ReconciliationItemStatus
from apps.ledger.models import (
    DisbursementRequest,
    JournalEntry,
    LedgerAccount,
)


class LedgerAccountSerializer(serializers.Serializer[Any]):
    """نمای سرفصل حساب در دفترکل."""

    id = serializers.UUIDField()
    code = serializers.CharField()
    title = serializers.CharField()
    account_type = serializers.CharField()
    benefactor_id = serializers.UUIDField(allow_null=True)
    debit_total_rial = serializers.IntegerField()
    credit_total_rial = serializers.IntegerField()
    balance_rial = serializers.IntegerField()
    balance_toman = serializers.SerializerMethodField()

    def get_balance_toman(self, obj: LedgerAccount) -> int:
        return rial_to_toman(obj.balance_rial)


class JournalEntrySerializer(serializers.Serializer[Any]):
    """نمای سند روزنامه."""

    id = serializers.UUIDField()
    reference_key = serializers.CharField()
    kind = serializers.CharField()
    description = serializers.CharField()
    total_amount_rial = serializers.IntegerField()
    total_amount_toman = serializers.SerializerMethodField()
    campaign_id = serializers.UUIDField(allow_null=True)
    benefactor_id = serializers.UUIDField(allow_null=True)
    created_at = serializers.DateTimeField()
    created_at_jalali = serializers.SerializerMethodField()

    def get_total_amount_toman(self, obj: JournalEntry) -> int:
        return rial_to_toman(obj.total_amount_rial)

    def get_created_at_jalali(self, obj: JournalEntry) -> str | None:
        return format_jalali_datetime(obj.created_at)


class DisbursementRequestSerializer(serializers.Serializer[Any]):
    """نمای خروجی درخواست تسویه با خیریه."""

    id = serializers.UUIDField()
    benefactor_id = serializers.UUIDField()
    benefactor_name = serializers.CharField(source="benefactor.name")
    campaign_id = serializers.UUIDField(allow_null=True)
    amount_rial = serializers.IntegerField()
    amount_toman = serializers.SerializerMethodField()
    destination_iban = serializers.CharField()
    status = serializers.ChoiceField(choices=DisbursementStatus.choices)
    requested_by_id = serializers.UUIDField()
    request_note = serializers.CharField()
    reviewed_by_id = serializers.UUIDField(allow_null=True)
    reviewed_at = serializers.DateTimeField(allow_null=True)
    review_reason = serializers.CharField()
    bank_reference_number = serializers.CharField()
    journal_entry_id = serializers.UUIDField(allow_null=True)
    created_at = serializers.DateTimeField()
    created_at_jalali = serializers.SerializerMethodField()

    def get_amount_toman(self, obj: DisbursementRequest) -> int:
        return rial_to_toman(obj.amount_rial)

    def get_created_at_jalali(self, obj: DisbursementRequest) -> str | None:
        return format_jalali_datetime(obj.created_at)


class DisbursementCreateInputSerializer(serializers.Serializer[Any]):
    """ورودی ثبت درخواست تسویه جدید (Maker)."""

    benefactor_id = serializers.UUIDField()
    campaign_id = serializers.UUIDField(required=False, allow_null=True)
    amount_rial = serializers.IntegerField(min_value=10_000)
    request_note = serializers.CharField(
        max_length=400, required=False, allow_blank=True, default=""
    )


class DisbursementReviewInputSerializer(serializers.Serializer[Any]):
    """ورودی تأیید یا رد چهارچشمی درخواست تسویه (Checker + Step-Up MFA)."""

    approve = serializers.BooleanField()
    reason = serializers.CharField(min_length=3, max_length=400)
    bank_reference_number = serializers.CharField(
        max_length=80, required=False, allow_blank=True, default=""
    )


class ReconciliationRowInputSerializer(serializers.Serializer[Any]):
    """یک ردیف از فایل تسویه درگاه پرداخت."""

    authority = serializers.CharField(max_length=80)
    ref_id = serializers.CharField(max_length=80, required=False, allow_blank=True, default="")
    amount_rial = serializers.IntegerField(min_value=0)


class ReconciliationRunInputSerializer(serializers.Serializer[Any]):
    """ورودی اجرای مغایرت‌گیری درگاه پرداخت."""

    gateway_name = serializers.CharField(max_length=32, default="zarinpal")
    period_start = serializers.DateTimeField()
    period_end = serializers.DateTimeField()
    rows = ReconciliationRowInputSerializer(many=True)


class ReconciliationItemSerializer(serializers.Serializer[Any]):
    """نمای ردیف نتیجهٔ مغایرت‌گیری."""

    authority = serializers.CharField()
    ref_id = serializers.CharField()
    gateway_amount_rial = serializers.IntegerField()
    internal_amount_rial = serializers.IntegerField()
    status = serializers.ChoiceField(choices=ReconciliationItemStatus.choices)
    note = serializers.CharField()


class ReconciliationBatchSerializer(serializers.Serializer[Any]):
    """نمای خروجی دستهٔ مغایرت‌گیری به همراه مغایرت‌ها."""

    id = serializers.UUIDField()
    gateway_name = serializers.CharField()
    period_start = serializers.DateTimeField()
    period_end = serializers.DateTimeField()
    gateway_reported_count = serializers.IntegerField()
    matched_count = serializers.IntegerField()
    discrepancy_count = serializers.IntegerField()
    gateway_total_rial = serializers.IntegerField()
    internal_total_rial = serializers.IntegerField()
    items = ReconciliationItemSerializer(many=True)
    created_at = serializers.DateTimeField()


class FinancialControlSnapshotSerializer(serializers.Serializer[Any]):
    """نمای اسنپ‌شات تراز آزمایشی و کنترل یکپارچگی مالی."""

    id = serializers.UUIDField()
    total_debits_rial = serializers.IntegerField()
    total_credits_rial = serializers.IntegerField()
    gateway_receivable_rial = serializers.IntegerField()
    benefactor_payable_rial = serializers.IntegerField()
    external_custody_rial = serializers.IntegerField()
    is_balanced = serializers.BooleanField()
    counter_drift_rial = serializers.IntegerField()
    created_at = serializers.DateTimeField()
