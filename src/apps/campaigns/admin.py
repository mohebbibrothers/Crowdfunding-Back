"""ثبت مدل‌های حرکت، دسته‌بندی، حامی مضاعف و گزارش میدانی در ادمین جنگو."""

from __future__ import annotations

from django.contrib import admin

from apps.campaigns.models import (
    Campaign,
    CampaignCategory,
    CampaignImpactUpdate,
    CampaignMedia,
    MatchingGrant,
)


@admin.register(CampaignCategory)
class CampaignCategoryAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("title", "slug", "display_order", "is_active")


@admin.register(Campaign)
class CampaignAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = (
        "title",
        "short_code",
        "benefactor",
        "status",
        "urgency_level",
        "paid_shares",
        "total_shares",
        "share_price_rial",
    )
    list_filter = ("status", "urgency_level", "is_featured")
    search_fields = ("title", "slug", "short_code")


@admin.register(CampaignMedia)
class CampaignMediaAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("campaign", "kind", "url", "display_order")


@admin.register(MatchingGrant)
class MatchingGrantAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = (
        "sponsor_name",
        "campaign",
        "match_ratio",
        "consumed_shares",
        "total_pool_shares",
        "is_active",
    )


@admin.register(CampaignImpactUpdate)
class CampaignImpactUpdateAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = (
        "title",
        "campaign",
        "milestone_type",
        "progress_percent",
        "is_published",
        "created_at",
    )
