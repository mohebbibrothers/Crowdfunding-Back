"""قرارداد جهانی خطا بر پایهٔ استاندارد RFC 9457 (Problem Details for HTTP APIs).

نگاشت کدهای وضعیت:
    • 400: بدنهٔ بدشکل (JSON غیرقابل‌پارس)
    • 401: عدم احراز هویت یا نشست باطل‌شده
    • 403: عدم مجوز، ``mfa_required`` یا ``step_up_required``
    • 404: منبع ناموجود یا عدم مالکیت (ضد افشای شناسه)
    • 409: تصادم وضعیت، اتمام ظرفیت سهم، یا تعارض کلید هم‌توانی
    • 410: انقضای رزرو موقت یا توکن زمان‌دار
    • 422: تمامی خطاهای اعتبارسنجی فیلدها به‌صورت تجمیعی در کلید ``errors``
    • 429: عبور از سقف نرخ درخواست (همراه با هدر ``Retry-After``)
    • 503: خارج از ظرفیت موقت (همراه با هدر ``Retry-After``)
"""

from __future__ import annotations

import logging
from typing import Any

from django.conf import settings
from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.http import Http404, JsonResponse
from rest_framework import exceptions as drf_exc
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import set_rollback

from apps.core.errors import DomainError
from apps.core.uuid7 import uuid7_hex

logger = logging.getLogger(__name__)

PROBLEM_MEDIA_TYPE = "application/problem+json"


class ProblemJSONRenderer(JSONRenderer):
    """رندرر اختصاصی پاسخ‌های خطای منطبق بر ``application/problem+json``."""

    media_type = PROBLEM_MEDIA_TYPE
    charset = "utf-8"


def problem_type_uri(code: str) -> str:
    """ساخت نشانی پایدار نوع خطا بر پایهٔ دامنهٔ مستندات سامانه."""
    base = getattr(settings, "PROBLEM_DOCS_BASE_URL", "https://docs.crowdfunding.ir/problems")
    return f"{base.rstrip('/')}/{code}"


def _extract_trace_id(request: Any) -> str:
    """استخراج شناسهٔ ردیابی درخواست جاری یا تولید شناسهٔ پشتیبان."""
    if request is not None:
        raw = getattr(request, "_request", request)
        existing = getattr(raw, "trace_id", None) or getattr(request, "trace_id", None)
        if existing:
            return str(existing)
    return uuid7_hex()


def _flatten_drf_errors(detail: Any) -> dict[str, list[str]]:
    """تبدیل ساختار تودرتوی خطاهای DRF به نقشهٔ تخت ``field -> [messages]``."""
    errors: dict[str, list[str]] = {}
    if isinstance(detail, dict):
        for field_name, value in detail.items():
            key = str(field_name)
            if isinstance(value, list):
                errors[key] = [str(item) for item in value]
            elif isinstance(value, dict):
                nested = _flatten_drf_errors(value)
                for sub_key, sub_msgs in nested.items():
                    errors[f"{key}.{sub_key}"] = sub_msgs
            else:
                errors[key] = [str(value)]
    elif isinstance(detail, list):
        errors["non_field_errors"] = [str(item) for item in detail]
    else:
        errors["non_field_errors"] = [str(detail)]
    return errors


def build_problem_payload(
    *,
    status: int,
    code: str,
    title: str,
    detail: str,
    instance: str,
    trace_id: str,
    errors: dict[str, list[str]] | None = None,
    extensions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """ساخت دیکشنری استاندارد بدنهٔ RFC 9457."""
    payload: dict[str, Any] = {
        "type": problem_type_uri(code),
        "title": title,
        "status": status,
        "detail": detail,
        "code": code,
        "instance": instance,
        "trace_id": trace_id,
    }
    if errors:
        payload["errors"] = errors
    if extensions:
        for ext_key, ext_val in extensions.items():
            if ext_key not in payload:
                payload[ext_key] = ext_val
    return payload


def problem_response(
    *,
    status: int,
    code: str,
    title: str,
    detail: str,
    request: Any = None,
    errors: dict[str, list[str]] | None = None,
    extensions: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> Response:
    """تولید شیء ``Response`` در قالب استاندارد ``application/problem+json``."""
    instance = getattr(request, "path", "/") if request is not None else "/"
    trace_id = _extract_trace_id(request)
    body = build_problem_payload(
        status=status,
        code=code,
        title=title,
        detail=detail,
        instance=instance,
        trace_id=trace_id,
        errors=errors,
        extensions=extensions,
    )
    resp = Response(body, status=status, content_type=PROBLEM_MEDIA_TYPE, headers=headers)
    resp.accepted_renderer = ProblemJSONRenderer()
    resp.accepted_media_type = PROBLEM_MEDIA_TYPE
    resp_any: Any = resp
    resp_any.renderer_context = {}
    return resp


def json_problem_response(
    *,
    status: int,
    code: str,
    title: str,
    detail: str,
    request: Any = None,
    headers: dict[str, str] | None = None,
) -> JsonResponse:
    """تولید ``JsonResponse`` خام جنگو (برای میان‌افزارهای خارج از چرخهٔ DRF)."""
    instance = getattr(request, "path", "/") if request is not None else "/"
    trace_id = _extract_trace_id(request)
    body = build_problem_payload(
        status=status,
        code=code,
        title=title,
        detail=detail,
        instance=instance,
        trace_id=trace_id,
    )
    resp = JsonResponse(body, status=status, content_type=PROBLEM_MEDIA_TYPE)
    if headers:
        for key, value in headers.items():
            resp[key] = value
    return resp


def custom_exception_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    """هندلر مرکزی استثناهای DRF برای تبدیل تمام خطاها به RFC 9457 بدون نشت جزئیات داخلی."""
    request = context.get("request")
    set_rollback()

    if isinstance(exc, DomainError):
        headers: dict[str, str] = {}
        retry_after = exc.extensions.get("retry_after")
        if retry_after is not None:
            headers["Retry-After"] = str(int(retry_after))
        return problem_response(
            status=exc.status_code,
            code=exc.code,
            title=exc.title,
            detail=exc.detail,
            request=request,
            errors=exc.errors or None,
            extensions=exc.extensions or None,
            headers=headers or None,
        )

    if isinstance(exc, drf_exc.ParseError):
        return problem_response(
            status=400,
            code="malformed_request",
            title="درخواست بدشکل",
            detail="ساختار JSON یا بدنهٔ ارسالی قابل خواندن نیست.",
            request=request,
        )

    if isinstance(exc, drf_exc.ValidationError):
        flat_errors = _flatten_drf_errors(exc.detail)
        return problem_response(
            status=422,
            code="validation_error",
            title="خطای اعتبارسنجی ورودی",
            detail="لطفاً خطاهای مشخص‌شده در فیلدها را برطرف کنید.",
            request=request,
            errors=flat_errors,
        )

    if isinstance(exc, (drf_exc.NotAuthenticated, drf_exc.AuthenticationFailed)):
        detail = (
            str(exc.detail) if isinstance(exc.detail, str) else "ورود به حساب کاربری الزامی است."
        )
        return problem_response(
            status=401,
            code="authentication_required",
            title="احراز هویت ناموفق",
            detail=detail,
            request=request,
        )

    if isinstance(exc, (drf_exc.PermissionDenied, DjangoPermissionDenied)):
        detail = (
            str(exc.detail)
            if isinstance(exc, drf_exc.PermissionDenied) and isinstance(exc.detail, str)
            else "شما دسترسی لازم برای این عملیات را ندارید."
        )
        return problem_response(
            status=403,
            code="permission_denied",
            title="عدم مجوز دسترسی",
            detail=detail,
            request=request,
        )

    if isinstance(exc, (Http404, drf_exc.NotFound)):
        return problem_response(
            status=404,
            code="not_found",
            title="یافت نشد",
            detail="منبع مورد نظر یافت نشد.",
            request=request,
        )

    if isinstance(exc, drf_exc.MethodNotAllowed):
        return problem_response(
            status=405,
            code="method_not_allowed",
            title="متد غیرمجاز",
            detail="متد HTTP ارسالی برای این مسیر پشتیبانی نمی‌شود.",
            request=request,
        )

    if isinstance(exc, drf_exc.Throttled):
        raw_wait = getattr(exc, "wait", None)
        wait_seconds = max(int(raw_wait or 60), 1)
        return problem_response(
            status=429,
            code="rate_limited",
            title="عبور از سقف مجاز درخواست",
            detail="تعداد درخواست‌های شما بیش از حد مجاز است؛ کمی بعد تلاش کنید.",
            request=request,
            extensions={"retry_after": wait_seconds},
            headers={"Retry-After": str(wait_seconds)},
        )

    logger.error(
        "unhandled_api_exception", exc_info=exc, extra={"path": getattr(request, "path", "")}
    )
    return problem_response(
        status=500,
        code="internal_error",
        title="خطای داخلی سامانه",
        detail="خطای غیرمنتظره‌ای رخ داد. لطفاً کد پیگیری را نگه دارید.",
        request=request,
    )


def not_found_handler(request: Any, exception: Exception | None = None) -> JsonResponse:
    """پاسخ ۴۰۴ سطح مسیریاب ریشه جنگو در قالب استاندارد RFC 9457."""
    del exception
    return json_problem_response(
        status=404,
        code="not_found",
        title="یافت نشد",
        detail="مسیر درخواستی در این نسخه از API وجود ندارد.",
        request=request,
    )


def server_error_handler(request: Any) -> JsonResponse:
    """پاسخ ۵۰۰ سطح مسیریاب ریشه جنگو در قالب استاندارد RFC 9457."""
    return json_problem_response(
        status=500,
        code="internal_error",
        title="خطای داخلی سامانه",
        detail="خطای غیرمنتظره‌ای در پردازش درخواست رخ داد.",
        request=request,
    )
