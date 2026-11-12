"""کلاس‌های احراز هویت دوگانه: SessionAwareJWTAuthentication و SessionAwareCookieAuthentication."""

from __future__ import annotations

from datetime import timedelta
from typing import Any, cast

from django.utils import timezone
from drf_spectacular.extensions import OpenApiAuthenticationExtension
from rest_framework.authentication import SessionAuthentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import AuthUser, JWTAuthentication
from rest_framework_simplejwt.tokens import Token

from apps.identity.models import User, UserSession

TOUCH_INTERVAL = timedelta(minutes=5)


def _touch_user_session(session_obj: UserSession) -> None:
    """به‌روزرسانی کم‌هزینهٔ زمان آخرین فعالیت نشست حداکثر هر ۵ دقیقه یک‌بار."""
    now = timezone.now()
    if (now - session_obj.last_seen_at) >= TOUCH_INTERVAL:
        UserSession.objects.filter(pk=session_obj.pk, revoked_at__isnull=True).update(
            last_seen_at=now
        )
        session_obj.last_seen_at = now


class SessionAwareJWTAuthentication(JWTAuthentication):
    """احراز هویت JWT گره‌خورده به جدول ``UserSession`` برای ابطال آنی توکن‌ها."""

    def authenticate(self, request: Any) -> tuple[AuthUser, Token] | None:
        """اعتبارسنجی امضای JWT و بررسی فعال بودن ردیف نشست متناظر در دیتابیس."""
        result = super().authenticate(request)
        if result is None:
            return None
        user, validated_token = result
        if not isinstance(user, User) or not user.is_active:
            raise AuthenticationFailed("حساب کاربری غیرفعال است.")

        sid = str(validated_token.get("sid") or "")
        if not sid:
            raise AuthenticationFailed("توکن فاقد شناسهٔ نشست معتبر است.")

        session_obj = UserSession.objects.filter(pk=sid, user=user, revoked_at__isnull=True).first()
        if session_obj is None:
            raise AuthenticationFailed("این نشست باطل شده است؛ لطفاً مجدداً وارد شوید.")

        _touch_user_session(session_obj)
        raw_req = getattr(request, "_request", request)
        raw_req.active_user_session = session_obj
        request.active_user_session = session_obj
        return cast("tuple[AuthUser, Token]", (user, validated_token))


class SessionAwareCookieAuthentication(SessionAuthentication):
    """احراز هویت کوکی جنگو همراه با بررسی CSRF و تطابق با ``UserSession`` فعال."""

    def authenticate(self, request: Any) -> tuple[User, None] | None:
        """بررسی نشست کوکی، اجرای محافظت CSRF و اتصال شیء ``UserSession`` به درخواست."""
        result = super().authenticate(request)
        if result is None:
            return None
        user, _ = result
        if not isinstance(user, User) or not user.is_active:
            return None

        raw_req = getattr(request, "_request", request)
        django_session = getattr(raw_req, "session", None)
        sid = str(django_session.get("user_session_id", "")) if django_session else ""
        session_obj: UserSession | None = None
        if sid:
            session_obj = UserSession.objects.filter(
                pk=sid, user=user, revoked_at__isnull=True
            ).first()
            if session_obj is None:
                raise AuthenticationFailed("این نشست باطل شده است؛ لطفاً مجدداً وارد شوید.")
            _touch_user_session(session_obj)

        raw_req.active_user_session = session_obj
        request.active_user_session = session_obj
        return user, None


class SessionAwareJWTScheme(OpenApiAuthenticationExtension):  # type: ignore[no-untyped-call]
    """معرفی طرح امنیتی Bearer JWT به drf-spectacular برای مستندات OpenAPI 3.1."""

    target_class = "apps.identity.jwt_auth.SessionAwareJWTAuthentication"
    name = "bearerAuth"

    def get_security_definition(self, auto_schema: Any) -> dict[str, Any]:
        """تعریف استاندارد Bearer JWT در بخش securitySchemes."""
        del auto_schema
        return {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "توکن دسترسی SessionAwareJWT با قابلیت ابطال آنی نشست.",
        }


class SessionAwareCookieScheme(OpenApiAuthenticationExtension):  # type: ignore[no-untyped-call]
    """معرفی طرح امنیتی کوکی HttpOnly به drf-spectacular برای مستندات OpenAPI 3.1."""

    target_class = "apps.identity.jwt_auth.SessionAwareCookieAuthentication"
    name = "cookieAuth"

    def get_security_definition(self, auto_schema: Any) -> dict[str, Any]:
        """تعریف استاندارد نشست کوکی‌محور هم‌مبدأ."""
        del auto_schema
        return {
            "type": "apiKey",
            "in": "cookie",
            "name": "sessionid",
            "description": "نشست کوکی HttpOnly هم‌مبدأ همراه با هدر X-CSRFToken در درخواست‌های نوشتنی.",
        }
