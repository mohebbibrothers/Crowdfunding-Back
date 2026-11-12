"""سلکتورهای خوانشی فهرست حامیان عمومی، استعلام رسید، نیت‌نامه، شفافیت مرکل و گزارش‌های مدیریتی مشارکت."""

from __future__ import annotations

from typing import Any

from django.db.models import QuerySet

from apps.campaigns.selectors import get_public_campaign_by_slug_or_code
from apps.contributions.choices import ContributionStatus
from apps.contributions.models import (
    AmbassadorLink,
    CampaignTransparencySnapshot,
    Contribution,
    DedicationCard,
    DonationReceipt,
    ExternalContribution,
    Payment,
)
from apps.core.errors import FeatureDisabledError, NotFoundError
from apps.core.jalali import format_jalali_datetime
from apps.core.money import rial_to_toman
from apps.core.policy import is_feature_enabled


def list_public_campaign_supporters(*, identifier: str) -> list[dict[str, Any]]:
    """دیوار عمومی همراهان حرکت با احترام کامل به حریم خصوصی مشارکت ناشناس («خیر گمنام»)."""
    campaign = get_public_campaign_by_slug_or_code(identifier=identifier)
    paid_qs = (
        Contribution.objects.select_related("user", "dedication_card")
        .filter(campaign=campaign, status=ContributionStatus.PAID)
        .order_by("-paid_at")[:60]
    )
    items: list[dict[str, Any]] = []
    for c in paid_qs:
        supporter_name = (
            "خیر گمنام" if c.is_anonymous or not c.user.display_name else c.user.display_name
        )
        ded = getattr(c, "dedication_card", None)
        items.append(
            {
                "supporter_name": supporter_name,
                "shares_count": c.shares_count,
                "matched_shares_awarded": c.matched_shares_awarded,
                "public_note": c.public_note,
                "honoree_name": ded.honoree_name if (ded and ded.is_active) else None,
                "paid_at": c.paid_at,
                "paid_at_jalali": format_jalali_datetime(c.paid_at),
            }
        )
    return items


def get_public_receipt_verification(*, verification_code: str) -> dict[str, Any]:
    """استعلام اصالت عمومی رسید مشارکت از روی کد رهگیری بدون افشای شماره موبایل خیر."""
    receipt = (
        DonationReceipt.objects.select_related(
            "contribution",
            "contribution__user",
            "contribution__campaign",
            "contribution__charity_jar",
            "contribution__benefactor",
        )
        .filter(verification_code=verification_code)
        .first()
    )
    if receipt is None:
        raise NotFoundError("رسیدی با این کد رهگیری یافت نشد.")

    c = receipt.contribution
    donor_label = "خیر گمنام" if c.is_anonymous or not c.user.display_name else c.user.display_name
    target_title = (
        c.campaign.title
        if c.campaign is not None
        else (c.charity_jar.title if c.charity_jar is not None else c.benefactor.name)
    )
    return {
        "valid": c.status == ContributionStatus.PAID,
        "status": c.status,
        "receipt_number": receipt.receipt_number,
        "verification_code": receipt.verification_code,
        "signature_hmac": receipt.signature_hmac,
        "donor_display_name": donor_label,
        "benefactor_name": c.benefactor.name,
        "target_kind": c.target_kind,
        "target_title": target_title,
        "shares_count": c.shares_count,
        "matched_shares_awarded": c.matched_shares_awarded,
        "amount_rial": c.amount_rial,
        "amount_toman": rial_to_toman(c.amount_rial),
        "paid_at": c.paid_at,
        "paid_at_jalali": format_jalali_datetime(c.paid_at),
    }


def get_public_dedication_certificate(*, public_token: str) -> dict[str, Any]:
    """واکشی عمومی گواهی نیت‌نامه و کارت هدیهٔ معنوی (بدون نمایش هیچ رقم ریالی/تومانی!)."""
    if not is_feature_enabled("feature.spiritual_dedications"):
        raise FeatureDisabledError("نمایش گواهی نیت‌نامه در حال حاضر غیرفعال است.")

    card = (
        DedicationCard.objects.select_related(
            "contribution",
            "contribution__campaign",
            "contribution__charity_jar",
            "contribution__benefactor",
        )
        .filter(public_token=public_token, is_active=True)
        .first()
    )
    if card is None:
        raise NotFoundError("گواهی نیت‌نامه یافت نشد یا هنوز نهایی نشده است.")

    c = card.contribution
    target_title = (
        c.campaign.title
        if c.campaign is not None
        else (c.charity_jar.title if c.charity_jar is not None else c.benefactor.name)
    )
    target_slug = (
        c.campaign.slug
        if c.campaign is not None
        else (c.charity_jar.slug if c.charity_jar is not None else "")
    )
    return {
        "public_token": card.public_token,
        "dedication_type": card.dedication_type,
        "honoree_name": card.honoree_name,
        "dedicator_display_name": card.dedicator_display_name or "یک همراه نیک‌اندیش",
        "message": card.message,
        "benefactor_name": c.benefactor.name,
        "benefactor_logo_url": c.benefactor.logo_url,
        "target_kind": c.target_kind,
        "target_title": target_title,
        "target_slug": target_slug,
        "participation_badge": (
            f"مشارکت در {c.shares_count} سهم خیرخواهانه"
            if c.shares_count > 0
            else "مشارکت در قلک مهربانی"
        ),
        "signature_hmac": card.signature_hmac,
        "issued_at": c.paid_at or card.created_at,
        "issued_at_jalali": format_jalali_datetime(c.paid_at or card.created_at),
    }


def get_public_campaign_transparency(*, identifier: str) -> dict[str, Any]:
    """گزارش شفافیت عمومی حرکت شامل ریشهٔ درخت مرکل، تفکیک منابع آنلاین/مضاعف/آفلاین و تسویه‌های خیریه."""
    campaign = get_public_campaign_by_slug_or_code(identifier=identifier)
    latest_snap = (
        CampaignTransparencySnapshot.objects.filter(campaign=campaign)
        .order_by("-created_at")
        .first()
    )
    ext_items = ExternalContribution.objects.filter(campaign=campaign).order_by("-created_at")[:30]
    return {
        "campaign_id": str(campaign.id),
        "campaign_slug": campaign.slug,
        "campaign_title": campaign.title,
        "benefactor_name": campaign.benefactor.name,
        "shares_breakdown": {
            "total_shares": campaign.total_shares,
            "paid_online_shares": campaign.paid_shares,
            "matched_sponsor_shares": campaign.matched_shares,
            "external_offline_shares": campaign.external_shares,
            "reserved_shares": campaign.reserved_shares,
            "remaining_shares": campaign.remaining_shares,
        },
        "amounts_breakdown": {
            "target_amount_rial": campaign.target_amount_rial,
            "target_amount_toman": rial_to_toman(campaign.target_amount_rial),
            "collected_online_rial": campaign.collected_online_rial,
            "collected_online_toman": rial_to_toman(campaign.collected_online_rial),
            "matched_amount_rial": campaign.matched_amount_rial,
            "matched_amount_toman": rial_to_toman(campaign.matched_amount_rial),
            "external_amount_rial": campaign.external_amount_rial,
            "external_amount_toman": rial_to_toman(campaign.external_amount_rial),
            "disbursed_to_benefactor_rial": campaign.disbursed_amount_rial,
            "disbursed_to_benefactor_toman": rial_to_toman(campaign.disbursed_amount_rial),
        },
        "merkle_anchor": (
            {
                "merkle_root": latest_snap.merkle_root,
                "leaf_count": latest_snap.leaf_count,
                "signature_hmac": latest_snap.signature_hmac,
                "captured_at": latest_snap.created_at,
                "captured_at_jalali": format_jalali_datetime(latest_snap.created_at),
            }
            if latest_snap is not None
            else None
        ),
        "external_contributions": [
            {
                "donor_display_name": ext.donor_display_name,
                "shares_count": ext.shares_count,
                "amount_rial": ext.amount_rial,
                "amount_toman": rial_to_toman(ext.amount_rial),
                "reference_code": ext.reference_code,
                "recorded_at_jalali": format_jalali_datetime(ext.created_at),
            }
            for ext in ext_items
        ],
    }


def list_user_contributions(*, user_id: Any) -> QuerySet[Contribution]:
    """فهرست کامل مشارکت‌های کاربر."""
    return (
        Contribution.objects.select_related(
            "campaign", "charity_jar", "benefactor", "receipt", "dedication_card"
        )
        .filter(user_id=user_id)
        .order_by("-created_at", "-id")
    )


def list_user_ambassador_links(*, user_id: Any) -> QuerySet[AmbassadorLink]:
    """فهرست لینک‌های سفیر کاربر."""
    return (
        AmbassadorLink.objects.select_related("campaign", "charity_jar")
        .filter(user_id=user_id)
        .order_by("-created_at")
    )


def list_admin_payments(*, status_filter: str | None = None) -> QuerySet[Payment]:
    """فهرست مدیریتی پرداخت‌ها با شماره موبایل پوشانده."""
    qs = Payment.objects.select_related(
        "contribution",
        "contribution__user",
        "contribution__campaign",
        "contribution__charity_jar",
        "contribution__benefactor",
    ).order_by("-created_at")
    if status_filter:
        qs = qs.filter(status=status_filter)
    return qs
