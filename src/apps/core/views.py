"""نماهای HTTP هستهٔ مشترک: متادیتای نسخه، CSRF، بررسی سلامت، متریک و مدیریت سیاست‌ها."""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.middleware.csrf import get_token
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.choices import AuditAction
from apps.audit.services import AuditEntry, record_audit
from apps.core.conditional import conditional_json_response
from apps.core.health import build_detailed_health, check_cache, check_database
from apps.core.jalali import today_jalali
from apps.core.metrics import render_prometheus_metrics
from apps.core.models import PolicyRule
from apps.core.policy import POLICY_REGISTRY, get_all_policies, set_policy_value
from apps.core.serializers import (
    FinancialHealthSerializer,
    HealthStatusSerializer,
    LateCaptureReconcileInputSerializer,
    LateCaptureReconcileResultSerializer,
    PlatformMetaSerializer,
    PolicyRuleOutputSerializer,
    PolicyUpdateInputSerializer,
    RefundDispatchResultSerializer,
)
from apps.identity.permissions import (
    HasFreshMfa,
    IsFinanceOrSuperAdmin,
    IsStaffRole,
    authenticated_user,
)


class PlatformMetaView(APIView):
    """اطلاعات نسخهٔ قرارداد API، واحد پولی، تاریخ شمسی و کلیدهای فعال محصول."""

    permission_classes = [AllowAny]

    @extend_schema(
        operation_id="v1_meta_retrieve",
        summary="دریافت متادیتای نسخهٔ API و قابلیت‌های فعال سامانه",
        responses={200: PlatformMetaSerializer},
        tags=["System"],
    )
    def get(self, request: Request) -> Response:
        """برگرداندن متادیتای بوت‌استرپ فرانت‌اند همراه با پشتیبانی از ETag."""
        policies = get_all_policies()
        features = {
            key.removeprefix("feature."): bool(val)
            for key, val in policies.items()
            if key.startswith("feature.")
        }
        payload = {
            "service": "crowdfunding-back",
            "environment": getattr(settings, "ENVIRONMENT", "development"),
            "api_version": "v1",
            "app_version": str(settings.APP_VERSION),
            "supported_versions": ["v1"],
            "currency_base": "IRR",
            "currency_display_units": ["IRR", "TOMAN"],
            "timezone": settings.TIME_ZONE,
            "today_jalali": today_jalali(),
            "features": features,
            "share_hold_ttl_minutes": int(policies.get("share.hold_ttl_minutes", 15)),
        }
        return conditional_json_response(request, payload, version_hint="meta-v1", max_age=30)


class CsrfBootstrapView(APIView):
    """کاشت کوکی CSRF برای کلاینت‌های مرورگری هم‌مبدأ پیش از اولین درخواست نوشتنی."""

    permission_classes = [AllowAny]

    @extend_schema(
        operation_id="v1_csrf_bootstrap",
        summary="دریافت و کاشت توکن CSRF برای نشست‌های کوکی‌محور",
        responses={
            200: {
                "type": "object",
                "properties": {"csrf_token": {"type": "string"}},
                "required": ["csrf_token"],
            }
        },
        tags=["System"],
    )
    def get(self, request: Request) -> Response:
        """تولید توکن CSRF و ارسال در کوکی و بدنه.

        این توکن برای نشست کوکی‌محور تنها منبع معتبر است: پس از هر ورود/چرخش نشست،
        CsrfViewMiddleware توکن کوکی را عوض می‌کند و کلاینت باید مقدار تازه را بگیرد.
        """
        token = get_token(request._request)
        resp = Response({"csrf_token": token})
        resp["Cache-Control"] = "private, no-store"
        return resp


class HealthLiveView(APIView):
    """بررسی زنده بودن پروسهٔ وب‌سرور (بدون وابستگی به دیتابیس)."""

    permission_classes = [AllowAny]
    throttle_classes = []

    @extend_schema(
        operation_id="v1_health_live",
        summary="بررسی زنده بودن فرآیند برنامه (Liveness)",
        responses={200: HealthStatusSerializer},
        tags=["System"],
    )
    def get(self, request: Request) -> Response:
        """پاسخ سریع ۲۰۰ برای پروب زنده بودن."""
        del request
        return Response({"status": "alive"})


class HealthReadyView(APIView):
    """بررسی آمادگی سرویس برای پذیرش ترافیک (اتصال دیتابیس و کش)."""

    permission_classes = [AllowAny]
    throttle_classes = []

    @extend_schema(
        operation_id="v1_health_ready",
        summary="بررسی آمادگی دیتابیس و کش (Readiness)",
        responses={200: HealthStatusSerializer, 503: HealthStatusSerializer},
        tags=["System"],
    )
    def get(self, request: Request) -> Response:
        """بررسی اتصال زنده به MariaDB و انبار کش."""
        del request
        db_ok, db_msg = check_database()
        cache_ok, cache_msg = check_cache()
        ready = db_ok and cache_ok
        return Response(
            {
                "status": "ready" if ready else "not_ready",
                "checks": {
                    "database": {"ok": db_ok, "detail": db_msg},
                    "cache": {"ok": cache_ok, "detail": cache_msg},
                },
            },
            status=200 if ready else 503,
        )


class HealthDetailedView(APIView):
    """گزارش کامل سلامت عملیاتی مخصوص تیم عملیات و کارکنان."""

    permission_classes = [IsStaffRole]

    @extend_schema(
        operation_id="v1_health_detailed",
        summary="بررسی عمیق سلامت دیتابیس، کش، Outbox و زنجیرهٔ حسابرسی",
        responses={200: HealthStatusSerializer, 503: HealthStatusSerializer},
        tags=["Admin - System"],
    )
    def get(self, request: Request) -> Response:
        """اجرای بررسی جامع زیرساخت."""
        del request
        ok, report = build_detailed_health(include_audit=True)
        return Response(report, status=200 if ok else 503)


class AdminPolicyListView(APIView):
    """فهرست تمام سیاست‌های پویا و کلیدهای قابلیت‌های سامانه."""

    permission_classes = [IsStaffRole]

    @extend_schema(
        operation_id="v1_admin_policies_list",
        summary="مشاهدهٔ فهرست سیاست‌های زمان اجرا و وضعیت کلیدهای قابلیت‌ها",
        responses={200: PolicyRuleOutputSerializer(many=True)},
        tags=["Admin - Governance"],
    )
    def get(self, request: Request) -> Response:
        """بازگرداندن فهرست کامل سیاست‌ها همراه با نسخهٔ فعلی هر قانون."""
        del request
        current_values = get_all_policies()
        db_versions = dict(PolicyRule.objects.values_list("key", "version"))
        rows: list[dict[str, Any]] = []
        for spec in POLICY_REGISTRY.values():
            rows.append(
                {
                    "key": spec.key,
                    "value_type": spec.value_type,
                    "value": current_values.get(spec.key, spec.default),
                    "default": spec.default,
                    "description": spec.description,
                    "version": db_versions.get(spec.key, 0),
                }
            )
        return Response(rows)


class AdminPolicyUpdateView(APIView):
    """ویرایش نسخه‌دار یک سیاست سامانه توسط مدیر ارشد همراه با تأیید تازهٔ TOTP و دلیل."""

    permission_classes = [IsFinanceOrSuperAdmin, HasFreshMfa]

    @extend_schema(
        operation_id="v1_admin_policies_update",
        summary="تغییر نسخه‌دار یک سیاست سامانه با الزام دلیل و Step-Up MFA",
        request=PolicyUpdateInputSerializer,
        responses={200: PolicyRuleOutputSerializer},
        tags=["Admin - Governance"],
    )
    def post(self, request: Request, policy_key: str) -> Response:
        """اعمال تغییر سیاست و ثبت در زنجیرهٔ حسابرسی."""
        serializer = PolicyUpdateInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        actor = authenticated_user(request)
        rule = set_policy_value(
            key=policy_key,
            value=serializer.validated_data["value"],
            reason=serializer.validated_data["reason"],
            actor_id=actor.id,
        )
        record_audit(
            AuditEntry(
                action=AuditAction.POLICY_CHANGED,
                actor_id=actor.id,
                actor_label=actor.display_name,
                target_type="policy",
                target_id=rule.key,
                reason=serializer.validated_data["reason"],
                metadata={"version": rule.version, "new_value": rule.raw_value},
                request=request._request,
            )
        )
        spec = POLICY_REGISTRY[rule.key]
        return Response(
            {
                "key": rule.key,
                "value_type": rule.value_type,
                "value": rule.raw_value,
                "default": spec.default,
                "description": spec.description,
                "version": rule.version,
            }
        )


class AdminFinancialHealthView(APIView):
    """پنل «سلامت مالی» — پاسخ یک‌نگاهی به پرسش «آیا پولی گم شده است؟»

    این نقطهٔ پایانی، حلقهٔ وجه را از سه زاویه اندازه می‌گیرد و هشدارهای
    ماشین‌خوان می‌دهد تا شیفت عملیات بدون هیچ کوئری دستی بداند وضعیت چیست.
    """

    permission_classes = [IsStaffRole]

    @extend_schema(
        operation_id="v1_admin_financial_health_retrieve",
        summary="گزارش سلامت حلقهٔ وجه: پرداخت‌های رهاشده، تعهدهای بازپرداخت و هشدارها",
        responses={200: FinancialHealthSerializer},
        tags=["Admin - System"],
    )
    def get(self, request: Request) -> Response:
        """تولید گزارش سلامت مالی از داده‌های جاری."""
        del request
        from apps.contributions.financial_health import build_financial_health

        return Response(build_financial_health())


class AdminLateCaptureReconcileView(APIView):
    """اجرای دستی داوری پرداخت‌های رهاشده از پنل مدیریت (با قابلیت پیش‌نمایش)."""

    permission_classes = [IsFinanceOrSuperAdmin]

    @extend_schema(
        operation_id="v1_admin_late_captures_reconcile",
        summary="اجرای دستی داوری پرداخت‌های رهاشده با استعلام مستقیم از درگاه",
        request=LateCaptureReconcileInputSerializer,
        responses={200: LateCaptureReconcileResultSerializer},
        tags=["Admin - System"],
    )
    def post(self, request: Request) -> Response:
        """داوری دسته‌ای پرداخت‌های رهاشده و بازگشت آمار."""
        from apps.contributions.services import reconcile_abandoned_payments

        ser = LateCaptureReconcileInputSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        stats = reconcile_abandoned_payments(
            batch_size=int(ser.validated_data["batch_size"]),
            dry_run=bool(ser.validated_data["dry_run"]),
        )
        return Response(stats)


class AdminRefundDispatchView(APIView):
    """ارسال دسته‌ای تعهدهای بازپرداخت باز به درگاه (اجرای دستی همان کرون)."""

    permission_classes = [IsFinanceOrSuperAdmin]

    @extend_schema(
        operation_id="v1_admin_refunds_dispatch",
        summary="ارسال تعهدهای بازپرداخت معلق به درگاه پرداخت",
        request=None,
        responses={200: RefundDispatchResultSerializer},
        tags=["Admin - System"],
    )
    def post(self, request: Request) -> Response:
        """اجرای ارسال و بازگشت آمار نتیجه."""
        del request
        from apps.contributions.services import dispatch_pending_refunds

        return Response(dispatch_pending_refunds())


def prometheus_metrics_view(request: HttpRequest) -> HttpResponse:
    """نمایش متریک‌های Prometheus (در تولید محدود به توکن پایش یا شبکهٔ داخلی)."""
    expected_token = str(getattr(settings, "METRICS_BEARER_TOKEN", "") or "")
    if expected_token:
        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        if auth_header != f"Bearer {expected_token}":
            return HttpResponse("Forbidden", status=403, content_type="text/plain")
    payload, content_type = render_prometheus_metrics()
    return HttpResponse(payload, content_type=content_type)


def docs_protected_wrapper(view_func: Any) -> Any:
    """محافظت از صفحات Swagger/ReDoc/Schema در محیط تولید (فقط کارکنان یا در صورت باز بودن پرچم)."""

    def _wrapped(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        if settings.DEBUG or getattr(settings, "API_DOCS_ALLOW_ANONYMOUS", False):
            return view_func(request, *args, **kwargs)  # type: ignore[no-any-return]
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and getattr(user, "is_staff_member", False):
            return view_func(request, *args, **kwargs)  # type: ignore[no-any-return]
        admin_prefix = str(settings.ADMIN_URL_PATH).strip("/")
        resp = HttpResponse(status=302)
        resp["Location"] = f"/{admin_prefix}/login/?next={request.path}"
        return resp

    return _wrapped
