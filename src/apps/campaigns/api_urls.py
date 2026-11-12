"""مسیرهای API عمومی و مدیریتی حرکت‌های خیرخواهانه و حل‌کنندهٔ پیوندک."""

from __future__ import annotations

from django.urls import path

from apps.campaigns.views import (
    AdminCampaignDetailView,
    AdminCampaignImpactUpdateCreateView,
    AdminCampaignListCreateView,
    AdminCampaignMatchingGrantCreateView,
    AdminCategoryCreateView,
    PublicCampaignDetailView,
    PublicCampaignListView,
    PublicCategoryListView,
    PublicShortLinkResolveView,
)

urlpatterns = [
    path(
        "campaign-categories",
        PublicCategoryListView.as_view(),
        name="v1-campaign-categories",
    ),
    path("campaigns", PublicCampaignListView.as_view(), name="v1-campaigns-list"),
    path(
        "campaigns/<str:identifier>",
        PublicCampaignDetailView.as_view(),
        name="v1-campaigns-detail",
    ),
    path(
        "short-links/<str:short_code>",
        PublicShortLinkResolveView.as_view(),
        name="v1-short-links-resolve",
    ),
    path(
        "admin/campaign-categories",
        AdminCategoryCreateView.as_view(),
        name="v1-admin-campaign-categories-create",
    ),
    path(
        "admin/campaigns",
        AdminCampaignListCreateView.as_view(),
        name="v1-admin-campaigns-list",
    ),
    path(
        "admin/campaigns/<str:campaign_id>",
        AdminCampaignDetailView.as_view(),
        name="v1-admin-campaigns-detail",
    ),
    path(
        "admin/campaigns/<str:campaign_id>/matching-grants",
        AdminCampaignMatchingGrantCreateView.as_view(),
        name="v1-admin-campaigns-matching-grants",
    ),
    path(
        "admin/campaigns/<str:campaign_id>/impact-updates",
        AdminCampaignImpactUpdateCreateView.as_view(),
        name="v1-admin-campaigns-impact-updates",
    ),
]
