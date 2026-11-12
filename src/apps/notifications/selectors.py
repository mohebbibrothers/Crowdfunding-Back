"""سلکتورهای خوانشی اعلان‌های درون‌برنامه‌ای کاربر."""

from __future__ import annotations

from typing import Any

from django.db.models import QuerySet

from apps.notifications.models import UserNotification


def list_user_notifications(
    *, user_id: Any, unread_only: bool = False
) -> QuerySet[UserNotification]:
    """واکشی اعلان‌های درون‌برنامه‌ای کاربر به ترتیب جدیدترین."""
    qs = UserNotification.objects.filter(user_id=user_id).order_by("-created_at", "-id")
    if unread_only:
        qs = qs.filter(read_at__isnull=True)
    return qs


def count_unread_notifications(*, user_id: Any) -> int:
    """شمارش اعلان‌های خوانده‌نشدهٔ کاربر (برای نمایش نشان در داشبورد خیر)."""
    return int(UserNotification.objects.filter(user_id=user_id, read_at__isnull=True).count())
