"""ثبت مدل‌های مشارکت، پرداخت، نیت‌نامه، رسید و مرکل در ادمین جنگو."""

from __future__ import annotations

from django.contrib import admin

from apps.contributions.models import (
    AmbassadorLink,
    CampaignTransparencySnapshot,
    Contribution,
    DedicationCard,
    DonationReceipt,
    ExternalContribution,
    Payment,
    PaymentRefund,
)


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
    list_display = ("payment", "amount_rial", "refunded_by", "created_at")


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
