"""سلکتورهای فقط‌خواندنی هویت، نشست‌های فعال و سیگنال‌های ریسک."""

from __future__ import annotations

from typing import Any

from django.db.models import Q, QuerySet

from apps.identity.models import (
    AuthRiskSignal,
    StaffRecoveryCode,
    StaffTotpDevice,
    User,
    UserSession,
)


def list_active_sessions_for_user(
    *, user: User, current_session_id: str | None
) -> list[dict[str, Any]]:
    """واکشی فهرست نشست‌های فعال کاربر با قرار دادن نشست جاری در صدر فهرست."""
    rows = list(
        UserSession.objects.filter(user=user, revoked_at__isnull=True).order_by("-last_seen_at")
    )
    items = [
        {
            "id": str(row.id),
            "device": row.device_label,
            "network": row.network_prefix,
            "mfa_verified": row.mfa_verified_at is not None,
            "created_at": row.created_at,
            "last_seen_at": row.last_seen_at,
            "is_current": bool(current_session_id and str(row.id) == current_session_id),
        }
        for row in rows
    ]
    return sorted(items, key=lambda item: not item["is_current"])


def get_staff_mfa_status(*, user: User, current_session: UserSession | None) -> dict[str, Any]:
    """برگرداندن وضعیت ثبت‌نام TOTP، تأیید نشست جاری و تعداد کدهای بازیابی باقی‌مانده."""
    enrolled = StaffTotpDevice.objects.filter(user=user, confirmed_at__isnull=False).exists()
    remaining_recovery = StaffRecoveryCode.objects.filter(user=user, used_at__isnull=True).count()
    return {
        "enrolled": enrolled,
        "session_verified": bool(current_session and current_session.mfa_verified_at is not None),
        "verified_at": current_session.mfa_verified_at if current_session else None,
        "remaining_recovery_codes": remaining_recovery,
    }


def list_admin_users(*, search: str = "", role: str = "") -> QuerySet[User]:
    """فهرست کاربران سامانه برای پنل ادمین با قابلیت جست‌وجو."""
    qs = User.objects.all().order_by("-created_at")
    if role:
        qs = qs.filter(role=role)
    if search:
        qs = qs.filter(
            Q(first_name__icontains=search)
            | Q(last_name__icontains=search)
            | Q(phone__endswith=search[-4:])
        )
    return qs


def list_auth_risk_signals(*, status: str = "") -> QuerySet[AuthRiskSignal]:
    """فهرست سیگنال‌های ریسک احراز هویت برای بررسی امنیتی."""
    qs = AuthRiskSignal.objects.select_related("user", "reviewed_by").order_by("-created_at")
    if status:
        qs = qs.filter(status=status)
    return qs
