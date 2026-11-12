"""سلکتورهای خوانشی حرکت‌ها به همراه الگوریتم رتبه‌بندی توزیع منصفانه (Fair-Share Ranking v2)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from django.db.models import (
    Case,
    ExpressionWrapper,
    F,
    FloatField,
    IntegerField,
    Prefetch,
    Q,
    QuerySet,
    Value,
    When,
)
from django.db.models.functions import Cast
from django.utils import timezone

from apps.campaigns.choices import CampaignStatus, CampaignUrgency
from apps.campaigns.models import (
    Campaign,
    CampaignCategory,
    CampaignImpactUpdate,
    MatchingGrant,
)
from apps.core.errors import NotFoundError

PUBLIC_VISIBLE_STATUSES = (
    CampaignStatus.ACTIVE,
    CampaignStatus.COMPLETED,
    CampaignStatus.EXECUTING,
    CampaignStatus.FULFILLED,
)


def annotate_fair_share_ranking(qs: QuerySet[Campaign]) -> QuerySet[Campaign]:
    """افزودن ستون‌های محاسباتی SQL برای توزیع منصفانهٔ دیده‌شدن حرکت‌ها.

    قواعد اولویت در مرتب‌سازی پیش‌فرض ``fair``:
    ۱. حرکت‌های فعال دارای ظرفیت خالی بالاتر از حرکت‌های تکمیل‌شده قرار می‌گیرند.
    ۲. حرکت‌های اضطراری (``emergency``) و فوری (``urgent``) ضریب شتاب منصفانه می‌گیرند
       اما همچنان حرکت‌های کم‌پیشرفت و مغفول‌مانده در صدر فهرست دیده می‌شوند تا هیچ
       حرکت خیرخواهانه‌ای در صفحات پایین جا نماند.
    """
    funded_expr = F("paid_shares") + F("matched_shares") + F("external_shares")
    avail_expr = F("total_shares") - funded_expr - F("reserved_shares")

    urgency_discount = Case(
        When(urgency_level=CampaignUrgency.EMERGENCY, then=Value(-0.35)),
        When(urgency_level=CampaignUrgency.URGENT, then=Value(-0.15)),
        default=Value(0.0),
        output_field=FloatField(),
    )
    progress_ratio = ExpressionWrapper(
        Cast(funded_expr, FloatField()) / Cast(F("total_shares"), FloatField()),
        output_field=FloatField(),
    )
    return qs.annotate(
        _avail_shares=avail_expr,
        _open_bucket=Case(
            When(Q(status=CampaignStatus.ACTIVE) & Q(_avail_shares__gt=0), then=Value(0)),
            default=Value(1),
            output_field=IntegerField(),
        ),
        _fair_score=ExpressionWrapper(
            progress_ratio + urgency_discount,
            output_field=FloatField(),
        ),
    )


def list_public_campaigns(
    *,
    category_slug: str | None = None,
    benefactor_slug: str | None = None,
    province: str | None = None,
    status_filter: str | None = None,
    urgency: str | None = None,
    has_matching: bool = False,
    search: str | None = None,
    ordering: str = "fair",
) -> QuerySet[Campaign]:
    """واکشی فهرست عمومی حرکت‌ها با فیلترهای چندبعدی و مرتب‌سازی منصفانه."""
    now = timezone.now()
    active_grants = MatchingGrant.objects.filter(
        is_active=True,
        consumed_shares__lt=F("total_pool_shares"),
    ).filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))

    qs: QuerySet[Campaign] = (
        Campaign.objects.select_related("benefactor", "category")
        .prefetch_related(
            Prefetch("matching_grants", queryset=active_grants, to_attr="prefetched_active_grants")
        )
        .filter(status__in=PUBLIC_VISIBLE_STATUSES, benefactor__is_active=True)
    )

    if category_slug:
        qs = qs.filter(category__slug=category_slug)
    if benefactor_slug:
        qs = qs.filter(benefactor__slug=benefactor_slug)
    if province:
        qs = qs.filter(province=province)
    if status_filter and status_filter in PUBLIC_VISIBLE_STATUSES:
        qs = qs.filter(status=status_filter)
    if urgency:
        qs = qs.filter(urgency_level=urgency)
    if has_matching:
        qs = qs.filter(
            matching_grants__is_active=True,
            matching_grants__consumed_shares__lt=F("matching_grants__total_pool_shares"),
        ).distinct()
    if search:
        qs = qs.filter(Q(title__icontains=search) | Q(subtitle__icontains=search))

    ranked_qs: Any = annotate_fair_share_ranking(qs)

    if ordering == "newest":
        res = ranked_qs.order_by("_open_bucket", "-created_at", "-id")
    elif ordering == "ending_soon":
        res = ranked_qs.order_by(
            "_open_bucket",
            F("ends_at").asc(nulls_last=True),
            "_fair_score",
            "-id",
        )
    elif ordering == "most_funded":
        res = ranked_qs.order_by("_open_bucket", "-_fair_score", "-created_at", "-id")
    elif ordering == "urgent":
        res = ranked_qs.order_by(
            "_open_bucket", "_fair_score", F("ends_at").asc(nulls_last=True), "-id"
        )
    else:
        # پیش‌فرض: توزیع منصفانه (Fair-Share Ranking v2)
        res = ranked_qs.order_by(
            "_open_bucket", "_fair_score", F("ends_at").asc(nulls_last=True), "-created_at", "-id"
        )
    ordered_qs: QuerySet[Campaign] = res
    return ordered_qs


def get_public_campaign_by_slug_or_code(*, identifier: str) -> Campaign:
    """واکشی کامل صفحهٔ حرکت از روی نامک یا کد پیوندک کوتاه (با گالری، حامی مضاعف و گزارش‌های میدانی)."""
    now = timezone.now()
    active_grants = MatchingGrant.objects.filter(
        is_active=True,
        consumed_shares__lt=F("total_pool_shares"),
    ).filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
    published_updates = CampaignImpactUpdate.objects.filter(is_published=True).order_by(
        "-created_at"
    )

    base_qs = (
        Campaign.objects.select_related("benefactor", "category")
        .prefetch_related(
            "media_items",
            Prefetch("matching_grants", queryset=active_grants, to_attr="prefetched_active_grants"),
            Prefetch(
                "impact_updates", queryset=published_updates, to_attr="prefetched_impact_updates"
            ),
        )
        .filter(status__in=PUBLIC_VISIBLE_STATUSES, benefactor__is_active=True)
    )
    campaign = base_qs.filter(slug=identifier).first()
    if campaign is None:
        campaign = base_qs.filter(short_code=identifier).first()
    if campaign is None:
        raise NotFoundError("حرکت مورد نظر یافت نشد یا هنوز منتشر نشده است.")
    return campaign


def list_public_categories() -> QuerySet[CampaignCategory]:
    """فهرست دسته‌بندی‌های موضوعی فعال."""
    return CampaignCategory.objects.filter(is_active=True).order_by("display_order", "title")


def list_admin_campaigns(
    *,
    status_filter: str | None = None,
    benefactor_id: str | None = None,
) -> QuerySet[Campaign]:
    """فهرست مدیریتی همهٔ حرکت‌ها از جمله پیش‌نویس و لغوشده."""
    qs = Campaign.objects.select_related("benefactor", "category").prefetch_related(
        "media_items", "matching_grants", "impact_updates"
    )
    if status_filter:
        qs = qs.filter(status=status_filter)
    if benefactor_id:
        qs = qs.filter(benefactor_id=benefactor_id)
    return qs.order_by("-created_at", "-id")


_SHORT_CODE_FALLBACK_RESOLVERS: list[Callable[[str], dict[str, Any] | None]] = []


def register_short_code_resolver(resolver: Callable[[str], dict[str, Any] | None]) -> None:
    """ثبت آداپتور حل‌کنندهٔ مکمل پیوندک (مانند کدهای سفیر در اپ مشارکت‌ها) با رعایت وارونگی وابستگی."""
    if resolver not in _SHORT_CODE_FALLBACK_RESOLVERS:
        _SHORT_CODE_FALLBACK_RESOLVERS.append(resolver)


def resolve_short_code_target(*, short_code: str) -> dict[str, Any]:
    """حل‌کنندهٔ یکپارچهٔ پیوندک کوتاه (حرکت، قلک عام یا لینک سفیر اجتماعی)."""
    from apps.benefactors.models import CharityJar

    for resolver in _SHORT_CODE_FALLBACK_RESOLVERS:
        resolved = resolver(short_code)
        if resolved is not None:
            return resolved

    camp = (
        Campaign.objects.filter(short_code=short_code, status__in=PUBLIC_VISIBLE_STATUSES)
        .values("id", "slug", "title", "short_code")
        .first()
    )
    if camp is not None:
        return {
            "kind": "campaign",
            "short_code": short_code,
            "slug": camp["slug"],
            "title": camp["title"],
            "target_path": f"/campaigns/{camp['slug']}",
        }

    jar = (
        CharityJar.objects.filter(short_code=short_code, is_active=True)
        .values("id", "slug", "title", "short_code")
        .first()
    )
    if jar is not None:
        return {
            "kind": "charity_jar",
            "short_code": short_code,
            "slug": jar["slug"],
            "title": jar["title"],
            "target_path": f"/jars/{jar['slug']}",
        }

    raise NotFoundError("پیوندک کوتاه مورد نظر یافت نشد.")
