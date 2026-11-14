"""میان‌افزارهای امنیتی، ردیابی درخواست، کنترل کش، سد ظرفیت و محافظت از لاگین ادمین."""

from __future__ import annotations

from collections.abc import Callable
import ipaddress
import logging
import re
import secrets
import threading
import time
from typing import Any, Final

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.http import HttpRequest, HttpResponse
from django.utils.crypto import salted_hmac
import structlog

from apps.core.metrics import HTTP_REQUEST_DURATION_SECONDS, HTTP_REQUESTS_TOTAL
from apps.core.problems import json_problem_response
from apps.core.uuid7 import uuid7_hex

logger = logging.getLogger(__name__)

_SAFE_REQ_ID_RE = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
_PERSONAL_PREFIXES = ("/api/v1/me", "/api/v1/auth", "/api/v1/admin")
_DOCS_PREFIXES = ("/api/v1/docs", "/api/v1/redoc", "/api/v1/schema")
# Swagger UI / ReDoc از CDN مجاز drf-spectacular بارگذاری میشوند؛ CSP سختگیرانهٔ
# پیشفرض آنها را مسدود میکرد و صفحهٔ مستندات خالی رندر میشد.
_DOCS_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com; "
    "img-src 'self' data: https://cdn.jsdelivr.net; "
    "font-src 'self' data: https://fonts.gstatic.com; "
    "connect-src 'self' https://cdn.jsdelivr.net; "
    "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
)
_ADMIN_GUARD_SALT: Final[str] = "crowdfunding.admin_login_guard"
_KEY_CEILING_SECONDS: Final[int] = 86_400


def client_ip(request: HttpRequest) -> str:
    """استخراج امن IP واقعی کلاینت با رعایت دقیق تعداد پروکسی‌های مورد اعتماد."""
    trusted_hops = int(getattr(settings, "TRUSTED_PROXY_COUNT", 0))
    remote_addr = (request.META.get("REMOTE_ADDR") or "").strip()
    if trusted_hops > 0:
        xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
        chain = [part.strip() for part in xff.split(",") if part.strip()]
        if chain:
            idx = max(len(chain) - trusted_hops, 0)
            candidate = chain[idx]
            try:
                ipaddress.ip_address(candidate)
                return str(candidate)
            except ValueError:
                pass
    try:
        ipaddress.ip_address(remote_addr)
        return str(remote_addr)
    except ValueError:
        return ""


def request_metadata(request: HttpRequest | None) -> dict[str, str]:
    """استخراج متادیتای استاندارد درخواست برای ثبت در حسابرسی و لاگ."""
    if request is None:
        return {"request_id": "", "ip": "", "user_agent": "", "path": "", "method": ""}
    return {
        "request_id": str(getattr(request, "trace_id", "") or ""),
        "ip": client_ip(request),
        "user_agent": (request.META.get("HTTP_USER_AGENT") or "")[:300],
        "path": request.path[:200],
        "method": request.method or "",
    }


class RequestContextMiddleware:
    """تزریق شناسهٔ ردیابی (``X-Request-ID``)، هدرهای بودجهٔ کارایی و ثبت متریک‌ها."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self._get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        incoming_id = (request.META.get("HTTP_X_REQUEST_ID") or "").strip()
        trace_id = incoming_id if _SAFE_REQ_ID_RE.match(incoming_id) else uuid7_hex()
        request.trace_id = trace_id  # type: ignore[attr-defined]
        request.csp_nonce = secrets.token_urlsafe(16)  # type: ignore[attr-defined]

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(trace_id=trace_id, path=request.path)

        start = time.perf_counter()
        initial_queries = len(connection.queries) if settings.DEBUG else 0

        response = self._get_response(request)

        elapsed_sec = max(time.perf_counter() - start, 0.0)
        elapsed_ms = round(elapsed_sec * 1000, 2)
        response["X-Request-ID"] = trace_id
        response["X-Response-Time-ms"] = f"{elapsed_ms:.2f}"
        if settings.DEBUG:
            query_count = max(len(connection.queries) - initial_queries, 0)
            response["X-DB-Query-Count"] = str(query_count)

        resolver_match = getattr(request, "resolver_match", None)
        route_label = getattr(resolver_match, "route", None) or "unmatched"
        HTTP_REQUESTS_TOTAL.labels(
            method=request.method or "GET",
            route=route_label,
            status=str(response.status_code),
        ).inc()
        HTTP_REQUEST_DURATION_SECONDS.labels(
            method=request.method or "GET",
            route=route_label,
        ).observe(elapsed_sec)
        return response


class SecurityAndCacheHeadersMiddleware:
    """اعمال هدرهای امنیتی مرورگر، CSP با nonce و جلوگیری مطلق از کش شدن خطاها و داده‌های شخصی."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self._get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if request.path.startswith("/.env") or request.path.startswith("/.git"):
            return json_problem_response(
                status=404,
                code="not_found",
                title="یافت نشد",
                detail="مسیر درخواستی وجود ندارد.",
                request=request,
            )

        response = self._get_response(request)

        nonce = getattr(request, "csp_nonce", "")
        is_docs = request.path.startswith(_DOCS_PREFIXES)
        if is_docs:
            response["Content-Security-Policy"] = _DOCS_CSP
        elif "Content-Security-Policy" not in response:
            script_src = f"'self' 'nonce-{nonce}'" if nonce else "'self'"
            response["Content-Security-Policy"] = (
                f"default-src 'self'; script-src {script_src}; "
                "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
                "font-src 'self' data:; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
            )
        response.setdefault("X-Content-Type-Options", "nosniff")
        response.setdefault("X-Frame-Options", "DENY")
        response.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.setdefault(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=(), payment=()",
        )

        admin_prefix = f"/{str(settings.ADMIN_URL_PATH).strip('/')}"
        is_personal = request.path.startswith((*_PERSONAL_PREFIXES, admin_prefix))
        if response.status_code >= 400 or is_personal:
            response["Cache-Control"] = "private, no-store"
        return response


class LoadSheddingMiddleware:
    """سد ظرفیت سبک برای محافظت از کارگرهای هم‌زمان Passenger/WSGI در موج‌های ناگهانی ترافیک."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self._get_response = get_response
        max_inflight = int(getattr(settings, "MAX_INFLIGHT_REQUESTS", 64))
        self._semaphore = threading.BoundedSemaphore(max(max_inflight, 1))

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if request.path.startswith("/api/v1/health") or request.path == "/metrics":
            return self._get_response(request)

        acquired = self._semaphore.acquire(blocking=False)
        if not acquired:
            return json_problem_response(
                status=503,
                code="service_overloaded",
                title="سامانه موقتاً پرمشغله است",
                detail="ظرفیت پردازش هم‌زمان پر است؛ لطفاً ۵ ثانیه دیگر تلاش کنید.",
                request=request,
                headers={"Retry-After": "5"},
            )
        try:
            return self._get_response(request)
        finally:
            self._semaphore.release()


class AdminLoginGuardMiddleware:
    """قفل ضد Brute-Force روی صفحهٔ ورود پنل مدیریت جنگو بر پایهٔ کد وضعیت پاسخ (302/200)."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self._get_response = get_response

    @staticmethod
    def _admin_login_path() -> str:
        prefix = str(getattr(settings, "DJANGO_ADMIN_URL_PREFIX", "django-admin")).strip("/")
        return f"/{prefix}/login/"

    @staticmethod
    def _keys(request: HttpRequest) -> tuple[str, str]:
        ip = client_ip(request) or "unknown"
        username = str(request.POST.get("username", "")).strip().lower()
        pair_digest = salted_hmac(
            _ADMIN_GUARD_SALT, f"pair|{ip}|{username}", algorithm="sha256"
        ).hexdigest()[:32]
        ip_digest = salted_hmac(_ADMIN_GUARD_SALT, f"ip|{ip}", algorithm="sha256").hexdigest()[:32]
        return f"admguard:pair:{pair_digest}", f"admguard:ip:{ip_digest}"

    def __call__(self, request: HttpRequest) -> HttpResponse:
        is_login_post = request.method == "POST" and request.path == self._admin_login_path()
        pair_key, ip_key = ("", "")
        if is_login_post:
            pair_key, ip_key = self._keys(request)
            wait_sec = self._remaining_lockout(pair_key, ip_key)
            if wait_sec > 0:
                resp = HttpResponse(
                    "<h1>429 — تلاش بیش از حد مجاز</h1>"
                    "<p>به دلیل تلاش‌های ناموفق متوالی، ورود موقتاً مسدود شده است.</p>",
                    status=429,
                    content_type="text/html; charset=utf-8",
                )
                resp["Retry-After"] = str(wait_sec)
                return resp

        response = self._get_response(request)

        if is_login_post:
            if response.status_code == 302:
                self._clear_counters(pair_key, ip_key)
            elif response.status_code == 200:
                self._record_failure(pair_key, ip_key)
        return response

    @staticmethod
    def _remaining_lockout(pair_key: str, ip_key: str) -> int:
        now = time.time()
        remaining = 0
        for key in (pair_key, ip_key):
            try:
                until: Any = cache.get(f"{key}:block")
            except Exception:  # pragma: no cover
                logger.debug("admin_guard_cache_read_degraded")
                until = None
            if isinstance(until, (int, float)) and until > now:
                remaining = max(remaining, int(until - now))
        return remaining

    @staticmethod
    def _record_failure(pair_key: str, ip_key: str) -> None:
        pair_limit = max(int(getattr(settings, "ADMIN_LOGIN_MAX_FAILURES", 5)), 1)
        ip_limit = max(int(getattr(settings, "ADMIN_LOGIN_MAX_FAILURES_PER_IP", 20)), 1)
        lockout = min(
            int(getattr(settings, "ADMIN_LOGIN_LOCKOUT_SECONDS", 900)), _KEY_CEILING_SECONDS
        )
        for key, threshold in ((pair_key, pair_limit), (ip_key, ip_limit)):
            try:
                count = 1 if cache.add(key, 1, timeout=lockout) else int(cache.incr(key))
                if count >= threshold:
                    cache.set(f"{key}:block", time.time() + lockout, timeout=lockout)
            except Exception:  # pragma: no cover
                logger.warning("admin_guard_cache_degraded")

    @staticmethod
    def _clear_counters(pair_key: str, ip_key: str) -> None:
        for key in (pair_key, ip_key):
            try:
                cache.delete(key)
                cache.delete(f"{key}:block")
            except Exception:  # pragma: no cover
                logger.debug("admin_guard_cache_clear_degraded")
