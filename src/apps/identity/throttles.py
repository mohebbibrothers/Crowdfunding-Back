"""محدودکننده‌های نرخ درخواست (Rate Limiters) مبتنی بر IP امن برای کل سامانه."""

from __future__ import annotations

from rest_framework.throttling import SimpleRateThrottle


class IpScopedRateThrottle(SimpleRateThrottle):
    """پایهٔ محدودکنندهٔ نرخ بر اساس آدرس IP واقعی استخراج‌شدهٔ امن."""

    def get_cache_key(self, request: object, view: object) -> str | None:
        """تولید کلید کش بر پایهٔ IP کلاینت."""
        # واردات درون تابع برای جلوگیری از چرخهٔ واردات هنگام بارگذاری تنظیمات DRF.
        from apps.core.middleware import client_ip

        del view
        raw = getattr(request, "_request", request)
        ident = client_ip(raw) or "unknown"  # type: ignore[arg-type]
        return self.cache_format % {"scope": self.scope, "ident": ident}


class StandardIpThrottle(IpScopedRateThrottle):
    """سقف پیش‌فرض تمام نقاط پایانی (جلوگیری از اسکن و سوءاستفادهٔ ناشناس)."""

    scope = "anon_public"


class CheckoutThrottle(IpScopedRateThrottle):
    """سقف آغاز مشارکت مالی برای مهار رزرو انبوه سهام توسط یک عامل مخرب."""

    scope = "checkout"


class OtpRequestThrottle(IpScopedRateThrottle):
    """سقف درخواست ارسال کد یک‌بارمصرف پیامکی از یک IP."""

    scope = "otp_request"


class OtpVerifyThrottle(IpScopedRateThrottle):
    """سقف تلاش تأیید کد یک‌بارمصرف از یک IP."""

    scope = "otp_verify"


class MfaVerifyThrottle(IpScopedRateThrottle):
    """سقف تلاش تأیید کد TOTP / کد بازیابی (ضد حدس زدن عامل دوم)."""

    scope = "mfa_verify"
