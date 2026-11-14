"""سریالایزرهای حرکت‌های خیرخواهانه، دسته‌بندی‌ها، حامیان مضاعف و گزارش‌های پیشرفت میدانی."""

from __future__ import annotations

from typing import Any

from rest_framework import serializers

from apps.campaigns.choices import (
    CampaignMediaKind,
    CampaignStatus,
    CampaignUrgency,
    ImpactMilestoneType,
)
from apps.campaigns.models import (
    Campaign,
    CampaignImpactUpdate,
)
from apps.core.jalali import format_jalali_datetime
from apps.core.money import rial_to_toman
from apps.core.policy import is_feature_enabled


class CampaignCategorySerializer(serializers.Serializer[Any]):
    """نمای دسته‌بندی موضوعی حرکت."""

    id = serializers.UUIDField()
    title = serializers.CharField()
    slug = serializers.CharField()
    icon_name = serializers.CharField()
    description = serializers.CharField()
    display_order = serializers.IntegerField()


class CampaignCategoryWriteSerializer(serializers.Serializer[Any]):
    """ورودی ایجاد دسته‌بندی موضوعی."""

    title = serializers.CharField(max_length=120)
    slug = serializers.CharField(max_length=80)
    icon_name = serializers.CharField(max_length=64, required=False, allow_blank=True, default="")
    description = serializers.CharField(
        max_length=300, required=False, allow_blank=True, default=""
    )
    display_order = serializers.IntegerField(required=False, min_value=0, default=100)
    is_active = serializers.BooleanField(required=False, default=True)


class CampaignMediaSerializer(serializers.Serializer[Any]):
    """نمای آیتم رسانه در گالری حرکت."""

    id = serializers.UUIDField()
    kind = serializers.CharField()
    url = serializers.CharField()
    caption = serializers.CharField()
    display_order = serializers.IntegerField()


class MatchingGrantPublicSerializer(serializers.Serializer[Any]):
    """نمای عمومی حامی مضاعف‌کنندهٔ فعال روی حرکت."""

    id = serializers.UUIDField()
    sponsor_name = serializers.CharField()
    sponsor_logo_url = serializers.CharField()
    match_ratio = serializers.IntegerField()
    total_pool_shares = serializers.IntegerField()
    consumed_shares = serializers.IntegerField()
    remaining_pool_shares = serializers.IntegerField()
    expires_at = serializers.DateTimeField(allow_null=True)


class CampaignImpactUpdateSerializer(serializers.Serializer[Any]):
    """نمای گزارش پیشرفت میدانی حرکت."""

    id = serializers.UUIDField()
    milestone_type = serializers.CharField()
    title = serializers.CharField()
    body = serializers.CharField()
    progress_percent = serializers.IntegerField()
    spent_amount_rial = serializers.IntegerField()
    spent_amount_toman = serializers.SerializerMethodField()
    media_urls = serializers.ListField(child=serializers.CharField())
    created_at = serializers.DateTimeField()
    created_at_jalali = serializers.SerializerMethodField()

    def get_spent_amount_toman(self, obj: CampaignImpactUpdate) -> int:
        return rial_to_toman(obj.spent_amount_rial)

    def get_created_at_jalali(self, obj: CampaignImpactUpdate) -> str | None:
        return format_jalali_datetime(obj.created_at)


class CampaignSummarySerializer(serializers.Serializer[Any]):
    """نمای کارت خلاصهٔ حرکت برای فهرست‌های عمومی (با نمایش دوگانه ریال/تومان و سهم‌ها)."""

    id = serializers.UUIDField()
    title = serializers.CharField()
    slug = serializers.CharField()
    short_code = serializers.CharField()
    subtitle = serializers.CharField()
    cover_image_url = serializers.CharField()
    province = serializers.CharField()
    city = serializers.CharField()
    # ChoiceField نه CharField: فرانت باید union type دقیق داشته باشد،
    # نه «هر رشته‌ای ممکن است» — که ماشین حالت را بی‌معنا می‌کند.
    status = serializers.ChoiceField(choices=CampaignStatus.choices)
    urgency_level = serializers.ChoiceField(choices=CampaignUrgency.choices)
    is_featured = serializers.BooleanField()
    benefactor = serializers.SerializerMethodField()
    category = serializers.SerializerMethodField()

    # آمار سهم‌بندی
    total_shares = serializers.IntegerField()
    paid_shares = serializers.IntegerField()
    matched_shares = serializers.IntegerField()
    external_shares = serializers.IntegerField()
    reserved_shares = serializers.IntegerField()
    funded_shares = serializers.IntegerField()
    remaining_shares = serializers.IntegerField()
    progress_percent = serializers.FloatField()
    physical_progress_percent = serializers.IntegerField()
    supporter_count = serializers.IntegerField()

    # آمار ریالی و تومانی
    share_price_rial = serializers.IntegerField()
    share_price_toman = serializers.SerializerMethodField()
    target_amount_rial = serializers.IntegerField()
    target_amount_toman = serializers.SerializerMethodField()
    total_funded_rial = serializers.IntegerField()
    total_funded_toman = serializers.SerializerMethodField()
    disbursed_amount_rial = serializers.IntegerField()
    disbursed_amount_toman = serializers.SerializerMethodField()

    active_matching_grant = serializers.SerializerMethodField()
    ends_at = serializers.DateTimeField(allow_null=True)
    ends_at_jalali = serializers.SerializerMethodField()
    created_at = serializers.DateTimeField()
    created_at_jalali = serializers.SerializerMethodField()

    def get_benefactor(self, obj: Campaign) -> dict[str, Any]:
        return {
            "id": str(obj.benefactor_id),
            "name": obj.benefactor.name,
            "slug": obj.benefactor.slug,
            "logo_url": obj.benefactor.logo_url,
            "is_verified": obj.benefactor.is_verified,
        }

    def get_category(self, obj: Campaign) -> dict[str, Any] | None:
        if obj.category is None:
            return None
        return {
            "id": str(obj.category_id),
            "title": obj.category.title,
            "slug": obj.category.slug,
            "icon_name": obj.category.icon_name,
        }

    def get_share_price_toman(self, obj: Campaign) -> int:
        return rial_to_toman(obj.share_price_rial)

    def get_target_amount_toman(self, obj: Campaign) -> int:
        return rial_to_toman(obj.target_amount_rial)

    def get_total_funded_toman(self, obj: Campaign) -> int:
        return rial_to_toman(obj.total_funded_rial)

    def get_disbursed_amount_toman(self, obj: Campaign) -> int:
        return rial_to_toman(obj.disbursed_amount_rial)

    def get_active_matching_grant(self, obj: Campaign) -> dict[str, Any] | None:
        if not is_feature_enabled("feature.matching_grants"):
            return None
        grants = getattr(obj, "prefetched_active_grants", None)
        if grants is None:
            grants = list(obj.matching_grants.filter(is_active=True))
        for g in grants:
            if g.remaining_pool_shares > 0:
                return dict(MatchingGrantPublicSerializer(g).data)
        return None

    def get_ends_at_jalali(self, obj: Campaign) -> str | None:
        return format_jalali_datetime(obj.ends_at)

    def get_created_at_jalali(self, obj: Campaign) -> str | None:
        return format_jalali_datetime(obj.created_at)


class CampaignDetailSerializer(CampaignSummarySerializer):
    """نمای کامل صفحهٔ جزئیات حرکت شامل روایت چیستی‌وچرایی، گالری و تایم‌لاین پیشرفت میدانی."""

    why_and_what = serializers.CharField()
    video_url = serializers.CharField()
    min_shares_per_order = serializers.IntegerField()
    max_shares_per_order = serializers.IntegerField()
    collected_online_rial = serializers.IntegerField()
    collected_online_toman = serializers.SerializerMethodField()
    matched_amount_rial = serializers.IntegerField()
    matched_amount_toman = serializers.SerializerMethodField()
    external_amount_rial = serializers.IntegerField()
    external_amount_toman = serializers.SerializerMethodField()
    allow_anonymous = serializers.BooleanField()
    allow_dedication = serializers.BooleanField()
    media_items = CampaignMediaSerializer(many=True)
    impact_updates = serializers.SerializerMethodField()
    starts_at = serializers.DateTimeField(allow_null=True)
    completed_at = serializers.DateTimeField(allow_null=True)
    has_financial_activity = serializers.BooleanField()

    def get_collected_online_toman(self, obj: Campaign) -> int:
        return rial_to_toman(obj.collected_online_rial)

    def get_matched_amount_toman(self, obj: Campaign) -> int:
        return rial_to_toman(obj.matched_amount_rial)

    def get_external_amount_toman(self, obj: Campaign) -> int:
        return rial_to_toman(obj.external_amount_rial)

    def get_impact_updates(self, obj: Campaign) -> list[dict[str, Any]]:
        if not is_feature_enabled("feature.impact_updates"):
            return []
        items = getattr(obj, "prefetched_impact_updates", None)
        if items is None:
            items = obj.impact_updates.filter(is_published=True)
        return list(CampaignImpactUpdateSerializer(items, many=True).data)


class CampaignMediaInputSerializer(serializers.Serializer[Any]):
    """آیتم ورودی رسانه هنگام ایجاد حرکت."""

    kind = serializers.ChoiceField(
        choices=CampaignMediaKind.choices, default=CampaignMediaKind.IMAGE
    )
    url = serializers.CharField(max_length=500)
    caption = serializers.CharField(max_length=240, required=False, allow_blank=True, default="")
    display_order = serializers.IntegerField(required=False, min_value=0, default=100)


class CampaignWriteSerializer(serializers.Serializer[Any]):
    """ورودی ایجاد حرکت خیرخواهانهٔ سهم‌محور توسط مدیر."""

    benefactor_id = serializers.UUIDField()
    category_id = serializers.UUIDField(required=False, allow_null=True)
    title = serializers.CharField(max_length=220)
    slug = serializers.CharField(max_length=140)
    short_code = serializers.CharField(max_length=16, required=False, allow_blank=True, default="")
    subtitle = serializers.CharField(max_length=320, required=False, allow_blank=True, default="")
    why_and_what = serializers.CharField(required=False, allow_blank=True, default="")
    cover_image_url = serializers.CharField(
        max_length=500, required=False, allow_blank=True, default=""
    )
    video_url = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")
    province = serializers.CharField(max_length=80, required=False, allow_blank=True, default="")
    city = serializers.CharField(max_length=80, required=False, allow_blank=True, default="")
    total_shares = serializers.IntegerField(min_value=1, max_value=10_000_000)
    share_price_rial = serializers.IntegerField(min_value=10_000, max_value=100_000_000_000)
    min_shares_per_order = serializers.IntegerField(min_value=1, required=False, default=1)
    max_shares_per_order = serializers.IntegerField(min_value=0, required=False, default=0)
    status = serializers.ChoiceField(
        choices=CampaignStatus.choices, required=False, default=CampaignStatus.ACTIVE
    )
    urgency_level = serializers.ChoiceField(
        choices=CampaignUrgency.choices, required=False, default=CampaignUrgency.NORMAL
    )
    is_featured = serializers.BooleanField(required=False, default=False)
    allow_anonymous = serializers.BooleanField(required=False, default=True)
    allow_dedication = serializers.BooleanField(required=False, default=True)
    starts_at = serializers.DateTimeField(required=False, allow_null=True)
    ends_at = serializers.DateTimeField(required=False, allow_null=True)
    media_items = CampaignMediaInputSerializer(many=True, required=False)


class CampaignPatchSerializer(serializers.Serializer[Any]):
    """ورودی ویرایش جزئی حرکت توسط مدیر."""

    benefactor_id = serializers.UUIDField(required=False)
    category_id = serializers.UUIDField(required=False, allow_null=True)
    title = serializers.CharField(max_length=220, required=False)
    slug = serializers.CharField(max_length=140, required=False)
    subtitle = serializers.CharField(max_length=320, required=False, allow_blank=True)
    why_and_what = serializers.CharField(required=False, allow_blank=True)
    cover_image_url = serializers.CharField(max_length=500, required=False, allow_blank=True)
    video_url = serializers.CharField(max_length=500, required=False, allow_blank=True)
    province = serializers.CharField(max_length=80, required=False, allow_blank=True)
    city = serializers.CharField(max_length=80, required=False, allow_blank=True)
    total_shares = serializers.IntegerField(min_value=1, max_value=10_000_000, required=False)
    share_price_rial = serializers.IntegerField(min_value=10_000, required=False)
    min_shares_per_order = serializers.IntegerField(min_value=1, required=False)
    max_shares_per_order = serializers.IntegerField(min_value=0, required=False)
    status = serializers.ChoiceField(choices=CampaignStatus.choices, required=False)
    urgency_level = serializers.ChoiceField(choices=CampaignUrgency.choices, required=False)
    is_featured = serializers.BooleanField(required=False)
    allow_anonymous = serializers.BooleanField(required=False)
    allow_dedication = serializers.BooleanField(required=False)
    starts_at = serializers.DateTimeField(required=False, allow_null=True)
    ends_at = serializers.DateTimeField(required=False, allow_null=True)
    reason = serializers.CharField(max_length=400, required=False, allow_blank=True)


class MatchingGrantWriteSerializer(serializers.Serializer[Any]):
    """ورودی تعریف حامی مضاعف‌کننده روی حرکت."""

    sponsor_name = serializers.CharField(max_length=180)
    sponsor_logo_url = serializers.CharField(
        max_length=500, required=False, allow_blank=True, default=""
    )
    match_ratio = serializers.IntegerField(min_value=1, max_value=10, required=False, default=1)
    total_pool_shares = serializers.IntegerField(min_value=1)
    is_active = serializers.BooleanField(required=False, default=True)
    expires_at = serializers.DateTimeField(required=False, allow_null=True)


class ImpactUpdateWriteSerializer(serializers.Serializer[Any]):
    """ورودی انتشار گزارش پیشرفت میدانی حرکت."""

    milestone_type = serializers.ChoiceField(
        choices=ImpactMilestoneType.choices, default=ImpactMilestoneType.FIELD_DELIVERY
    )
    title = serializers.CharField(max_length=200)
    body = serializers.CharField(min_length=5)
    progress_percent = serializers.IntegerField(min_value=0, max_value=100)
    spent_amount_rial = serializers.IntegerField(min_value=0, required=False, default=0)
    media_urls = serializers.ListField(child=serializers.CharField(max_length=500), required=False)
    is_published = serializers.BooleanField(required=False, default=True)


class ShortLinkResolveResponseSerializer(serializers.Serializer[Any]):
    """پاسخ حل‌کنندهٔ پیوندک کوتاه."""

    kind = serializers.CharField()
    short_code = serializers.CharField()
    slug = serializers.CharField()
    title = serializers.CharField()
    target_path = serializers.CharField()
    ambassador_code = serializers.CharField(required=False, allow_null=True)
