"""ثبت مدل‌های مشارکت، پرداخت، نیت‌نامه، رسید و مرکل در ادمین جنگو."""

from __future__ import annotations

from django.contrib import admin, messages
from django.db.models import QuerySet
from django.http import HttpRequest
from django.utils.html import format_html

from apps.contributions.models import (
    AmbassadorLink,
    CampaignTransparencySnapshot,
    Contribution,
    DedicationCard,
    DonationReceipt,
    ExternalContribution,
    LateCaptureRecovery,
    Payment,
    PaymentRefund,
)
from apps.contributions.services import settle_refund_obligation


@admin.register(Contribution)
class ContributionAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = (
        "id",
        "user",
        "target_kind",
        "shares_count",
        "amount_rial",
        "status",
        "created_at",
    )
    list_filter = ("target_kind", "status", "is_anonymous")


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("authority", "gateway_name", "amount_rial", "status", "ref_id", "verified_at")
    list_filter = ("gateway_name", "status")


@admin.register(PaymentRefund)
class PaymentRefundAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """پنل بازپرداخت‌ها با اکشن «تسویه» برای بستن رسمی تعهد بدهی."""

    list_display = (
        "payment",
        "amount_rial",
        "outcome",
        "attempt_count",
        "gateway_reference",
        "created_at",
    )
    list_filter = ("outcome", "attempt_count")
    search_fields = ("payment__authority", "gateway_reference", "bank_reference")
    readonly_fields = ("gateway_raw_code", "attempt_count", "last_attempt_at", "automation_note")
    actions = ("settle_selected_refunds",)

    @admin.action(description="✅ تسویه بازپرداخت‌های انتخاب‌شده و بستن تعهد بدهی")
    def settle_selected_refunds(
        self, request: HttpRequest, queryset: QuerySet[PaymentRefund]
    ) -> None:
        """نهایی‌سازی بازپرداخت‌هایی که بانک/درگاه پرداخت را تأیید کرده است."""
        settled = 0
        actor = request.user if request.user.is_authenticated else None
        for refund in queryset.select_related("payment"):
            settle_refund_obligation(
                refund_id=refund.pk,
                actor=actor,  # type: ignore[arg-type]
                bank_reference=refund.gateway_reference or refund.bank_reference,
                note="تسویه از پنل مدیریت",
            )
            settled += 1
        self.message_user(
            request, f"{settled} بازپرداخت تسویه و تعهد بدهی آن بسته شد.", messages.SUCCESS
        )


@admin.register(LateCaptureRecovery)
class LateCaptureRecoveryAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """پنل «سلامت مالی حلقهٔ وجه» — هر پرداخت رهاشده و سرنوشت آن."""

    list_display = (
        "payment",
        "outcome",
        "decision_reason",
        "capacity_at_decision",
        "recovered_shares",
        "attempt_count",
        "resolved_at",
        "created_at",
    )
    list_filter = ("outcome", "decision_reason")
    search_fields = ("payment__authority", "gateway_ref_id", "decision_reason")
    readonly_fields = ("gateway_verdict_raw", "last_error", "status_badge")
    date_hierarchy = "created_at"

    @admin.display(description="وضعیت")
    def status_badge(self, obj: LateCaptureRecovery) -> str:
        """نشان رنگی وضعیت داوری برای خوانایی سریع در پنل عملیات."""
        palette = {
            "recovered": ("#0f766e", "#ccfbf1"),
            "refund_pending": ("#b45309", "#fef3c7"),
            "not_captured": ("#334155", "#f1f5f9"),
            "manual_review": ("#b91c1c", "#fee2e2"),
        }
        fg, bg = palette.get(str(obj.outcome), ("#334155", "#f1f5f9"))
        return format_html(
            '<span style="background:{};color:{};padding:2px 8px;border-radius:999px;'
            'font-weight:600">{}</span>',
            bg,
            fg,
            obj.get_outcome_display(),
        )


@admin.register(ExternalContribution)
class ExternalContributionAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = (
        "campaign",
        "shares_count",
        "amount_rial",
        "donor_display_name",
        "reference_code",
    )


@admin.register(DedicationCard)
class DedicationCardAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("public_token", "dedication_type", "honoree_name", "is_active", "created_at")


@admin.register(AmbassadorLink)
class AmbassadorLinkAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = (
        "code",
        "user",
        "click_count",
        "referred_donors_count",
        "attributed_amount_rial",
    )


@admin.register(DonationReceipt)
class DonationReceiptAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("receipt_number", "verification_code", "contribution", "created_at")


@admin.register(CampaignTransparencySnapshot)
class CampaignTransparencySnapshotAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("campaign", "leaf_count", "merkle_root", "created_at")
