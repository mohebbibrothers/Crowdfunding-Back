"""کلاس‌های مجوز دسترسی دامنه‌ای، اجبار MFA کارکنان و تأیید تازه (Step-Up MFA)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any, cast

from django.utils import timezone
from rest_framework.permissions import BasePermission

from apps.core.errors import AuthenticationRequiredError, MfaRequiredError, StepUpRequiredError
from apps.core.policy import get_policy
from apps.identity.models import StaffTotpDevice, User, UserSession


def authenticated_user(request: Any) -> User:
    """بازگرداندن شیء کاربر احرازهویت‌شده با تضمین نوع ایستا برای mypy --strict."""
    user = getattr(request, "user", None)
    if user is None or not getattr(user, "is_authenticated", False):
        raise AuthenticationRequiredError()
    return cast(User, user)


def resolve_active_session(request: Any) -> UserSession | None:
    """استخراج نشست فعال جاری از روی درخواست (ست‌شده توسط JWT یا Cookie Auth)."""
    session_obj = getattr(request, "active_user_session", None)
    if isinstance(session_obj, UserSession):
        return session_obj
    raw = getattr(request, "_request", request)
    raw_session = getattr(raw, "active_user_session", None)
    if isinstance(raw_session, UserSession):
        return raw_session
    return None


def assert_staff_mfa_satisfied(request: Any, user: User) -> UserSession:
    """اطمینان از این‌که کارمند/مدیر در نشست جاری خود تأیید دومرحله‌ای TOTP را گذرانده است."""
    session_obj = resolve_active_session(request)
    enrolled = StaffTotpDevice.objects.filter(user=user, confirmed_at__isnull=False).exists()
    if session_obj is None or session_obj.mfa_verified_at is None:
        raise MfaRequiredError(
            extensions={
                "mfa": {
                    "enrolled": enrolled,
                    "verified": False,
                }
            }
        )
    return session_obj


def assert_fresh_step_up_mfa(request: Any, user: User) -> None:
    """اطمینان از تازگی تأیید دومرحله‌ای (در بازهٔ مجاز Policy) برای عملیات حساس مالی/حریم خصوصی."""
    session_obj = assert_staff_mfa_satisfied(request, user)
    max_age_sec = int(get_policy("security.staff_step_up_seconds"))
    if session_obj.mfa_verified_at is None or (
        timezone.now() - session_obj.mfa_verified_at
    ) > timedelta(seconds=max_age_sec):
        raise StepUpRequiredError(
            extensions={
                "mfa": {
                    "enrolled": True,
                    "verified": True,
                    "step_up_max_age_seconds": max_age_sec,
                }
            }
        )


class IsStaffRole(BasePermission):
    """دسترسی کارکنان عملیات، مدیران مالی و مدیران ارشد (همراه با الزام عامل دوم TOTP)."""

    message = "این عملیات فقط برای کارکنان مجاز سامانه فعال است."

    def has_permission(self, request: Any, view: Any) -> bool:
        """بررسی نقش کارمندی و وضعیت MFA نشست."""
        del view
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated or not getattr(user, "is_staff_member", False):
            return False
        assert_staff_mfa_satisfied(request, cast(User, user))
        return True


class IsFinanceOrSuperAdmin(BasePermission):
    """دسترسی ویژهٔ مدیران مالی و مدیران ارشد (همراه با الزام عامل دوم TOTP)."""

    message = "این عملیات فقط برای مدیر مالی یا مدیر ارشد مجاز است."

    def has_permission(self, request: Any, view: Any) -> bool:
        """بررسی نقش مالی/ارشد و وضعیت MFA نشست."""
        del view
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated or not getattr(user, "is_finance_or_super", False):
            return False
        assert_staff_mfa_satisfied(request, cast(User, user))
        return True


class HasFreshMfa(BasePermission):
    """الزام تأیید تازهٔ عامل دوم (Step-Up) برای عملیات پرخطر."""

    def has_permission(self, request: Any, view: Any) -> bool:
        """بررسی تازگی زمان تأیید MFA در نشست فعال."""
        del view
        user = authenticated_user(request)
        assert_fresh_step_up_mfa(request, user)
        return True
