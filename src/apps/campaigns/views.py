"""نماهای HTTP عمومی و مدیریتی حرکت‌های خیرخواهانه، دسته‌بندی‌ها، حامیان مضاعف و گزارش‌های میدانی."""

from __future__ import annotations

from typing import Any

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.campaigns.models import Campaign
from apps.campaigns.selectors import (
    get_public_campaign_by_slug_or_code,
    list_admin_campaigns,
    list_public_campaigns,
    list_public_categories,
    resolve_short_code_target,
)
from apps.campaigns.serializers import (
    CampaignCategorySerializer,
    CampaignCategoryWriteSerializer,
    CampaignDetailSerializer,
    CampaignImpactUpdateSerializer,
    CampaignPatchSerializer,
    CampaignSummarySerializer,
    CampaignWriteSerializer,
    ImpactUpdateWriteSerializer,
    MatchingGrantPublicSerializer,
    MatchingGrantWriteSerializer,
    ShortLinkResolveResponseSerializer,
)
from apps.campaigns.services import (
    create_campaign,
    create_category,
    create_matching_grant,
    publish_impact_update,
    update_campaign,
)
from apps.core.cache import get_or_set_versioned
from apps.core.conditional import conditional_json_response
from apps.core.errors import NotFoundError
from apps.core.policy import is_feature_enabled
from apps.identity.permissions import IsStaffRole, authenticated_user


class PublicCategoryListView(APIView):
    """فهرست دسته‌بندی‌های موضوعی حرکت‌های خیرخواهانه."""

    permission_classes = [AllowAny]
    authentication_classes: list[Any] = []

    @extend_schema(
        operation_id="v1_campaign_categories_list",
        summary="فهرست دسته‌بندی‌های موضوعی حرکت‌ها",
        responses={200: CampaignCategorySerializer(many=True)},
        tags=["Public - Campaigns"],
    )
    def get(self, request: Request) -> Response:
        data = get_or_set_versioned(
            "campaigns",
            "global",
            "categories",
            lambda: list(CampaignCategorySerializer(list_public_categories(), many=True).data),
            timeout=120,
        )
        return conditional_json_response(request, data, max_age=30)


class PublicCampaignListView(APIView):
    """فهرست عمومی حرکت‌های سهم‌محور با مرتب‌سازی پیش‌فرض توزیع منصفانه (Fair-Share Ranking v2)."""

    permission_classes = [AllowAny]
    authentication_classes: list[Any] = []

    @extend_schema(
        operation_id="v1_campaigns_list",
        summary="فهرست حرکت‌های خیرخواهانه با رتبه‌بندی توزیع منصفانه",
        responses={200: CampaignSummarySerializer(many=True)},
        tags=["Public - Campaigns"],
    )
    def get(self, request: Request) -> Response:
        category = request.query_params.get("category")
        benefactor = request.query_params.get("benefactor")
        province = request.query_params.get("province")
        status_filter = request.query_params.get("status")
        urgency = request.query_params.get("urgency")
        has_matching = request.query_params.get("has_matching") == "true"
        search = request.query_params.get("q")
        ordering = request.query_params.get("order", "fair")
        match_flag = is_feature_enabled("feature.matching_grants")

        cache_id = (
            f"list:{category or ''}:{benefactor or ''}:{province or ''}:"
            f"{status_filter or ''}:{urgency or ''}:{has_matching}:{search or ''}:"
            f"{ordering}:{match_flag}"
        )

        def _produce() -> dict[str, Any]:
            qs = list_public_campaigns(
                category_slug=category,
                benefactor_slug=benefactor,
                province=province,
                status_filter=status_filter,
                urgency=urgency,
                has_matching=has_matching,
                search=search,
                ordering=ordering,
            )
            items = list(CampaignSummarySerializer(qs[:100], many=True).data)
            return {
                "ordering": ordering,
                "count": len(items),
                "results": items,
            }

        data = get_or_set_versioned(
            "campaigns",
            "global",
            cache_id,
            _produce,
            timeout=20,
        )
        return conditional_json_response(request, data, max_age=10)


class PublicCampaignDetailView(APIView):
    """جزئیات کامل یک حرکت خیرخواهانه از روی نامک یا کد پیوندک کوتاه."""

    permission_classes = [AllowAny]
    authentication_classes: list[Any] = []

    @extend_schema(
        operation_id="v1_campaigns_retrieve",
        summary="مشاهدهٔ جزئیات حرکت خیرخواهانه، سهم‌های آزاد و گزارش‌های میدانی",
        responses={200: CampaignDetailSerializer},
        tags=["Public - Campaigns"],
    )
    def get(self, request: Request, identifier: str) -> Response:
        match_flag = is_feature_enabled("feature.matching_grants")
        impact_flag = is_feature_enabled("feature.impact_updates")
        data = get_or_set_versioned(
            "campaigns",
            "global",
            f"detail:{identifier}:{match_flag}:{impact_flag}",
            lambda: dict(
                CampaignDetailSerializer(
                    get_public_campaign_by_slug_or_code(identifier=identifier)
                ).data
            ),
            timeout=15,
        )
        return conditional_json_response(request, data, max_age=5)


class PublicShortLinkResolveView(APIView):
    """حل‌کنندهٔ پیوندک کوتاه (حرکت، قلک عام یا لینک سفیر اجتماعی با ثبت کلیک)."""

    permission_classes = [AllowAny]
    authentication_classes: list[Any] = []

    @extend_schema(
        operation_id="v1_short_links_resolve",
        summary="حل نشانی پیوندک کوتاه (حرکت، قلک عام یا لینک سفیر اجتماعی)",
        responses={200: ShortLinkResolveResponseSerializer},
        tags=["Public - Short-Links & Ambassadors"],
    )
    def get(self, request: Request, short_code: str) -> Response:
        del request
        return Response(resolve_short_code_target(short_code=short_code))


# ── مسیرهای مدیریتی حرکت‌ها ──────────────────────────────────────────────────


class AdminCategoryCreateView(APIView):
    """ایجاد دسته‌بندی موضوعی جدید برای حرکت‌ها."""

    permission_classes = [IsStaffRole]

    @extend_schema(
        operation_id="v1_admin_campaign_categories_create",
        summary="ایجاد دسته‌بندی موضوعی حرکت",
        request=CampaignCategoryWriteSerializer,
        responses={201: CampaignCategorySerializer},
        tags=["Admin - Campaigns"],
    )
    def post(self, request: Request) -> Response:
        ser = CampaignCategoryWriteSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        actor = authenticated_user(request)
        cat = create_category(actor=actor, data=ser.validated_data, request=request)
        return Response(CampaignCategorySerializer(cat).data, status=status.HTTP_201_CREATED)


class AdminCampaignListCreateView(APIView):
    """فهرست کامل مدیریتی و تعریف حرکت سهم‌محور جدید."""

    permission_classes = [IsStaffRole]

    @extend_schema(
        operation_id="v1_admin_campaigns_list",
        summary="فهرست مدیریتی همهٔ حرکت‌ها",
        responses={200: CampaignDetailSerializer(many=True)},
        tags=["Admin - Campaigns"],
    )
    def get(self, request: Request) -> Response:
        status_filter = request.query_params.get("status")
        benefactor_id = request.query_params.get("benefactor_id")
        qs = list_admin_campaigns(status_filter=status_filter, benefactor_id=benefactor_id)
        return Response(CampaignDetailSerializer(qs[:200], many=True).data)

    @extend_schema(
        operation_id="v1_admin_campaigns_create",
        summary="تعریف حرکت خیرخواهانهٔ سهم‌محور جدید",
        request=CampaignWriteSerializer,
        responses={201: CampaignDetailSerializer},
        tags=["Admin - Campaigns"],
    )
    def post(self, request: Request) -> Response:
        ser = CampaignWriteSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        actor = authenticated_user(request)
        campaign = create_campaign(actor=actor, data=ser.validated_data, request=request)
        return Response(CampaignDetailSerializer(campaign).data, status=status.HTTP_201_CREATED)


class AdminCampaignDetailView(APIView):
    """دریافت و ویرایش حرکت توسط مدیر (با قفل تغییرناپذیری فیلدهای مالی پس از اولین پرداخت)."""

    permission_classes = [IsStaffRole]

    @extend_schema(
        operation_id="v1_admin_campaigns_retrieve",
        summary="دریافت جزئیات مدیریتی یک حرکت",
        responses={200: CampaignDetailSerializer},
        tags=["Admin - Campaigns"],
    )
    def get(self, request: Request, campaign_id: str) -> Response:
        del request
        campaign = (
            Campaign.objects.select_related("benefactor", "category")
            .prefetch_related("media_items", "matching_grants", "impact_updates")
            .filter(pk=campaign_id)
            .first()
        )
        if campaign is None:
            raise NotFoundError("حرکت مورد نظر یافت نشد.")
        return Response(CampaignDetailSerializer(campaign).data)

    @extend_schema(
        operation_id="v1_admin_campaigns_partial_update",
        summary="ویرایش حرکت (محافظت از قیمت سهم و خیریه پس از اولین مشارکت)",
        request=CampaignPatchSerializer,
        responses={200: CampaignDetailSerializer},
        tags=["Admin - Campaigns"],
    )
    def patch(self, request: Request, campaign_id: str) -> Response:
        ser = CampaignPatchSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        actor = authenticated_user(request)
        updated = update_campaign(
            actor=actor,
            campaign_id=campaign_id,
            data=ser.validated_data,
            request=request,
        )
        return Response(CampaignDetailSerializer(updated).data)


class AdminCampaignMatchingGrantCreateView(APIView):
    """تعریف حامی مضاعف‌کننده (Matching Grant) برای یک حرکت."""

    permission_classes = [IsStaffRole]

    @extend_schema(
        operation_id="v1_admin_campaigns_matching_grants_create",
        summary="ثبت تعهد حامی مضاعف‌کننده برای حرکت",
        request=MatchingGrantWriteSerializer,
        responses={201: MatchingGrantPublicSerializer},
        tags=["Admin - Campaigns"],
    )
    def post(self, request: Request, campaign_id: str) -> Response:
        ser = MatchingGrantWriteSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        actor = authenticated_user(request)
        grant = create_matching_grant(
            actor=actor,
            campaign_id=campaign_id,
            data=ser.validated_data,
            request=request,
        )
        return Response(MatchingGrantPublicSerializer(grant).data, status=status.HTTP_201_CREATED)


class AdminCampaignImpactUpdateCreateView(APIView):
    """انتشار گزارش تصویری پیشرفت میدانی حرکت و اطلاع‌رسانی خودکار به خیرین."""

    permission_classes = [IsStaffRole]

    @extend_schema(
        operation_id="v1_admin_campaigns_impact_updates_create",
        summary="انتشار گزارش پیشرفت میدانی حرکت برای سهام‌داران",
        request=ImpactUpdateWriteSerializer,
        responses={201: CampaignImpactUpdateSerializer},
        tags=["Admin - Campaigns"],
    )
    def post(self, request: Request, campaign_id: str) -> Response:
        ser = ImpactUpdateWriteSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        actor = authenticated_user(request)
        impact = publish_impact_update(
            actor=actor,
            campaign_id=campaign_id,
            data=ser.validated_data,
            request=request,
        )
        return Response(CampaignImpactUpdateSerializer(impact).data, status=status.HTTP_201_CREATED)
