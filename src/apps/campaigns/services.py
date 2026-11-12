"""سرویس‌های دامنهٔ حرکت‌ها: ایجاد/ویرایش با قفل تغییرناپذیری مالی، حامی مضاعف و گزارش میدانی."""

from __future__ import annotations

import secrets
import string
from typing import Any

from django.db import transaction

from apps.audit.choices import AuditAction
from apps.audit.services import record_audit_event
from apps.benefactors.models import Benefactor
from apps.campaigns.choices import CampaignStatus
from apps.campaigns.models import (
    Campaign,
    CampaignCategory,
    CampaignImpactUpdate,
    CampaignMedia,
    MatchingGrant,
)
from apps.core.cache import bump_epoch
from apps.core.errors import (
    ConflictError,
    FeatureDisabledError,
    NotFoundError,
    ValidationError as DomainValidationError,
)
from apps.core.outbox import enqueue_outbox
from apps.core.policy import is_feature_enabled
from apps.identity.models import User

_SHORT_ALPHABET = string.ascii_lowercase + string.digits


def generate_unique_campaign_short_code(length: int = 6) -> str:
    """تولید کد پیوندک ۶ کاراکتری یکتا برای حرکت (مشابه پیوندک مددا)."""
    for _ in range(25):
        candidate = "".join(secrets.choice(_SHORT_ALPHABET) for _ in range(length))
        if not Campaign.objects.filter(short_code=candidate).exists():
            return candidate
    raise ConflictError("تولید کد پیوندک یکتا ممکن نشد؛ دوباره تلاش کنید.")


def sync_benefactor_campaign_counters(*, benefactor_id: Any) -> None:
    """بازشماری دقیق تعداد حرکت‌های فعال و تکمیل‌شدهٔ یک خیریه در داخل تراکنش."""
    active_cnt = Campaign.objects.filter(
        benefactor_id=benefactor_id, status=CampaignStatus.ACTIVE
    ).count()
    completed_cnt = Campaign.objects.filter(
        benefactor_id=benefactor_id,
        status__in=[
            CampaignStatus.COMPLETED,
            CampaignStatus.EXECUTING,
            CampaignStatus.FULFILLED,
        ],
    ).count()
    Benefactor.objects.filter(pk=benefactor_id).update(
        active_campaigns_count=active_cnt,
        completed_campaigns_count=completed_cnt,
    )


@transaction.atomic
def create_category(*, actor: User, data: dict[str, Any], request: Any = None) -> CampaignCategory:
    """ایجاد دسته‌بندی موضوعی حرکت توسط مدیر."""
    slug = str(data["slug"]).strip()
    if CampaignCategory.objects.filter(slug=slug).exists():
        raise ConflictError("نامک دسته‌بندی تکراری است.")
    cat = CampaignCategory.objects.create(
        title=str(data["title"]).strip(),
        slug=slug,
        icon_name=str(data.get("icon_name") or "").strip(),
        description=str(data.get("description") or "").strip(),
        display_order=int(data.get("display_order", 100)),
        is_active=bool(data.get("is_active", True)),
    )
    record_audit_event(
        action=AuditAction.CAMPAIGN_SAVED,
        actor=actor,
        target_type="CampaignCategory",
        target_id=str(cat.id),
        metadata={"category_created": True, "slug": cat.slug},
        request=request,
    )
    transaction.on_commit(lambda: bump_epoch("campaigns"))
    return cat


@transaction.atomic
def create_campaign(*, actor: User, data: dict[str, Any], request: Any = None) -> Campaign:
    """ایجاد حرکت خیرخواهانهٔ سهم‌محور جدید توسط مدیر با محاسبهٔ قطعی مبلغ هدف."""
    benefactor = Benefactor.objects.select_for_update().filter(pk=data["benefactor_id"]).first()
    if benefactor is None or not benefactor.is_active:
        raise NotFoundError("خیریهٔ انتخاب‌شده یافت نشد یا غیرفعال است.")

    category = None
    if data.get("category_id"):
        category = CampaignCategory.objects.filter(pk=data["category_id"]).first()
        if category is None:
            raise NotFoundError("دسته‌بندی موضوعی یافت نشد.")

    slug = str(data["slug"]).strip()
    if Campaign.objects.filter(slug=slug).exists():
        raise ConflictError("نامک (slug) حرکت پیش‌تر ثبت شده است.")

    total_shares = int(data["total_shares"])
    share_price_rial = int(data["share_price_rial"])
    if total_shares < 1 or share_price_rial < 10_000:
        raise DomainValidationError(
            "تعداد کل سهم‌ها باید حداقل ۱ و مبلغ هر سهم حداقل ۱۰٬۰۰۰ ریال (۱٬۰۰۰ تومان) باشد."
        )
    target_amount_rial = total_shares * share_price_rial

    min_shares = int(data.get("min_shares_per_order", 1))
    max_shares = int(data.get("max_shares_per_order", 0))
    if min_shares < 1 or min_shares > total_shares:
        raise DomainValidationError("حداقل تعداد سهم در هر سفارش نامعتبر است.")
    if max_shares != 0 and max_shares < min_shares:
        raise DomainValidationError("حداکثر سهم در هر سفارش نمی‌تواند کمتر از حداقل سهم باشد.")

    short_code = str(data.get("short_code") or "").strip() or generate_unique_campaign_short_code()
    if Campaign.objects.filter(short_code=short_code).exists():
        raise ConflictError("کد پیوندک کوتاه انتخاب‌شده تکراری است.")

    campaign = Campaign.objects.create(
        benefactor=benefactor,
        category=category,
        title=str(data["title"]).strip(),
        slug=slug,
        short_code=short_code,
        subtitle=str(data.get("subtitle") or "").strip(),
        why_and_what=str(data.get("why_and_what") or "").strip(),
        cover_image_url=str(data.get("cover_image_url") or "").strip(),
        video_url=str(data.get("video_url") or "").strip(),
        province=str(data.get("province") or benefactor.province or "").strip(),
        city=str(data.get("city") or benefactor.city or "").strip(),
        total_shares=total_shares,
        share_price_rial=share_price_rial,
        target_amount_rial=target_amount_rial,
        min_shares_per_order=min_shares,
        max_shares_per_order=max_shares,
        status=str(data.get("status") or CampaignStatus.ACTIVE),
        urgency_level=str(data.get("urgency_level") or "normal"),
        is_featured=bool(data.get("is_featured", False)),
        allow_anonymous=bool(data.get("allow_anonymous", True)),
        allow_dedication=bool(data.get("allow_dedication", True)),
        starts_at=data.get("starts_at"),
        ends_at=data.get("ends_at"),
        created_by=actor,
    )

    for idx, media in enumerate(data.get("media_items") or []):
        CampaignMedia.objects.create(
            campaign=campaign,
            kind=str(media.get("kind") or "image"),
            url=str(media["url"]).strip(),
            caption=str(media.get("caption") or "").strip(),
            display_order=int(media.get("display_order", idx * 10)),
        )

    sync_benefactor_campaign_counters(benefactor_id=benefactor.id)
    record_audit_event(
        action=AuditAction.CAMPAIGN_SAVED,
        actor=actor,
        target_type="Campaign",
        target_id=str(campaign.id),
        metadata={
            "slug": campaign.slug,
            "short_code": campaign.short_code,
            "total_shares": campaign.total_shares,
            "share_price_rial": campaign.share_price_rial,
            "target_amount_rial": campaign.target_amount_rial,
        },
        request=request,
    )
    transaction.on_commit(lambda: bump_epoch("campaigns"))
    transaction.on_commit(lambda: bump_epoch("benefactors"))
    return campaign


@transaction.atomic
def update_campaign(
    *,
    actor: User,
    campaign_id: str,
    data: dict[str, Any],
    request: Any = None,
) -> Campaign:
    """ویرایش حرکت خیرخواهانه با محافظت سخت‌گیرانه از فیلدهای مالی پس از اولین پرداخت/رزرو."""
    campaign = (
        Campaign.objects.select_for_update()
        .select_related("benefactor", "category")
        .filter(pk=campaign_id)
        .first()
    )
    if campaign is None:
        raise NotFoundError("حرکت مورد نظر یافت نشد.")

    old_status = campaign.status
    changed: list[str] = []

    # محافظت تغییرناپذیری مالی پس از ثبت اولین مشارکت یا رزرو
    if campaign.has_financial_activity:
        if (
            "share_price_rial" in data
            and int(data["share_price_rial"]) != campaign.share_price_rial
        ):
            raise ConflictError("پس از ثبت اولین مشارکت یا رزرو سهم، تغییر مبلغ هر سهم مجاز نیست.")
        if "benefactor_id" in data and str(data["benefactor_id"]) != str(campaign.benefactor_id):
            raise ConflictError(
                "پس از جذب منابع، تغییر خیریهٔ صاحب حرکت به دلیل یکپارچگی دفترکل مجاز نیست."
            )
        if "total_shares" in data:
            new_total = int(data["total_shares"])
            min_allowed = campaign.funded_shares + campaign.reserved_shares
            if new_total < min_allowed:
                raise ConflictError(
                    f"تعداد کل سهم‌ها نمی‌تواند از مجموع سهم‌های تأمین‌شده و رزروشده ({min_allowed}) کمتر باشد."
                )

    if "benefactor_id" in data and str(data["benefactor_id"]) != str(campaign.benefactor_id):
        new_ben = Benefactor.objects.filter(pk=data["benefactor_id"], is_active=True).first()
        if new_ben is None:
            raise NotFoundError("خیریهٔ جدید یافت نشد یا غیرفعال است.")
        old_ben_id = campaign.benefactor_id
        campaign.benefactor = new_ben
        changed.append("benefactor")
        transaction.on_commit(lambda: bump_epoch("benefactors"))
    else:
        old_ben_id = None

    if "category_id" in data:
        cat_id = data["category_id"]
        campaign.category = CampaignCategory.objects.filter(pk=cat_id).first() if cat_id else None
        changed.append("category")

    if "slug" in data:
        new_slug = str(data["slug"]).strip()
        if (
            new_slug != campaign.slug
            and Campaign.objects.filter(slug=new_slug).exclude(pk=campaign.pk).exists()
        ):
            raise ConflictError("نامک انتخاب‌شده تکراری است.")
        campaign.slug = new_slug
        changed.append("slug")

    if "total_shares" in data or "share_price_rial" in data:
        t_shares = int(data.get("total_shares", campaign.total_shares))
        s_price = int(data.get("share_price_rial", campaign.share_price_rial))
        if t_shares < 1 or s_price < 10_000:
            raise DomainValidationError("مشخصات سهم و قیمت هر سهم نامعتبر است.")
        campaign.total_shares = t_shares
        campaign.share_price_rial = s_price
        campaign.target_amount_rial = t_shares * s_price
        changed.extend(["total_shares", "share_price_rial", "target_amount_rial"])

    for sfield in (
        "title",
        "subtitle",
        "why_and_what",
        "cover_image_url",
        "video_url",
        "province",
        "city",
        "urgency_level",
    ):
        if sfield in data:
            setattr(campaign, sfield, str(data[sfield] or "").strip())
            changed.append(sfield)

    for ifield in ("min_shares_per_order", "max_shares_per_order"):
        if ifield in data:
            setattr(campaign, ifield, int(data[ifield]))
            changed.append(ifield)

    for bfield in ("is_featured", "allow_anonymous", "allow_dedication"):
        if bfield in data:
            setattr(campaign, bfield, bool(data[bfield]))
            changed.append(bfield)

    for dfield in ("starts_at", "ends_at"):
        if dfield in data:
            setattr(campaign, dfield, data[dfield])
            changed.append(dfield)

    if "status" in data and str(data["status"]) != campaign.status:
        new_status = str(data["status"])
        if new_status == CampaignStatus.CANCELLED and campaign.paid_shares > 0:
            raise ConflictError(
                "حرکت دارای مشارکت پرداخت‌شده را نمی‌توان مستقیماً لغو کرد؛ ابتدا استرداد وجه را انجام دهید."
            )
        campaign.status = new_status
        changed.append("status")

    if changed:
        campaign.save(update_fields=list(dict.fromkeys([*changed, "updated_at"])))
        sync_benefactor_campaign_counters(benefactor_id=campaign.benefactor_id)
        if old_ben_id is not None:
            sync_benefactor_campaign_counters(benefactor_id=old_ben_id)

        action = (
            AuditAction.CAMPAIGN_CLOSED
            if campaign.status == CampaignStatus.CANCELLED
            else AuditAction.CAMPAIGN_SAVED
        )
        record_audit_event(
            action=action,
            actor=actor,
            target_type="Campaign",
            target_id=str(campaign.id),
            reason=str(data.get("reason") or "به‌روزرسانی وضعیت حرکت"),
            metadata={
                "changed_fields": changed,
                "old_status": old_status,
                "new_status": campaign.status,
            },
            request=request,
        )
        transaction.on_commit(lambda: bump_epoch("campaigns"))
        transaction.on_commit(lambda: bump_epoch("benefactors"))
    return campaign


@transaction.atomic
def create_matching_grant(
    *,
    actor: User,
    campaign_id: str,
    data: dict[str, Any],
    request: Any = None,
) -> MatchingGrant:
    """ثبت حامی مضاعف‌کننده برای دوبرابر (یا چندبرابر) کردن سهم‌های خریداری‌شدهٔ خیرین."""
    if not is_feature_enabled("feature.matching_grants"):
        raise FeatureDisabledError("قابلیت حامی مضاعف‌کننده در سیاست سامانه غیرفعال است.")

    campaign = Campaign.objects.select_for_update().filter(pk=campaign_id).first()
    if campaign is None:
        raise NotFoundError("حرکت مورد نظر یافت نشد.")

    pool_shares = int(data["total_pool_shares"])
    if pool_shares < 1 or pool_shares > campaign.total_shares:
        raise DomainValidationError("ظرفیت استخر مضاعف‌سازی باید بین ۱ تا کل سهم‌های حرکت باشد.")

    grant = MatchingGrant.objects.create(
        campaign=campaign,
        sponsor_name=str(data["sponsor_name"]).strip(),
        sponsor_logo_url=str(data.get("sponsor_logo_url") or "").strip(),
        match_ratio=int(data.get("match_ratio", 1)),
        total_pool_shares=pool_shares,
        is_active=bool(data.get("is_active", True)),
        expires_at=data.get("expires_at"),
    )
    record_audit_event(
        action=AuditAction.MATCHING_GRANT_CREATED,
        actor=actor,
        target_type="MatchingGrant",
        target_id=str(grant.id),
        metadata={
            "campaign_id": str(campaign.id),
            "sponsor_name": grant.sponsor_name,
            "total_pool_shares": grant.total_pool_shares,
            "match_ratio": grant.match_ratio,
        },
        request=request,
    )
    transaction.on_commit(lambda: bump_epoch("campaigns"))
    return grant


@transaction.atomic
def publish_impact_update(
    *,
    actor: User,
    campaign_id: str,
    data: dict[str, Any],
    request: Any = None,
) -> CampaignImpactUpdate:
    """انتشار گزارش پیشرفت میدانی حرکت و صف‌گذاری اعلان مژده برای تمام سهام‌داران حرکت."""
    if not is_feature_enabled("feature.impact_updates"):
        raise FeatureDisabledError("قابلیت گزارش‌های پیشرفت میدانی در سیاست سامانه غیرفعال است.")

    campaign = Campaign.objects.select_for_update().filter(pk=campaign_id).first()
    if campaign is None:
        raise NotFoundError("حرکت مورد نظر یافت نشد.")

    progress = int(data.get("progress_percent", campaign.physical_progress_percent))
    if not (0 <= progress <= 100):
        raise DomainValidationError("درصد پیشرفت فیزیکی باید بین ۰ تا ۱۰۰ باشد.")

    impact = CampaignImpactUpdate.objects.create(
        campaign=campaign,
        milestone_type=str(data.get("milestone_type") or "field_delivery"),
        title=str(data["title"]).strip(),
        body=str(data["body"]).strip(),
        progress_percent=progress,
        spent_amount_rial=int(data.get("spent_amount_rial", 0)),
        media_urls=list(data.get("media_urls") or []),
        is_published=bool(data.get("is_published", True)),
        published_by=actor,
    )

    update_fields = ["updated_at"]
    if progress > campaign.physical_progress_percent:
        campaign.physical_progress_percent = progress
        update_fields.append("physical_progress_percent")
    if progress == 100 and campaign.status in {CampaignStatus.COMPLETED, CampaignStatus.EXECUTING}:
        campaign.status = CampaignStatus.FULFILLED
        update_fields.append("status")
    elif progress > 0 and campaign.status == CampaignStatus.COMPLETED:
        campaign.status = CampaignStatus.EXECUTING
        update_fields.append("status")

    if len(update_fields) > 1:
        campaign.save(update_fields=update_fields)
        sync_benefactor_campaign_counters(benefactor_id=campaign.benefactor_id)

    if impact.is_published:
        enqueue_outbox(
            event_type="campaign.impact_published",
            aggregate_type="CampaignImpactUpdate",
            aggregate_id=str(impact.id),
            payload={
                "impact_id": str(impact.id),
                "campaign_id": str(campaign.id),
                "campaign_slug": campaign.slug,
                "campaign_title": campaign.title,
                "title": impact.title,
                "progress_percent": impact.progress_percent,
            },
        )

    record_audit_event(
        action=AuditAction.IMPACT_UPDATE_PUBLISHED,
        actor=actor,
        target_type="CampaignImpactUpdate",
        target_id=str(impact.id),
        metadata={
            "campaign_id": str(campaign.id),
            "progress_percent": impact.progress_percent,
            "milestone_type": impact.milestone_type,
        },
        request=request,
    )
    transaction.on_commit(lambda: bump_epoch("campaigns"))
    return impact
