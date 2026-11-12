"""سلسله‌مراتب خطاهای دامنه‌ای مستقل از لایهٔ HTTP (سازگار با استاندارد RFC 9457)."""

from __future__ import annotations

from typing import Any


class DomainError(Exception):
    """خطای پایهٔ دامنه که در لایهٔ HTTP به ساختار RFC 9457 تبدیل می‌شود."""

    status_code: int = 400
    code: str = "domain_error"
    title: str = "خطای دامنه"
    default_detail: str = "درخواست با قوانین کسب‌وکار هم‌خوانی ندارد."

    def __init__(
        self,
        detail: str | None = None,
        *,
        code: str | None = None,
        title: str | None = None,
        errors: dict[str, list[str]] | None = None,
        extensions: dict[str, Any] | None = None,
    ) -> None:
        self.detail = detail or self.default_detail
        if code is not None:
            self.code = code
        if title is not None:
            self.title = title
        self.errors = errors or {}
        self.extensions = extensions or {}
        super().__init__(self.detail)


class BadRequestError(DomainError):
    """خطای بدنهٔ بدشکل یا درخواست غیرقابل‌پارس (۴۰۰)."""

    status_code = 400
    code = "malformed_request"
    title = "درخواست نامعتبر"
    default_detail = "ساختار بدنهٔ درخواست معتبر نیست."


class AuthenticationRequiredError(DomainError):
    """خطای نیازمندی به ورود کاربر (۴۰۱)."""

    status_code = 401
    code = "authentication_required"
    title = "نیازمند احراز هویت"
    default_detail = "برای انجام این عملیات ابتدا وارد حساب کاربری خود شوید."


class PermissionDeniedError(DomainError):
    """خطای عدم مجوز دسترسی بر پایهٔ نقش یا عامل دوم (۴۰۳)."""

    status_code = 403
    code = "permission_denied"
    title = "عدم مجوز دسترسی"
    default_detail = "شما مجوز انجام این عملیات را ندارید."


class MfaRequiredError(PermissionDeniedError):
    """نشست کارمند/مدیر هنوز تأیید دومرحله‌ای (TOTP) را نگذرانده است (۴۰۳)."""

    code = "mfa_required"
    title = "تأیید دومرحله‌ای الزامی است"
    default_detail = "برای دسترسی به پنل عملیاتی، ابتدا کد تأیید دومرحله‌ای را وارد کنید."


class StepUpRequiredError(PermissionDeniedError):
    """عملیات حساس نیازمند تأیید تازهٔ TOTP در ۱۰ دقیقهٔ اخیر است (۴۰۳)."""

    code = "step_up_required"
    title = "نیازمند تأیید مجدد امنیتی"
    default_detail = "این عملیات حساس است؛ لطفاً کد تأیید دومرحله‌ای خود را مجدداً وارد کنید."


class NotFoundError(DomainError):
    """منبع یافت نشد یا متعلق به کاربر جاری نیست — ضد افشای مالکیت (۴۰۴)."""

    status_code = 404
    code = "not_found"
    title = "یافت نشد"
    default_detail = "مورد درخواستی یافت نشد."


class ConflictError(DomainError):
    """تصادم وضعیت موجودیت، اتمام سهم یا قفل فیلدهای مالی (۴۰۹)."""

    status_code = 409
    code = "conflict"
    title = "تصادم با وضعیت فعلی"
    default_detail = "وضعیت فعلی اجازهٔ انجام این عملیات را نمی‌دهد."


class IdempotencyConflictError(ConflictError):
    """استفادهٔ مجدد از کلید هم‌توانی با بدنه یا کاربر متفاوت (۴۰۹)."""

    code = "idempotency_conflict"
    title = "تعارض کلید هم‌توانی"
    default_detail = "این کلید هم‌توانی پیش‌تر برای درخواست متفاوتی ثبت شده است."


class ResourceExpiredError(DomainError):
    """انقضای رزرو موقت سهم، لینک یا کد یک‌بارمصرف (۴۱۰)."""

    status_code = 410
    code = "resource_expired"
    title = "منقضی‌شده"
    default_detail = "مهلت استفاده از این مورد به پایان رسیده است."


class ValidationError(DomainError):
    """خطای اعتبارسنجی فیلدها و قواعد کسب‌وکار با بازگشت یک‌جای تمام خطاها (۴۲۲)."""

    status_code = 422
    code = "validation_error"
    title = "خطای اعتبارسنجی داده‌ها"
    default_detail = "برخی از مقادیر واردشده معتبر نیستند."


class FeatureDisabledError(ConflictError):
    """قابلیت انتخابی در سیاست‌های جاری سامانه غیرفعال شده است (۴۰۹)."""

    code = "feature_disabled"
    title = "قابلیت غیرفعال است"
    default_detail = "این قابلیت در تنظیمات فعلی سامانه فعال نیست."


class RateLimitedError(DomainError):
    """عبور از سقف مجاز نرخ درخواست‌ها (۴۲۹)."""

    status_code = 429
    code = "rate_limited"
    title = "تعداد درخواست‌ها بیش از حد مجاز"
    default_detail = "لطفاً چند لحظه صبر کنید و دوباره تلاش نمایید."


class ServiceOverloadedError(DomainError):
    """سد ظرفیت فعال‌شده برای محافظت از کارگرها در اوج بار (۵۰۳)."""

    status_code = 503
    code = "service_overloaded"
    title = "سامانه موقتاً پرمشغله است"
    default_detail = "ترافیک لحظه‌ای بالاست؛ چند ثانیه دیگر دوباره تلاش کنید."
