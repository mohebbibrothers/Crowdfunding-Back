"""محدودکننده‌های نرخ درخواست (Rate Limiters) اختصاصی احراز هویت و مشارکت سریع."""

from __future__ import annotations

from rest_framework.throttling import SimpleRateThrottle

from apps.core.middleware import client_ip


class IpScopedRateThrottle(SimpleRateThrottle):
    """پایهٔ محدودکنندهٔ نرخ بر اساس آدرس IP واقعی استخراج‌شدهٔ امن."""

    def get_cache_key(self, request: object, view: object) -> str | None:
        """تولید کلید کش بر پایهٔ IP کلاینت."""
        del view
        raw = getattr(request, "_request", request)
        ident = client_ip(raw) or "unknown"  # type: ignore[arg-type]
        return self.cache_format % {"scope": self.scope, "ident": ident}


class OtpRequestThrottle(IpScopedRateThrottle):
    """سقف درخواست ارسال کد یک‌بارمصرف پیامکی از یک IP."""

    scope = "otp_request"


class OtpVerifyThrottle(IpScopedRateThrottle):
    """سقف تلاش تأیید کد یک‌بارمصرف از یک IP."""

    scope = "otp_verify"
