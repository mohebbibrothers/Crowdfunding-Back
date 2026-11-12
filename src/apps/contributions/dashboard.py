"""سازندهٔ داشبورد جامع و انگیزه‌بخش خیر (Donor Motivation & Impact Dashboard)."""

from __future__ import annotations

from typing import Any

from django.db.models import Count, Q, Sum
from django.utils import timezone

from apps.campaigns.choices import CampaignStatus
from apps.campaigns.models import Campaign, CampaignImpactUpdate
from apps.campaigns.selectors import list_public_campaigns
from apps.campaigns.serializers import CampaignImpactUpdateSerializer, CampaignSummarySerializer
from apps.contributions.choices import ContributionStatus, ContributionTargetKind
from apps.contributions.models import (
    AmbassadorLink,
    Contribution,
    DedicationCard,
)
from apps.core.jalali import format_jalali_datetime
from apps.core.money import rial_to_toman
from apps.identity.models import User
from apps.notifications.selectors import count_unread_notifications


def _compute_monthly_streak(paid_dates: list[Any]) -> int:
    """محاسبهٔ تعداد ماه‌های پیاپی مشارکت خیر تا ماه جاری/گذشته."""
    if not paid_dates:
        return 0
    ym_set = {(dt.year, dt.month) for dt in paid_dates if dt is not None}
    if not ym_set:
        return 0

    now = timezone.now()
    cur_y, cur_m = now.year, now.month
    if (cur_y, cur_m) not in ym_set:
        # بررسی ماه قبل (تا رشتهٔ ماهانه پیش از پایان ماه جاری شکسته تلقی نشود)
        prev_y, prev_m = (cur_y - 1, 12) if cur_m == 1 else (cur_y, cur_m - 1)
        if (prev_y, prev_m) not in ym_set:
            return 0
        cur_y, cur_m = prev_y, prev_m

    streak = 0
    while (cur_y, cur_m) in ym_set:
        streak += 1
        cur_y, cur_m = (cur_y - 1, 12) if cur_m == 1 else (cur_y, cur_m - 1)
    return streak


def _build_donor_badges(
    *,
    paid_count: int,
    shares_bought: int,
    completed_backed_count: int,
    jar_count: int,
    referred_donors: int,
    dedications_count: int,
) -> list[dict[str, Any]]:
    """محاسبهٔ نشان‌های افتخار و گام‌های انگیزشی خیر بر اساس کارنامهٔ واقعی."""
    return [
        {
            "code": "first_step",
            "title": "همقدم نخستین",
            "description": "ثبت نخستین مشارکت موفق در مسیر خیر",
            "earned": paid_count >= 1,
            "current": min(paid_count, 1),
            "target": 1,
        },
        {
            "code": "share_builder",
            "title": "بانی ده سهم مهربانی",
            "description": "تأمین دست‌کم ۱۰ سهم در حرکت‌های خیرخواهانه",
            "earned": shares_bought >= 10,
            "current": min(shares_bought, 10),
            "target": 10,
        },
        {
            "code": "completion_partner",
            "title": "شریک تکمیل حرکت",
            "description": "همراهی در حرکتی که ۱۰۰٪ سهم‌های آن تأمین شد",
            "earned": completed_backed_count >= 1,
            "current": min(completed_backed_count, 1),
            "target": 1,
        },
        {
            "code": "jar_supporter",
            "title": "یاور قلک‌های خیریه",
            "description": "مشارکت آزاد در قلک عام خیریه‌ها",
            "earned": jar_count >= 1,
            "current": min(jar_count, 1),
            "target": 1,
        },
        {
            "code": "social_ambassador",
            "title": "سفیر نیکوکاری",
            "description": "جذب دست‌کم یک مشارکت موفق از طریق لینک دعوت اختصاصی",
            "earned": referred_donors >= 1,
            "current": min(referred_donors, 1),
            "target": 1,
        },
        {
            "code": "memorial_giver",
            "title": "احیاگر یاد نیکان",
            "description": "ثبت نیت‌نامه یا کارت هدیهٔ معنوی ماندگار",
            "earned": dedications_count >= 1,
            "current": min(dedications_count, 1),
            "target": 1,
        },
    ]


def build_donor_dashboard(*, user: User) -> dict[str, Any]:
    """تجمیع کامل کارنامهٔ معنوی و مالی خیر در یک پاسخ یکپارچه برای داشبورد."""
    paid_qs = Contribution.objects.filter(user=user, status=ContributionStatus.PAID)
    agg = paid_qs.aggregate(
        paid_count=Count("id"),
        shares_bought=Sum("shares_count"),
        matched_shares=Sum("matched_shares_awarded"),
        total_rial=Sum("amount_rial"),
        matched_rial=Sum("matched_amount_rial"),
        jar_count=Count("id", filter=Q(target_kind=ContributionTargetKind.CHARITY_JAR)),
        jar_rial=Sum(
            "amount_rial",
            filter=Q(target_kind=ContributionTargetKind.CHARITY_JAR),
        ),
        benefactors_count=Count("benefactor_id", distinct=True),
    )

    paid_count = int(agg["paid_count"] or 0)
    shares_bought = int(agg["shares_bought"] or 0)
    matched_shares = int(agg["matched_shares"] or 0)
    total_rial = int(agg["total_rial"] or 0)
    matched_rial = int(agg["matched_rial"] or 0)
    jar_count = int(agg["jar_count"] or 0)
    jar_rial = int(agg["jar_rial"] or 0)
    benefactors_count = int(agg["benefactors_count"] or 0)

    backed_campaign_ids = list(
        paid_qs.filter(campaign_id__isnull=False).values_list("campaign_id", flat=True).distinct()
    )
    completed_backed_count = (
        Campaign.objects.filter(
            id__in=backed_campaign_ids,
            status__in=[
                CampaignStatus.COMPLETED,
                CampaignStatus.EXECUTING,
                CampaignStatus.FULFILLED,
            ],
        ).count()
        if backed_campaign_ids
        else 0
    )

    dedications_count = DedicationCard.objects.filter(
        contribution__user=user, is_active=True
    ).count()

    # آمار اثرگذاری سفیر اجتماعی
    amb_qs = AmbassadorLink.objects.select_related("campaign", "charity_jar").filter(user=user)
    amb_agg = amb_qs.aggregate(
        links_count=Count("id"),
        clicks=Sum("click_count"),
        donors=Sum("referred_donors_count"),
        shares=Sum("attributed_shares"),
        amount_rial=Sum("attributed_amount_rial"),
    )
    referred_donors = int(amb_agg["donors"] or 0)
    amb_amount_rial = int(amb_agg["amount_rial"] or 0)

    paid_dates = list(paid_qs.values_list("paid_at", flat=True))
    monthly_streak = _compute_monthly_streak(paid_dates)
    badges = _build_donor_badges(
        paid_count=paid_count,
        shares_bought=shares_bought,
        completed_backed_count=completed_backed_count,
        jar_count=jar_count,
        referred_donors=referred_donors,
        dedications_count=dedications_count,
    )

    # رزروهای فعال ۱۵ دقیقه‌ای برای ادامهٔ پرداخت با یک کلیک
    now = timezone.now()
    active_holds_qs = (
        Contribution.objects.select_related("campaign", "charity_jar")
        .prefetch_related("payments")
        .filter(user=user, status=ContributionStatus.RESERVED, hold_expires_at__gt=now)
        .order_by("hold_expires_at")
    )
    active_reservations = []
    for hold in active_holds_qs:
        latest_payment = hold.payments.first()
        secs_left = max(0, int((hold.hold_expires_at - now).total_seconds()))
        active_reservations.append(
            {
                "contribution_id": str(hold.id),
                "target_kind": hold.target_kind,
                "title": hold.campaign.title
                if hold.campaign
                else (hold.charity_jar.title if hold.charity_jar else ""),
                "shares_count": hold.shares_count,
                "amount_rial": hold.amount_rial,
                "amount_toman": rial_to_toman(hold.amount_rial),
                "seconds_remaining": secs_left,
                "gateway_redirect_url": latest_payment.redirect_url if latest_payment else "",
                "authority": latest_payment.authority if latest_payment else "",
            }
        )

    # فهرست حرکت‌هایی که خیر در آن‌ها سهام‌دار است همراه با سهم خیر و پیشرفت فعلی حرکت
    per_campaign_shares = {
        row["campaign_id"]: {
            "my_shares": int(row["my_shares"] or 0),
            "my_matched_shares": int(row["my_matched"] or 0),
            "my_amount_rial": int(row["my_rial"] or 0),
        }
        for row in paid_qs.filter(campaign_id__isnull=False)
        .values("campaign_id")
        .annotate(
            my_shares=Sum("shares_count"),
            my_matched=Sum("matched_shares_awarded"),
            my_rial=Sum("amount_rial"),
        )
    }
    backed_campaigns = list(
        Campaign.objects.select_related("benefactor", "category")
        .filter(id__in=backed_campaign_ids)
        .order_by("-updated_at")[:12]
    )
    backed_campaigns_cards = []
    for camp in backed_campaigns:
        mine = per_campaign_shares.get(
            camp.id, {"my_shares": 0, "my_matched_shares": 0, "my_amount_rial": 0}
        )
        backed_campaigns_cards.append(
            {
                "campaign_id": str(camp.id),
                "title": camp.title,
                "slug": camp.slug,
                "benefactor_name": camp.benefactor.name,
                "status": camp.status,
                "progress_percent": camp.progress_percent,
                "physical_progress_percent": camp.physical_progress_percent,
                "my_shares": mine["my_shares"],
                "my_matched_shares": mine["my_matched_shares"],
                "my_amount_rial": mine["my_amount_rial"],
                "my_amount_toman": rial_to_toman(mine["my_amount_rial"]),
            }
        )

    # تایم‌لاین گزارش‌های پیشرفت میدانی حرکت‌های همراهی‌شده توسط خیر
    impact_updates_qs = (
        CampaignImpactUpdate.objects.select_related("campaign")
        .filter(campaign_id__in=backed_campaign_ids, is_published=True)
        .order_by("-created_at")[:10]
        if backed_campaign_ids
        else CampaignImpactUpdate.objects.none()
    )
    impact_timeline = [
        {
            "campaign_title": upd.campaign.title,
            "campaign_slug": upd.campaign.slug,
            **dict(CampaignImpactUpdateSerializer(upd).data),
        }
        for upd in impact_updates_qs
    ]

    # آخرین مشارکت‌های خیر (حرکت + قلک عام + رسید + نیت‌نامه)
    recent_contribs_qs = paid_qs.select_related(
        "campaign", "charity_jar", "benefactor", "receipt", "dedication_card"
    ).order_by("-paid_at")[:10]
    recent_contributions = []
    for c in recent_contribs_qs:
        receipt_obj = getattr(c, "receipt", None)
        ded_obj = getattr(c, "dedication_card", None)
        recent_contributions.append(
            {
                "id": str(c.id),
                "target_kind": c.target_kind,
                "target_title": c.campaign.title
                if c.campaign
                else (c.charity_jar.title if c.charity_jar else ""),
                "target_slug": c.campaign.slug
                if c.campaign
                else (c.charity_jar.slug if c.charity_jar else ""),
                "benefactor_name": c.benefactor.name,
                "shares_count": c.shares_count,
                "matched_shares_awarded": c.matched_shares_awarded,
                "amount_rial": c.amount_rial,
                "amount_toman": rial_to_toman(c.amount_rial),
                "is_anonymous": c.is_anonymous,
                "paid_at": c.paid_at,
                "paid_at_jalali": format_jalali_datetime(c.paid_at),
                "receipt_number": receipt_obj.receipt_number if receipt_obj else None,
                "verification_code": receipt_obj.verification_code if receipt_obj else None,
                "dedication_token": ded_obj.public_token
                if (ded_obj and ded_obj.is_active)
                else None,
            }
        )

    # پیشنهاد هوشمند حرکت‌های بعدی بر اساس الگوریتم توزیع منصفانه
    rec_qs = list_public_campaigns(status_filter=CampaignStatus.ACTIVE, ordering="fair").exclude(
        id__in=backed_campaign_ids
    )[:4]
    recommended = list(CampaignSummarySerializer(rec_qs, many=True).data)

    return {
        "user": {
            "id": str(user.id),
            "display_name": user.display_name or "نیکوکار گرامی",
            "phone": user.phone,
        },
        "summary": {
            "total_contributions_count": paid_count,
            "campaign_shares_bought": shares_bought,
            "matched_shares_unlocked": matched_shares,
            "total_effective_shares": shares_bought + matched_shares,
            "charity_jar_donations_count": jar_count,
            "charity_jar_total_rial": jar_rial,
            "charity_jar_total_toman": rial_to_toman(jar_rial),
            "total_contributed_rial": total_rial,
            "total_contributed_toman": rial_to_toman(total_rial),
            "total_impact_with_matching_rial": total_rial + matched_rial,
            "total_impact_with_matching_toman": rial_to_toman(total_rial + matched_rial),
            "backed_campaigns_count": len(backed_campaign_ids),
            "completed_backed_campaigns_count": completed_backed_count,
            "benefactors_supported_count": benefactors_count,
            "active_dedications_count": dedications_count,
            "unread_notifications_count": count_unread_notifications(user_id=user.id),
        },
        "ambassador_impact": {
            "links_count": int(amb_agg["links_count"] or 0),
            "total_clicks": int(amb_agg["clicks"] or 0),
            "referred_donors_count": referred_donors,
            "attributed_shares": int(amb_agg["shares"] or 0),
            "attributed_amount_rial": amb_amount_rial,
            "attributed_amount_toman": rial_to_toman(amb_amount_rial),
            "links": [
                {
                    "code": link.code,
                    "target_title": link.campaign.title
                    if link.campaign
                    else (link.charity_jar.title if link.charity_jar else ""),
                    "click_count": link.click_count,
                    "referred_donors_count": link.referred_donors_count,
                    "attributed_shares": link.attributed_shares,
                    "attributed_amount_rial": link.attributed_amount_rial,
                    "attributed_amount_toman": rial_to_toman(link.attributed_amount_rial),
                }
                for link in amb_qs[:10]
            ],
        },
        "motivation": {
            "active_months_streak": monthly_streak,
            "earned_badges_count": sum(1 for b in badges if b["earned"]),
            "total_badges_count": len(badges),
            "badges": badges,
        },
        "active_reservations": active_reservations,
        "backed_campaigns": backed_campaigns_cards,
        "backed_impact_timeline": impact_timeline,
        "recent_contributions": recent_contributions,
        "recommended_campaigns": recommended,
    }
