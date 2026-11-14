"""نماهای HTTP عمومی و مدیریتی خیریه‌ها و قلک‌های عام خیریه."""

from __future__ import annotations

from typing import Any

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.benefactors.models import Benefactor, CharityJar
from apps.benefactors.selectors import (
    get_public_benefactor_by_slug,
    get_public_jar_by_slug_or_code,
    list_admin_benefactors,
    list_public_benefactors,
    list_public_jars,
)
from apps.benefactors.serializers import (
    BenefactorAdminSerializer,
    BenefactorPatchSerializer,
    BenefactorPublicSerializer,
    BenefactorWriteSerializer,
    CharityJarPatchSerializer,
    CharityJarPublicSerializer,
    CharityJarWriteSerializer,
)
from apps.benefactors.services import (
    create_benefactor,
    create_charity_jar,
    deactivate_or_delete_benefactor,
    update_benefactor,
    update_charity_jar,
)
from apps.core.cache import get_or_set_versioned
from apps.core.conditional import conditional_json_response
from apps.core.errors import FeatureDisabledError, NotFoundError
from apps.core.policy import is_feature_enabled
from apps.identity.permissions import IsStaffRole, authenticated_user


class PublicBenefactorListView(APIView):
    """فهرست عمومی خیریه‌ها و نهادهای نیکوکاری فعال."""

    permission_classes = [AllowAny]
    authentication_classes: list[Any] = []

    @extend_schema(
        operation_id="v1_benefactors_list",
        summary="فهرست خیریه‌ها و نهادهای نیکوکاری فعال",
        parameters=[
            OpenApiParameter(name="province", type=str, required=False),
            OpenApiParameter(name="q", type=str, required=False),
        ],
        responses={200: BenefactorPublicSerializer(many=True)},
        tags=["Public - Benefactors & Jars"],
    )
    def get(self, request: Request) -> Response:
        province = request.query_params.get("province")
        search = request.query_params.get("q")
        jar_flag = is_feature_enabled("feature.charity_general_jars")

        def _produce() -> list[dict[str, Any]]:
            qs = list_public_benefactors(province=province, search=search)
            return list(BenefactorPublicSerializer(qs, many=True).data)

        data = get_or_set_versioned(
            "benefactors",
            "global",
            f"list:{province or ''}:{search or ''}:{jar_flag}",
            _produce,
            timeout=45,
        )
        return conditional_json_response(request, data, max_age=15)


class PublicBenefactorDetailView(APIView):
    """جزئیات عمومی پروفایل خیریه از روی نامک."""

    permission_classes = [AllowAny]
    authentication_classes: list[Any] = []

    @extend_schema(
        operation_id="v1_benefactors_retrieve",
        summary="دریافت جزئیات خیریه و قلک‌های عام آن",
        responses={200: BenefactorPublicSerializer},
        tags=["Public - Benefactors & Jars"],
    )
    def get(self, request: Request, slug: str) -> Response:
        jar_flag = is_feature_enabled("feature.charity_general_jars")
        data = get_or_set_versioned(
            "benefactors",
            "global",
            f"detail:{slug}:{jar_flag}",
            lambda: dict(BenefactorPublicSerializer(get_public_benefactor_by_slug(slug=slug)).data),
            timeout=45,
        )
        return conditional_json_response(request, data, max_age=15)


class PublicCharityJarListView(APIView):
    """فهرست عمومی قلک‌های عام خیریه برای مشارکت با مبلغ آزاد."""

    permission_classes = [AllowAny]
    authentication_classes: list[Any] = []

    @extend_schema(
        operation_id="v1_jars_list",
        summary="فهرست قلک‌های عام فعال خیریه‌ها",
        parameters=[OpenApiParameter(name="benefactor", type=str, required=False)],
        responses={200: CharityJarPublicSerializer(many=True)},
        tags=["Public - Benefactors & Jars"],
    )
    def get(self, request: Request) -> Response:
        if not is_feature_enabled("feature.charity_general_jars"):
            raise FeatureDisabledError("قابلیت قلک عام خیریه در حال حاضر غیرفعال است.")
        bslug = request.query_params.get("benefactor")
        data = get_or_set_versioned(
            "jars",
            "global",
            f"list:{bslug or ''}",
            lambda: list(
                CharityJarPublicSerializer(list_public_jars(benefactor_slug=bslug), many=True).data
            ),
            timeout=30,
        )
        return conditional_json_response(request, data, max_age=10)


class PublicCharityJarDetailView(APIView):
    """مشاهدهٔ جزئیات یک قلک عام خیریه با نامک یا کد پیوندک کوتاه."""

    permission_classes = [AllowAny]
    authentication_classes: list[Any] = []

    @extend_schema(
        operation_id="v1_jars_retrieve",
        summary="جزئیات قلک عام خیریه از روی نامک یا کد پیوندک",
        responses={200: CharityJarPublicSerializer},
        tags=["Public - Benefactors & Jars"],
    )
    def get(self, request: Request, identifier: str) -> Response:
        if not is_feature_enabled("feature.charity_general_jars"):
            raise FeatureDisabledError("قابلیت قلک عام خیریه در حال حاضر غیرفعال است.")
        data = get_or_set_versioned(
            "jars",
            "global",
            f"detail:{identifier}",
            lambda: dict(
                CharityJarPublicSerializer(
                    get_public_jar_by_slug_or_code(identifier=identifier)
                ).data
            ),
            timeout=30,
        )
        return conditional_json_response(request, data, max_age=10)


# ── مسیرهای مدیریتی خیریه‌ها و قلک‌ها ─────────────────────────────────────────


class AdminBenefactorListCreateView(APIView):
    """فهرست کامل و ایجاد خیریه/نهاد توسط مدیر سامانه."""

    permission_classes = [IsStaffRole]

    @extend_schema(
        operation_id="v1_admin_benefactors_list",
        summary="فهرست مدیریتی تمام خیریه‌ها",
        parameters=[OpenApiParameter(name="active_only", type=bool, required=False)],
        responses={200: BenefactorAdminSerializer(many=True)},
        tags=["Admin - Benefactors & Jars"],
    )
    def get(self, request: Request) -> Response:
        include_inactive = request.query_params.get("active_only") != "true"
        qs = list_admin_benefactors(include_inactive=include_inactive)
        return Response(BenefactorAdminSerializer(qs, many=True).data)

    @extend_schema(
        operation_id="v1_admin_benefactors_create",
        summary="ایجاد خیریه/نهاد نیکوکاری جدید",
        request=BenefactorWriteSerializer,
        responses={201: BenefactorAdminSerializer},
        tags=["Admin - Benefactors & Jars"],
    )
    def post(self, request: Request) -> Response:
        ser = BenefactorWriteSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        actor = authenticated_user(request)
        benefactor = create_benefactor(actor=actor, data=ser.validated_data, request=request)
        return Response(BenefactorAdminSerializer(benefactor).data, status=status.HTTP_201_CREATED)


class AdminBenefactorDetailView(APIView):
    """مشاهده، ویرایش و غیرفعال‌سازی/حذف خیریه توسط مدیر."""

    permission_classes = [IsStaffRole]

    @extend_schema(
        operation_id="v1_admin_benefactors_retrieve",
        summary="دریافت مشخصات کامل مدیریتی خیریه",
        responses={200: BenefactorAdminSerializer},
        tags=["Admin - Benefactors & Jars"],
    )
    def get(self, request: Request, benefactor_id: str) -> Response:
        del request
        benefactor = Benefactor.objects.filter(pk=benefactor_id).first()
        if benefactor is None:
            raise NotFoundError("خیریهٔ مورد نظر یافت نشد.")
        return Response(BenefactorAdminSerializer(benefactor).data)

    @extend_schema(
        operation_id="v1_admin_benefactors_partial_update",
        summary="ویرایش جزئی مشخصات خیریه",
        request=BenefactorPatchSerializer,
        responses={200: BenefactorAdminSerializer},
        tags=["Admin - Benefactors & Jars"],
    )
    def patch(self, request: Request, benefactor_id: str) -> Response:
        ser = BenefactorPatchSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        actor = authenticated_user(request)
        updated = update_benefactor(
            actor=actor,
            benefactor_id=benefactor_id,
            data=ser.validated_data,
            request=request,
        )
        return Response(BenefactorAdminSerializer(updated).data)

    @extend_schema(
        operation_id="v1_admin_benefactors_destroy",
        summary="حذف خیریهٔ بدون سابقه یا غیرفعال‌سازی ایمن آن",
        parameters=[OpenApiParameter(name="reason", type=str, required=False)],
        responses={
            200: {
                "type": "object",
                "properties": {
                    "deleted": {"type": "boolean"},
                    "deactivated": {"type": "boolean"},
                    "id": {"type": "string"},
                },
            }
        },
        tags=["Admin - Benefactors & Jars"],
    )
    def delete(self, request: Request, benefactor_id: str) -> Response:
        actor = authenticated_user(request)
        reason = str(request.query_params.get("reason") or "")
        result = deactivate_or_delete_benefactor(
            actor=actor,
            benefactor_id=benefactor_id,
            reason=reason,
            request=request,
        )
        return Response(result)


class AdminCharityJarListCreateView(APIView):
    """فهرست و ایجاد قلک عام خیریه در پنل مدیریت."""

    permission_classes = [IsStaffRole]

    @extend_schema(
        operation_id="v1_admin_jars_list",
        summary="فهرست مدیریتی قلک‌های عام خیریه‌ها",
        responses={200: CharityJarPublicSerializer(many=True)},
        tags=["Admin - Benefactors & Jars"],
    )
    def get(self, request: Request) -> Response:
        del request
        qs = CharityJar.objects.select_related("benefactor").order_by("-created_at")
        return Response(CharityJarPublicSerializer(qs, many=True).data)

    @extend_schema(
        operation_id="v1_admin_jars_create",
        summary="ایجاد قلک عام جدید برای خیریه",
        request=CharityJarWriteSerializer,
        responses={201: CharityJarPublicSerializer},
        tags=["Admin - Benefactors & Jars"],
    )
    def post(self, request: Request) -> Response:
        ser = CharityJarWriteSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        actor = authenticated_user(request)
        jar = create_charity_jar(actor=actor, data=ser.validated_data, request=request)
        return Response(CharityJarPublicSerializer(jar).data, status=status.HTTP_201_CREATED)


class AdminCharityJarDetailView(APIView):
    """ویرایش جزئیات و فعال/غیرفعال‌سازی قلک عام خیریه."""

    permission_classes = [IsStaffRole]

    @extend_schema(
        operation_id="v1_admin_jars_partial_update",
        summary="ویرایش تنظیمات قلک عام خیریه",
        request=CharityJarPatchSerializer,
        responses={200: CharityJarPublicSerializer},
        tags=["Admin - Benefactors & Jars"],
    )
    def patch(self, request: Request, jar_id: str) -> Response:
        ser = CharityJarPatchSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        actor = authenticated_user(request)
        jar = update_charity_jar(
            actor=actor,
            jar_id=jar_id,
            data=ser.validated_data,
            request=request,
        )
        return Response(CharityJarPublicSerializer(jar).data)
